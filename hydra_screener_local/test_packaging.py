"""Audit phase 10 — packaging, dependency coherence, serialisation and migration.

Reproductions R-1001..R-1003 in docs/AUDIT_REPRODUCTIONS.md (R-1004, the lint
gate that passed over an unlinted tree, is a CI step: `ruff check .`).

These are fast, offline checks. The full build-install-run smoke lives in
`tools/wheel_smoke.py` (it creates a venv and downloads dependencies), and CI runs it
as its own job.
"""
import json
import os
import re
import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core.portfolio_engine as E  # noqa: E402
from config import V9  # noqa: E402
from core.state_migrations import migrate  # noqa: E402

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))
import wheel_smoke as WS  # noqa: E402

PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _req_names(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z0-9._-]+)\s*(.*)$", line)
        if m:
            out[m.group(1).lower()] = m.group(2).strip()
    return out


def _proj_names(specs) -> dict[str, str]:
    out = {}
    for spec in specs or []:
        m = re.match(r"^([A-Za-z0-9._-]+)\s*(.*)$", str(spec).strip())
        if m:
            out[m.group(1).lower()] = m.group(2).strip()
    return out


# ------------------------------------------------------------------ R-1001 packaging
def test_r1001_every_shipped_package_is_declared():
    """R-1001 — phase 10.1. `include` listed core*, data*, utils* and **not**
    sleeves*, so `sleeves` never reached the wheel."""
    include = PYPROJECT["tool"]["setuptools"]["packages"]["find"]["include"]
    for pkg in WS.PACKAGES:
        assert f"{pkg}*" in include, f"{pkg} is not shipped"


def test_r1001_the_entry_point_modules_are_shipped():
    """R-1001. The console scripts point at top-level modules, which are not package
    members: the wheel contained none of them, so all five scripts were broken."""
    declared = set(WS.declared_py_modules())
    for target in WS.declared_scripts().values():
        module = target.split(":")[0]
        assert module in declared, f"{module} is an entry point but is not in py-modules"


def test_r1001_config_is_shipped():
    """Every package module does `from config import ...`, so without config.py in
    the wheel even `import core.signals` failed."""
    assert "config" in WS.declared_py_modules()


def test_r1001_the_import_closure_is_complete():
    """The guard that stops this regressing: recompute what the code needs and
    compare it with what the wheel declares."""
    missing = WS.check_closure()
    assert missing == [], f"py-modules does not ship: {missing}"


def test_every_declared_module_actually_exists():
    for module in WS.declared_py_modules():
        assert (ROOT / f"{module}.py").exists(), module


def test_every_console_script_target_is_callable():
    import importlib
    for name, target in WS.declared_scripts().items():
        module_name, func = target.split(":")
        module = importlib.import_module(module_name)
        assert callable(getattr(module, func, None)), f"{name} -> {target} is not callable"


def test_the_smoke_test_covers_every_declared_script():
    assert set(WS.CONSOLE_SCRIPTS) == set(WS.declared_scripts()), \
        "tools/wheel_smoke.py must smoke every script pyproject declares"


# ------------------------------------------------------------------ R-1002 dependencies
def test_r1002_requirements_and_pyproject_agree():
    """R-1002 — phase 10.3. They diverged: pyproject had `requests` and no scipy,
    rich or python-dateutil; requirements.txt had rich (not even installed) and no
    requests. Nothing noticed."""
    req = _req_names(ROOT / "requirements.txt")
    proj = _proj_names(PYPROJECT["project"]["dependencies"])
    assert set(req) == set(proj), (
        f"only in requirements.txt: {sorted(set(req) - set(proj))}; "
        f"only in pyproject: {sorted(set(proj) - set(req))}")
    for name in sorted(req):
        assert req[name] == proj[name], f"{name}: requirements {req[name]!r} vs pyproject {proj[name]!r}"


def test_r1002_dev_requirements_and_pyproject_agree():
    req = _req_names(ROOT / "requirements-dev.txt")
    proj = _proj_names(PYPROJECT["project"]["optional-dependencies"]["dev"])
    assert set(req) == set(proj)
    for name in sorted(req):
        assert req[name] == proj[name], name


def test_r1002_every_dependency_carries_a_lower_bound():
    """An unpinned dependency makes a result unreproducible in principle."""
    for spec in PYPROJECT["project"]["dependencies"]:
        assert ">=" in spec or "==" in spec, f"{spec} has no version bound"


def test_r1002_no_dependency_is_declared_that_nothing_imports():
    """R-1002 — phase 10.3. `rich` was a hard requirement nobody installed and nothing
    needed. Its one importer, console_dashboard.py, has since been deleted, so the
    optional extra went with it: what this now guards is that it does not come back
    as a hard dependency."""
    hard = _proj_names(PYPROJECT["project"]["dependencies"])
    assert "rich" not in hard
    extras = PYPROJECT["project"].get("optional-dependencies") or {}
    assert "rich" not in extras


def test_r1003_the_python_floor_matches_the_code():
    """R-1003 — phase 10.3. `requires-python = ">=3.9"` was wrong: the tree uses
    `zip(..., strict=True)`, which is 3.10+."""
    floor = PYPROJECT["project"]["requires-python"]
    assert floor == ">=3.10", floor

    uses_strict_zip = [
        p.name for p in list(ROOT.glob("*.py")) + list(ROOT.glob("core/*.py"))
        + list(ROOT.glob("data/*.py")) + list(ROOT.glob("utils/*.py"))
        if "strict=True" in p.read_text(encoding="utf-8", errors="replace")
    ]
    assert uses_strict_zip, "if nothing uses strict=True any more, revisit the floor"


def test_the_ruff_target_matches_the_python_floor():
    ruff = (ROOT / "ruff.toml").read_text(encoding="utf-8")
    assert "target-version" in ruff
    assert 'target-version = "py312"' in ruff or 'target-version = "py310"' in ruff


# ------------------------------------------------------------------ serialisation
def test_a_fresh_state_round_trips_through_json():
    """Phase 10.6: the state is written as JSON every run; a non-serialisable value
    in it is a run that cannot be committed."""
    st = E.new_state(100000.0, "2026-01-02", V9)
    blob = json.dumps(st)
    back = json.loads(blob)
    assert back["schema_version"] == E.STATE_SCHEMA
    assert back["mix"] == {"stocks": 0.5, "etf": 0.5}
    assert back["config"]["step_bars"] == V9["step_bars"]
    assert json.dumps(back, sort_keys=True) == json.dumps(st, sort_keys=True)


def test_the_persisted_config_is_json_clean():
    """V9 itself must be serialisable, because new_state persists a copy of it."""
    assert json.loads(json.dumps(V9)) == json.loads(json.dumps(dict(V9)))


def test_a_state_with_every_new_key_round_trips():
    st = E.new_state(100000.0, "2026-01-02", V9)
    st["calendar"] = ["2026-01-02", "2026-01-05"]
    st["data_errors"] = [{"date": "2026-01-02", "ticker": "AAA", "intent": "buy",
                          "reason": "no print", "code": "price_not_executable"}]
    st["dividend_coverage"] = {"through": "2026-01-02", "verified_at": "2026-01-02T00:00:00Z"}
    st["dividend_gaps"] = [{"start": "2025-12-12", "end": "2026-01-02", "status": "open",
                            "tickers": ["AAA"], "seen": 1}]
    st["ledger"] = [{"event_id": "abc123", "exec_date": "2026-01-02", "sleeve": "stocks",
                     "tranche": 0, "side": "buy", "ticker": "AAA", "units": 1.0,
                     "price": 10.0, "dollars": 10.0, "cost": 0.01, "status": "confirmed",
                     "correction_of": None, "revisions": []}]
    assert json.loads(json.dumps(st)) == json.loads(json.dumps(st))
    assert json.loads(json.dumps(st))["ledger"][0]["event_id"] == "abc123"


def test_the_instruction_payload_round_trips():
    import portfolio_v9 as V
    st = E.new_state(100000.0, "2026-01-02", V9)
    st["week_index"] = 0
    sheet = V.render_instructions(
        "2026-01-02", [], [], {"total": 100000.0, "sleeves": {}}, st, "2026-01-05")
    payload = json.loads(sheet["json_text"])
    assert payload["date"] == "2026-01-02"
    assert payload["exec_date"] == "2026-01-05"
    assert json.loads(json.dumps(payload)) == payload


# ------------------------------------------------------------------ migration
def test_a_pre_phase_1_state_still_migrates_and_reads():
    """Phase 10.6: the state on Lucas's disk predates every field this branch added.
    It must migrate without a rewrite and without losing a number."""
    legacy = {
        "schema_version": 1,
        "algo_version": "v9",
        "anchor_date": "2026-09-04",
        "last_run_date": "2026-09-04",
        "last_renewal_date": "2026-09-04",
        "week_index": 0,
        "capital_reference": 100000.0,
        "sleeves": {
            "stocks": {"tranches": [{"k": 0, "opened": "2026-09-04", "units": {"AAA": 10.0},
                                     "cash": 100.0, "last_px": {"AAA": 10.0}, "stale": {}}]},
            "etf": {"tranches": [{"k": 0, "opened": None, "units": {}, "cash": 200.0,
                                  "last_px": {}, "stale": {}}]},
        },
        "pending": [],
        "ledger": [{"exec_date": "2026-09-04", "sleeve": "stocks", "tranche": 0,
                    "side": "buy", "ticker": "AAA", "units": 10.0, "price": 10.0,
                    "dollars": 100.0, "cost": 0.1, "status": "filled"}],
        "write_offs": [], "transfers": [], "interest": [],
    }
    migrate(legacy)
    assert legacy["schema_version"] == 1

    # the new readers cope with the old shape
    from core.dividends import coverage_through
    from core.ledger import check_invariants, index_by_event_id
    from dashboard_v9 import _lots_from_ledger

    assert check_invariants(legacy) == []
    ids = index_by_event_id(legacy)
    assert len(ids) == 1, "an event id is backfilled deterministically, not invented twice"
    assert legacy["ledger"][0]["units"] == 10.0, "no number moved"
    assert coverage_through(legacy) == "2026-09-04", "the dividend watermark falls back"
    assert _lots_from_ledger(legacy)[("stocks", 0, "AAA")]["qty"] == 10.0
    assert E.sleeve_names(legacy) == ["stocks", "etf"]
    assert E.effective_config(legacy)["step_bars"] == V9["step_bars"], \
        "no persisted config -> the module default"


def test_a_legacy_state_can_be_marked_and_summarised():
    import pandas as pd
    legacy = {
        "schema_version": 1, "anchor_date": "2026-09-04", "last_run_date": "2026-09-04",
        "week_index": 0, "capital_reference": 300.0,
        "sleeves": {
            "stocks": {"tranches": [{"k": 0, "units": {"AAA": 10.0}, "cash": 100.0,
                                     "last_px": {"AAA": 10.0}, "stale": {}}]},
            "etf": {"tranches": [{"k": 0, "units": {}, "cash": 200.0, "last_px": {},
                                  "stale": {}}]},
        },
        "pending": [], "ledger": [], "write_offs": [], "transfers": [], "interest": [],
    }
    cfg = dict(V9, tranches=1)
    summary = E.summary_table(legacy, pd.Series({"AAA": 11.0}),
                              pd.Series({t: 50.0 for t in V9["etf_universe"]}), cfg)
    assert summary["total"] == pytest.approx(410.0)
    assert set(summary["sleeves"]) == {"stocks", "etf"}


def test_migrate_rejects_a_state_from_the_future():
    from core.state_migrations import SchemaError
    with pytest.raises(SchemaError):
        migrate({"schema_version": 999})


# ------------------------------------------------------------------ hygiene
def test_no_broker_or_cloud_execution_is_declared():
    """Phase 10.8, and rule 3 of the brief: no broker, no cloud execution."""
    forbidden = ("ib_insync", "ibapi", "alpaca", "ccxt", "boto3", "google-cloud")
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    for name in forbidden:
        assert name not in text, name
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for name in forbidden:
        assert name not in req, name


def test_no_secret_looking_literal_in_the_shipped_modules():
    """A cheap standing check; the CI secret scan is the thorough one."""
    patterns = [
        re.compile(r"(?i)\b(api[_-]?key|secret[_-]?key|password|passwd)\s*=\s*['\"][^'\"]{12,}"),
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{24,}"),
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ]
    offenders = []
    files = [ROOT / f"{m}.py" for m in WS.declared_py_modules()]
    for pkg in WS.PACKAGES:
        files += [p for p in (ROOT / pkg).rglob("*.py") if "__pycache__" not in p.parts]
    for path in files:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for rx in patterns:
            if rx.search(text):
                offenders.append(f"{path.name}: {rx.pattern[:40]}")
    assert offenders == [], offenders
