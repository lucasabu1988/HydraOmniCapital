"""TASK-337 independent review of the executable simulator (commit 0d4f2e5).

Findings D (nominal tranche mean) and E (look-ahead mix weights). Review, do not
re-implement. Counterexamples against the OLD paths are on record here; new attacks
are hand-computed cases the author did not write. A failing assertion is a finding.

Run: python -m pytest experiments/test_review_337.py -q
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tranche_book import TrancheBook, run_book
from sleeve_lab import mix


def _prices(table):
    df = pd.DataFrame(table, dtype=float)
    return lambda i: df.iloc[i], len(df)


# ---------------------------------------------------------------------------
# D — old path on record
# ---------------------------------------------------------------------------

def test_D_old_mean_of_tranche_returns_is_plus_12_5_on_a_flat_book():
    """Reproduce the author's counterexample against the old arithmetic.

    Two 50% tranches, one long 100->200->100, one cash. Units+cash are flat.
    The pre-audit mean-of-tranche-returns compounds to +12.5%.
    """
    price_at, n = _prices({"A": [100, 200, 100, 100]})
    targets = {0: pd.Series({"A": 1.0}), 1: pd.Series(dtype=float)}
    df = run_book(n, k=2, step=1, start=0, lag=0, cost_bp=0.0, price_at=price_at,
                  target_fn=lambda t, k, held: targets[k])
    assert (1 + df["net"]).prod() == pytest.approx(1.0)
    old = (1 + np.mean([1.0, 0.0])) * (1 + np.mean([-0.5, 0.0])) - 1
    assert old == pytest.approx(0.125)
    assert df["net"].iloc[0] == pytest.approx(0.50)
    assert df["net"].iloc[1] == pytest.approx(-1 / 3)


# ---------------------------------------------------------------------------
# E — old combine on record (reconstructed from git 203c395)
# ---------------------------------------------------------------------------

def _old_combine(a, b, lookback=20):
    """Pre-audit combine(mode='rp'): rolling std includes the step being weighted."""
    df = pd.concat([a["net"].rename("a"), b["net"].rename("b")], axis=1).dropna()
    va = df["a"].rolling(lookback).std()
    vb = df["b"].rolling(lookback).std()
    w = (1 / va) / (1 / va + 1 / vb)
    w = w.fillna(0.5).clip(0.2, 0.8)
    net = w * df["a"] + (1 - w) * df["b"]
    out = pd.DataFrame({"net": net, "w_a": w}, index=df.index)
    return out


def test_E_old_combine_looks_ahead_and_new_mix_does_not():
    rng = np.random.default_rng(0)
    idx = pd.date_range("2010-01-01", periods=80, freq="7D")
    a = pd.DataFrame({"net": rng.normal(0.002, 0.02, 80)}, index=idx)
    b = pd.DataFrame({"net": rng.normal(0.001, 0.01, 80)}, index=idx)
    i = 40
    a2 = a.copy()
    a2.iloc[i, 0] = 0.5
    old = _old_combine(a, b)
    old_s = _old_combine(a2, b)
    assert old["w_a"].iloc[i] != pytest.approx(old_s["w_a"].iloc[i]), (
        "old combine should move the weight AT step i when only step i changes"
    )
    new = mix([a, b], "rp", lookback=20)
    new_s = mix([a2, b], "rp", lookback=20)
    pd.testing.assert_frame_equal(
        new[["w_0", "w_1"]].iloc[: i + 1], new_s[["w_0", "w_1"]].iloc[: i + 1]
    )


# ---------------------------------------------------------------------------
# New attacks on the book
# ---------------------------------------------------------------------------

def test_three_tranches_staggered_renewals_keep_own_value():
    """K=3, each tranche buys a different name on its first renewal; prices flat."""
    price_at, n = _prices({
        "A": [10, 10, 10, 10, 10, 10],
        "B": [10, 10, 10, 10, 10, 10],
        "C": [10, 10, 10, 10, 10, 10],
    })
    names = {0: "A", 1: "B", 2: "C"}
    df = run_book(n, k=3, step=1, start=0, lag=0, cost_bp=0.0, price_at=price_at,
                  target_fn=lambda t, k, held: pd.Series({names[k]: 1.0}))
    # after 3 renewals the book is fully invested, value conserved, each name held
    assert df["value"].iloc[2] == pytest.approx(1.0)
    assert df["distinct"].iloc[2] == 3
    assert (1 + df["net"]).prod() == pytest.approx(1.0)


def test_one_name_held_by_two_tranches_moves_both():
    price_at, n = _prices({"A": [100, 100, 200, 200]})
    df = run_book(n, k=2, step=1, start=0, lag=0, cost_bp=0.0, price_at=price_at,
                  target_fn=lambda t, k, held: pd.Series({"A": 1.0}))
    # t=0: tranche 0 buys A at 100 (0.5 of book), tranche 1 cash. End px=100, net 0.
    # t=1: tranche 1 buys A at 100; end px=200. Both tranches are long, book doubles.
    assert df["net"].iloc[1] == pytest.approx(1.0)
    assert df["value"].iloc[1] == pytest.approx(2.0)
    assert df["distinct"].iloc[1] == 1


def test_full_invested_target_with_10bp_does_not_go_cash_negative():
    book = TrancheBook(k=1, cost_bp=10.0)
    px = pd.Series({"A": 25.0, "B": 40.0, "C": 10.0})
    w = pd.Series({"A": 1 / 3, "B": 1 / 3, "C": 1 / 3})
    assert w.sum() == pytest.approx(1.0)
    book.rebalance(0, w, px)
    assert book.tranches[0].cash >= -1e-12
    assert book.value(px) < 1.0                          # costs came out of the book
    invested = sum(book.tranches[0].units[t] * px[t] for t in w.index)
    # leftover cash is the residual of cost-before-sizing (~1e-6 of book), not a short
    assert invested / book.value(px) == pytest.approx(1.0, abs=1e-5)


def test_nan_at_renewal_valid_at_step_end_is_carried_not_zeroed():
    """A prints 100 at t=0, NaN at the next renewal (t=1), 110 at the step end (t=2)."""
    price_at, n = _prices({"A": [100.0, np.nan, 110.0, 110.0]})
    df = run_book(n, k=1, step=1, start=0, lag=0, cost_bp=0.0, price_at=price_at,
                  target_fn=lambda t, k, held: pd.Series({"A": 1.0}))
    # step 0: buy at 100, end at NaN -> carried at 100, net 0
    assert df["net"].iloc[0] == pytest.approx(0.0)
    # step 1: renewal at NaN cannot trade; end at 110 -> +10%
    assert df["net"].iloc[1] == pytest.approx(0.10)
    assert df.attrs["write_offs"] == []


def test_partial_exposure_accrues_cash_on_the_idle_sleeve():
    price_at, n = _prices({"A": [100, 100, 100, 100]})
    df = run_book(n, k=1, step=1, start=0, lag=0, cost_bp=0.0, price_at=price_at,
                  target_fn=lambda t, k, held: pd.Series({"A": 0.4}),
                  rate_at=lambda t: 0.252)
    # 40% in A (flat), 60% cash earning 0.252/252 per step. Accrual happens before
    # expo is read, so expo is 0.4 / (1 + 0.6 * rate_step).
    rate_step = 0.252 / 252
    assert df["net"].iloc[0] == pytest.approx(0.6 * rate_step)
    assert df["expo"].iloc[0] == pytest.approx(0.4 / (1 + 0.6 * rate_step))


def test_renewal_that_keeps_every_name_at_unchanged_prices_has_near_zero_turnover():
    price_at, n = _prices({"A": [50, 50, 50, 50, 50, 50], "B": [50, 50, 50, 50, 50, 50]})
    w = pd.Series({"A": 0.5, "B": 0.5})
    df = run_book(n, k=1, step=1, start=0, lag=0, cost_bp=0.0, price_at=price_at,
                  target_fn=lambda t, k, held: w)
    assert df["turnover"].iloc[0] == pytest.approx(0.5)     # initial deployment
    assert df["turnover"].iloc[1] == pytest.approx(0.0)
    assert df["turnover"].iloc[2] == pytest.approx(0.0)


def test_exposure_includes_names_carried_at_last_price():
    """While a held name is stale (< max_stale_bars) P&L uses last_px, so expo must too.

    exposure() currently calls value() which drops NaN names, so a fully-invested
    book reports expo=0 during the carry. That is the attack.
    """
    prices = pd.DataFrame({"A": [100.0, np.nan, np.nan, 100.0]}, dtype=float)
    df = run_book(len(prices), k=1, step=1, start=0, lag=0, cost_bp=0.0,
                  price_at=lambda i: prices.iloc[i],
                  target_fn=lambda t, k, held: pd.Series({"A": 1.0}),
                  max_stale_bars=10)
    assert df["net"].iloc[0] == pytest.approx(0.0)           # carried, not zeroed
    assert df["expo"].iloc[0] == pytest.approx(1.0), (
        f"stale carry reported expo={df['expo'].iloc[0]} while the book is still long A at last_px"
    )


def test_cannot_exit_a_name_whose_renewal_print_is_missing():
    """Held A; next target is cash; A is NaN at the renewal bar. Left in the book
    (cannot trade). Documented; this records the size of the stuck position."""
    book = TrancheBook(k=1, cost_bp=0.0)
    book.rebalance(0, pd.Series({"A": 1.0}), pd.Series({"A": 100.0}))
    assert "A" in book.tranches[0].units
    book.rebalance(0, pd.Series(dtype=float), pd.Series({"A": np.nan}))
    assert "A" in book.tranches[0].units, "NaN renewal must not silently drop the position"
    # and must not invent a fill at last_px either
    assert book.tranches[0].cash == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Causality
# ---------------------------------------------------------------------------

def test_run_book_rows_do_not_depend_on_prices_after_the_step():
    base = pd.DataFrame({"A": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]})
    shocked = base.copy()
    shocked.loc[5, "A"] = 999.0                              # strictly after step 0..3 (x<=4)
    def run(px):
        return run_book(len(px), k=1, step=1, start=0, lag=0, cost_bp=0.0,
                        price_at=lambda i: px.iloc[i],
                        target_fn=lambda t, k, held: pd.Series({"A": 1.0}))
    a, b = run(base), run(shocked)
    # steps whose measurement end x = t+1 is <= 4 must match (t=0..3)
    for col in ("gross", "net", "turnover", "value"):
        pd.testing.assert_series_equal(a[col].iloc[:4], b[col].iloc[:4], check_names=False)


def test_mix_weights_and_nets_up_to_i_ignore_returns_after_i():
    rng = np.random.default_rng(1)
    idx = pd.date_range("2010-01-01", periods=60, freq="7D")
    a = pd.DataFrame({"net": rng.normal(0.001, 0.015, 60)}, index=idx)
    b = pd.DataFrame({"net": rng.normal(0.001, 0.010, 60)}, index=idx)
    i = 25
    shocked_a = a.copy()
    shocked_a.iloc[i + 1 :, 0] = 0.2
    base = mix([a, b], "rp", lookback=15)
    shocked = mix([shocked_a, b], "rp", lookback=15)
    pd.testing.assert_frame_equal(
        base[["w_0", "w_1", "net"]].iloc[: i + 1],
        shocked[["w_0", "w_1", "net"]].iloc[: i + 1],
    )
