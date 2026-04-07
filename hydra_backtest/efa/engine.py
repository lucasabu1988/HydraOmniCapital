"""hydra_backtest.efa.engine — EFA passive trend backtest engine.

Pure functions only. Implements the regime gate inline (no pure
function exists in omnicapital_live.py to import — the logic lives
embedded in _manage_efa_position at omnicapital_live.py:2409).
"""
import subprocess
from datetime import datetime
from typing import Optional, Tuple

import pandas as pd

from hydra_backtest.data import compute_data_fingerprint
from hydra_backtest.engine import (
    BacktestResult,
    BacktestState,
    _get_exec_price,
    _mark_to_market,
)


# These two constants mirror omnicapital_live.py:264-266. If live ever
# changes them, this duplication is the only contract surface to update.
EFA_SYMBOL = 'EFA'
EFA_SMA_PERIOD = 200


def _efa_close_on(efa_data: pd.DataFrame, date: pd.Timestamp) -> Optional[float]:
    """Return EFA Close on `date`, or None if data unavailable."""
    if date not in efa_data.index:
        return None
    return float(efa_data.loc[date, 'Close'])


def _efa_above_sma200(
    efa_data: pd.DataFrame,
    date: pd.Timestamp,
) -> bool:
    """True if EFA closed above its 200-day SMA on `date`.

    Returns False when there is insufficient history (so the engine
    treats EFA as 'not held' before there are enough bars to compute
    the SMA — matches the live behavior in COMPASSLive._efa_above_sma200).
    """
    sliced = efa_data.loc[:date]
    if len(sliced) < EFA_SMA_PERIOD:
        return False
    close = float(sliced['Close'].iloc[-1])
    sma = float(sliced['Close'].iloc[-EFA_SMA_PERIOD:].mean())
    return close > sma


def apply_efa_decision(
    state: BacktestState,
    date: pd.Timestamp,
    i: int,
    efa_data: pd.DataFrame,
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[BacktestState, list, list]:
    """Pure equivalent of COMPASSLive._manage_efa_position for the
    standalone case (no recycling, no min-buy threshold, no 90% cap).

    Decision matrix:
        above_sma200 | held | action
        -------------+------+--------------------------------
        True         | no   | BUY 100% of cash
        True         | yes  | no-op
        False        | no   | no-op
        False        | yes  | SELL all (EFA_BELOW_SMA200)

    Returns (new_state, trades_list, decisions_list).
    """
    trades: list = []
    decisions: list = []

    above = _efa_above_sma200(efa_data, date)
    held = EFA_SYMBOL in state.positions
    commission_per_share = config.get('COMMISSION_PER_SHARE', 0.0035)

    new_positions = dict(state.positions)
    cash = state.cash

    # Case 1: above SMA200 and NOT held → BUY
    if above and not held:
        entry_price = _get_exec_price(
            EFA_SYMBOL, date, i, all_dates,
            {EFA_SYMBOL: efa_data}, execution_mode,
        )
        if entry_price is not None and entry_price > 0:
            # Compute affordable shares accounting for commission. Two-step
            # to avoid floating-point edge cases where cost+commission > cash
            # by a few cents.
            est_shares = int(cash / entry_price)
            if est_shares > 0:
                est_commission = est_shares * commission_per_share
                while (
                    est_shares > 0
                    and est_shares * entry_price + est_commission > cash
                ):
                    est_shares -= 1
                    est_commission = est_shares * commission_per_share
                if est_shares > 0:
                    cost = est_shares * entry_price
                    commission = est_shares * commission_per_share
                    cash -= cost + commission
                    new_positions[EFA_SYMBOL] = {
                        'symbol': EFA_SYMBOL,
                        'entry_price': entry_price,
                        'shares': est_shares,
                        'entry_date': date,
                        'entry_idx': i,
                        'days_held': 0,
                        'sub_strategy': 'passive_intl',
                        'sector': 'International Equity',
                        'entry_vol': 0.0,
                        'entry_daily_vol': 0.0,
                        'high_price': entry_price,
                    }
                    decisions.append({
                        'date': date,
                        'action': 'ENTRY',
                        'symbol': EFA_SYMBOL,
                        'shares': est_shares,
                    })

    # Case 2: NOT above SMA200 and held → SELL
    elif not above and held:
        pos = new_positions[EFA_SYMBOL]
        exit_price = _get_exec_price(
            EFA_SYMBOL, date, i, all_dates,
            {EFA_SYMBOL: efa_data}, execution_mode,
        )
        if exit_price is not None:
            shares = pos['shares']
            commission = shares * commission_per_share
            cash += shares * exit_price - commission
            pnl = (exit_price - pos['entry_price']) * shares - commission
            ret = (
                (exit_price / pos['entry_price'] - 1.0)
                if pos['entry_price'] > 0 else 0.0
            )
            trades.append({
                'symbol': EFA_SYMBOL,
                'entry_date': pos['entry_date'],
                'exit_date': date,
                'exit_reason': 'EFA_BELOW_SMA200',
                'entry_price': pos['entry_price'],
                'exit_price': exit_price,
                'shares': shares,
                'pnl': pnl,
                'return': ret,
                'sector': 'International Equity',
            })
            decisions.append({
                'date': date,
                'action': 'EXIT',
                'symbol': EFA_SYMBOL,
                'reason': 'EFA_BELOW_SMA200',
            })
            del new_positions[EFA_SYMBOL]

    # Cases 3 & 4 (above+held, not-above+not-held) → no-op

    new_state = state._replace(cash=cash, positions=new_positions)
    return new_state, trades, decisions


def _apply_efa_daily_costs(
    state: BacktestState,
    cash_yield_annual_pct: float,
) -> BacktestState:
    """Apply one trading day's cash yield. EFA has no leverage,
    no margin cost. Negative yields are ignored (fail-safe).
    """
    cash = state.cash
    if cash > 0 and cash_yield_annual_pct > 0:
        daily_rate = cash_yield_annual_pct / 100.0 / 252
        cash += cash * daily_rate
    return state._replace(cash=cash)


def _capture_git_sha() -> str:
    """Get current git commit sha, or 'unknown' if not in a repo."""
    try:
        out = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return 'unknown'
