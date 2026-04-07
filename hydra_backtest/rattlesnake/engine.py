"""Rattlesnake mean-reversion backtest engine.

Pure-function consumer of rattlesnake_signals.py. Reuses v1.0
infrastructure: BacktestState, BacktestResult, _mark_to_market,
_get_exec_price, _slice_history_to_date.
"""
from datetime import datetime
import subprocess
from typing import Dict, List, Optional, Tuple

import pandas as pd

from hydra_backtest.data import compute_data_fingerprint
from hydra_backtest.engine import (
    BacktestResult,
    BacktestState,
    _get_exec_price,
    _mark_to_market,
    _slice_history_to_date,
)
from rattlesnake_signals import (
    R_MAX_HOLD_DAYS,
    R_MAX_POS_RISK_OFF,
    R_MAX_POSITIONS,
    R_POSITION_SIZE,
    R_UNIVERSE,
    R_VIX_PANIC,
    check_rattlesnake_exit,
    check_rattlesnake_regime,
    find_rattlesnake_candidates,
)


def _resolve_rattlesnake_universe(
    pit_universe: Dict[int, List[str]],
    year: int,
) -> List[str]:
    """Intersect R_UNIVERSE (S&P 100 hardcoded) with PIT S&P 500 for `year`.

    Drops survivorship bias from R_UNIVERSE without requiring fresh PIT
    S&P 100 data. Tickers in R_UNIVERSE that were never in S&P 500 are
    permanently excluded (rare edge case).
    """
    sp500_year = set(pit_universe.get(year, []))
    return sorted(t for t in R_UNIVERSE if t in sp500_year)


def apply_rattlesnake_exits(
    state: BacktestState,
    date: pd.Timestamp,
    i: int,
    price_data: Dict[str, pd.DataFrame],
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[BacktestState, list, list]:
    """Pure equivalent of COMPASSLive._check_rattlesnake_exits.

    Source: omnicapital_live.py:2040. Mirrors the live exit loop:
    iterate positions, call check_rattlesnake_exit, exit via _get_exec_price.

    Exit reasons get the 'R_' prefix to match the live trade tag at
    omnicapital_live.py:2080: 'R_PROFIT', 'R_STOP', 'R_TIME'.

    Returns (new_state, trades_list, decisions_list).
    """
    trades: list = []
    decisions: list = []
    cash = state.cash
    positions = dict(state.positions)

    for symbol in list(positions.keys()):
        pos = positions[symbol]
        df = price_data.get(symbol)
        if df is None or date not in df.index:
            continue
        current_price = float(df.loc[date, 'Close'])

        reason = check_rattlesnake_exit(
            symbol,
            pos['entry_price'],
            current_price,
            pos.get('days_held', 0),
        )
        if reason is None:
            continue

        # Resolve execution price (handles next-open mode + gap-through implicitly)
        exit_price = _get_exec_price(
            symbol, date, i, all_dates, price_data, execution_mode
        )
        if exit_price is None:
            continue  # cannot execute — position carries

        shares = pos['shares']
        proceeds = shares * exit_price
        commission = shares * config['COMMISSION_PER_SHARE']
        cash += proceeds - commission
        pnl = (exit_price - pos['entry_price']) * shares - commission
        exit_date = date if execution_mode == 'same_close' else all_dates[i + 1]
        exit_reason = f'R_{reason}'  # 'R_PROFIT' / 'R_STOP' / 'R_TIME'

        trades.append({
            'symbol': symbol,
            'entry_date': pos['entry_date'],
            'exit_date': exit_date,
            'exit_reason': exit_reason,
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'shares': shares,
            'pnl': pnl,
            'return': pnl / (pos['entry_price'] * shares) if pos['entry_price'] > 0 else 0.0,
            'sector': pos.get('sector', 'Unknown'),
        })
        decisions.append({
            'type': 'exit',
            'symbol': symbol,
            'date': str(date),
            'reason': exit_reason,
            'exit_price': exit_price,
        })
        del positions[symbol]

    new_state = state._replace(cash=cash, positions=positions)
    return new_state, trades, decisions


def apply_rattlesnake_entries(
    state: BacktestState,
    date: pd.Timestamp,
    i: int,
    price_data: Dict[str, pd.DataFrame],
    candidates: List[dict],
    max_positions: int,
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[BacktestState, list]:
    """Pure equivalent of COMPASSLive._open_rattlesnake_positions.

    Source: omnicapital_live.py:2092. Sized at 20% of the cash snapshot
    captured BEFORE the candidate loop (mirroring r_budget * R_POSITION_SIZE
    at omnicapital_live.py:2151). Uses INTEGER shares
    (omnicapital_live.py:2152).
    """
    decisions: list = []
    cash = state.cash
    positions = dict(state.positions)

    slots = max_positions - len(positions)
    if slots <= 0 or cash < 1000:
        return state, decisions

    # CRITICAL: capture initial_cash BEFORE the loop. All entries in this
    # call size against this fixed snapshot, NOT against decreasing cash.
    # This mirrors the live engine where r_budget is computed once via
    # compute_allocation() and reused for every candidate in the loop.
    initial_cash = cash

    for cand in candidates[:slots]:
        symbol = cand.get('symbol')
        if not symbol or symbol in positions:
            continue

        entry_price = _get_exec_price(
            symbol, date, i, all_dates, price_data, execution_mode
        )
        if entry_price is None or entry_price <= 0:
            continue

        position_value = initial_cash * R_POSITION_SIZE  # 20% of fixed snapshot
        shares = int(position_value / entry_price)       # INTEGER shares
        if shares < 1:
            continue

        cost = shares * entry_price
        commission = shares * config['COMMISSION_PER_SHARE']
        # Cash buffer check uses CURRENT cash (matching live which uses
        # portfolio.cash * 0.90 at omnicapital_live.py:2159)
        if cost + commission > cash * 0.90:
            continue

        # In next_open mode, the position is recorded at the fill bar (i+1),
        # so days_held counts forward correctly from the fill day.
        if execution_mode == 'next_open':
            effective_entry_date = all_dates[i + 1]
            effective_entry_idx = i + 1
        else:
            effective_entry_date = date
            effective_entry_idx = i

        positions[symbol] = {
            'symbol': symbol,
            'entry_price': entry_price,
            'shares': float(shares),
            'entry_date': effective_entry_date,
            'entry_idx': effective_entry_idx,
            'days_held': 0,
            'sector': 'Unknown',
            'entry_vol': 0.0,
            'entry_daily_vol': 0.0,
            'high_price': entry_price,
        }
        cash -= cost + commission
        decisions.append({
            'type': 'entry',
            'symbol': symbol,
            'date': str(effective_entry_date),
            'entry_price': entry_price,
            'shares': float(shares),
            'drop_pct': cand.get('drop_pct'),
            'rsi': cand.get('rsi'),
        })

    return state._replace(cash=cash, positions=positions), decisions


def _apply_rattlesnake_daily_costs(
    state: BacktestState,
    cash_yield_annual_pct: float,
) -> BacktestState:
    """Apply one trading day's cash yield. Rattlesnake has no leverage
    so there is no margin cost component.

    Negative yields are ignored (fail-safe — see v1.0 design §13.4 for the
    same behavior on the COMPASS side).
    """
    cash = state.cash
    if cash > 0 and cash_yield_annual_pct > 0:
        daily_rate = cash_yield_annual_pct / 100.0 / 252
        cash += cash * daily_rate
    return state._replace(cash=cash)
