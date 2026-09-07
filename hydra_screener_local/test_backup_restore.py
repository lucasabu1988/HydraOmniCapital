"""TASK-ASTRA-12 — the book can be recovered, and a manual execution can be closed out.

Two guarantees nothing proved before:

1. A `shutil.copy2` to HYDRA_BACKUP_DIR is not a verified backup, and the JOURNAL is written
   *after* that copy, so it was never in it. Worse, `daily.py` caught a journal failure, printed
   it and still finished 0: a run could complete having recorded nothing.
2. Nothing proved the sheet -> broker fills -> book chain closed. Reconciling positions cannot
   say whether the FILL was timely: a holiday, a missed or duplicated order, or a confirmation
   arriving after the next renewal all change the book while the position count still matches.

Everything here is synthetic and offline. The autouse guard below makes the whole module
physically unable to write to the real `state/`, `journal/`, `runs/`, `history/`, `data_cache/`
or the default `../hydra_backups` — a restore drill must never land on a live book.
"""
from __future__ import annotations

import builtins
import hashlib
import json
import os
import pathlib
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import daily as D  # noqa: E402
import journal as J  # noqa: E402
import portfolio_v9 as V  # noqa: E402
import verify_state as VS  # noqa: E402
from core.state_check import check, replay  # noqa: E402
from utils.trading_calendar import is_nyse_session  # noqa: E402

ROOT = Path(__file__).resolve().parent
# Real, live-money locations. Nothing in this module may write inside them.
LIVE_DIRS = tuple(
    p.resolve()
    for p in (
        ROOT / "state",
        ROOT / "journal",
        ROOT / "runs",
        ROOT / "history",
        ROOT / "data_cache",
        ROOT / "pine",
        ROOT.parent / "hydra_backups",
    )
)


class LiveWriteBlocked(AssertionError):
    """A test tried to write into the production tree."""


def _is_live(target) -> bool:
    try:
        p = Path(target)
    except TypeError:
        return False
    try:
        p = p if p.is_absolute() else (Path.cwd() / p)
        resolved = Path(os.path.normpath(str(p)))
    except (OSError, ValueError):
        return False
    for live in LIVE_DIRS:
        if resolved == live or live in resolved.parents:
            return True
    return False


def _block(target, what: str):
    if _is_live(target):
        raise LiveWriteBlocked(f"{what} into the live tree refused: {target}")


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    """Redirect every default the code would reach for, then forbid the real paths outright."""
    monkeypatch.setattr(V, "DEFAULT_STATE_DIR", tmp_path / "never" / "state", raising=True)
    monkeypatch.setattr(VS, "DEFAULT_STATE", tmp_path / "never" / "state" / VS.STATE_NAME)
    monkeypatch.setattr(J, "DEFAULT_DIR", tmp_path / "never" / "journal", raising=True)
    monkeypatch.setattr(V, "_OFFDISK_WARNED", False, raising=False)
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "backup_root"))

    real_open = builtins.open
    real_write_text = pathlib.Path.write_text
    real_write_bytes = pathlib.Path.write_bytes
    real_mkdir = pathlib.Path.mkdir
    real_replace = pathlib.Path.replace
    real_unlink = pathlib.Path.unlink
    real_copy2 = shutil.copy2
    real_copytree = shutil.copytree
    real_os_replace = os.replace

    def guarded_open(file, mode="r", *a, **kw):
        if any(c in str(mode) for c in ("w", "a", "x", "+")):
            _block(file, "open() for writing")
        return real_open(file, mode, *a, **kw)

    def guarded_write_text(self, *a, **kw):
        _block(self, "write_text()")
        return real_write_text(self, *a, **kw)

    def guarded_write_bytes(self, *a, **kw):
        _block(self, "write_bytes()")
        return real_write_bytes(self, *a, **kw)

    def guarded_mkdir(self, *a, **kw):
        _block(self, "mkdir()")
        return real_mkdir(self, *a, **kw)

    def guarded_replace(self, target, *a, **kw):
        _block(target, "Path.replace()")
        return real_replace(self, target, *a, **kw)

    def guarded_unlink(self, *a, **kw):
        _block(self, "unlink()")
        return real_unlink(self, *a, **kw)

    def guarded_copy2(src, dst, *a, **kw):
        _block(dst, "shutil.copy2()")
        return real_copy2(src, dst, *a, **kw)

    def guarded_copytree(src, dst, *a, **kw):
        _block(dst, "shutil.copytree()")
        return real_copytree(src, dst, *a, **kw)

    def guarded_os_replace(src, dst, *a, **kw):
        _block(dst, "os.replace()")
        return real_os_replace(src, dst, *a, **kw)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(pathlib.Path, "write_text", guarded_write_text)
    monkeypatch.setattr(pathlib.Path, "write_bytes", guarded_write_bytes)
    monkeypatch.setattr(pathlib.Path, "mkdir", guarded_mkdir)
    monkeypatch.setattr(pathlib.Path, "replace", guarded_replace)
    monkeypatch.setattr(pathlib.Path, "unlink", guarded_unlink)
    monkeypatch.setattr(shutil, "copy2", guarded_copy2)
    monkeypatch.setattr(shutil, "copytree", guarded_copytree)
    monkeypatch.setattr(os, "replace", guarded_os_replace)
    yield


# --------------------------------------------------------------------------- fixtures

DATE = "2026-09-04"          # Friday: the anchor Lucas asked for
EXEC_DATE = "2026-09-08"     # Labor Day is 2026-09-07, so the MOC lands on Tuesday


def _clean_state() -> dict:
    """800 USD, 50/50, two tranches each; one booked buy that replays exactly."""
    each = 200.0

    def tr(i, cash=each, units=None, last_px=None):
        return {"k": i, "opened": None, "units": dict(units or {}), "cash": cash,
                "last_px": dict(last_px or {}), "stale": {}}

    return {
        "schema_version": 1,
        "capital_reference": 800.0,
        "anchor_date": DATE,
        # the booked fill is at EXEC_DATE, so the book must already have run past it
        "last_run_date": "2026-09-11",
        "last_renewal_date": DATE,
        "week_index": 1,
        "sleeves": {
            "stocks": {"tranches": [
                tr(0, cash=99.8, units={"AAA": 10.0}, last_px={"AAA": 11.0}), tr(1)]},
            "etf": {"tranches": [tr(0), tr(1)]},
        },
        "pending": [],
        "ledger": [{
            "exec_date": EXEC_DATE, "sleeve": "stocks", "tranche": 0, "side": "buy",
            "ticker": "AAA", "units": 10.0, "price": 10.0, "dollars": 100.0, "cost": 0.2,
            "status": "filled",
        }],
        "write_offs": [], "transfers": [], "interest": [], "dividends": [],
    }


def _sheet(exec_date: str = EXEC_DATE) -> dict:
    return {
        "date": DATE, "algo_version": "v9", "exec_date": exec_date, "no_trades": False,
        "orders": [{"planned": DATE, "sleeve": "stocks", "tranche": 0, "ticker": "AAA",
                    "side": "buy", "dollars": 100.0}],
        "capital_reference": 800.0,
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _prod_tree(tmp_path: Path) -> dict:
    """A synthetic production tree: state + sheet + journal + PIT snapshot + run manifest."""
    state_dir = tmp_path / "prod" / "state"
    jdir = tmp_path / "prod" / "journal"
    pit = tmp_path / "prod" / "pit"
    runs = tmp_path / "prod" / "runs" / "20260904_120000_v9"
    for d in (state_dir, jdir, pit, runs):
        d.mkdir(parents=True, exist_ok=True)

    state = _clean_state()
    state_path = state_dir / V.STATE_NAME
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    md = state_dir / f"instructions_{DATE.replace('-', '')}.md"
    md.write_text(f"# HYDRA v9 instructions - {DATE}\n\nejecutar al cierre del {EXEC_DATE}\n",
                  encoding="utf-8")
    sj = state_dir / f"instructions_{DATE.replace('-', '')}.json"
    sj.write_text(json.dumps(_sheet(), indent=2), encoding="utf-8")
    jrec = jdir / f"{DATE}.json"
    jrec.write_text(json.dumps({"date": DATE, "book": {"total": 800.0},
                                "observations": ["synthetic"]}, indent=2), encoding="utf-8")
    jmd = jdir / "JOURNAL.md"
    jmd.write_text(f"# HYDRA journal\n\n## {DATE}\n\ntotal 800.00\n", encoding="utf-8")
    snap = pit / f"universe_sp500_{DATE.replace('-', '')}.json"
    snap.write_text(json.dumps({"source": "fixture", "count": 2,
                                "tickers": ["AAA", "BBB"]}, indent=2), encoding="utf-8")
    runman = runs / "manifest.json"
    runman.write_text(json.dumps({"name": "v9", "exit_status": 0}, indent=2), encoding="utf-8")
    return {"state": state_path, "sheet_md": md, "sheet_json": sj, "journal": jrec,
            "journal_md": jmd, "pit": snap, "run_manifest": runman}


def _full_backup(tmp_path: Path) -> tuple[dict, Path]:
    """Run the two copies a real run makes: sheet-time, then journal-time (daily.py)."""
    files = _prod_tree(tmp_path)
    dest = V.copy_state_off_disk(
        DATE, [files["state"], files["sheet_md"], files["sheet_json"],
               files["pit"], files["run_manifest"]], silent=True)
    again = V.copy_state_off_disk(DATE, [files["journal"], files["journal_md"]], silent=True)
    assert again == dest
    return files, dest


# --------------------------------------------------------------------------- the guard itself

def test_guard_blocks_a_write_into_the_real_state_tree():
    """If this ever passes silently, every other test in the file is unprotected."""
    target = ROOT / "state" / "astra12_probe.json"
    with pytest.raises(LiveWriteBlocked):
        target.write_text("{}", encoding="utf-8")
    with pytest.raises(LiveWriteBlocked):
        with open(target, "w", encoding="utf-8") as f:  # noqa: SIM115
            f.write("{}")
    assert not target.exists()


def test_guard_allows_the_tmp_tree(tmp_path):
    p = tmp_path / "ok.json"
    p.write_text("{}", encoding="utf-8")
    assert p.exists()


# --------------------------------------------------------------------------- backup + restore

def test_backup_manifest_records_every_role_including_the_journal(tmp_path):
    files, dest = _full_backup(tmp_path)
    manifest = VS.read_backup_manifest(dest)
    assert manifest is not None, "copy2 without a manifest is not a verified backup"
    roles = {rec["role"] for rec in manifest["files"].values()}
    assert {"state", "sheet_md", "sheet_json", "journal", "journal_md", "pit",
            "run_manifest"} <= roles, roles
    for role, src in files.items():
        rec = manifest["files"][src.name]
        assert rec["sha256"] == _sha(src), (role, src.name)
    assert VS.verify_backup(dest) == []


def test_second_copy_does_not_drop_the_first_copys_entries(tmp_path):
    """Regression: the journal copy must APPEND. A truncating manifest re-opens the hole."""
    files, dest = _full_backup(tmp_path)
    names = set(VS.read_backup_manifest(dest)["files"])
    assert files["state"].name in names and files["journal"].name in names
    V.copy_state_off_disk(DATE, [files["journal"]], silent=True)
    assert set(VS.read_backup_manifest(dest)["files"]) == names


def test_restore_into_isolated_dir_keeps_every_hash_and_replays_clean(tmp_path):
    files, dest = _full_backup(tmp_path)
    target = tmp_path / "drill" / "restored"
    res = VS.restore_into(dest, target, live_state=files["state"])

    errors = [f for f in res["findings"] if f.level == "ERROR"]
    assert errors == [], errors
    for role, src in files.items():
        assert res["hashes"][src.name] == _sha(src), f"{role} differs after restore"
        assert (target / src.name).exists()
    # the source tree is untouched: a drill is not a migration
    assert _sha(files["state"]) == _sha(dest / files["state"].name)

    restored = res["state"]
    assert restored["ledger"] == json.loads(files["state"].read_text(encoding="utf-8"))["ledger"]
    assert check(restored) == []
    rec = res["replay"] or replay(restored)
    assert rec["stocks"]["tranches"][0]["cash"] == pytest.approx(99.8)
    assert rec["stocks"]["tranches"][0]["units"]["AAA"] == pytest.approx(10.0)


def test_restore_refuses_the_live_state_tree_and_any_occupied_dir(tmp_path):
    files, dest = _full_backup(tmp_path)
    live_dir = files["state"].parent
    with pytest.raises(VS.RestoreRefused):
        VS.restore_into(dest, live_dir, live_state=files["state"])
    with pytest.raises(VS.RestoreRefused):
        VS.restore_into(dest, live_dir / "sub", live_state=files["state"])

    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / V.STATE_NAME).write_text("{}", encoding="utf-8")
    with pytest.raises(VS.RestoreRefused):
        VS.restore_into(dest, occupied, live_state=files["state"])

    dirty = tmp_path / "dirty"
    dirty.mkdir()
    (dirty / "something.txt").write_text("x", encoding="utf-8")
    with pytest.raises(VS.RestoreRefused):
        VS.restore_into(dest, dirty, live_state=files["state"])
    # nothing was written into the refused targets
    assert sorted(p.name for p in live_dir.iterdir()) == sorted(
        p.name for p in (files["state"], files["sheet_md"], files["sheet_json"]))


def test_verify_backup_catches_a_silently_corrupted_or_partial_copy(tmp_path):
    files, dest = _full_backup(tmp_path)
    (dest / files["state"].name).write_text("{}", encoding="utf-8")
    codes = {f.code for f in VS.verify_backup(dest)}
    assert "BACKUP_HASH_MISMATCH" in codes, codes

    files2, dest2 = _full_backup(tmp_path / "b")
    (dest2 / files2["journal"].name).unlink()
    codes2 = {f.code for f in VS.verify_backup(dest2)}
    assert "BACKUP_FILE_MISSING" in codes2, codes2


def test_a_sheet_only_backup_is_incomplete_because_the_journal_is_missing(tmp_path):
    """The confirmed defect: the journal is written after copy_state_off_disk."""
    files = _prod_tree(tmp_path)
    dest = V.copy_state_off_disk(
        DATE, [files["state"], files["sheet_md"], files["sheet_json"]], silent=True)
    codes = {f.code for f in VS.verify_backup(dest)}
    assert "BACKUP_INCOMPLETE" in codes, codes
    assert not VS.backup_is_complete(dest)
    V.copy_state_off_disk(DATE, [files["journal"]], silent=True)
    assert VS.backup_is_complete(dest)


def test_verify_backup_without_a_manifest_is_not_a_pass(tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / V.STATE_NAME).write_text(json.dumps(_clean_state()), encoding="utf-8")
    codes = {f.code for f in VS.verify_backup(bare)}
    assert "BACKUP_NO_MANIFEST" in codes, codes


# --------------------------------------------------------------------------- daily.py completeness

def _v9_out(tmp_path: Path) -> dict:
    state_dir = tmp_path / "run" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state = _clean_state()
    (state_dir / V.STATE_NAME).write_text(json.dumps(state, indent=2), encoding="utf-8")
    return {"today": DATE, "state": state, "state_path": str(state_dir / V.STATE_NAME),
            "orders": [], "fills": [], "no_trades": True}


def _run_daily(monkeypatch, out, journal_fn):
    monkeypatch.setattr(V, "run", lambda **kw: out, raising=False)
    monkeypatch.setattr(J, "append_from_v9", journal_fn, raising=False)
    return D.main(["--skip-screener", "--no-instructions", "--v9"])


def test_journal_write_failure_marks_the_run_incomplete(tmp_path, monkeypatch):
    """Was: print the exception, finish 0, having recorded nothing."""
    out = _v9_out(tmp_path)

    def boom(*a, **kw):
        raise OSError("disk full")

    code = _run_daily(monkeypatch, out, boom)
    assert code != 0, "a run that recorded no journal must not exit 0"
    status = json.loads((Path(out["state_path"]).parent / "run_status.json").read_text("utf-8"))
    assert status["status"] == "incomplete"
    assert "disk full" in (status["detail"] or "")


def test_incomplete_backup_marks_the_run_incomplete(tmp_path, monkeypatch):
    """The journal landed, but the copy it landed in has no state/sheet: not recoverable."""
    out = _v9_out(tmp_path)
    jdir = tmp_path / "run" / "journal"

    def writes_journal(v9_out, note=None, **kw):
        jdir.mkdir(parents=True, exist_ok=True)
        p = jdir / f"{v9_out['today']}.json"
        p.write_text(json.dumps({"date": v9_out["today"], "book": {"total": 800.0}}),
                     encoding="utf-8")
        return p

    code = _run_daily(monkeypatch, out, writes_journal)
    assert code != 0
    status = json.loads((Path(out["state_path"]).parent / "run_status.json").read_text("utf-8"))
    assert status["status"] == "incomplete"
    assert "BACKUP_INCOMPLETE" in (status["detail"] or "")


def test_a_complete_run_exits_zero_and_records_complete(tmp_path, monkeypatch):
    out = _v9_out(tmp_path)
    state_dir = Path(out["state_path"]).parent
    md = state_dir / f"instructions_{DATE.replace('-', '')}.md"
    md.write_text("sheet", encoding="utf-8")
    sj = state_dir / f"instructions_{DATE.replace('-', '')}.json"
    sj.write_text(json.dumps(_sheet()), encoding="utf-8")
    V.copy_state_off_disk(DATE, [Path(out["state_path"]), md, sj], silent=True)

    jdir = tmp_path / "run" / "journal"

    def writes_journal(v9_out, note=None, **kw):
        jdir.mkdir(parents=True, exist_ok=True)
        p = jdir / f"{v9_out['today']}.json"
        p.write_text(json.dumps({"date": v9_out["today"], "book": {"total": 800.0}}),
                     encoding="utf-8")
        (jdir / "JOURNAL.md").write_text("# journal\n", encoding="utf-8")
        return p

    code = _run_daily(monkeypatch, out, writes_journal)
    assert code == 0, "a run with journal + complete backup must exit 0"
    status = json.loads((state_dir / "run_status.json").read_text("utf-8"))
    assert status["status"] == "complete"
    dest = Path(os.environ["HYDRA_BACKUP_DIR"]) / "state_v9" / DATE.replace("-", "")
    assert VS.backup_is_complete(dest)


# --------------------------------------------------------------------------- manual close-out

def _csv(tmp_path: Path, rows: list[dict], name: str = "broker.csv") -> Path:
    p = tmp_path / name
    header = "exec_date,sleeve,tranche,ticker,side,units,price,fee"
    lines = [header] + [
        ",".join(str(r.get(k, "")) for k in header.split(",")) for r in rows
    ]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_labor_day_sheet_is_caught_before_the_order_is_placed(tmp_path):
    assert not is_nyse_session("2026-09-07"), "fixture assumes Labor Day 2026-09-07"
    state = _clean_state()
    rows = [{"exec_date": EXEC_DATE, "sleeve": "stocks", "tranche": 0, "ticker": "AAA",
             "side": "buy", "units": 10.0, "price": 10.0, "fee": 0.2}]
    findings = VS.closeout(state, rows, sheet=_sheet(exec_date="2026-09-07"))
    codes = {f.code for f in findings}
    assert "SHEET_EXEC_NOT_SESSION" in codes, codes
    assert VS.closeout(state, rows, sheet=_sheet()) == []


def test_an_order_the_broker_never_executed_is_detectable(tmp_path):
    state = _clean_state()
    findings = VS.closeout(state, [], sheet=_sheet())
    codes = {f.code for f in findings}
    assert "ORDER_NOT_EXECUTED" in codes, codes


def test_an_order_executed_twice_is_detectable(tmp_path):
    state = _clean_state()
    row = {"exec_date": EXEC_DATE, "sleeve": "stocks", "tranche": 0, "ticker": "AAA",
           "side": "buy", "units": 10.0, "price": 10.0, "fee": 0.2}
    findings = VS.closeout(state, [dict(row), dict(row)], sheet=_sheet())
    codes = {f.code for f in findings}
    assert "ORDER_EXECUTED_TWICE" in codes, codes


def test_a_confirmation_arriving_after_the_next_renewal_is_detectable(tmp_path):
    """The book already renewed on the presumed price; the correction lands afterwards."""
    state = _clean_state()
    state["last_run_date"] = "2026-09-15"
    state["last_renewal_date"] = "2026-09-15"
    state["ledger"].append({
        "exec_date": "2026-09-16", "sleeve": "etf", "tranche": 0, "side": "buy",
        "ticker": "SPY", "units": 1.0, "price": 500.0, "dollars": 500.0, "cost": 0.5,
        "status": "filled"})
    state["pending"] = [{"planned": "2026-09-15", "sleeve": "stocks", "tranche": 1,
                         "ticker": "BBB", "side": "buy", "dollars": 100.0}]
    rows = [{"exec_date": EXEC_DATE, "sleeve": "stocks", "tranche": 0, "ticker": "AAA",
             "side": "buy", "units": 10.0, "price": 11.5, "fee": 0.2}]
    findings = VS.closeout(state, rows)
    late = [f for f in findings if f.code == "LATE_CONFIRMATION"]
    assert late, {f.code for f in findings}
    assert "renewed on 2026-09-15" in late[0].message
    assert "pending order" in late[0].message


def test_a_broker_execution_with_no_booked_order_is_detectable(tmp_path):
    state = _clean_state()
    rows = [
        {"exec_date": EXEC_DATE, "sleeve": "stocks", "tranche": 0, "ticker": "AAA",
         "side": "buy", "units": 10.0, "price": 10.0, "fee": 0.2},
        {"exec_date": EXEC_DATE, "sleeve": "stocks", "tranche": 0, "ticker": "ZZZ",
         "side": "buy", "units": 5.0, "price": 40.0, "fee": 0.2},
    ]
    codes = {f.code for f in VS.closeout(state, rows, sheet=_sheet())}
    assert "BROKER_UNPLANNED" in codes, codes


def test_closeout_cli_is_read_only_and_exits_nonzero_on_a_gap(tmp_path):
    files = _prod_tree(tmp_path)
    csv_path = _csv(tmp_path, [])            # the order was never executed
    before = {p: _sha(p) for p in (files["state"], files["sheet_json"], csv_path)}
    code = VS.main(["--state", str(files["state"]), "--closeout", str(csv_path),
                    "--sheet", str(files["sheet_json"])])
    assert code != 0
    assert {p: _sha(p) for p in before} == before, "closeout must not write anything"


def test_restore_into_cli_refuses_a_populated_target(tmp_path):
    files, dest = _full_backup(tmp_path)
    code = VS.main(["--state", str(files["state"]), "--restore-into", str(files["state"].parent),
                    "--from-backup-dir", str(dest)])
    assert code == 2, "the CLI must refuse, not overwrite"


def test_restore_writes_nothing_outside_the_target(tmp_path):
    """Regression: a drill that leaks a write is a drill that can corrupt the book."""
    files, dest = _full_backup(tmp_path)
    before = {p: _sha(p) for p in list(files.values()) + sorted(dest.iterdir())}
    target = tmp_path / "drill2"
    res = VS.restore_into(dest, target, live_state=files["state"])
    assert {p: _sha(p) for p in before} == before, "restore mutated a source file"
    expected = set(VS.read_backup_manifest(dest)["files"]) | {VS.BACKUP_MANIFEST}
    assert {p.name for p in target.iterdir()} == expected
    assert set(res["files"]) == expected - {VS.BACKUP_MANIFEST}


def test_every_closeout_gap_is_error_level_not_a_warning(tmp_path):
    """Regression: downgrading any of the four to WARN silently un-gates the CLI."""
    row = {"exec_date": EXEC_DATE, "sleeve": "stocks", "tranche": 0, "ticker": "AAA",
           "side": "buy", "units": 10.0, "price": 10.0, "fee": 0.2}
    late_state = _clean_state()
    late_state["last_renewal_date"] = "2026-09-15"
    late_state["last_run_date"] = "2026-09-15"
    cases = {
        "SHEET_EXEC_NOT_SESSION": (_clean_state(), [dict(row)], _sheet(exec_date="2026-09-07")),
        "ORDER_NOT_EXECUTED": (_clean_state(), [], _sheet()),
        "ORDER_EXECUTED_TWICE": (_clean_state(), [dict(row), dict(row)], _sheet()),
        "LATE_CONFIRMATION": (late_state, [dict(row, price=11.5)], None),
    }
    for code, (state, rows, sheet) in cases.items():
        findings = VS.closeout(state, rows, sheet=sheet)
        hit = [f for f in findings if f.code == code]
        assert hit, f"{code} not detected: {[f.code for f in findings]}"
        assert all(f.level == "ERROR" for f in hit), (code, [f.level for f in hit])
