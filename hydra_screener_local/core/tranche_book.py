"""
Executable portfolio accounting (audit finding D). Used by the labs and by the v9 production engine.

The previous runners kept NOMINAL weights per tranche between renewals and compounded the mean
of tranche returns. That is an implicit, free rebalance across tranches at every step: with two
50% tranches, one long an asset that goes 100 -> 200 -> 100 and one in cash, the old arithmetic
reports +12.5% for a book that is worth exactly what it started with. This module tracks units,
cash and value per tranche so that:

- weights drift with prices; nothing is rebalanced unless a trade is recorded and charged;
- a renewal trades only the renewed tranche, with that tranche's own value (no cross-tranche
  transfers), and every buy/sell is listed and costed at `cost_bp` per side;
- the step return is the change in total book value, cash included;
- a name that stops printing prices is carried at its last price for up to `max_stale_bars`
  bars and then written off at that price (explicit policy; see `write_offs`).

Assumptions that are not obvious from the interface (review 337):
- a write-off is NOT a trade: converting the last price into cash costs 0; marking to zero
  instead is the pessimistic sensitivity (T20: -0.46 pp, TASK-338);
- staleness is aged at the step END, so a name without a print at its renewal bar cannot be
  sold there; it waits for a later print or for the write-off;
- target weights summing above 1 are renormalised to 1, below 1 leave cash (that is how
  vol-targeting and "off" ETF names get into the book);
- the renewed tranche's `held` set is what the caller uses for buy/hold buffers; run_sleeve
  ignores it (no buffer on the ETF sleeve by design);
- exposure() and P&L both value stale names at last price; n / distinct count units.

Pure python/pandas, no market data access: the labs pass prices in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


@dataclass
class Trade:
    step: int
    tranche: int
    ticker: str
    dollars: float          # signed: + buy, - sell
    price: float
    cost: float


@dataclass
class Tranche:
    cash: float
    units: Dict[str, float] = field(default_factory=dict)
    stale: Dict[str, int] = field(default_factory=dict)      # bars since a held name last printed
    last_px: Dict[str, float] = field(default_factory=dict)  # last price seen for each held name

    def value(self, px: pd.Series) -> float:
        v = self.cash
        for tk, u in self.units.items():
            p = px.get(tk, np.nan)
            if np.isfinite(p):
                v += u * p
        return float(v)

    def invested(self, px: pd.Series) -> float:
        return self.value(px) - self.cash


class TrancheBook:
    def __init__(self, k: int, cost_bp: float, capital: float = 1.0, max_stale_bars: int = 10):
        self.k = k
        self.bp = cost_bp / 10000.0
        self.tranches = [Tranche(cash=capital / k) for _ in range(k)]
        self.max_stale_bars = max_stale_bars
        self.trades: List[Trade] = []
        self.write_offs: List[dict] = []
        self.step = 0

    # ---------------------------------------------------------------- valuation
    def value(self, px: pd.Series) -> float:
        return float(sum(t.value(px) for t in self.tranches))

    def exposure(self, px: pd.Series) -> float:
        """Invested share of the book, valuing stale names at their last price like P&L does
        (review 337: value() dropped them and a fully-invested book read expo=0 during a carry)."""
        v = self.value_with_stale(px)
        cash = sum(t.cash for t in self.tranches)
        return float((v - cash) / v) if v > 0 else 0.0

    def held(self, k: int) -> set:
        return {tk for tk, u in self.tranches[k].units.items() if u > 0}

    def distinct(self) -> int:
        return len(set().union(*[self.held(k) for k in range(self.k)]))

    def n_positions(self) -> float:
        return float(np.mean([len(self.held(k)) for k in range(self.k)]))

    # ---------------------------------------------------------------- trading
    def rebalance(self, k: int, target_w: pd.Series, px: pd.Series) -> float:
        """Trade tranche k to `target_w` (weights of the tranche's own value, sum <= 1) at prices
        `px`. Names without a finite price cannot be traded and are left alone (their weight is
        excluded from the target). Returns one-way dollars traded (sum |trade| / 2)."""
        tr = self.tranches[k]
        v = tr.value(px)
        if v <= 0:
            return 0.0
        target_w = target_w[target_w > 0] if len(target_w) else pd.Series(dtype=float)
        tradeable = [tk for tk in target_w.index if np.isfinite(px.get(tk, np.nan)) and px.get(tk) > 0]
        target_w = target_w[tradeable]
        if target_w.sum() > 1.0 + 1e-12:
            target_w = target_w / target_w.sum()
        names = set(target_w.index) | set(tr.units)
        # costs come out of the tranche before sizing so cash never goes negative
        current = {tk: tr.units.get(tk, 0.0) * px.get(tk, np.nan) for tk in names}
        est_trade = sum(abs(float(target_w.get(tk, 0.0)) * v - (current[tk] if np.isfinite(current[tk]) else 0.0)) for tk in names)
        v_net = v - self.bp * est_trade
        traded = 0.0
        for tk in sorted(names):
            p = px.get(tk, np.nan)
            if not (np.isfinite(p) and p > 0):
                continue                                             # cannot trade what has no price
            cur = tr.units.get(tk, 0.0) * p
            tgt = float(target_w.get(tk, 0.0)) * v_net
            d = tgt - cur
            if abs(d) < 1e-12:
                continue
            cost = abs(d) * self.bp
            tr.units[tk] = tr.units.get(tk, 0.0) + d / p
            tr.last_px[tk] = float(p)
            if tr.units[tk] <= 1e-12:
                tr.units.pop(tk, None); tr.stale.pop(tk, None)
            tr.cash -= d + cost
            traded += abs(d)
            self.trades.append(Trade(self.step, k, tk, d, float(p), cost))
        tr.cash = float(tr.cash)
        return traded / 2.0

    def accrue_cash(self, rate_per_step: float):
        for tr in self.tranches:
            tr.cash *= (1.0 + rate_per_step)

    def age_stale(self, px: pd.Series):
        """Call once per step with the step's END prices: names without a price age; past the
        limit they are written off at their last valuation (recorded, not silent)."""
        for k, tr in enumerate(self.tranches):
            for tk in list(tr.units):
                p = px.get(tk, np.nan)
                if np.isfinite(p):
                    tr.stale.pop(tk, None)
                    tr.last_px[tk] = float(p)
                    continue
                tr.stale[tk] = tr.stale.get(tk, 0) + 1
                if tr.stale[tk] >= self.max_stale_bars:
                    last = tr.last_px.get(tk, np.nan)
                    proceeds = tr.units[tk] * last if np.isfinite(last) else 0.0
                    tr.cash += proceeds
                    self.write_offs.append(dict(step=self.step, tranche=k, ticker=tk, proceeds=float(proceeds)))
                    tr.units.pop(tk); tr.stale.pop(tk)

    def value_with_stale(self, px: pd.Series) -> float:
        """Value using last known prices for names that do not print at `px`."""
        v = 0.0
        for tr in self.tranches:
            v += tr.cash
            for tk, u in tr.units.items():
                p = px.get(tk, np.nan)
                if not np.isfinite(p):
                    p = tr.last_px.get(tk, np.nan)
                if np.isfinite(p):
                    v += u * p
        return float(v)


def run_book(idx_len: int, k: int, step: int, start: int, lag: int, cost_bp: float,
             price_at, target_fn, rate_at=None, max_stale_bars: int = 10, dates=None) -> pd.DataFrame:
    """Generic driver. At bar t (every `step` bars) tranche j%k is renewed with weights
    `target_fn(t, k_renew, held)` executed at bar e = t+lag; the step is measured from e to
    x = e+step. `price_at(i)` -> Series of prices at bar i; `rate_at(t)` -> annualised cash rate.
    Returns one row per step with gross/net/turnover/expo/n/distinct and per-name traded dollars."""
    book = TrancheBook(k, cost_bp, max_stale_bars=max_stale_bars)
    recs = []
    for j, t in enumerate(range(start, idx_len - step - lag - 1, step)):
        book.step = j
        kk = j % k
        e, x = t + lag, t + lag + step
        px_e, px_x = price_at(e), price_at(x)
        v_pre = book.value_with_stale(px_e)
        w = target_fn(t, kk, book.held(kk))
        before = len(book.trades)
        traded = book.rebalance(kk, w if w is not None else pd.Series(dtype=float), px_e)
        cost_paid = sum(tr.cost for tr in book.trades[before:])
        traded_by_name = {}
        for tr in book.trades[before:]:
            traded_by_name[tr.ticker] = traded_by_name.get(tr.ticker, 0.0) + abs(tr.dollars) / v_pre
        if rate_at is not None:
            book.accrue_cash(float(rate_at(t)) * step / 252.0)
        book.age_stale(px_x)
        v_x = book.value_with_stale(px_x)
        net = v_x / v_pre - 1.0 if v_pre > 0 else 0.0
        gross = net + (cost_paid / v_pre if v_pre > 0 else 0.0)
        recs.append(dict(date=dates[t] if dates is not None else t, gross=gross, net=net,
                         turnover=traded / v_pre if v_pre > 0 else 0.0,
                         expo=book.exposure(px_x), n=book.n_positions(), distinct=float(book.distinct()),
                         traded=traded_by_name, value=v_x))
    out = pd.DataFrame(recs).set_index('date')
    out.attrs['trades'] = len(book.trades)
    out.attrs['write_offs'] = book.write_offs
    return out
