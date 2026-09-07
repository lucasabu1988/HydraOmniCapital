"""Astra findings 01 / 08 / 10 — the three contracts that are NOT implemented yet.

These are Astra's probes with their assertions preserved verbatim, marked
`xfail(strict=True)` because the fixes are scoring / accounting-policy / selection changes and
wait for Lucas's approval (GROKBOARD rule 6). The pre-registration is
`.comms/astra-prereg-01-08-10.md`; the hypotheses are H-004 / H-005 / H-006 in
`.comms/hypotheses.md`.

`strict=True` is the point: this file is green while the defect stands and goes RED the moment
somebody changes the behaviour. Either direction is a signal that needs an action:

- a test flips to XPASS  -> the fix landed. Close the hypothesis in `.comms/hypotheses.md` with
  the measured numbers, update the pre-registration, and remove the xfail marker here.
- a test flips to FAIL for a different reason -> the fixture or the code path moved; re-derive
  the numbers with `python experiments/measure_astra_01_08_10.py` before touching the doc.

No network, no `state/`, no `data_cache/`, no `history/`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import portfolio_engine as E  # noqa: E402
from core.signals import generate_daily_candidates  # noqa: E402

COMMS = ROOT.parent / ".comms"
PREREG = COMMS / "astra-prereg-01-08-10.md"
REGISTER = COMMS / "hypotheses.md"
HYPOTHESES = ("H-004", "H-005", "H-006")


def _owned() -> dict:
    """Astra's fixture: one filled 10-unit position at 20.00 in stocks tranche 0."""
    s = E.new_state(8000, "2026-09-04")
    s["last_run_date"] = "2026-09-11"
    tr = s["sleeves"]["stocks"]["tranches"][0]
    tr.update(units={"AAA": 10.0}, last_px={"AAA": 20.0}, cash=800.0)
    s["ledger"] = [dict(exec_date="2026-09-08", sleeve="stocks", tranche=0,
       ticker="AAA", side="buy", units=10., price=20., dollars=200., cost=0., status="filled")]
    return s


# ----------------------------------------------------------------------- ASTRA-08 (H-005)
@pytest.mark.xfail(strict=True, reason="H-005 PROPOSED: staleness ages per mark() call, not per session")
def test_mark_same_date_does_not_write_off_after_ten_calls():
    s = _owned()
    for _ in range(10):
        E.mark(s, pd.Series({'AAA': np.nan}), pd.Series(dtype=float))
    assert s['sleeves']['stocks']['tranches'][0]['units'].get('AAA') == 10., s['write_offs']


# ----------------------------------------------------------------------- ASTRA-01 (H-004)
@pytest.mark.xfail(strict=True, reason="H-004 PROPOSED: stock_targets uses the quota, not the surviving count")
def test_zero_authoritative_recommendations_park_live_targets():
    idx = pd.bdate_range('2025-01-01', periods=300)
    t = np.arange(300)
    prices = pd.DataFrame({f'A{i}': 30*np.exp(.002*t+.02*np.sin(t*.8+i)) for i in range(60)}, index=idx)
    prices.iloc[-10:] *= .7
    spy = pd.Series(100*np.exp(.001*t), index=idx)
    vol = pd.DataFrame(1_000_000., index=idx, columns=prices.columns)
    ranking = generate_daily_candidates(prices, spy, vol, sector_map={x: 'Other' for x in prices},
                                        momentum_window='mom12_7')
    assert int(ranking['recommended'].sum()) == 0, 'fixture must veto every selected name'
    targets = E.stock_targets(ranking, set(), prices)
    assert targets.empty, {'recommended': 0, 'dynamic_count': int(ranking.recommended_count.iloc[0]),
                           'targets': targets.to_dict()}


# ----------------------------------------------------------------------- ASTRA-10 (H-006)
@pytest.mark.xfail(strict=True, reason="H-006 PROPOSED: the sector cap does not gate the buffer's keep loop")
def test_cap_holds_for_buffered_positions_after_sector_change():
    ranking = pd.DataFrame({'ticker': [f'A{i}' for i in range(10)], 'rank': range(1, 11),
        'sector': ['Technology']*6+['Energy']*4, 'reason': ['ok']*10})
    picked = E.select_tranche_names(ranking, 10, {f'A{i}' for i in range(6)}, 2.0, 5)
    count = sum(int(x[1:]) < 6 for x in picked)
    assert count <= 5, picked


# ----------------------------------------------------------------------- the doc is the deliverable
def test_prereg_and_register_stay_in_sync():
    """The three hypotheses must exist in BOTH the pre-registration and the register, and the
    register must still call them PROPOSED. Without this, closing one file and forgetting the
    other is invisible — which is exactly the failure the evidence protocol exists to prevent."""
    assert PREREG.is_file(), f"missing pre-registration: {PREREG}"
    assert REGISTER.is_file(), f"missing hypothesis register: {REGISTER}"
    prereg = PREREG.read_text(encoding="utf-8")
    register = REGISTER.read_text(encoding="utf-8")
    for h in HYPOTHESES:
        assert h in prereg, f"{h} not named in {PREREG.name}"
        row = [ln for ln in register.splitlines() if ln.strip().startswith(f"| {h} ")]
        assert len(row) == 1, f"{h} must have exactly one row in {REGISTER.name}, found {len(row)}"
        assert re.search(r"\bPROPOSED\b", row[0]), (
            f"{h} is no longer PROPOSED in {REGISTER.name}: a decision landed, so the xfail markers "
            f"in this file and {PREREG.name} need updating with the measured numbers"
        )
    for finding in ("ASTRA-01", "ASTRA-08", "ASTRA-10"):
        assert finding in prereg, f"{finding} not documented in {PREREG.name}"


def test_t20_is_bars_and_the_quota_floor_is_six():
    """Pins the three facts the ASTRA-10 doc correction rests on. Fix-agnostic: it holds before
    and after H-006, and goes red if somebody moves the clamp, `hold_bars` or the cap — at which
    point the 83.3% figure in the pre-registration is wrong and must be recomputed."""
    from config import MAX_PER_SECTOR, V9

    # "T20" is a 20-BAR tranche, not a 20-stock list. Nothing in v9 sizes a list at 20.
    assert V9["hold_bars"] == 20
    assert V9["tranches"] == 4 and V9["step_bars"] == 5
    assert V9["hold_bars"] == V9["tranches"] * V9["step_bars"]
    assert "positions" not in V9 and "n_stocks" not in V9

    # The quota is clamped to [6, 28] in core/signals.py; 14 is the BASE, not the floor.
    src = (ROOT / "core" / "signals.py").read_text(encoding="utf-8")
    assert "dynamic_count = max(6, min(dynamic_count, 28))" in src
    assert "base_recommendations = 14" in src
    spec = (ROOT / "HYDRA_ALGORITHM_SPEC.md").read_text(encoding="utf-8")
    assert "clamp( round(14 * overall_aggression * compass_mult) , 6, 28 )" in spec

    # So the sector cap is a share of the tranche that swings by 4.7x with the quota, and is
    # loosest exactly where aggression is lowest. There is no 25% anything.
    assert MAX_PER_SECTOR == 5
    assert round(MAX_PER_SECTOR / 6, 4) == 0.8333          # quota floor
    assert round(MAX_PER_SECTOR / 28, 4) == 0.1786         # quota ceiling
    doc = PREREG.read_text(encoding="utf-8")
    assert "83.3%" in doc and "20-BAR tranche" in doc
