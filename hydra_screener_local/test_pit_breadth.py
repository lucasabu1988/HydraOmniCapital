"""ASTRA-06 — the lab's breadth universe must be point-in-time.

Astra's probe `test_breadth_does_not_include_future_universe_columns` (external audit
2026-09-06) showed that `core.regime.compute_rich_regime_scores` counts EVERY column of the
frame it is handed: a name with no observation on the date compares False against its own SMA
and still sits in the breadth denominator. Adding 50 all-NaN columns moved `overall` from
0.773 to 0.723 (breadth 1.0 -> 0.5).

The lab handed it `c.iloc[lo:t + 1]` — every column of a panel that is the union of every S&P
member 2004-2026 — so names that were not in the index at t, and columns with no history at
all, were setting the historical regime, hence aggression, hence `dynamic_count`, hence how
many names the lab bought. Production cannot have those columns: screener.py fetches today's
members and filters them before scoring.

The fix is in the lab (`redesign_lab.breadth_universe` / `Panels.breadth_universe`), not in
core: changing how core treats missing data would change the LIVE regime and therefore the
recommended list, which is GROKBOARD rule 6 (Lucas's approval). This file therefore asserts the
probe's property where the fix lives — the metamorphic form Lucas asked for: adding or removing
NON-MEMBER instruments at t must leave the regime, the dynamic count and the orders at t
bit-identical.

WHAT THIS FILE DOES NOT COVER. core/regime.py is still broken in exactly the way Astra measured.
The last section says so out loud: `test_DEFECT_core_regime_counts_unobserved_columns_in_breadth`
is an `xfail(strict=True)` written against the DESIRED behaviour, so it is red-in-waiting rather
than a test that passes because the code is wrong. It carries `@pytest.mark.defect`; the patch,
its measured effect and its kill criterion are in
`.comms/claude-astra06-core-proposal-2026-09-07.md` (hypothesis H-004), and Lucas decides.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.join(HERE, "experiments")
sys.path.insert(0, HERE)
sys.path.insert(0, LAB)

import core.portfolio_engine as E  # noqa: E402
from config import MAX_PER_SECTOR, V9  # noqa: E402
from core.regime import compute_rich_regime_scores  # noqa: E402

N_MEMBERS = 60
N_ROWS = 420
T = 400                      # the bar every assertion is made on
SECTORS = ["Technology", "Energy", "Healthcare", "Financials"]
CFG = dict(V9, stock_buffer=2.0)


# ----------------------------------------------------------------------------- synthetic panel
def _index():
    return pd.bdate_range("2004-01-02", periods=N_ROWS)


def _member_prices(idx):
    """60 deterministic members, drifts spread either side of zero so breadth is not degenerate."""
    rng = np.random.default_rng(20260906)
    out = {}
    for i in range(N_MEMBERS):
        drift = (i - 24) * 0.00015          # keeps every member above the $5 filter for 420 bars
        shocks = drift + rng.normal(0.0, 0.008, len(idx))
        out[f"M{i:02d}"] = 50.0 * np.exp(np.cumsum(shocks))
    return pd.DataFrame(out, index=idx)


def _non_members(idx, kind):
    """Instruments that are NOT in the index on any date of the panel.

    `nan`  — columns with no observation at all (a future member back-filled with nothing:
             exactly the shape Astra's probe used).
    `real` — columns with a full, hard-downtrending price history (a company that traded in
             2004 but only joined the index in 2015). These are the dangerous ones: dropna()
             keeps them, so a data-availability fix would not remove them.
    """
    rng = np.random.default_rng(7)
    out = {}
    if kind == "nan":
        for i in range(50):
            out[f"FUTURE{i:02d}"] = np.full(len(idx), np.nan)
    else:
        for i in range(30):
            shocks = -0.0025 + rng.normal(0.0, 0.010, len(idx))
            out[f"NONMEM{i:02d}"] = 300.0 * np.exp(np.cumsum(shocks))
    return pd.DataFrame(out, index=idx)


def _build(tmpdir, extra_kinds=(), drop_members=0):
    """A prepared lab panel whose PIT membership is exactly M00..M59 (minus `drop_members`).

    Written as pickles into `tmpdir` and loaded through the real loader, so the object under
    test is a real `bvs.Panels` with the real derived feature panels — no stubs.
    """
    import backtest_variant_sweep as bvs
    import redesign_lab as L

    idx = _index()
    close = _member_prices(idx)
    members = [c for c in close.columns][: N_MEMBERS - drop_members]
    frames = [close] + [_non_members(idx, k) for k in extra_kinds]
    close = pd.concat(frames, axis=1)
    volume = pd.DataFrame(2_000_000.0, index=idx, columns=close.columns)
    volume[close.isna()] = np.nan
    spy = pd.Series(100.0 * np.exp(np.cumsum(np.full(len(idx), 0.00035))), index=idx)

    os.makedirs(tmpdir, exist_ok=True)
    close.to_pickle(os.path.join(tmpdir, "close.pkl"))
    volume.to_pickle(os.path.join(tmpdir, "volume.pkl"))
    spy.to_frame("SPY").to_pickle(os.path.join(tmpdir, "spy.pkl"))

    payload = {"snapshots": {"2003-12-01": list(members)}}
    sector_map = {t: SECTORS[i % len(SECTORS)] for i, t in enumerate(close.columns)}
    P = bvs.Panels(cache_dir=tmpdir, pit_payload=payload)
    return L.prepare_panel(P, sectors=sector_map), members


@pytest.fixture(scope="module")
def panels(tmp_path_factory):
    root = tmp_path_factory.mktemp("astra06")
    return {
        "base": _build(str(root / "base")),
        "nan": _build(str(root / "nan"), extra_kinds=("nan",)),
        "real": _build(str(root / "real"), extra_kinds=("real",)),
        "both": _build(str(root / "both"), extra_kinds=("nan", "real")),
    }


# ----------------------------------------------------------------------------- observables at t
def _observables(P, t=T, cfg=None):
    """(regime, dynamic count, target weights) at bar t — the three things Lucas named.

    The weights come from production's own `core.portfolio_engine.stock_targets` fed the
    production-shaped ranking frame, i.e. the orders the tranche would send at t.
    """
    import redesign_lab as L

    c = dict(L.BASE)
    c.update(cfg or {})
    out = L.rank_day(P, t, c)
    assert out is not None, "the synthetic panel must produce a ranking at t"
    m = P.meta_for(t, c)
    n = max(6, min(int(round(14 * m.overall_aggression * m.pillar_multipliers["COMPASS"])), 28))
    rk = pd.DataFrame({"ticker": out.index, "rank": range(1, len(out) + 1),
                       "sector": out["sector"].values,
                       "reason": np.where(L.vetoed(out).values, "Vetado: gate", ""),
                       "recommended_count": n})
    w = E.stock_targets(rk, set(), P.close.iloc[:t + 1], CFG)
    return m.regime_score, n, w, out


def test_synthetic_panel_is_a_meaningful_fixture(panels):
    """Guard against a vacuous test: the fixture must actually exercise the machinery."""
    P, members = panels["base"]
    import redesign_lab as L
    c = dict(L.BASE)
    univ = L.breadth_universe(P, T, c)
    assert len(univ) > 30, "breadth is skipped (0.5) below 31 columns — the fixture would prove nothing"
    assert set(univ) <= set(members)
    regime, n, w, out = _observables(P)
    assert 0.0 < regime < 1.0 and 6 <= n <= 28 and len(w) > 0
    assert (out["sector"].value_counts() >= MAX_PER_SECTOR).any(), "the sector cap must be able to bind"


# ----------------------------------------------------------------------------- the probe, ported
@pytest.mark.parametrize("variant", ["nan", "real", "both"])
def test_non_member_instruments_do_not_move_regime_count_or_orders(panels, variant):
    """ASTRA-06 metamorphic property: adding instruments that were NOT members at t changes
    nothing observable at t. Bit-identical, not approximately — the regime feeds a threshold
    and an int(round()), so a 1e-9 drift is a different order list."""
    base_P, _ = panels["base"]
    var_P, _ = panels[variant]
    b_reg, b_n, b_w, b_out = _observables(base_P)
    v_reg, v_n, v_w, v_out = _observables(var_P)
    assert v_reg == b_reg, (variant, b_reg, v_reg)
    assert v_n == b_n, (variant, b_n, v_n)
    pd.testing.assert_series_equal(v_w.sort_index(), b_w.sort_index(), rtol=0, atol=0)
    pd.testing.assert_frame_equal(v_out.sort_index(), b_out.sort_index(), rtol=0, atol=0)


def test_removing_non_member_instruments_does_not_move_anything(panels):
    """The other direction of the metamorphic relation: dropping non-members is also a no-op."""
    both_P, _ = panels["both"]
    real_P, _ = panels["real"]
    assert _observables(real_P)[:2] == _observables(both_P)[:2]
    pd.testing.assert_series_equal(_observables(real_P)[2].sort_index(),
                                   _observables(both_P)[2].sort_index(), rtol=0, atol=0)


def test_dropping_a_real_member_does_move_the_regime(panels, tmp_path):
    """Sanity in the opposite direction: the breadth universe is not being ignored. Removing a
    real member from the point-in-time list must be visible, or the property above would hold
    for a `breadth=None` implementation too."""
    base_P, _ = panels["base"]
    fewer_P, _ = _build(str(tmp_path / "fewer"), drop_members=8)
    assert _observables(fewer_P)[0] != _observables(base_P)[0]


def test_the_masking_is_load_bearing(panels):
    """Without the mask the regime does move — this is the defect Astra measured, reproduced on
    the lab's own panel so the test above cannot pass for the wrong reason."""
    import redesign_lab as L
    both_P, _ = panels["both"]
    c = dict(L.BASE)
    lo, s = max(0, T - 300), both_P.spy.iloc[max(0, T - 300):T + 1]
    masked = compute_rich_regime_scores(s, both_P.close.loc[:, L.breadth_universe(both_P, T, c)].iloc[lo:T + 1])
    unmasked = compute_rich_regime_scores(s, both_P.close.iloc[lo:T + 1])          # the old lab behaviour
    assert unmasked.overall != masked.overall
    assert unmasked.breadth_proxy != masked.breadth_proxy


def test_dropna_is_not_a_substitute_for_membership(panels):
    """Why `dropna(axis=1)` over the window is not the fix, stated as an assertion.

    dropna answers "did this column have data", membership answers "was this company in the
    index". The all-NaN columns go either way, but a non-member with a full price history
    survives dropna and still poisons the historical breadth."""
    import redesign_lab as L
    both_P, _ = panels["both"]
    c = dict(L.BASE)
    lo = max(0, T - 300)
    window = both_P.close.iloc[lo:T + 1]
    dropna_cols = set(window.dropna(axis=1).columns)
    pit_cols = set(L.breadth_universe(both_P, T, c))
    assert any(x.startswith("NONMEM") for x in dropna_cols), "dropna keeps non-members with full history"
    assert not any(x.startswith(("NONMEM", "FUTURE")) for x in pit_cols)
    s = both_P.spy.iloc[lo:T + 1]
    by_dropna = compute_rich_regime_scores(s, window.dropna(axis=1))
    by_pit = compute_rich_regime_scores(s, both_P.close.loc[:, sorted(pit_cols)].iloc[lo:T + 1])
    assert by_dropna.overall != by_pit.overall


# ----------------------------------------------------------------------------- cache / config
def test_meta_cache_keys_on_the_filters_that_define_the_universe(panels):
    """One `Panels` is reused across every CONFIG of a --dev sweep. Now that breadth depends on
    the filter config, a cache keyed on `t` alone would serve config A's regime to config B."""
    P, _ = panels["base"]
    loose = P.meta_for(T, dict(min_dollar_vol=5e6))
    tight = P.meta_for(T, dict(min_dollar_vol=1e15))       # nothing is eligible -> breadth skipped
    assert loose.regime_score != tight.regime_score
    assert P.meta_for(T, dict(min_dollar_vol=5e6)).regime_score == loose.regime_score


def test_breadth_off_still_reaches_the_no_breadth_path(panels):
    """`regime_breadth=False` (a real config lever) must still bypass breadth entirely, and the
    legacy positional-bool call signature must keep working for the parity tests."""
    P, _ = panels["base"]
    off = P.meta_for(T, dict(regime_breadth=False))
    assert off.regime_score != P.meta_for(T, dict(regime_breadth=True)).regime_score
    assert P.meta_for(T, False).regime_score == off.regime_score
    assert P.meta_for(T, True).regime_score == P.meta_for(T, dict(regime_breadth=True)).regime_score


# ----------------------------------------------------------------------------- sweep replica
def test_sweep_replica_is_masked_too(panels, tmp_path):
    """`experiments/backtest_variant_sweep.py` carries the same regime call and the same defect;
    its Panels.meta_for must be invariant to non-member columns as well."""
    import backtest_variant_sweep as bvs
    base_P, _ = panels["base"]
    both_P, _ = panels["both"]
    assert bvs.Panels.meta_for(both_P, T).regime_score == bvs.Panels.meta_for(base_P, T).regime_score
    assert set(base_P.breadth_universe(T)) == set(both_P.breadth_universe(T))


# --------------------------------------------------------------- core: a LIVE DEFECT, not coverage
#
# Below are the two tests that speak about core/regime.py. Read the difference:
#
#   test_core_regime_breadth_reference_on_a_clean_frame  -- real coverage. Pins the documented
#       output of SPEC 4.3 on a WELL-FORMED frame. It must stay green.
#   test_DEFECT_core_regime_counts_unobserved_columns_in_breadth  -- NOT coverage. It is an
#       xfail(strict=True) written against the DESIRED behaviour, so it is red-in-waiting: it
#       reports xfail while the defect is live and FAILS the day the defect is fixed, which is
#       the signal we want (the lab mask above then becomes belt-and-braces and the headline
#       numbers move). Never read a passing suite as "core's breadth is covered".
#
# Marked `@pytest.mark.defect` (registered in pytest.ini): `pytest -m defect` lists every
# known-broken behaviour this suite documents.


def test_core_regime_breadth_reference_on_a_clean_frame():
    """Reference values of SPEC 4.3 on a frame where every column has a full history.

    This is the baseline the defect test below is measured against, and it is the assertion that
    trips if anyone edits the regime formulas or the breadth blend (locked: GROKBOARD rule 6)."""
    idx = pd.bdate_range("2005-01-03", periods=260)
    t = np.arange(260)
    prices = pd.DataFrame({f"M{i}": 100 + t for i in range(50)}, index=idx)
    spy = pd.Series(100 + t * 0.1, index=idx)
    rr = compute_rich_regime_scores(spy, prices)
    assert (rr.overall, rr.breadth_proxy) == (0.773, 1.0), rr


@pytest.mark.defect
@pytest.mark.xfail(strict=True, reason=(
    "LIVE DEFECT (ASTRA-06 / H-004): core.regime counts a column with no observation on the date "
    "in the breadth denominator. NOT fixed here -- core/regime.py's treatment of missing data is "
    "GROKBOARD rule 6 (Lucas's explicit approval). The patch, its measured effect and its kill "
    "criterion are in .comms/claude-astra06-core-proposal-2026-09-07.md, registered as H-004. "
    "This test is written against the DESIRED behaviour on purpose: it xfails while the defect is "
    "live and turns RED the day the fix lands, so nobody has to remember to come back."))
def test_DEFECT_core_regime_counts_unobserved_columns_in_breadth():
    """DESIRED behaviour, asserted so the fix un-xfails this test. Currently xfail.

    Waiting on: Lucas's rule-6 approval of H-004 (.comms/claude-astra06-core-proposal-2026-09-07.md).

    Astra's probe (external audit 2026-09-06), verbatim: appending 50 columns with no observation
    at all must not move the regime, because a column with no price cannot be a market
    participant. Today it moves overall 0.773 -> 0.723 (breadth 1.0 -> 0.5): `NaN > sma` is False,
    and False sits in the denominator of `(...).mean()`.

    The lab is already immune -- the tests above assert that on the lab's own panel -- because
    ASTRA-06 restricted the frame handed to core to the point-in-time eligible universe. This
    test is about core itself, which the live screener calls directly (core/signals.py:195)."""
    idx = pd.bdate_range("2005-01-03", periods=260)
    t = np.arange(260)
    prices = pd.DataFrame({f"M{i}": 100 + t for i in range(50)}, index=idx)
    spy = pd.Series(100 + t * 0.1, index=idx)
    original = compute_rich_regime_scores(spy, prices)
    expanded = prices.assign(**{f"FUTURE{i}": np.full(len(idx), np.nan) for i in range(50)})
    after = compute_rich_regime_scores(spy, expanded)
    assert (after.overall, after.breadth_proxy) == (original.overall, original.breadth_proxy), (
        f"unobserved columns must not enter breadth: {original} -> {after}")


@pytest.mark.defect
def test_DEFECT_is_currently_unreachable_from_the_live_filter_chain():
    """Why the defect above is a latent risk and not a live wrong number today.

    Not an endorsement of the defect: it is the evidence that the minimal patch (drop columns with
    no observation on the date) cannot move the live recommended list, which is what makes it
    approvable. `screener.py` hands `core.signals.generate_daily_candidates` -- and therefore
    `compute_rich_regime_scores` -- the frame that came out of the filter chain, and the minimum
    price filter compares `prices.iloc[-1] >= 5.0`, which is False for NaN. So a column with no
    observation on the run date is already gone before the regime is computed.

    If this test ever fails, the live regime IS being computed over unobserved columns and the
    patch stops being cosmetic -- escalate, do not wait for the approval."""
    from core.filters import apply_data_quality_filter, apply_practical_filters, remove_zombie_tickers
    from config import FILTERS
    idx = pd.bdate_range("2005-01-03", periods=260)
    t = np.arange(260)
    frame = pd.DataFrame({f"M{i}": 100.0 + t for i in range(50)}, index=idx)
    frame["NOOBS"] = np.nan                                  # no observation, ever
    frame["GONE"] = np.where(t < 200, 100.0 + t, np.nan)     # traded, then stopped printing
    volumes = pd.DataFrame(3_000_000.0, index=idx, columns=frame.columns)
    assert FILTERS["min_price"] > 0, "the guarantee below rests on the minimum price filter"
    out, _ = apply_practical_filters(frame, volumes=volumes, min_avg_volume=FILTERS["min_avg_volume"],
                                     min_price=FILTERS["min_price"], max_price=FILTERS.get("max_price"),
                                     min_dollar_volume=FILTERS["min_dollar_volume"])
    out = remove_zombie_tickers(apply_data_quality_filter(out, max_abs_daily_return=1.0, lookback=252))
    assert "NOOBS" not in out.columns and "GONE" not in out.columns, list(out.columns)
    assert out.iloc[-1].notna().all(), "every surviving column prints on the run date"
