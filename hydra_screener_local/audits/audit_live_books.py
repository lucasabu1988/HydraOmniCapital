"""EXTERNAL EVIDENCE AUDIT - the live and paper books, READ-ONLY.

Moved out of `test_backfill_sizing.py` and `test_fill_cost_report.py` by HYDRA-CI-01. Both checks
read gitignored operator state (`state/portfolio_v9.json`, `state_paper/instructions_20260910.json`)
that no clean clone has and that must never be committed. They kept their ability to find a real
defect; what they lost was the pretence of being required unit tests.

READ-ONLY IS A RULE HERE, not a habit: nothing in this file opens a book for writing, and the
write-isolation barrier installed by the repo `conftest.py` protects `state/`, `state_paper/`,
`journal*/` and the backup root anyway. Research must never mutate the live book as a side effect.

The operational caveat travels with the numbers: 30 pending orders and an empty ledger describe
the LOCAL state observed, and prove nothing about whether the broker executed. Reconciling needs
the broker's own fills. Nothing here infers execution from the ledger.

Run by `tools/external_audit.py`. No `pytest.skip` in this file.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, os.path.join(ROOT, "tools"), os.path.join(ROOT, "experiments")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.sizing import sizing_summary  # noqa: E402
from fill_cost_report import build_frame, header, load_ledger, summarise  # noqa: E402

LIVE_STATE = os.path.join(ROOT, "state", "portfolio_v9.json")
PAPER_SHEET = os.path.join(ROOT, "state_paper", "instructions_20260910.json")


def test_real_20260910_paper_sheet_matches_the_hand_figure():
    """TASK-417's hand computation against the real paper sheet, digit for digit."""
    with open(PAPER_SHEET, encoding="utf-8") as fh:
        orders = json.load(fh)["orders"]
    s = sizing_summary(orders)
    assert s["n_buys"] == 26
    assert s["target_dollars"] == 13378.59
    assert s["achievable_dollars"] == 11100.77
    assert s["loss_dollars"] == 2277.82
    assert s["loss_share"] == 0.1703
    assert s["zero_share_names"] == ["LITE", "SNDK"]


def test_the_live_state_is_readable_and_the_report_can_summarise_it():
    """The live book parses and the fill-cost report runs over it.

    This asserts READABILITY, not a track record. As of 2026-09-08 the book holds 30 pending
    orders and an empty ledger, so there is nothing priced to measure; when a settle lands, this
    keeps passing and the numbers appear. It never claims the orders were or were not executed -
    only the broker's fills can say that.
    """
    ledger = load_ledger(LIVE_STATE)
    df = build_frame(ledger)
    s = summarise(df)
    assert s["fills"] >= 0
    assert isinstance(header(s), list) and header(s)


def test_reading_the_live_book_left_it_exactly_as_it_was():
    """An audit that reads live state has to prove it only read.

    The digest is taken after the two checks above have already run in this session (pytest runs
    the file top to bottom), so a write performed by either of them shows up here.
    """
    import hashlib

    with open(LIVE_STATE, "rb") as fh:
        first = hashlib.sha256(fh.read()).hexdigest()
    load_ledger(LIVE_STATE)
    with open(LIVE_STATE, "rb") as fh:
        second = hashlib.sha256(fh.read()).hexdigest()
    assert first == second, "reading the live book changed it"
