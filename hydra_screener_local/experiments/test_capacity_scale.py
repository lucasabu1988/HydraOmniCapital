"""F5 - scale homogeneity as an EXECUTABLE property, and the sidecar as an observer, on a full
synthetic drive of `engine_backtest.drive_engine`.

The pre-registration licenses "one drive at capital 1.0 -> 100 k / 500 k / 1 M by rescaling" only
if this passes: NAV_K / K == NAV_1, every fill's dollars / K equal, identical (settle, sleeve,
tranche, ticker, side) sets in identical order. If it ever fails, §2 of the prereg says three
drives, and the amendment goes on the board BEFORE anything else.
"""
from __future__ import annotations

import os
import sys
import types

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capacity as C  # noqa: E402
import engine_backtest as EB  # noqa: E402
import redesign_lab as L  # noqa: E402
from config import V9  # noqa: E402

IDX = pd.bdate_range("2019-01-01", periods=420)
NAMES = [f"S{i:02d}" for i in range(60)]   # rank_day returns None below ~60 eligible names


def _panel(seed=17):
    """Everything `drive_engine` and `rank_day` read, deterministic. Same shape as
    test_h011_vol_penalty._panel plus ETF / IRX / meta_for, which the engine drive needs."""
    rng = np.random.default_rng(seed)
    rets = pd.DataFrame(rng.normal(0.0004, 0.02, (len(IDX), len(NAMES))) * rng.uniform(0.5, 2.0, len(NAMES)),
                        index=IDX, columns=NAMES)
    close = 50.0 * (1 + rets).cumprod()
    P = types.SimpleNamespace()
    P.close = close
    P.rets = rets
    P.volume = pd.DataFrame(1_000_000.0, index=IDX, columns=NAMES)
    P.spy = close.mean(axis=1)
    P.VOL63 = rets.rolling(63).std() * np.sqrt(252)
    P.VOL20M = pd.DataFrame(1_000_000.0, index=IDX, columns=NAMES)
    P.FLAT5 = pd.DataFrame(0, index=IDX, columns=NAMES)
    P.RET10 = close / close.shift(10) - 1
    P.DIST20 = close / close.rolling(20).max() - 1
    P.VRATIO = pd.DataFrame(1.0, index=IDX, columns=NAMES)
    P.MOM = close.shift(5) / close.shift(95) - 1
    P.MOM_12_1 = close.shift(21) / close.shift(252) - 1
    P.MOM_6_1 = close.shift(21) / close.shift(126) - 1
    P.MOM_12_7 = close.shift(126) / close.shift(252) - 1
    P.ADV_USD = (close * P.volume).rolling(20).mean()
    P.JUMP252 = rets.abs().rolling(252, min_periods=20).max()
    P.ENS_PARTS = {lb: (close.shift(5) / close.shift(5 + lb) - 1) for lb in L.ENS_LOOKBACKS}
    P.CLOSE_ELIG = None
    P.ADV_USD_ELIG = None
    P.pit_payload = None
    P.SECTOR_MAPPER = L.SectorMapper(close.columns, {n: ("Tech" if i % 2 else "Health") for i, n in enumerate(NAMES)})
    P.SECTOR = P.SECTOR_MAPPER.map
    P.sector_at = P.SECTOR_MAPPER.at
    P.SECTOR_SOURCE = P.SECTOR_MAPPER.info
    etf_rets = pd.DataFrame(rng.normal(0.0003, 0.01, (len(IDX), len(V9["etf_universe"]))),
                            index=IDX, columns=list(V9["etf_universe"]))
    P.ETF = 100.0 * (1 + etf_rets).cumprod()
    P.IRX = pd.Series(0.02, index=IDX)
    P.meta_for = lambda t, c=None: types.SimpleNamespace(overall_aggression=1.0,
                                                          pillar_multipliers={"COMPASS": 1.0})
    return P


def _drive(capital: float):
    P = _panel()
    with C.FillTap() as tap:
        nav, counts = EB.drive_engine(P, progress_every=0, capital=capital)
    return nav, counts, tap.frame()


@pytest.fixture(scope="module")
def unit_drive():
    return _drive(1.0)


def test_the_synthetic_drive_actually_trades(unit_drive):
    nav, counts, fills = unit_drive
    assert len(nav) > 10 and counts["plans"] > 10
    assert len(fills) > 50, "no fills: the property below would be vacuous"
    assert set(fills["sleeve"]) == {"stocks", "etf"}


@pytest.mark.parametrize("K", [7.3, 1_000.0, 1_000_000.0])
def test_f5_the_engine_is_homogeneous_of_degree_one_in_capital(unit_drive, K):
    nav1, counts1, f1 = unit_drive
    navK, countsK, fK = _drive(K)
    pd.testing.assert_index_equal(nav1.index, navK.index)
    assert np.allclose(navK.to_numpy() / K, nav1.to_numpy(), rtol=1e-9, atol=0.0)
    keys = ["exec_date", "sleeve", "tranche", "ticker", "side"]
    assert f1[keys].to_dict("records") == fK[keys].to_dict("records"), (
        "the same decisions, in the same order - not merely the same totals")
    assert np.allclose(fK["dollars"].to_numpy() / K, f1["dollars"].to_numpy(), rtol=1e-9, atol=0.0)
    assert np.allclose(fK["cost"].to_numpy() / K, f1["cost"].to_numpy(), rtol=1e-9, atol=0.0)
    assert np.allclose(fK["units"].to_numpy() / K, f1["units"].to_numpy(), rtol=1e-9, atol=0.0)
    assert (fK["price"].to_numpy() == f1["price"].to_numpy()).all()
    for k in ("plans", "not_filled", "hold_no_price", "transfers", "write_offs"):
        assert counts1[k] == countsK[k]


def test_f5_fails_loudly_when_whole_shares_break_homogeneity(unit_drive):
    """The property is not vacuous: integer share sizes make the result depend on size (TASK-407),
    and the test above would catch it. Shown here at a tiny capital where rounding bites."""
    nav1, _, _ = unit_drive
    P = _panel()
    navW, _ = EB.drive_engine(P, progress_every=0, capital=1_000.0, whole_shares=True)
    assert not np.allclose(navW.to_numpy() / 1_000.0, nav1.to_numpy(), rtol=1e-9, atol=0.0)


def test_the_sidecar_does_not_change_the_path(unit_drive):
    """Sink on vs sink off: identical NAV and counts. The tap copies, it does not participate."""
    nav_on, counts_on, _ = unit_drive
    P = _panel()
    nav_off, counts_off = EB.drive_engine(P, progress_every=0, capital=1.0)
    pd.testing.assert_series_equal(nav_on, nav_off)
    for k in ("plans", "not_filled", "hold_no_price", "transfers", "write_offs", "turnover"):
        assert counts_on[k] == counts_off[k]


def test_the_sidecar_is_the_ledger_disaggregated(unit_drive):
    """Per-settle, per-sleeve sums of the sidecar equal what cost_stress._LedgerTap records on the
    same drive - nothing invented, nothing dropped."""
    import cost_stress as CS
    P = _panel()
    with CS._LedgerTap() as led, C.FillTap() as tap:
        EB.drive_engine(P, progress_every=0, capital=1.0)
    side = tap.frame()
    mine = side.groupby([side["exec_date"].dt.strftime("%Y-%m-%d"), "sleeve"])["dollars"].sum()
    theirs = {(d, s): rec["filled_dollars"] for d, sl in led.by_step.items() for s, rec in sl.items()
              if rec["filled_dollars"] > 0}
    assert set(mine.index) == set(theirs)
    for key, v in theirs.items():
        assert mine[key] == pytest.approx(v, rel=1e-12)
