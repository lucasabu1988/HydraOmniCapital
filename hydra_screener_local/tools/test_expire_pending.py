"""HYDRA-OPS-02: expiry reclassifies, moves no money, and unblocks the book.

Every case here is synthetic and lives under tmp_path. The one real-book fact it encodes is
the shape of the 2026-09-04 sheet - 30 buys, empty ledger - and it encodes it by BUILDING that
shape, not by reading `state/`.

The first test is the one that matters and the reason this tool exists rather than a
`confirm_fills` invocation: with an empty ledger, `units=0` has nothing to attach to.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import core.portfolio_engine as E  # noqa: E402
import expire_pending as X  # noqa: E402
from config import V9  # noqa: E402

CFG = dict(V9, tranches=2, step_bars=1, hold_bars=2, stock_cost_bp=0.0, etf_cost_bp=0.0)
DATES = pd.bdate_range("2026-09-04", periods=8)
REASON = "no executions took place; the 2026-09-04 sheet expired unexecuted (Lucas 2026-09-13)"


def _prices(cols, rows):
    return pd.DataFrame(rows, index=DATES[:len(rows)], columns=cols, dtype=float)


def _ranking(names):
    return pd.DataFrame({"ticker": names, "rank": range(1, len(names) + 1),
                         "sector": ["Other"] * len(names),
                         "recommended": [True] * len(names),
                         "reason": [""] * len(names),
                         "recommended_count": len(names)})


@pytest.fixture
def planned_book():
    """A book that planned and was never settled: orders pending, ledger empty. The live shape."""
    st = E.new_state(100000.0, "2026-09-04", CFG)
    px = _prices(["A", "B"], [[10.0, 20.0]])
    epx = _prices(["SPY"], [[100.0]])
    st, orders = E.plan(st, "2026-09-04", _ranking(["A", "B"]), px, epx, 0.0, CFG)
    assert st["pending"], "the fixture must actually leave orders pending"
    assert st["ledger"] == [], "the fixture must leave the ledger empty, like the live book"
    return st


# ------------------------------------------------- why confirm_fills is not the tool for this

def test_confirming_units_zero_cannot_answer_a_plan_that_was_never_settled(planned_book):
    """The finding OPS-02 exists for: an empty ledger is not a confirmation problem.

    `core/fills.py` needs a booked line to attach `units=0` to. The settle never ran, so every
    row is rejected - and a rejected confirmation leaves `pending` exactly as it was.
    """
    from core.fills import apply_confirmations
    rows = [dict(exec_date="2026-09-08", sleeve=o["sleeve"], tranche=o["tranche"],
                 ticker=o["ticker"], side=o["side"], units=0, price="", fee="")
            for o in planned_book["pending"]]
    result = apply_confirmations(copy.deepcopy(planned_book), rows)
    assert result["rejected"], "confirm_fills accepted rows against an empty ledger"
    assert any("no plan matches this key" in " ".join(r["errors"]) for r in result["rejected"])
    assert result["state"]["pending"], "the orders are still pending after the rejection"


# ----------------------------------------------------------------- the reclassification itself

def test_the_pending_orders_move_to_expired(planned_book):
    n = len(planned_book["pending"])
    rep = X.expire(planned_book, reason=REASON, today="2026-09-13")
    assert rep["expired"] == n
    assert planned_book["pending"] == []
    assert len(planned_book[X.EXPIRED_KEY]) == n


def test_every_field_of_every_order_survives(planned_book):
    before = copy.deepcopy(planned_book["pending"])
    X.expire(planned_book, reason=REASON, today="2026-09-13")
    for original, kept in zip(before, planned_book[X.EXPIRED_KEY], strict=True):
        for key, value in original.items():
            assert kept[key] == value, f"expiry altered {key} of {original['ticker']}"


def test_each_expired_order_says_when_why_and_who(planned_book):
    X.expire(planned_book, reason=REASON, today="2026-09-13", run_id="r-123")
    for rec in planned_book[X.EXPIRED_KEY]:
        assert rec["expired_on"] == "2026-09-13"
        assert rec["expired_reason"] == REASON
        assert rec["expired_run_id"] == "r-123"
        assert set(rec["expired_by"]) == {"user", "host"}
        assert rec["expired_at_utc"].startswith("20")
        assert "never executed" in rec["expired_note"]


def test_nothing_economic_moves(planned_book):
    """The claim of the whole tool, asserted field by field rather than trusted."""
    before = X._fingerprint(planned_book)
    X.expire(planned_book, reason=REASON, today="2026-09-13")
    assert X._differences(before, X._fingerprint(planned_book)) == []


def test_no_ledger_event_is_invented(planned_book):
    X.expire(planned_book, reason=REASON, today="2026-09-13")
    assert planned_book["ledger"] == [], "expiry booked something; nothing was ever executed"
    assert planned_book.get("transfers") == []


def test_the_tranche_opened_mark_is_left_alone(planned_book):
    """The tranche really WAS renewed: a plan ran and a sheet was issued. Only the fills are missing."""
    opened = planned_book["sleeves"]["stocks"]["tranches"][0]["opened"]
    assert opened == "2026-09-04"
    X.expire(planned_book, reason=REASON, today="2026-09-13")
    assert planned_book["sleeves"]["stocks"]["tranches"][0]["opened"] == opened


def test_the_renewal_schedule_is_untouched(planned_book):
    week, anchor = planned_book["week_index"], planned_book["anchor_date"]
    X.expire(planned_book, reason=REASON, today="2026-09-13")
    assert (planned_book["week_index"], planned_book["anchor_date"]) == (week, anchor)


# --------------------------------------------------------------------- the book is unblocked

def test_the_engine_refuses_to_plan_while_the_orders_are_pending(planned_book):
    """Half of the point: this is the state the live book was stuck in."""
    px = _prices(["A", "B"], [[10.0, 20.0], [11.0, 21.0]])
    epx = _prices(["SPY"], [[100.0], [101.0]])
    with pytest.raises(RuntimeError, match="not settled"):
        E.plan(planned_book, "2026-09-05", _ranking(["A", "B"]), px, epx, 0.0, CFG)


def test_after_expiry_the_engine_can_plan_again(planned_book):
    """The other half. If this passes without the test above, expiry proved nothing."""
    X.expire(planned_book, reason=REASON, today="2026-09-13")
    px = _prices(["A", "B"], [[10.0, 20.0], [11.0, 21.0]])
    epx = _prices(["SPY"], [[100.0], [101.0]])
    state, orders = E.plan(planned_book, "2026-09-05", _ranking(["A", "B"]), px, epx, 0.0, CFG)
    assert state["pending"] == orders


# ------------------------------------------------------------------------------- the refusals

@pytest.mark.parametrize("reason", ["", "   ", "expired", "typo"])
def test_a_reason_that_says_nothing_is_refused(planned_book, reason):
    with pytest.raises(X.ExpiryRefused, match="must say what expired and why"):
        X.expire(planned_book, reason=reason, today="2026-09-13")


def test_a_plan_that_has_not_reached_its_execution_day_is_refused(planned_book):
    with pytest.raises(X.ExpiryRefused, match="has not reached its execution day"):
        X.expire(planned_book, reason=REASON, today="2026-09-04")


def test_a_plan_that_was_partly_settled_is_refused_and_names_the_right_tool(planned_book):
    planned_book["ledger"].append(dict(planned="2026-09-04", sleeve="stocks", tranche=0,
                                       ticker="A", side="buy", units=1.0, price=10.0,
                                       exec_date="2026-09-05", status="presumed"))
    with pytest.raises(X.ExpiryRefused) as exc:
        X.expire(planned_book, reason=REASON, today="2026-09-13")
    assert "this plan WAS settled" in str(exc.value)
    assert "confirm_fills.py" in str(exc.value)


def test_unresolved_unfilled_obligations_are_refused(planned_book):
    planned_book["unfilled"] = [dict(ticker="A", sleeve="stocks", tranche=0, side="buy")]
    with pytest.raises(X.ExpiryRefused, match="unresolved obligation"):
        X.expire(planned_book, reason=REASON, today="2026-09-13")


def test_a_refusal_leaves_the_state_byte_identical(planned_book):
    before = json.dumps(planned_book, sort_keys=True, default=str)
    with pytest.raises(X.ExpiryRefused):
        X.expire(planned_book, reason="no", today="2026-09-13")
    assert json.dumps(planned_book, sort_keys=True, default=str) == before


def test_every_broken_premise_is_reported_not_just_the_first(planned_book):
    planned_book["unfilled"] = [dict(ticker="A")]
    with pytest.raises(X.ExpiryRefused) as exc:
        X.expire(planned_book, reason="no", today="2026-09-04")
    msg = str(exc.value)
    assert "must say what expired" in msg
    assert "has not reached its execution day" in msg
    assert "unresolved obligation" in msg


# -------------------------------------------------------------------------------- idempotence

def test_nothing_pending_is_a_no_op_and_not_an_error(planned_book):
    X.expire(planned_book, reason=REASON, today="2026-09-13")
    again = X.expire(planned_book, reason=REASON, today="2026-09-13")
    assert again["no_op"] is True and again["expired"] == 0


def test_a_second_expiry_appends_and_never_replaces(planned_book):
    first = len(planned_book["pending"])
    X.expire(planned_book, reason=REASON, today="2026-09-13")
    planned_book["pending"] = [dict(sleeve="etf", tranche=1, ticker="SPY", side="buy",
                                    dollars=1.0, est_units=1.0, est_price=1.0,
                                    planned="2026-09-11", week=1, cost_bp=5.0)]
    X.expire(planned_book, reason=REASON, today="2026-09-13")
    assert len(planned_book[X.EXPIRED_KEY]) == first + 1
    assert {r["planned"] for r in planned_book[X.EXPIRED_KEY]} == {"2026-09-04", "2026-09-11"}


# --------------------------------------------------------------------------------- the CLI

@pytest.fixture
def live_dir(tmp_path, planned_book, monkeypatch):
    """A throwaway `state/` plus a throwaway backup root marked as a test destination."""
    from core import backup as B
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "portfolio_v9.json").write_text(json.dumps(planned_book), encoding="utf-8")
    (state_dir / "instructions_20260904.json").write_text('{"orders": []}', encoding="utf-8")
    (state_dir / "instructions_20260904.md").write_text("# sheet\n", encoding="utf-8")
    backups = tmp_path / "offdisk"
    B.mark_test_destination(backups)
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(backups))
    import journal
    monkeypatch.setattr(journal, "DEFAULT_DIR", tmp_path / "journal")
    return state_dir


def _run(state_dir, *extra):
    return X.main(["--state-dir", str(state_dir), "--today", "2026-09-13", *extra])


def test_the_dry_run_reports_and_writes_nothing(live_dir, capsys):
    before = (live_dir / "portfolio_v9.json").read_bytes()
    assert _run(live_dir, "--reason", REASON) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "-> expired" in out
    assert (live_dir / "portfolio_v9.json").read_bytes() == before


def test_a_refused_run_exits_two_and_writes_nothing(live_dir, capsys):
    before = (live_dir / "portfolio_v9.json").read_bytes()
    assert _run(live_dir, "--reason", "no", "--apply") == 2
    assert "refusing to expire" in capsys.readouterr().out
    assert (live_dir / "portfolio_v9.json").read_bytes() == before


def test_apply_takes_a_verified_generation_of_the_PRE_change_book_first(live_dir, capsys):
    from core import backup as B
    before = json.loads((live_dir / "portfolio_v9.json").read_text(encoding="utf-8"))
    assert _run(live_dir, "--reason", REASON, "--apply") == 0
    gen = Path(str(live_dir.parent / "offdisk" / "state_v9" / "20260913"))
    assert B.is_complete(gen), "no verified generation was written"
    saved = json.loads((gen / "portfolio_v9.json").read_text(encoding="utf-8"))
    assert saved["pending"] == before["pending"], "the backup holds the POST-change book"
    assert len(saved["pending"]) == len(before["pending"]) > 0


def test_apply_with_no_backup_destination_aborts_rather_than_writing(live_dir, monkeypatch,
                                                                     capsys):
    monkeypatch.delenv("HYDRA_BACKUP_DIR", raising=False)
    before = (live_dir / "portfolio_v9.json").read_bytes()
    assert _run(live_dir, "--reason", REASON, "--apply") == 3
    assert "ABORT" in capsys.readouterr().out
    assert (live_dir / "portfolio_v9.json").read_bytes() == before


def test_no_backup_is_an_explicit_decision_that_still_works(live_dir, monkeypatch):
    monkeypatch.delenv("HYDRA_BACKUP_DIR", raising=False)
    assert _run(live_dir, "--reason", REASON, "--apply", "--no-backup") == 0
    after = json.loads((live_dir / "portfolio_v9.json").read_text(encoding="utf-8"))
    assert after["pending"] == [] and after["expired"]


def test_apply_writes_the_state_a_journal_entry_and_a_verbatim_copy(live_dir, tmp_path):
    assert _run(live_dir, "--reason", REASON, "--apply") == 0
    after = json.loads((live_dir / "portfolio_v9.json").read_text(encoding="utf-8"))
    assert after["pending"] == []
    assert len(after["expired"]) > 0

    verbatim = json.loads((live_dir / "expired_20260913.json").read_text(encoding="utf-8"))
    assert verbatim == after["expired"], "the side copy must match what went into the state"

    records = list((tmp_path / "journal").glob("*.json"))
    assert records, "no journal revision was written"
    blob = " ".join(p.read_text(encoding="utf-8") for p in records)
    assert "HYDRA-OPS-02" in blob and "reclassified as expired" in blob


def test_the_state_still_passes_its_own_invariants_afterwards(live_dir):
    from core.ledger import check_invariants
    from core.state_check import check as check_state
    assert _run(live_dir, "--reason", REASON, "--apply") == 0
    after = json.loads((live_dir / "portfolio_v9.json").read_text(encoding="utf-8"))
    assert check_invariants(after) == []
    errors = [f for f in check_state(after) if f.level == "ERROR"]
    assert errors == [], f"expiry left the state failing its own check: {errors}"
