"""HYDRA-CI-01: engine-vs-lab parity on a SYNTHETIC panel, so a clean clone runs it.

What this replaces and why
--------------------------
Three cases carried the whole parity contract and all three skipped unless the gitignored lab
caches happened to be on the machine:

    test_portfolio_engine.py::test_parity_stock_targets_with_redesign_lab   (experiments/_sweep_cache/)
    test_portfolio_engine.py::test_parity_etf_targets_with_sleeve_lab       (experiments/_sweep_cache_etf/)
    test_review_341.py::test_parity_stock_targets_reproduced                (experiments/_sweep_cache/)

They skipped in every CI run since they were written. What the cache actually supplied was the
INPUT (prices and a ranked frame), never the property: `redesign_lab.select` and
`redesign_lab.vetoed` import with no cache at all (measured), and the ETF rule is arithmetic on a
price frame. So the inputs are generated here, deterministically, and BOTH implementations stay
real:

    stocks : redesign_lab.select / .vetoed  vs  core.portfolio_engine.select_tranche_names,
             and the lab's own vol-scaling  vs  core.portfolio_engine.stock_targets
    etf    : the pre-registered rule as written in .comms/claude-sleeves-design-2026-09-06.md
             (12-month excess return over the accumulated T-bill, inverse-63d-vol normalised over
             the WHOLE eligible universe)  vs  sleeves.etf_trend.target_weights

A fixture that only reproduces the implementation proves nothing, so the generator is checked
against the branches it has to reach before any parity assertion is trusted: the sector cap must
bind, the veto must exclude, the buffer must keep a held name, and the exposure must be clipped on
some days and not on others. `test_the_fixture_reaches_the_branches_the_parity_depends_on` goes red
if the synthetic panel stops exercising any of them - that is, if this file ever degrades into a
tautology.

No committed fixture bytes: the panel comes from a seeded generator, so there is nothing to copy,
nothing private, and nothing that can go stale.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in (ROOT, os.path.join(ROOT, "experiments")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import redesign_lab as L  # noqa: E402
import core.portfolio_engine as E  # noqa: E402
from config import MAX_PER_SECTOR, V9  # noqa: E402
from sleeves.etf_trend import target_weights  # noqa: E402

SECTORS = ("Tech", "Health", "Energy", "Financials", "Utilities", "Other")
#: enough bars for the engine's 63-bar basket vol and the ETF sleeve's 252-bar lookback
N_BARS = 400
N_NAMES = 90
BUFFER = float(V9["stock_buffer"])
TARGET_VOL = float(V9["stock_target_vol"])


# --------------------------------------------------------------------------- the synthetic panel
def _prices(seed, n_names=N_NAMES, n_bars=N_BARS, columns=None):
    """Geometric random walk: a common market factor whose volatility ramps, plus idiosyncratic noise.

    The common factor is not decoration. Without it an equal-weight basket of 6..28 independent
    names diversifies to a 63-bar volatility far below `stock_target_vol`, `min(1, target/rv)` is
    1.0 on every single day, and the vol-scaling branch of the parity is never executed - measured:
    `clipped == 0` and the fixture guard below went red. The factor's annualised sigma ramps from
    4% to 35% across the panel, so early windows sit under the target and late ones over it, and
    both sides of the `min()` are exercised. Per-name sigma spans 8%..55% on top of that.
    """
    rng = np.random.default_rng(seed)
    cols = list(columns) if columns is not None else [f"T{i:03d}" for i in range(n_names)]
    idx = pd.bdate_range("2020-01-02", periods=n_bars)
    sigma = rng.uniform(0.08, 0.55, len(cols)) / np.sqrt(252)
    drift = rng.normal(0.0004, 0.0006, len(cols))
    steps = rng.normal(drift, sigma, size=(n_bars, len(cols)))
    factor_sigma = np.linspace(0.04, 0.35, n_bars) / np.sqrt(252)
    factor = rng.normal(0.0, 1.0, n_bars) * factor_sigma
    steps = steps + factor[:, None]
    px = 50.0 * np.exp(np.cumsum(steps, axis=0))
    return pd.DataFrame(px, index=idx, columns=cols)


def _ranking_frame(seed, names):
    """A lab-shaped ranked frame: the columns `select` and `vetoed` read, in descending `comp`.

    `ret` and `dist` are drawn so `redesign_lab.vetoed` fires on a real minority rather than on
    nobody or on everybody, and sectors are drawn so the hard cap can bind.
    """
    rng = np.random.default_rng(seed)
    comp = np.sort(rng.normal(0.0, 1.0, len(names)))[::-1]
    out = pd.DataFrame({
        "comp": comp,
        "ret": rng.normal(3.0, 14.0, len(names)),
        "dist": -np.abs(rng.normal(3.5, 4.0, len(names))),
        "vol": np.abs(rng.normal(0.30, 0.10, len(names))) + 0.05,
        "sector": rng.choice(SECTORS, len(names), p=[0.30, 0.22, 0.16, 0.16, 0.10, 0.06]),
    }, index=list(names))
    return out.sort_values("comp", ascending=False)


def _production_shaped(out, n):
    """The lab frame as production hands it to the engine: rank order, sector, veto as a reason."""
    return pd.DataFrame({
        "ticker": out.index,
        "rank": range(1, len(out) + 1),
        "sector": out["sector"].values,
        "reason": np.where(L.vetoed(out).values, "Vetado: gate", ""),
        "recommended_count": n,
    })


def _lab_weights(out, n, held, close):
    """The lab's own answer: select, then equal weight scaled by min(1, target_vol / basket vol63)."""
    sel = L.select(out, n, held, BUFFER)
    if not len(sel):
        return pd.Series(dtype=float), sel, 1.0
    rets = close[list(sel.index)].pct_change(fill_method=None).iloc[-63:]
    basket = rets.mean(axis=1)
    rv = float(basket.std(ddof=1)) * np.sqrt(252)
    expo = min(1.0, TARGET_VOL / rv) if rv > 0 else 1.0
    return pd.Series(expo / len(sel), index=sel.index), sel, expo


def _stock_days(seed0=1000, days=25):
    """One decision per synthetic day, with `held` carried forward exactly as a run would."""
    close = _prices(seed=7)
    names = list(close.columns)
    held = set()
    for k in range(days):
        out = _ranking_frame(seed0 + k, names)
        n = 6 + (k * 3) % 23                      # dynamic count sweeps the production range 6..28
        window = close.iloc[: 120 + k * 5]
        lab_w, sel, expo = _lab_weights(out, n, held, window)
        rk = _production_shaped(out, n)
        eng_w = E.stock_targets(rk, held, window,
                                dict(V9, stock_buffer=BUFFER, stock_target_vol=TARGET_VOL))
        yield dict(day=k, out=out, n=n, held=set(held), sel=sel, expo=expo,
                   lab_w=lab_w, eng_w=eng_w)
        held = set(sel.index)


# ----------------------------------------------------------------------- the fixture's own guard
def test_the_fixture_reaches_the_branches_the_parity_depends_on():
    """A synthetic panel that never binds the cap or the veto would make the parity vacuous.

    Each counter below is one branch the two implementations could disagree on. If the generator
    drifts and stops reaching one, this goes red BEFORE the parity assertions are trusted.
    """
    cap_bound = veto_excluded = buffer_kept = clipped = unclipped = 0
    for d in _stock_days():
        out, sel, n, held = d["out"], d["sel"], d["n"], d["held"]
        alive = out[~L.vetoed(out)]
        counts = sel["sector"].value_counts()
        if any(v >= MAX_PER_SECTOR for k, v in counts.items() if k != "Other"):
            cap_bound += 1
        vetoed_names = set(out.index[L.vetoed(out)])
        if vetoed_names and not (set(sel.index) & vetoed_names):
            veto_excluded += 1
        keep_zone = set(list(alive.index)[: int(round(BUFFER * n))])
        if held & keep_zone & set(sel.index):
            buffer_kept += 1
        if d["expo"] < 1.0:
            clipped += 1
        else:
            unclipped += 1
    assert cap_bound > 0, "the hard sector cap never bound: the cap branch is untested"
    assert veto_excluded > 0, "nothing was ever vetoed: the veto branch is untested"
    assert buffer_kept > 0, "no held name was ever kept by the buffer: the buffer branch is untested"
    assert clipped > 0, "exposure was never clipped: the vol-scaling branch is untested"
    assert unclipped > 0, "exposure was always clipped: the min(1, .) branch is untested"


# ------------------------------------------------------------------------------------- stocks
def test_parity_stock_targets_engine_matches_the_lab_selection_and_scaling():
    """Replaces test_parity_stock_targets_with_redesign_lab and test_parity_stock_targets_reproduced.

    The same comparison those made against the 13 MB cache: `redesign_lab.select` plus the lab's
    vol-scaling on one side, `core.portfolio_engine.stock_targets` on the other, bit for bit.
    """
    checked = 0
    for d in _stock_days():
        pd.testing.assert_series_equal(d["eng_w"].sort_index(), d["lab_w"].sort_index(),
                                       check_names=False, rtol=0, atol=1e-12)
        checked += 1
    assert checked >= 20, f"only {checked} days compared; the loop stopped early"


def test_parity_holds_when_every_name_is_vetoed_and_the_tranche_goes_to_tbill():
    """The boundary the cache never reached: both sides return an EMPTY series, not a fallback."""
    close = _prices(seed=11)
    out = _ranking_frame(2000, list(close.columns))
    out["ret"] = -20.0                                     # ret < 0 and dist under the gate
    out["dist"] = -30.0
    assert bool(L.vetoed(out).all()), "the fixture must veto every name or it proves nothing here"
    lab_w, sel, _ = _lab_weights(out, 20, set(), close)
    eng_w = E.stock_targets(_production_shaped(out, 20), set(), close, V9)
    assert len(sel) == 0 and lab_w.empty and eng_w.empty


def test_parity_holds_when_the_dynamic_count_is_zero():
    close = _prices(seed=12)
    out = _ranking_frame(2001, list(close.columns))
    lab_w, sel, _ = _lab_weights(out, 0, set(), close)
    eng_w = E.stock_targets(_production_shaped(out, 0), set(), close, V9)
    assert len(sel) == 0 and lab_w.empty and eng_w.empty


# ---------------------------------------------------------------------------------------- etf
def _etf_panel(seed=21):
    """Closes for the production ETF universe, plus a daily T-bill rate series."""
    names = list(V9["etf_universe"])
    close = _prices(seed=seed, columns=names, n_bars=N_BARS)
    tb_annual = pd.Series(np.linspace(0.005, 0.05, len(close.index)), index=close.index)
    return close, tb_annual / 252.0


def _etf_lab_weights(px, tb_daily, t):
    """The pre-registered rule, written out rather than called: the lab side of the parity."""
    lookback, vol_bars = int(V9["etf_lookback_bars"]), int(V9["etf_vol_bars"])
    rets = px.pct_change(fill_method=None)
    vol63 = rets.rolling(vol_bars).std() * np.sqrt(252)
    tb_acc = tb_daily.rolling(lookback).sum()
    mom = px / px.shift(lookback) - 1
    names = px.columns[(px.iloc[t].notna() & px.iloc[t - lookback].notna()).values]
    on = mom.iloc[t][names] - tb_acc.iloc[t] > 0
    iv = (1.0 / vol63.iloc[t][names]).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    base = iv / iv.sum()
    w = base * on.astype(float)
    return w[w > 0]


def test_parity_etf_targets_engine_matches_the_preregistered_rule():
    """Replaces test_parity_etf_targets_with_sleeve_lab; same rule, synthetic prices."""
    px, tb_daily = _etf_panel()
    checked, some_off, some_on = 0, 0, 0
    for t in range(300, len(px.index), 5):
        lab_w = _etf_lab_weights(px, tb_daily, t)
        eng_w = target_weights(px.iloc[: t + 1], tb_daily.iloc[: t + 1])
        pd.testing.assert_series_equal(eng_w.sort_index(), lab_w.sort_index(),
                                       check_names=False, rtol=0, atol=1e-12)
        checked += 1
        some_off += int(len(lab_w) < len(px.columns))
        some_on += int(len(lab_w) > 0)
    assert checked >= 20, f"only {checked} bars compared"
    assert some_off > 0, "every ETF was long on every bar: the T-bill gate was never exercised"
    assert some_on > 0, "no ETF was ever long: the inverse-vol weighting was never exercised"


def test_the_etf_sleeve_leaves_the_off_share_in_cash_rather_than_renormalising():
    """The half of the rule a same-shape reimplementation gets wrong: the weights sum to < 1 when
    some ETFs are off, because the base is normalised over the WHOLE eligible universe."""
    px, tb_daily = _etf_panel(seed=23)
    lookback = int(V9["etf_lookback_bars"])
    found = False
    for t in range(300, len(px.index), 3):
        w = target_weights(px.iloc[: t + 1], tb_daily.iloc[: t + 1])
        eligible = int((px.iloc[t].notna() & px.iloc[t - lookback].notna()).sum())
        if 0 < len(w) < eligible:
            assert float(w.sum()) < 1.0 - 1e-9, (
                f"bar {t}: {len(w)} of {eligible} ETFs long but the weights sum to {w.sum()!r}; "
                "the off share was renormalised away instead of being left in T-bill")
            found = True
    assert found, "no bar had a partial universe long: the exposure<1 property was never reached"


def test_an_etf_panel_shorter_than_the_lookback_is_empty_not_an_error():
    px, tb_daily = _etf_panel()
    short = px.iloc[: int(V9["etf_lookback_bars"])]
    assert target_weights(short, tb_daily.iloc[: len(short)]).empty
