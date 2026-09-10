"""Audit phase 3 — staged commit, backups and recovery. No network.

Reproductions R-301..R-303 in docs/AUDIT_REPRODUCTIONS.md.
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import portfolio_v9 as V  # noqa: E402
from config import V9  # noqa: E402
from core.commit import (  # noqa: E402
    COMMITTED,
    INSTRUCTIONS_WRITTEN,
    INTENT_NAME,
    MANIFEST_NAME,
    PLANNED,
    RECOVERY_REQUIRED,
    CommitError,
    RunTransaction,
    append_journal,
    last_status,
    new_run_id,
    pending_runs,
    read_journal,
    recover,
    unique_path,
)
from test_portfolio_v9_cli import FakeEngine, _market, _rank  # noqa: E402

N = 301


def _fetch(_universe=None):
    idx = pd.bdate_range("2025-01-01", periods=N)
    stocks = pd.DataFrame({t: np.linspace(10.0, 20.0, N) for t in ("AAA", "BBB", "CCC")}, index=idx)
    etf = pd.DataFrame({t: np.linspace(50.0, 60.0, N) for t in V9["etf_universe"]}, index=idx)
    return dict(prices=stocks, volumes=stocks * 1e6,
                spy=pd.Series(np.linspace(400.0, 500.0, N), index=idx),
                etf=etf, irx=pd.Series(4.0, index=idx),
                stock_report={}, etf_report={}, irx_report={})


def _rank_real(prices, spy, volumes):
    return pd.DataFrame({"ticker": ["AAA", "BBB", "CCC"], "rank": [1, 2, 3],
                         "sector": ["Tech"] * 3, "recommended": [True] * 3,
                         "reason": [""] * 3, "composite": [1.0, 0.9, 0.8]})


# ------------------------------------------------------------------ run ids / backups
def test_r302_run_ids_are_unique_inside_one_second():
    """R-302 — phase 3.5. `%Y%m%d_%H%M%S` collided, and the colliding backup was
    silently overwritten: three saves in one second left one file."""
    ids = {new_run_id() for _ in range(500)}
    assert len(ids) == 500
    assert all(len(i.split("_")) == 4 for i in ids)


def test_r302_repeated_saves_never_lose_a_backup(tmp_path):
    """R-302 end to end: every previous version survives."""
    path = tmp_path / V.STATE_NAME
    for v in (1, 2, 3, 4, 5):
        V.save_state(path, {"v": v})
    backups = sorted((tmp_path / "backup").glob("*.json"))
    assert len(backups) == 4, [b.name for b in backups]
    kept = sorted(json.loads(b.read_text(encoding="utf-8"))["v"] for b in backups)
    assert kept == [1, 2, 3, 4]
    assert json.loads(path.read_text(encoding="utf-8"))["v"] == 5


def test_unique_path_never_overwrites(tmp_path):
    p = tmp_path / "a.json"
    p.write_text("first", encoding="utf-8")
    q = unique_path(p)
    assert q != p and not q.exists()
    q.write_text("second", encoding="utf-8")
    r = unique_path(p)
    assert r not in (p, q)
    assert p.read_text(encoding="utf-8") == "first"


# ------------------------------------------------------------------ staging + validation
def test_a_transaction_writes_nothing_until_it_commits(tmp_path):
    live = tmp_path / V.STATE_NAME
    live.write_text(json.dumps({"generation": 1}), encoding="utf-8")

    tx = RunTransaction(tmp_path, date="2026-09-04")
    tx.stage_text("instructions_20260904.md", "# sheet\n")
    tx.stage_state(V.STATE_NAME, {"generation": 2})
    assert json.loads(live.read_text(encoding="utf-8"))["generation"] == 1
    assert not (tmp_path / "instructions_20260904.md").exists()

    tx.commit(state={"sleeves": {}, "ledger": []})
    assert json.loads(live.read_text(encoding="utf-8"))["generation"] == 2
    assert (tmp_path / "instructions_20260904.md").read_text(encoding="utf-8") == "# sheet\n"


def test_validate_refuses_a_transaction_with_no_state(tmp_path):
    tx = RunTransaction(tmp_path)
    tx.stage_text("sheet.md", "x")
    assert any("no candidate state" in p for p in tx.validate())
    with pytest.raises(CommitError):
        tx.commit()


def test_validate_catches_a_staged_file_that_was_truncated(tmp_path):
    tx = RunTransaction(tmp_path)
    staged = tx.stage_text("sheet.md", "the whole sheet")
    tx.stage_state(V.STATE_NAME, {"a": 1})
    Path(staged).write_text("trunc", encoding="utf-8")
    problems = tx.validate()
    assert any("staged" in p and "bytes" in p for p in problems)


def test_validate_catches_a_state_that_breaks_an_invariant(tmp_path):
    tx = RunTransaction(tmp_path)
    tx.stage_state(V.STATE_NAME, {"a": 1})
    poisoned = {"sleeves": {"stocks": {"tranches": [{"cash": float("nan"), "units": {}}]}},
                "ledger": []}
    problems = tx.validate(state=poisoned)
    assert any("cash_not_finite" in p for p in problems)
    with pytest.raises(CommitError):
        tx.commit(state=poisoned)


def test_a_refused_commit_leaves_the_previous_state_authoritative(tmp_path):
    live = tmp_path / V.STATE_NAME
    live.write_text(json.dumps({"generation": 1}), encoding="utf-8")
    tx = RunTransaction(tmp_path)
    tx.stage_state(V.STATE_NAME, {"generation": 2})
    with pytest.raises(CommitError):
        tx.commit(state={"sleeves": {"stocks": {"tranches": [{"cash": float("inf"), "units": {}}]}},
                         "ledger": []})
    assert json.loads(live.read_text(encoding="utf-8"))["generation"] == 1
    assert last_status(tmp_path, run_id=tx.run_id) == "failed"


def test_commit_backs_up_every_file_it_replaces(tmp_path):
    (tmp_path / V.STATE_NAME).write_text(json.dumps({"generation": 1}), encoding="utf-8")
    (tmp_path / "sheet.md").write_text("old sheet", encoding="utf-8")
    tx = RunTransaction(tmp_path)
    tx.stage_text("sheet.md", "new sheet")
    tx.stage_state(V.STATE_NAME, {"generation": 2})
    record = tx.commit(state={"sleeves": {}, "ledger": []})
    bdir = tmp_path / "backup" / tx.run_id
    assert {p.name for p in bdir.iterdir()} == {V.STATE_NAME, "sheet.md"}
    assert (bdir / "sheet.md").read_text(encoding="utf-8") == "old sheet"
    assert len(record["backups"]) == 2


def test_commit_is_idempotent(tmp_path):
    tx = RunTransaction(tmp_path)
    tx.stage_state(V.STATE_NAME, {"generation": 1})
    a = tx.commit(state={"sleeves": {}, "ledger": []})
    b = tx.commit(state={"sleeves": {}, "ledger": []})
    assert a["run_id"] == b["run_id"]
    statuses = [r["status"] for r in read_journal(tmp_path) if r["run_id"] == tx.run_id]
    assert statuses.count(COMMITTED) == 1


# ------------------------------------------------------------------ journal
def test_the_run_journal_is_append_only(tmp_path):
    tx = RunTransaction(tmp_path, date="2026-09-04")
    tx.mark(INSTRUCTIONS_WRITTEN)
    tx.stage_state(V.STATE_NAME, {"a": 1})
    tx.commit(state={"sleeves": {}, "ledger": []})
    records = [r for r in read_journal(tmp_path) if r["run_id"] == tx.run_id]
    assert [r["status"] for r in records] == [PLANNED, INSTRUCTIONS_WRITTEN, COMMITTED]
    assert all(r["at"] for r in records)


def test_a_second_run_the_same_day_adds_records_it_does_not_replace_them(tmp_path):
    for _ in range(3):
        tx = RunTransaction(tmp_path, date="2026-09-04")
        tx.stage_state(V.STATE_NAME, {"a": 1})
        tx.commit(state={"sleeves": {}, "ledger": []})
    same_day = [r for r in read_journal(tmp_path) if r.get("date") == "2026-09-04"]
    assert len({r["run_id"] for r in same_day}) == 3
    assert len(same_day) == 6


def test_an_unparseable_journal_line_is_reported_not_swallowed(tmp_path):
    append_journal(tmp_path, {"run_id": "a", "status": PLANNED})
    with (tmp_path / "runs.jsonl").open("a", encoding="utf-8") as f:
        f.write("{not json\n")
    records = read_journal(tmp_path)
    assert records[-1]["status"] == "unparseable"


# ------------------------------------------------------------------ recovery
def test_recovery_finishes_a_run_interrupted_after_commit_intent(tmp_path):
    """Phase 3.4: state is replaced last, so an interruption mid-apply is recoverable."""
    live = tmp_path / V.STATE_NAME
    live.write_text(json.dumps({"generation": 1}), encoding="utf-8")

    tx = RunTransaction(tmp_path, date="2026-09-04")
    tx.stage_text("sheet.md", "new sheet")
    tx.stage_state(V.STATE_NAME, {"generation": 2})
    assert tx.validate(state={"sleeves": {}, "ledger": []}) == []
    # simulate a crash right after COMMIT_INTENT: the manifest and the staged bytes
    # are on disk, nothing has been applied
    (tx.staging / MANIFEST_NAME).write_text(json.dumps(tx.manifest(), indent=2), encoding="utf-8")
    (tx.staging / INTENT_NAME).write_text(tx.run_id + "\n", encoding="utf-8")

    assert json.loads(live.read_text(encoding="utf-8"))["generation"] == 1
    pend = pending_runs(tmp_path)
    assert len(pend) == 1 and pend[0]["needs_recovery"] is True

    out = recover(tmp_path)
    assert out["recovered"] == [tx.run_id]
    assert json.loads(live.read_text(encoding="utf-8"))["generation"] == 2
    assert (tmp_path / "sheet.md").read_text(encoding="utf-8") == "new sheet"
    assert last_status(tmp_path, run_id=tx.run_id) == COMMITTED


def test_recovery_is_idempotent(tmp_path):
    live = tmp_path / V.STATE_NAME
    live.write_text(json.dumps({"generation": 1}), encoding="utf-8")
    tx = RunTransaction(tmp_path)
    tx.stage_state(V.STATE_NAME, {"generation": 2})
    (tx.staging / MANIFEST_NAME).write_text(json.dumps(tx.manifest(), indent=2), encoding="utf-8")
    (tx.staging / INTENT_NAME).write_text(tx.run_id + "\n", encoding="utf-8")

    first = recover(tmp_path)
    second = recover(tmp_path)
    third = recover(tmp_path)
    assert first["recovered"] == [tx.run_id]
    assert second == {"recovered": [], "discarded": [], "failed": []}
    assert third == second
    assert json.loads(live.read_text(encoding="utf-8"))["generation"] == 2


def test_recovery_completes_a_partially_applied_run(tmp_path):
    """The artefact landed, the state did not: recovery finishes the job."""
    live = tmp_path / V.STATE_NAME
    live.write_text(json.dumps({"generation": 1}), encoding="utf-8")
    tx = RunTransaction(tmp_path)
    tx.stage_text("sheet.md", "new sheet")
    tx.stage_state(V.STATE_NAME, {"generation": 2})
    (tx.staging / MANIFEST_NAME).write_text(json.dumps(tx.manifest(), indent=2), encoding="utf-8")
    (tx.staging / INTENT_NAME).write_text(tx.run_id + "\n", encoding="utf-8")
    # the sheet was already written and its staged copy removed
    (tmp_path / "sheet.md").write_text("new sheet", encoding="utf-8")
    (tx.staging / "sheet.md").unlink()

    out = recover(tmp_path)
    assert out["recovered"] == [tx.run_id]
    assert json.loads(live.read_text(encoding="utf-8"))["generation"] == 2


def test_staging_without_commit_intent_is_discarded_not_applied(tmp_path):
    """Nothing was replaced, so the candidate must be dropped, not half-applied."""
    live = tmp_path / V.STATE_NAME
    live.write_text(json.dumps({"generation": 1}), encoding="utf-8")
    tx = RunTransaction(tmp_path)
    tx.stage_state(V.STATE_NAME, {"generation": 999})
    out = recover(tmp_path)
    assert out["discarded"] == [tx.run_id]
    assert json.loads(live.read_text(encoding="utf-8"))["generation"] == 1
    assert not tx.staging.exists()


def test_recovery_reports_a_run_it_cannot_finish(tmp_path):
    tx = RunTransaction(tmp_path)
    tx.stage_state(V.STATE_NAME, {"a": 1})
    (tx.staging / INTENT_NAME).write_text(tx.run_id + "\n", encoding="utf-8")   # no manifest
    out = recover(tmp_path)
    assert out["failed"] and out["failed"][0]["run_id"] == tx.run_id
    assert last_status(tmp_path, run_id=tx.run_id) == RECOVERY_REQUIRED


def test_abandon_refuses_past_the_point_of_no_return(tmp_path):
    tx = RunTransaction(tmp_path)
    tx.stage_state(V.STATE_NAME, {"a": 1})
    tx.abandon()
    assert not tx.staging.exists()

    tx2 = RunTransaction(tmp_path)
    tx2.stage_state(V.STATE_NAME, {"a": 1})
    (tx2.staging / INTENT_NAME).write_text("x", encoding="utf-8")
    with pytest.raises(CommitError):
        tx2.abandon()


# ------------------------------------------------------------------ R-301 end to end
def test_r301_a_failed_instruction_write_does_not_advance_the_state(tmp_path, monkeypatch):
    """R-301 — phase 3.1/3.3. Pre-fix `save_state()` ran before the sheet was
    written, so a sheet failure left the book advanced with nothing to execute."""
    out1 = V.run(tmp_path, capital=100000.0, fetch_fn=_fetch, rank_fn=_rank_real, silent=True)
    before = json.loads((tmp_path / V.STATE_NAME).read_text(encoding="utf-8"))
    assert before["last_run_date"] == out1["today"]

    def boom(*a, **k):
        raise OSError("disk full while writing the instruction sheet")

    monkeypatch.setattr(V, "render_instructions", boom)
    with pytest.raises(OSError):
        V.run(tmp_path, fetch_fn=_fetch, rank_fn=_rank_real, silent=True)

    after = json.loads((tmp_path / V.STATE_NAME).read_text(encoding="utf-8"))
    assert after == before, "the previous state must stay byte-identical"


def test_r301_a_failed_state_stage_also_leaves_the_sheet_alone(tmp_path, monkeypatch):
    """The other order: the sheet must not land on its own either."""
    V.run(tmp_path, capital=100000.0, fetch_fn=_fetch, rank_fn=_rank_real, silent=True)
    sheets_before = sorted(p.name for p in tmp_path.glob("instructions_*"))
    state_before = (tmp_path / V.STATE_NAME).read_text(encoding="utf-8")

    real_stage = RunTransaction.stage_state

    def boom(self, name, state):
        raise OSError("disk full while staging the state")

    monkeypatch.setattr(RunTransaction, "stage_state", boom)
    with pytest.raises(OSError):
        V.run(tmp_path, fetch_fn=_fetch, rank_fn=_rank_real, silent=True)
    monkeypatch.setattr(RunTransaction, "stage_state", real_stage)

    assert sorted(p.name for p in tmp_path.glob("instructions_*")) == sheets_before
    assert (tmp_path / V.STATE_NAME).read_text(encoding="utf-8") == state_before


def test_r301_the_failure_is_recorded_and_needs_no_recovery(tmp_path, monkeypatch):
    V.run(tmp_path, capital=100000.0, fetch_fn=_fetch, rank_fn=_rank_real, silent=True)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(V, "render_instructions", boom)
    with pytest.raises(OSError):
        V.run(tmp_path, fetch_fn=_fetch, rank_fn=_rank_real, silent=True)
    monkeypatch.undo()

    # nothing was staged past the point of no return, so nothing needs recovering
    assert [p for p in pending_runs(tmp_path) if p["needs_recovery"]] == []
    assert recover(tmp_path)["recovered"] == []


def test_a_retry_after_a_failure_succeeds(tmp_path, monkeypatch):
    """Phase 3.7: the run is resumable by simply running it again."""
    V.run(tmp_path, capital=100000.0, fetch_fn=_fetch, rank_fn=_rank_real, silent=True)
    before = json.loads((tmp_path / V.STATE_NAME).read_text(encoding="utf-8"))

    def boom(*a, **k):
        raise OSError("transient disk error")

    monkeypatch.setattr(V, "render_instructions", boom)
    with pytest.raises(OSError):
        V.run(tmp_path, fetch_fn=_fetch, rank_fn=_rank_real, silent=True)
    monkeypatch.undo()

    out = V.run(tmp_path, fetch_fn=_fetch, rank_fn=_rank_real, silent=True)
    after = json.loads((tmp_path / V.STATE_NAME).read_text(encoding="utf-8"))
    assert out["run_status"] == COMMITTED
    assert after["last_run_date"] == before["last_run_date"]
    assert Path(out["instructions_md"]).exists()


# ------------------------------------------------------------------ R-303
def test_r303_the_run_has_an_operational_status(tmp_path):
    """R-303 — phase 9.7: planned -> instructions_written -> committed, on disk."""
    out = V.run(tmp_path, capital=100000.0, fetch_fn=_fetch, rank_fn=_rank_real, silent=True)
    assert out["run_id"]
    assert out["run_status"] == COMMITTED
    statuses = [r["status"] for r in read_journal(tmp_path) if r["run_id"] == out["run_id"]]
    assert statuses == [PLANNED, INSTRUCTIONS_WRITTEN, COMMITTED]


def test_run_refuses_to_plan_on_a_state_that_breaks_an_invariant(tmp_path):
    """Rule 10: a poisoned state on disk stops the run rather than being extended."""
    V.run(tmp_path, capital=100000.0, fetch_fn=_fetch, rank_fn=_rank_real, silent=True)
    path = tmp_path / V.STATE_NAME
    state = json.loads(path.read_text(encoding="utf-8"))
    state["sleeves"]["stocks"]["tranches"][0]["cash"] = float("inf")
    path.write_text(json.dumps(state).replace("Infinity", "1e999"), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        V.run(tmp_path, fetch_fn=_fetch, rank_fn=_rank_real, silent=True)
    assert "invariant" in str(exc.value)


def test_a_fake_engine_run_still_commits_transactionally(tmp_path):
    eng = FakeEngine()
    out = V.run(tmp_path, capital=100000.0, fetch_fn=_market, rank_fn=_rank, engine=eng, silent=True)
    assert out["run_status"] == COMMITTED
    assert (tmp_path / "runs.jsonl").exists()
    assert not (tmp_path / ".staging").exists() or not list((tmp_path / ".staging").iterdir())
