"""Hand-computable checks for experiments/tranche_book.py (audit finding D).

Run: python -m pytest experiments/test_tranche_book.py -q
"""
import numpy as np
import pandas as pd
import pytest

from tranche_book import TrancheBook, run_book


def _prices(table):
    """table: {ticker: [p0, p1, ...]} -> price_at(i)"""
    df = pd.DataFrame(table, dtype=float)
    return lambda i: df.iloc[i], len(df)


def test_reference_case_two_tranches_is_flat_not_plus_12_5():
    # tranche 0 buys A at 100 and is never renewed; tranche 1 stays in cash. A: 100 -> 200 -> 100.
    price_at, n = _prices({"A": [100, 200, 100, 100]})
    targets = {0: pd.Series({"A": 1.0}), 1: pd.Series(dtype=float)}
    df = run_book(n, k=2, step=1, start=0, lag=0, cost_bp=0.0, price_at=price_at,
                  target_fn=lambda t, k, held: targets[k])
    assert df["net"].iloc[0] == pytest.approx(0.50)            # 0.5 cash + 0.5 -> 1.0 in A
    assert df["net"].iloc[1] == pytest.approx(-1 / 3)          # 1.5 -> 1.0
    assert (1 + df["net"]).prod() == pytest.approx(1.0)        # units + cash: the book is flat
    assert df["turnover"].iloc[1] == 0.0                       # nothing traded in step 2
    # the old arithmetic (mean of tranche returns, compounded) says +12.5%
    old = (1 + np.mean([1.0, 0.0])) * (1 + np.mean([-0.5, 0.0])) - 1
    assert old == pytest.approx(0.125)


def test_costs_are_charged_on_every_dollar_traded_and_value_is_conserved():
    book = TrancheBook(k=1, cost_bp=10.0)
    px = pd.Series({"A": 50.0, "B": 20.0})
    v0 = book.value(px)
    traded = book.rebalance(0, pd.Series({"A": 0.5, "B": 0.5}), px)
    v1 = book.value(px)
    paid = sum(tr.cost for tr in book.trades)
    assert v0 - v1 == pytest.approx(paid)                      # value only changes by the costs paid
    assert paid == pytest.approx(2 * traded * 10 / 10000)      # one-way dollars * 2 sides * bp
    assert book.tranches[0].cash >= -1e-12
    assert len(book.trades) == 2 and {t.ticker for t in book.trades} == {"A", "B"}


def test_drift_is_not_rebalanced_for_free_and_a_reset_records_trades():
    book = TrancheBook(k=1, cost_bp=10.0)
    px0 = pd.Series({"A": 100.0, "B": 100.0})
    book.rebalance(0, pd.Series({"A": 0.5, "B": 0.5}), px0)
    px1 = pd.Series({"A": 200.0, "B": 100.0})                   # A doubles: weights drift to 2/3, 1/3
    tr = book.tranches[0]
    inv_a = tr.units["A"] * 200.0; inv_b = tr.units["B"] * 100.0
    assert inv_a / (inv_a + inv_b) == pytest.approx(2 / 3)
    n_before = len(book.trades)
    traded = book.rebalance(0, pd.Series({"A": 0.5, "B": 0.5}), px1)   # explicit reset to targets
    new = book.trades[n_before:]
    assert {t.ticker: np.sign(t.dollars) for t in new} == {"A": -1.0, "B": 1.0}
    assert traded == pytest.approx(sum(abs(t.dollars) for t in new) / 2)
    assert traded > 0


def test_renewal_sells_what_is_not_kept_and_buys_the_new_list_with_own_value():
    book = TrancheBook(k=2, cost_bp=0.0)
    px = pd.Series({"A": 10.0, "B": 10.0, "C": 10.0})
    book.rebalance(0, pd.Series({"A": 0.5, "B": 0.5}), px)
    book.rebalance(1, pd.Series({"C": 1.0}), px)
    px2 = pd.Series({"A": 20.0, "B": 10.0, "C": 10.0})
    v0_before = book.tranches[0].value(px2)                    # 0.75 (A doubled)
    book.rebalance(0, pd.Series({"B": 0.5, "C": 0.5}), px2)    # A leaves, C enters, B kept
    t0 = book.tranches[0]
    assert "A" not in t0.units
    assert t0.value(px2) == pytest.approx(v0_before)           # own value, zero cost
    assert t0.units["B"] * 10 == pytest.approx(0.5 * v0_before)
    assert book.tranches[1].value(px2) == pytest.approx(0.5)   # untouched tranche


def test_cash_earns_the_rate_and_uninvested_book_is_reported():
    price_at, n = _prices({"A": [100, 100, 100, 100]})
    df = run_book(n, k=1, step=1, start=0, lag=0, cost_bp=0.0, price_at=price_at,
                  target_fn=lambda t, k, held: pd.Series(dtype=float), rate_at=lambda t: 0.0252)
    assert df["net"].iloc[0] == pytest.approx(0.0252 / 252)
    assert df["expo"].iloc[0] == 0.0 and df["n"].iloc[0] == 0.0


def test_missing_price_is_carried_then_written_off_and_recorded():
    prices = pd.DataFrame({"A": [100.0] + [np.nan] * 6}, dtype=float)
    price_at = lambda i: prices.iloc[i]
    df = run_book(len(prices), k=1, step=1, start=0, lag=0, cost_bp=0.0, price_at=price_at,
                  target_fn=lambda t, k, held: pd.Series({"A": 1.0}) if t == 0 else pd.Series(dtype=float),
                  max_stale_bars=3)
    assert df["net"].iloc[0] == pytest.approx(0.0)             # carried at the last price, not zeroed
    assert df.attrs["write_offs"] and df.attrs["write_offs"][0]["ticker"] == "A"
    assert df["value"].iloc[-1] == pytest.approx(1.0)          # written off at the last price (policy: explicit)
