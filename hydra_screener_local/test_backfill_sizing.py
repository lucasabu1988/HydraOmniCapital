"""TASK-417 — backfill did.sizing from an instruction sheet into journal_paper.

No network. Does not import portfolio_v9. The 2026-09-10 assertion runs only when
the local paper book is present.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))

from backfill_sizing import apply_sizing, backfill  # noqa: E402
from core.sizing import sizing_summary  # noqa: E402

SHEET_ORDERS = [
    {"side": "buy", "ticker": "DBRG", "dollars": 328.40864047383866, "est_price": 15.920000076293945},
    {"side": "buy", "ticker": "SNDK", "dollars": 328.40864047383866, "est_price": 1692.5899658203125},
    {"side": "buy", "ticker": "LITE", "dollars": 328.40864047383866, "est_price": 935.70},
    {"side": "sell", "ticker": "AAA", "dollars": 200.0, "est_price": 30.0},
]


def _sheet(tmp_path, orders=None, date="2026-09-10"):
    p = tmp_path / f"instructions_{date.replace('-', '')}.json"
    p.write_text(json.dumps({"date": date, "orders": orders if orders is not None else SHEET_ORDERS}),
                 encoding="utf-8")
    return p


def test_apply_sizing_is_idempotent_on_the_same_record():
    sizing = {"n_buys": 1, "target_dollars": 1.0}
    rec, changed = apply_sizing({"date": "2026-09-10"}, sizing)
    assert changed and rec["did"]["sizing"] == sizing
    rec2, changed2 = apply_sizing(rec, sizing)
    assert not changed2 and rec2 == rec
    rec3, changed3 = apply_sizing(rec, {"n_buys": 2, "target_dollars": 2.0})
    assert changed3 and rec3["did"]["sizing"]["n_buys"] == 2


def test_backfill_writes_journal_paper_only_and_is_idempotent(tmp_path):
    sheet = _sheet(tmp_path)
    journal = tmp_path / "journal_paper"
    state = tmp_path / "state_paper"
    state.mkdir()
    (state / "portfolio_v9.json").write_text('{"untouched": true}', encoding="utf-8")
    path, rec, changed = backfill(sheet, journal)
    assert changed and path == journal / "2026-09-10.json"
    sz = rec["did"]["sizing"]
    expected = sizing_summary(SHEET_ORDERS)
    assert sz == expected
    assert sz["zero_share_names"] == ["LITE", "SNDK"]
    blob = path.read_text(encoding="utf-8")
    path2, rec2, changed2 = backfill(sheet, journal)
    assert path2 == path and not changed2
    assert path.read_text(encoding="utf-8") == blob
    assert list(journal.glob("*")) == [path]
    assert json.loads((state / "portfolio_v9.json").read_text(encoding="utf-8")) == {"untouched": True}


def test_backfill_repairs_an_existing_record_without_dropping_fields(tmp_path):
    sheet = _sheet(tmp_path)
    journal = tmp_path / "journal_paper"
    journal.mkdir()
    pointer = journal / "2026-09-10.json"
    pointer.write_text(json.dumps({"date": "2026-09-10", "book": {"total": 100000}, "did": {"n_orders": 26}}),
                       encoding="utf-8")
    _, rec, changed = backfill(sheet, journal)
    assert changed
    assert rec["book"]["total"] == 100000 and rec["did"]["n_orders"] == 26
    assert rec["did"]["sizing"]["n_zero_share"] == 2


REAL_SHEET = HERE / "state_paper" / "instructions_20260910.json"


@pytest.mark.skipif(not REAL_SHEET.exists(), reason="paper book not on this disk")
def test_real_20260910_sheet_matches_the_hand_figure():
    orders = json.loads(REAL_SHEET.read_text(encoding="utf-8"))["orders"]
    s = sizing_summary(orders)
    assert s["n_buys"] == 26
    assert s["target_dollars"] == 13378.59
    assert s["achievable_dollars"] == 11100.77
    assert s["loss_dollars"] == 2277.82
    assert s["loss_share"] == 0.1703
    assert s["zero_share_names"] == ["LITE", "SNDK"]
