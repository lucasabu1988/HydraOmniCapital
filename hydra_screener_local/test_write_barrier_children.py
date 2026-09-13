"""SAFE-04: the barrier reaches the processes the runner starts, or the run does not happen.

The defect, measured on 27afcf8 with a decoy in a protected directory:

    parent: refused -> WriteIsolationError
    child : wrote, exit 0, the decoy's hash changed

`write_isolation` patches one process. `run_all_tests.py` runs nine files as SCRIPTS, and a
script loads no conftest, so those children had no barrier at all. #82 armed pytest-routed
children (they do load conftest); this covers the rest.

Every test below drives a REAL child process against an ISOLATED decoy under tmp_path. None
of them points at a genuine evidence directory, and each one that expects a refusal also
proves the write was actually attempted - otherwise "the file is unchanged" would pass for a
child that never got that far.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import run_all_tests as R  # noqa: E402
import write_isolation as WI  # noqa: E402

ORIGINAL = b"ORIGINAL EVIDENCE BYTES"


def _decoy(tmp_path):
    """A protected root, a decoy inside it, and a disposable scratch beside it."""
    protected = tmp_path / "evidence"
    protected.mkdir()
    decoy = protected / "book.bin"
    decoy.write_bytes(ORIGINAL)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return protected, decoy, scratch


def _env(protected, **over):
    env = R.build_child_env(os.environ)
    env["HYDRA_WRITE_BARRIER_ROOTS"] = json.dumps([str(protected)])
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(over)
    return env


def _run(code, env, cwd=None):
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env,
                          cwd=str(cwd or ROOT), timeout=180)


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ------------------------------------------------------------------ the defect, both ways

def test_a_child_process_is_refused_the_write_the_parent_was_refused(tmp_path):
    protected, decoy, scratch = _decoy(tmp_path)
    before = _sha(decoy)
    reached = scratch / "attempted.marker"
    # The marker is the POSITIVE CONTROL: it proves the child got as far as the write.
    r = _run(f"open(r'{reached}','w').write('here'); "
             f"open(r'{decoy}','wb').write(b'CHILD OVERWROTE')", _env(protected))
    assert reached.exists(), "the child never reached the write; the test proves nothing"
    assert r.returncode != 0, f"the child wrote and exited 0 (stderr: {r.stderr[:300]})"
    assert "WRITE ISOLATION BARRIER" in (r.stderr or ""), r.stderr[:400]
    assert decoy.read_bytes() == ORIGINAL
    assert _sha(decoy) == before


def test_a_write_during_IMPORT_is_refused_too(tmp_path):
    """The barrier must be armed before the module under test is imported, not after."""
    protected, decoy, scratch = _decoy(tmp_path)
    mod = scratch / "writes_at_import.py"
    mod.write_text(f"open(r'{decoy!s}'.replace(chr(92)*2, chr(92)), 'wb').write(b'AT IMPORT')\n",
                   encoding="utf-8")
    marker = scratch / "reached.marker"
    r = _run(f"open(r'{marker}','w').write('here'); "
             f"import sys; sys.path.insert(0, r'{scratch}'); import writes_at_import",
             _env(protected))
    assert marker.exists(), "the child never reached the import"
    assert r.returncode != 0, f"the import-time write landed (stderr: {r.stderr[:300]})"
    assert decoy.read_bytes() == ORIGINAL


def test_a_grandchild_is_armed_as_well(tmp_path):
    """Declared coverage, so it is tested: PYTHONPATH and the flag are inherited."""
    protected, decoy, scratch = _decoy(tmp_path)
    inner = f"open(r'{decoy}','wb').write(b'GRANDCHILD')"
    r = _run("import subprocess,sys;"
             f"p=subprocess.run([sys.executable,'-c',{inner!r}],capture_output=True,text=True);"
             "print('INNER_RC=%d' % p.returncode)", _env(protected))
    assert "INNER_RC=" in r.stdout, r.stdout[:300] + r.stderr[:300]
    assert "INNER_RC=0" not in r.stdout, "the grandchild wrote and exited 0"
    assert decoy.read_bytes() == ORIGINAL


# --------------------------------------------------------- a failed bootstrap runs nothing

def test_a_bootstrap_that_cannot_arm_stops_the_child_before_its_body(tmp_path):
    """Fail closed. The body must not run, and the code must name the cause."""
    protected, decoy, scratch = _decoy(tmp_path)
    ran = scratch / "body_ran.marker"
    env = _env(protected, HYDRA_WRITE_BARRIER_ROOTS="{not json at all")
    r = _run(f"open(r'{ran}','w').write('the body ran')", env)
    assert r.returncode == R.EXIT_BOOTSTRAP_FAILED, (
        f"expected exit {R.EXIT_BOOTSTRAP_FAILED}, got {r.returncode}: {r.stderr[:300]}")
    assert not ran.exists(), "the body ran even though the barrier could not be armed"
    assert "refusing to run unprotected" in (r.stderr or "")


def test_a_bootstrap_that_arms_the_wrong_roots_stops_the_child(tmp_path):
    """An empty list is legitimate on a clean clone; a list that is not what the parent
    asked for is a lost variable, and must not pass for protection."""
    protected, decoy, scratch = _decoy(tmp_path)
    ran = scratch / "body_ran.marker"
    boot = tmp_path / "liar"
    boot.mkdir()
    (boot / "sitecustomize.py").write_text(
        "import os, sys\n"
        f"sys.path.insert(0, r'{ROOT / 'tools'}')\n"
        "import write_isolation as W\n"
        "W.install(protected=[], index_identities=False, import_optional=False)\n"
        f"sys.path.insert(0, r'{ROOT / 'tools' / '_bootstrap'}')\n"
        "import sitecustomize_real\n", encoding="utf-8")
    # Import the real bootstrap AFTER a bogus install: install() is idempotent, so the real
    # one finds roots it did not ask for and must refuse.
    import shutil
    shutil.copy(ROOT / "tools" / "_bootstrap" / "sitecustomize.py",
                boot / "sitecustomize_real.py")
    env = _env(protected)
    env["PYTHONPATH"] = str(boot) + os.pathsep + env["PYTHONPATH"]
    r = _run(f"open(r'{ran}','w').write('the body ran')", env)
    assert r.returncode == R.EXIT_BOOTSTRAP_FAILED, r.stderr[:400]
    assert not ran.exists()
    assert "armed the wrong roots" in (r.stderr or ""), r.stderr[:400]


def test_a_raising_bootstrap_would_be_swallowed_which_is_why_this_one_exits(tmp_path):
    """The measurement behind the design, kept as a test so it cannot rot.

    CPython swallows an exception raised by sitecustomize and runs the child anyway.
    """
    _, _, scratch = _decoy(tmp_path)
    boot = tmp_path / "raiser"
    boot.mkdir()
    (boot / "sitecustomize.py").write_text(
        "raise RuntimeError('BARRIER BOOTSTRAP FAILED')\n", encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(boot), PYTHONIOENCODING="utf-8")
    env.pop("HYDRA_WRITE_BARRIER", None)
    r = _run("print('CHILD RAN ANYWAY')", env, cwd=scratch)
    assert r.returncode == 0 and "CHILD RAN ANYWAY" in r.stdout, (
        "if CPython ever starts propagating this, the bootstrap may raise instead of "
        "calling os._exit - until then, raising is fail-OPEN")


# ------------------------------------------------------------------- the run is not crippled

def test_the_disposable_scratch_stays_writable(tmp_path):
    protected, decoy, scratch = _decoy(tmp_path)
    target = scratch / "normal_output.txt"
    r = _run(f"open(r'{target}','w').write('tests must still be able to write')",
             _env(protected))
    assert r.returncode == 0, r.stderr[:400]
    assert target.exists(), "a guarded child cannot write its own temp output"


def test_an_unguarded_child_is_untouched_when_the_flag_is_absent(tmp_path):
    """The bootstrap does nothing outside a guarded run: no global side effect on the box."""
    protected, decoy, scratch = _decoy(tmp_path)
    env = _env(protected)
    env.pop("HYDRA_WRITE_BARRIER")
    r = _run(f"open(r'{decoy}','wb').write(b'UNGUARDED')", env)
    assert r.returncode == 0, r.stderr[:300]
    assert decoy.read_bytes() == b"UNGUARDED"


# --------------------------------------------------------------- the runner's own wiring

def test_the_runner_resolves_real_roots_and_never_the_throwaway():
    roots = R.real_evidence_roots()
    assert roots is not None, "write_isolation must be importable for the suite to run"
    for r in roots:
        assert R.TEST_BACKUP_MARKER not in r.lower(), f"a throwaway is being protected: {r}"


def test_the_child_env_carries_the_bootstrap_and_the_real_backup_root():
    env = R.build_child_env(os.environ)
    assert env["HYDRA_WRITE_BARRIER"] == "1"
    assert R.BOOTSTRAP_DIR in env["PYTHONPATH"].split(os.pathsep)
    assert env["HYDRA_SCREENER_DIR"] == str(R.ROOT)
    # No frozen root list: the child resolves the repo-local dirs at its own start, so a
    # directory an earlier test created is protected for the children that follow it.
    assert "HYDRA_WRITE_BARRIER_ROOTS" not in env
    assert R.TEST_BACKUP_MARKER not in env["HYDRA_WRITE_BARRIER_BACKUP_ROOT"].lower()


def test_a_child_protects_an_evidence_dir_created_after_the_runner_started(tmp_path):
    r"""The clean-clone failure this design exists for.

    The runner resolves its own roots once, at import. On a fresh checkout `_lab_scratch/`
    is absent then and an earlier test file creates it; a child that inherited a frozen list
    would run beside real evidence it had never been told about. Measured exactly that way:
    test_write_barrier_armed.py failed on a clean clone with "evidence directories present
    on disk but NOT protected: [...\experiments\_lab_scratch]".
    """
    screener = tmp_path / "screener"
    (screener / "tools").mkdir(parents=True)
    born_later = screener / "state"          # absent when the "runner" starts
    env = R.build_child_env(os.environ)
    env["HYDRA_SCREENER_DIR"] = str(screener)
    env["PYTHONIOENCODING"] = "utf-8"
    env["T"] = str(R.ROOT / "tools")
    env.pop("HYDRA_WRITE_BARRIER_ROOTS", None)
    probe = ("import json,sys,os;sys.path.insert(0,os.environ['T']);"
             "import write_isolation as W;print(json.dumps(W.protected_roots()))")

    def armed():
        out = _run(probe, env).stdout.strip().splitlines()[-1]
        return {os.path.normcase(r) for r in json.loads(out)}

    want = os.path.normcase(str(born_later))
    assert want not in armed(), "precondition: the directory does not exist yet"
    born_later.mkdir()                        # an earlier test file creates it
    assert want in armed(), (
        "a child started after the directory appeared must protect it")


def test_the_canary_passes_for_this_invocation():
    ok, detail = R.canary(R.build_child_env(os.environ))
    assert ok, f"children of this runner would be unprotected: {detail}"


def test_the_canary_fails_when_the_bootstrap_is_not_on_the_path():
    """The silent case the canary exists for: PYTHONPATH stripped, -S, -E."""
    env = R.build_child_env(os.environ)
    env["PYTHONPATH"] = ""
    ok, detail = R.canary(env)
    assert not ok, "the canary passed with no bootstrap on the path"
    assert "NOT installed" in detail or "exited" in detail, detail


def test_the_documented_gaps_are_still_written_down():
    """An honest limit list is part of the deliverable; SAFE-04 does not close these."""
    raw = (ROOT / "tools" / "_bootstrap" / "sitecustomize.py").read_text(encoding="utf-8")
    # Collapse whitespace: a documented gap must not stop being documented because the
    # sentence rewrapped across a line.
    src = " ".join(raw.lower().split())
    for gap in ("non-python", "`-s`", "file handle opened before install",
                "raw file descriptor", "c-level path opener"):
        assert gap in src, f"the bootstrap must name the {gap!r} gap in writing"


def test_install_is_idempotent_so_conftest_after_the_bootstrap_is_safe():
    """A pytest child gets both layers; the second must not re-patch or widen the roots."""
    assert WI.is_installed(), "this test runs under conftest's barrier"
    before = WI.protected_roots()
    assert WI.install(protected=["/nonexistent/should/be/ignored"]) == before
    assert WI.protected_roots() == before
