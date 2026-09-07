"""reprint_sheet.py: whole-share view of pending orders, and proof that it writes nothing."""
import json

import reprint_sheet as R

STATE = {
    "capital_reference": 100000.0,
    "week_index": 0,
    "pending": [
        dict(sleeve="stocks", tranche=0, side="buy", ticker="AAA", dollars=323.88,
             est_units=1.4683, est_price=220.58, planned="2026-09-04", cost_bp=10.0, week=0),
        dict(sleeve="etf", tranche=0, side="buy", ticker="SPY", dollars=1286.92,
             est_units=1.6709, est_price=770.19, planned="2026-09-04", cost_bp=5.0, week=0),
    ],
}


def _write_state(tmp_path, state=None):
    p = tmp_path / "portfolio_v9.json"
    p.write_text(json.dumps(state if state is not None else STATE), encoding="utf-8")
    return p


def test_shares_are_floor_and_leftover_is_the_unspent_dollars(tmp_path):
    p = _write_state(tmp_path)
    pending, state = R.load_pending(p)
    text = R.render(pending, state)
    # 323.88 / 220.58 = 1.468 -> 1 share at 220.58, 103.30 unspent
    assert "| 1 | 220.58 | 103.30 |" in text
    # 1286.92 / 770.19 = 1.670 -> 1 share, 516.73 unspent
    assert "| 1 | 770.19 | 516.73 |" in text
    assert "stocks tranche 0: **103.30** USD" in text
    assert "etf tranche 0: **516.73** USD" in text
    assert "total: 620.03 USD" in text


def test_reading_never_mutates_the_state_file(tmp_path):
    p = _write_state(tmp_path)
    before = p.read_bytes()
    assert R.main(["--state", str(p)]) == 0
    assert p.read_bytes() == before


def test_out_refuses_to_overwrite_the_state(tmp_path):
    p = _write_state(tmp_path)
    before = p.read_bytes()
    assert R.main(["--state", str(p), "--out", str(p)]) == 1
    assert p.read_bytes() == before


def test_out_writes_the_markdown_elsewhere(tmp_path):
    p = _write_state(tmp_path)
    out = tmp_path / "sheet.md"
    assert R.main(["--state", str(p), "--out", str(out)]) == 0
    assert "whole shares" in out.read_text(encoding="utf-8")


def test_order_smaller_than_one_share_is_called_out(tmp_path):
    # 323.88 USD against a 1740 USD share: whole shares means no position at all
    state = dict(STATE, pending=[dict(STATE["pending"][0], ticker="SNDK", est_price=1740.0)])
    p = _write_state(tmp_path, state)
    pending, st = R.load_pending(p)
    text = R.render(pending, st)
    assert "Cannot be bought in whole shares" in text
    assert "**SNDK**: order 323.88 USD, one share 1740.00 USD" in text
    assert "confirm_fills.py" in text


def test_order_without_a_usable_price_is_listed_not_crashed(tmp_path):
    state = dict(STATE, pending=[dict(STATE["pending"][0], est_price=None)])
    p = _write_state(tmp_path, state)
    pending, st = R.load_pending(p)
    text = R.render(pending, st)
    assert "No usable estimated price" in text and "AAA" in text


def test_empty_pending_says_so(tmp_path):
    p = _write_state(tmp_path, dict(STATE, pending=[]))
    pending, st = R.load_pending(p)
    assert "No pending orders" in R.render(pending, st)


def test_missing_state_returns_one(tmp_path):
    assert R.main(["--state", str(tmp_path / "nope.json")]) == 1


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
