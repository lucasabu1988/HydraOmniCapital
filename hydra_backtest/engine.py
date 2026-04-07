"""Backtest engine — pure function consumer of live signal logic.

This module imports signal-computation functions directly from
omnicapital_live.py (the live production engine). When a live function
depends on class state (self.broker, threads, etc.) we reimplement a
pure equivalent here with a docstring pointing to the source line.

The engine is state-machine-free: each backtest run is a single call
to run_backtest() that produces a BacktestResult. No globals, no I/O,
no mutation of shared state.
"""
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Dict, List, Tuple

import pandas as pd


@dataclass(frozen=True)
class BacktestState:
    """Mutable backtest state snapshot — immutable via frozen dataclass.

    Each per-day iteration produces a NEW BacktestState via _replace().
    This eliminates a class of bugs where one function accidentally mutates
    shared state that another function expected to be fixed.
    """
    cash: float
    positions: dict           # symbol -> PositionDict
    peak_value: float
    crash_cooldown: int
    portfolio_value_history: tuple  # immutable rolling history

    def _replace(self, **kwargs) -> 'BacktestState':
        return replace(self, **kwargs)


@dataclass(frozen=True)
class BacktestResult:
    """Result of a single backtest run.

    Contains everything needed to inspect, audit, or export the run.
    """
    config: dict
    daily_values: pd.DataFrame
    trades: pd.DataFrame
    decisions: list
    exit_events: list
    universe_size: Dict[int, int]
    started_at: datetime
    finished_at: datetime
    git_sha: str
    data_inputs_hash: str


# -----------------------------------------------------------------------------
# Pure-function helpers
# -----------------------------------------------------------------------------


def _mark_to_market(
    state: BacktestState,
    price_data: Dict[str, pd.DataFrame],
    date: pd.Timestamp,
) -> float:
    """Compute total portfolio value at the end of `date`.

    = cash + sum(shares * Close[date]) for each open position.
    If a position's price data is missing for `date`, falls back to the
    stored entry_price (so a temporarily stale symbol doesn't blow up).
    """
    pv = state.cash
    for symbol, pos in state.positions.items():
        df = price_data.get(symbol)
        if df is not None and date in df.index:
            price = float(df.loc[date, 'Close'])
        else:
            price = float(pos['entry_price'])
        pv += float(pos['shares']) * price
    return pv


def get_tradeable_symbols(
    pit_universe: Dict[int, List[str]],
    price_data: Dict[str, pd.DataFrame],
    date: pd.Timestamp,
    min_age_days: int = 63,
) -> List[str]:
    """Intersect PIT membership for this year with symbols that have:
      (a) price data available for `date`
      (b) at least `min_age_days` of price history prior to `date`
    """
    year = date.year
    candidates = pit_universe.get(year, [])
    tradeable = []
    for sym in candidates:
        df = price_data.get(sym)
        if df is None or date not in df.index:
            continue
        history_before_date = df.loc[:date]
        if len(history_before_date) < min_age_days:
            continue
        tradeable.append(sym)
    return tradeable
