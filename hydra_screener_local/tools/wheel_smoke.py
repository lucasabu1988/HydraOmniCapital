"""Build the wheel, install it into a clean venv, and prove it actually works.

Audit phase 10.2. Run it locally or in CI:

    python tools/wheel_smoke.py            # build + install + smoke, then clean up
    python tools/wheel_smoke.py --keep     # leave the venv for inspection

What it checks, in order:

1. the wheel builds;
2. it installs into a **fresh** venv with only its declared dependencies;
3. every module in `[tool.setuptools] py-modules` and every shipped package module
   imports from the installed copy — with the working directory somewhere else, so a
   module that only worked because of `sys.path.insert(0, ROOT)` is caught;
4. every console script in `[project.scripts]` runs. `--help` is the contract: it
   proves the entry point resolves and its imports load, without touching the network,
   a broker, or Lucas's state;
5. the import closure in `py-modules` still covers what the code imports.

Exit code 0 only if all of that holds. No network beyond pip, no broker, no secrets.
"""
from __future__ import annotations

import argparse
import ast
import glob
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent


def _discover_packages() -> tuple[str, ...]:
    """Every importable package in the tree, found rather than listed.

    This was a hand-kept literal, which is the same defect R-1001 was about: the
    check certified a list instead of the thing. `analytics/` was added by another
    branch and no gate noticed it never reached the wheel.
    """
    return tuple(sorted(
        d.name for d in ROOT.iterdir()
        if d.is_dir() and (d / "__init__.py").exists() and not d.name.startswith((".", "_"))
    ))


PACKAGES = _discover_packages()
#: scripts whose --help must work from an installed wheel
CONSOLE_SCRIPTS = (
    "hydra-daily", "hydra-refresh", "hydra-watch", "hydra-dashboard", "hydra-console",
    "hydra-store", "hydra-journal", "hydra-reconcile", "hydra-confirm", "hydra-runlog",
)


def _run(cmd, *, cwd=None, env=None, timeout=600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def declared_py_modules(root: Path = ROOT) -> list[str]:
    """`py-modules` from pyproject.toml."""
    import tomllib
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    return list(((data.get("tool") or {}).get("setuptools") or {}).get("py-modules") or [])


def declared_scripts(root: Path = ROOT) -> dict[str, str]:
    import tomllib
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    return dict((data.get("project") or {}).get("scripts") or {})


def _imports_of(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add(node.module.split(".")[0])
    return out


def required_top_modules(root: Path = ROOT) -> set[str]:
    """The import closure the wheel must carry: entry points + package imports.

    Recomputed rather than trusted, so a new top-level import cannot silently break
    the installed wheel again (repro R-1001).
    """
    top = {p.stem for p in root.glob("*.py") if not p.stem.startswith("test_")}
    scripts = {target.split(":")[0] for target in declared_scripts(root).values()}
    need: set[str] = set()
    seen: set[str] = set()
    queue = list(scripts)
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        if name not in top:
            continue
        need.add(name)
        for imp in _imports_of(root / f"{name}.py"):
            if imp in top or imp in PACKAGES:
                queue.append(imp)
    for pkg in PACKAGES:
        for path in (root / pkg).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            for imp in _imports_of(path):
                if imp in top:
                    need.add(imp)
    return need


def shipped_package_modules(root: Path = ROOT) -> list[str]:
    out = []
    for pkg in PACKAGES:
        for path in sorted((root / pkg).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(root).with_suffix("")
            parts = list(rel.parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if parts:
                out.append(".".join(parts))
    return out


def check_closure(root: Path = ROOT) -> list[str]:
    """Modules the code needs that `py-modules` does not ship."""
    declared = set(declared_py_modules(root))
    return sorted(required_top_modules(root) - declared)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="build + install + smoke the wheel")
    ap.add_argument("--keep", action="store_true", help="do not delete the temp venv")
    ap.add_argument("--structure-only", action="store_true",
                    help="check the wheel's contents and the import closure, without "
                         "creating a venv (no downloads; does NOT prove the scripts run)")
    args = ap.parse_args(argv)

    failures: list[str] = []

    print("[1/5] import closure vs py-modules")
    missing = check_closure()
    if missing:
        failures.append(f"py-modules is missing: {', '.join(missing)}")
        print(f"      FAIL missing {missing}")
    else:
        print(f"      ok ({len(declared_py_modules())} modules declared)")

    work = Path(tempfile.mkdtemp(prefix="hydra-wheel-smoke-"))
    dist = work / "dist"
    venv = work / "venv"
    try:
        print("[2/5] build wheel")
        r = _run([sys.executable, "-m", "pip", "wheel", "--no-deps", "-q", "-w", str(dist), "."],
                 cwd=str(ROOT))
        wheels = sorted(glob.glob(str(dist / "*.whl")))
        if r.returncode != 0 or not wheels:
            failures.append(f"wheel build failed: {(r.stderr or r.stdout)[-800:]}")
            print("      FAIL")
            return _finish(failures, work, args.keep)
        wheel = wheels[-1]
        print(f"      ok {os.path.basename(wheel)}")

        if args.structure_only:
            import zipfile
            names = set(zipfile.ZipFile(wheel).namelist())
            for mod in declared_py_modules():
                if f"{mod}.py" not in names:
                    failures.append(f"{mod}.py is declared but not in the wheel")
            for pkg in PACKAGES:
                if not any(n.startswith(f"{pkg}/") for n in names):
                    failures.append(f"package {pkg} is not in the wheel")
            print(f"      structure-only: {len(names)} files, "
                  f"{len(declared_py_modules())} modules, {len(PACKAGES)} packages")
            return _finish(failures, work, args.keep,
                            label="wheel structure ok: every declared module and package is "
                                  "in the wheel (run without --structure-only to prove the "
                                  "console scripts execute)")

        print("[3/5] create a clean venv and install the wheel")
        r = _run([sys.executable, "-m", "venv", str(venv)])
        if r.returncode != 0:
            failures.append(f"venv creation failed: {r.stderr[-500:]}")
            return _finish(failures, work, args.keep)
        bindir = "Scripts" if os.name == "nt" else "bin"
        py = venv / bindir / ("python.exe" if os.name == "nt" else "python")
        r = _run([str(py), "-m", "pip", "install", "-q", wheel], timeout=1800)
        if r.returncode != 0:
            failures.append(f"wheel install failed: {(r.stderr or r.stdout)[-1200:]}")
            print("      FAIL")
            return _finish(failures, work, args.keep)
        print("      ok")

        # cwd is deliberately NOT the repo: a module that only worked because of
        # sys.path.insert(0, ROOT) must fail here
        elsewhere = str(work)

        print("[4/5] import every public module from the installed copy")
        modules = declared_py_modules() + shipped_package_modules()
        script = "import importlib, sys\n"
        script += "bad = []\n"
        script += f"for m in {modules!r}:\n"
        script += "    try:\n        importlib.import_module(m)\n"
        script += "    except BaseException as e:\n        bad.append(f'{m}: {type(e).__name__}: {e}')\n"
        script += "print('BAD=' + repr(bad))\n"
        script += "sys.exit(1 if bad else 0)\n"
        r = _run([str(py), "-c", script], cwd=elsewhere, timeout=900)
        if r.returncode != 0:
            detail = (r.stdout or "") + (r.stderr or "")
            failures.append(f"module imports failed: {detail[-2000:]}")
            print(f"      FAIL\n{detail[-1500:]}")
        else:
            print(f"      ok ({len(modules)} modules)")

        print("[5/5] run every console script")
        for name in CONSOLE_SCRIPTS:
            exe = venv / bindir / (f"{name}.exe" if os.name == "nt" else name)
            if not exe.exists():
                failures.append(f"console script not installed: {name}")
                print(f"      FAIL {name} not installed")
                continue
            r = _run([str(exe), "--help"], cwd=elsewhere, timeout=300)
            if r.returncode != 0:
                detail = ((r.stderr or "") + (r.stdout or ""))[-800:]
                failures.append(f"{name} --help exited {r.returncode}: {detail}")
                print(f"      FAIL {name} -> {r.returncode}")
            else:
                print(f"      ok   {name}")
    finally:
        pass

    return _finish(failures, work, args.keep)


def _finish(failures: list[str], work: Path, keep: bool, *, label: str = "") -> int:
    if keep:
        print(f"\nvenv kept at {work}")
    else:
        shutil.rmtree(work, ignore_errors=True)
    print()
    if failures:
        print(f"wheel smoke FAILED: {len(failures)} problem(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(label or ("wheel smoke ok: built, installed clean, every module imports, "
                    "every console script runs"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
