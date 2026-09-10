"""H-016 — BOND identity with production's SLOW on IEF, the equity block, states, power gate and rule."""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import h015_fast_confirmation as H15  # noqa: E402
import h016_bond_cross_asset as H  # noqa: E402
import sleeve_lab as S  # noqa: E402

IDX = pd.bdate_range("2004-01-01", periods=700)


def _panel(seed=4):
    rng = np.random.default_rng(seed)
    drifts = np.linspace(-0.0004, 0.0012, len(S.UNIVERSE))
    rets = pd.DataFrame(rng.normal(0.0, 0.004, (len(IDX), len(S.UNIVERSE))) + drifts, index=IDX, columns=S.UNIVERSE)
    px = 100.0 * (1 + rets).cumprod()
    irx = pd.Series(0.03, index=IDX)
    return px, irx


def test_bond_is_production_s_slow_on_ief_number_for_number_and_state_for_state():
    px, irx = _panel()
    bond = H.bond_signal(px, irx)
    slow = H15.slow_signal(px, irx)
    assert bond.equals(slow["IEF"])
    tb12 = (irx / 252.0).rolling(252).sum()
    mom12 = px["IEF"] / px["IEF"].shift(252) - 1.0
    ref = (mom12 - tb12)
    ok = ref.notna()
    assert np.allclose(bond[ok].to_numpy(), ref[ok].to_numpy())
    assert ((bond[ok] > 0) == (ref[ok] > 0)).all()


def test_the_equity_block_and_the_untouched_block_partition_the_universe():
    assert set(H.EQUITY) | set(H.UNTOUCHED) == set(S.UNIVERSE)
    assert not set(H.EQUITY) & set(H.UNTOUCHED)
    assert H.BOND_PROXY == "IEF" and "VNQ" in H.EQUITY and "TLT" not in H.EQUITY


def test_step_row_states_and_that_only_equity_etfs_are_counted():
    px, irx = _panel()
    own, bond = H15.slow_signal(px, irx), H.bond_signal(px, irx)
    t = 400
    own2, bond2 = own.copy(), bond.copy()
    own2.iloc[t] = 0.1                                  # everyone ON, including TLT/GLD/DBC/IEF
    bond2.iloc[t] = -0.02
    row = H.step_row(px, own2, bond2, irx, t)
    assert row["state"] == "cross_bad" and row["equity_on"] == 6 and row["n_affected"] == 6
    ex = H15.forward_excess(px, irx, t)
    assert row["excess"] == pytest.approx(float(ex.reindex(list(H.EQUITY)).mean()))
    bond2.iloc[t] = 0.02
    assert H.step_row(px, own2, bond2, irx, t)["state"] == "cross_confirmed"
    own2.iloc[t] = -0.1                                 # no equity ETF ON -> outside the hypothesis
    assert H.step_row(px, own2, bond2, irx, t)["state"] is None
    own2.iloc[t] = 0.1
    bond2.iloc[t] = np.nan                              # IEF without 252 bars -> not eligible
    assert H.step_row(px, own2, bond2, irx, t)["state"] is None


def test_power_gate_and_rule():
    n = 200
    base = {"date": pd.bdate_range("2009-01-05", periods=n), "bond_defined": True, "bond": -0.01,
            "equity_on": 4, "n_affected": 4, "names": None}
    rng = np.random.default_rng(6)
    good = pd.concat([
        pd.DataFrame({**base, "state": "cross_bad", "excess": rng.normal(-0.006, 0.006, n)}),
        pd.DataFrame({**base, "bond": 0.01, "state": "cross_confirmed", "excess": rng.normal(0.004, 0.006, n)}),
    ], ignore_index=True)
    s = H.summarise(good, n=500)
    assert s["cross_bad_dates"] == n and s["cross_bad_excess_bp"] < 0 and s["ci_p95"] < 0
    assert s["confirmed_minus_bad_bp"] > 0
    assert H.verdict(s).startswith("X_bar < 0 with the 90 % upper bound below zero")
    beats_cash = pd.DataFrame({**base, "state": "cross_bad", "excess": rng.normal(0.004, 0.006, n)})
    assert H.verdict(H.summarise(beats_cash, n=500)).startswith("REJECTED: equity ETFs ON")
    weak = pd.DataFrame({**base, "state": "cross_bad", "excess": rng.normal(-0.0005, 0.01, n)})
    assert H.verdict(H.summarise(weak, n=500)).startswith("REJECTED")
    few = good[good["state"] == "cross_bad"].iloc[:129]
    assert H.verdict(H.summarise(few, n=500)).startswith("UNMEASURABLE")
    assert H.verdict({"cross_bad_dates": 0}).startswith("UNMEASURABLE")
