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

from omnicapital_live import (
    _dd_leverage,
    compute_dynamic_leverage,
)


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


def get_current_leverage_pure(
    drawdown: float,
    portfolio_value_history: tuple,
    crash_cooldown: int,
    config: dict,
    spy_hist: pd.DataFrame,
) -> Tuple[float, int, bool]:
    """Pure equivalent of COMPASSLive.get_current_leverage.

    Source: omnicapital_live.py:1396. Returns (leverage, new_crash_cooldown,
    crash_active).

    Mirrors the live logic exactly, including the crash brake bypass of
    LEV_FLOOR at lines 1444-1446 of the live engine:

        if crash_brake_active:
            return target_lev           # bypass the floor
        return max(target_lev, config['LEV_FLOOR'])
    """
    # 1. DD scaling (tiered drawdown leverage)
    dd_lev = _dd_leverage(drawdown, config)
    crash_brake_active = False
    new_cooldown = crash_cooldown

    # 2. Crash brake — three pathways (cooldown active, 5d velocity, 10d velocity).
    # Mirror omnicapital_live.py:1412-1432 exactly.
    if crash_cooldown > 0:
        dd_lev = min(config['CRASH_LEVERAGE'], dd_lev)
        crash_brake_active = True
    elif len(portfolio_value_history) >= 5:
        current_val = portfolio_value_history[-1]
        val_5d = portfolio_value_history[-5]
        if val_5d > 0:
            ret_5d = (current_val / val_5d) - 1.0
            if ret_5d <= config['CRASH_VEL_5D']:
                dd_lev = min(config['CRASH_LEVERAGE'], dd_lev)
                new_cooldown = config['CRASH_COOLDOWN'] - 1
                crash_brake_active = True
        if not crash_brake_active and len(portfolio_value_history) >= 10:
            val_10d = portfolio_value_history[-10]
            if val_10d > 0:
                ret_10d = (current_val / val_10d) - 1.0
                if ret_10d <= config['CRASH_VEL_10D']:
                    dd_lev = min(config['CRASH_LEVERAGE'], dd_lev)
                    new_cooldown = config['CRASH_COOLDOWN'] - 1
                    crash_brake_active = True

    # 3. Vol targeting (scaled into [LEV_FLOOR, LEVERAGE_MAX] by the live fn)
    if spy_hist is not None and len(spy_hist) > 0:
        vol_lev = compute_dynamic_leverage(
            spy_hist,
            config['TARGET_VOL'],
            config['VOL_LOOKBACK'],
            config['LEV_FLOOR'],
            config['LEVERAGE_MAX'],
        )
    else:
        vol_lev = 1.0

    # 4. Final: minimum of DD-scaled and vol-targeted leverage.
    # Crash brake bypass: when the brake fires, do NOT clamp to LEV_FLOOR.
    target_lev = min(dd_lev, vol_lev)
    if crash_brake_active:
        return target_lev, new_cooldown, True
    return max(target_lev, config['LEV_FLOOR']), new_cooldown, False
