"""H-011 — the lever and the step-0 harness on synthetic data. No network, no lab cache."""
from __future__ import annotations

import os
import sys
import types

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import h011_vol_penalty as H  # noqa: E402
import redesign_lab as L  # noqa: E402

IDX = pd.bdate_range("2024-01-01", periods=320)
NAMES = [f"S{i:02d}" for i in range(60)]


def _panel(seed=11):
    """A Panels-shaped object with the attributes rank_day reads. Prices random-walk; the sector
    map is a plain dict so SectorMapper runs in fixed mode without any snapshot on disk."""
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
    P.SECTOR_MAPPER = L.SectorMapper(close.columns, {n: "Tech" for n in NAMES})
    P.SECTOR = P.SECTOR_MAPPER.map
    P.sector_at = P.SECTOR_MAPPER.at
    P.SECTOR_SOURCE = P.SECTOR_MAPPER.info
    return P


def _cfg(**over):
    c = dict(L.BASE)
    c.update(L.CONFIGS["T20"])
    c.update(over)
    return c


def test_the_lever_defaults_to_production_and_t20_raw_differs_only_by_it():
    assert L.BASE["risk_adjust"] is True
    assert {k: v for k, v in L.CONFIGS["T20_raw"].items() if k != "risk_adjust"} == L.CONFIGS["T20"]
    assert L.CONFIGS["T20_raw"]["risk_adjust"] is False


def test_with_the_lever_on_the_score_is_momentum_over_vol63_and_off_it_is_momentum():
    P = _panel()
    t = 300
    on = L.rank_day(P, t, _cfg())
    off = L.rank_day(P, t, _cfg(risk_adjust=False))
    assert on is not None and off is not None
    common = on.index.intersection(off.index)
    assert len(common) >= 30
    vol = P.VOL63.iloc[t].reindex(common)
    # boosts and the strict flag depend on RET10 / DIST20 / VRATIO, never on the score itself, so
    # they multiply both sides identically: the ratio of the two comps is exactly 1 / vol63
    ratio = (on.loc[common, "comp"] / off.loc[common, "comp"]).dropna()
    assert np.allclose(ratio.to_numpy(), (1.0 / vol.reindex(ratio.index)).to_numpy(), rtol=1e-9)
    # and the two rankings really differ (otherwise there is nothing to test)
    assert (on.loc[common, "comp"].rank() != off.loc[common, "comp"].rank()).any()


def test_step_row_pairs_the_same_pool_and_reports_both_legs():
    P = _panel()
    row = H.step_row(P, 300, _cfg())
    assert row is not None
    for k in ("control_spread", "raw_spread", "control_top", "raw_top", "top_overlap", "spearman", "pool"):
        assert k in row
    assert 0.0 <= row["top_overlap"] <= 1.0
    assert row["pool"] >= 30


def test_summarise_and_verdict_follow_the_pre_registered_rule():
    rng = np.random.default_rng(3)
    n = 120
    df = pd.DataFrame({
        "date": pd.bdate_range("2010-01-01", periods=n),
        "pool": 100, "spearman": 0.8, "top_overlap": 0.6,
        "control_top_vol": 0.3, "raw_top_vol": 0.4,
        "control_spread": rng.normal(0.0010, 0.01, n), "raw_spread": rng.normal(0.0010, 0.01, n),
        "control_top": rng.normal(0.0010, 0.002, n), "raw_top": rng.normal(0.0030, 0.002, n),
    })
    s = H.summarise(df, n=500)
    assert s["steps"] == n and s["top_diff_bp"] > 0 and s["top_diff_p05"] > 0
    assert H.verdict(s).startswith("PREDICTED SIGN")
    s["top_diff_bp"] = -1.0
    assert H.verdict(s).startswith("WRONG SIGN")
    s["top_overlap_mean"] = 0.99
    assert H.verdict(s).startswith("NOTHING TO GAIN")
    assert H.verdict({"steps": 0}) == "NO DATA"
