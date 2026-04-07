"""hydra_backtest.catalyst.engine — Catalyst cross-asset trend backtest engine.

Pure functions only. Mirrors COMPASSLive._manage_catalyst_positions
(omnicapital_live.py:2196) without side effects.
"""
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

from catalyst_signals import (
    CATALYST_REBALANCE_DAYS,
    CATALYST_SMA_PERIOD,
    CATALYST_TREND_ASSETS,
    compute_trend_holdings,
)
from hydra_backtest.data import compute_data_fingerprint
from hydra_backtest.engine import (
    BacktestResult,
    BacktestState,
    _get_exec_price,
    _mark_to_market,
    _slice_history_to_date,
)


def _has_enough_history(
    asset_data: Dict[str, pd.DataFrame],
    ticker: str,
    date: pd.Timestamp,
) -> bool:
    """Return True if `ticker` has at least CATALYST_SMA_PERIOD bars on/before `date`."""
    df = asset_data.get(ticker)
    if df is None:
        return False
    return len(df.loc[:date]) >= CATALYST_SMA_PERIOD


def apply_catalyst_rebalance(
    state: BacktestState,
    date: pd.Timestamp,
    i: int,
    asset_data: Dict[str, pd.DataFrame],
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[BacktestState, list, list]:
    """Pure equivalent of COMPASSLive._manage_catalyst_positions.

    Side-effect-free rebalance. Computes trend_holdings via
    compute_trend_holdings, sells positions no longer in trend
    (exit_reason='CATALYST_TREND_OFF'), and buys new entrants OR adds to
    existing holdings if target_shares grew. Mirrors live's "no downsize"
    behavior (omnicapital_live.py:2270).

    Returns
    -------
    new_state, trades_list, decisions_list
    """
    trades: list = []
    decisions: list = []

    # 1. Slice history to `date` for the 4 trend assets only
    sliced = _slice_history_to_date(
        asset_data, date, symbols=list(CATALYST_TREND_ASSETS)
    )

    # 2. Belt-and-suspenders: drop assets without enough history
    #    (compute_trend_holdings already enforces this internally)
    sliced_eligible = {
        t: df for t, df in sliced.items()
        if _has_enough_history(asset_data, t, date)
    }
    trend_holdings = compute_trend_holdings(sliced_eligible)

    # 3. Equal-weight target value per holding
    portfolio_value = _mark_to_market(state, asset_data, date)
    per_asset = portfolio_value / len(trend_holdings) if trend_holdings else 0.0

    commission_per_share = config.get('COMMISSION_PER_SHARE', 0.0035)

    # 4. SELLS: positions no longer in trend (deterministic order via sorted)
    new_positions = dict(state.positions)
    cash = state.cash
    for sym in sorted(new_positions.keys()):
        if sym in trend_holdings:
            continue
        pos = new_positions[sym]
        exit_price = _get_exec_price(
            sym, date, i, all_dates, asset_data, execution_mode
        )
        if exit_price is None:
            # Cannot execute (last bar or missing data) — keep the position
            continue
        shares = pos['shares']
        commission = shares * commission_per_share
        proceeds = shares * exit_price - commission
        cash += proceeds
        pnl = (exit_price - pos['entry_price']) * shares - commission
        ret = (exit_price / pos['entry_price'] - 1.0) if pos['entry_price'] > 0 else 0.0
        trades.append({
            'symbol': sym,
            'entry_date': pos['entry_date'],
            'exit_date': date,
            'exit_reason': 'CATALYST_TREND_OFF',
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'shares': shares,
            'pnl': pnl,
            'return': ret,
            'sector': 'Catalyst',
        })
        decisions.append({
            'date': date,
            'action': 'EXIT',
            'symbol': sym,
            'reason': 'CATALYST_TREND_OFF',
        })
        del new_positions[sym]

    # 5. BUYS: new entrants and existing holdings whose target_shares grew
    for sym in sorted(trend_holdings):
        entry_price = _get_exec_price(
            sym, date, i, all_dates, asset_data, execution_mode
        )
        if entry_price is None or entry_price <= 0:
            continue
        target_shares = int(per_asset / entry_price)
        if target_shares <= 0:
            continue

        current_shares = new_positions[sym]['shares'] if sym in new_positions else 0
        needed = target_shares - current_shares
        if needed <= 0:
            # Mirrors live "no downsize" behavior (omnicapital_live.py:2270)
            continue

        cost = needed * entry_price
        commission = needed * commission_per_share
        if cash < cost + commission:
            # Not enough cash — buy what we can afford (rounded down)
            affordable = int((cash - commission) / entry_price) if entry_price > 0 else 0
            if affordable <= 0:
                continue
            needed = affordable
            cost = needed * entry_price
            commission = needed * commission_per_share
        cash -= cost + commission

        if sym in new_positions:
            existing = new_positions[sym]
            total_shares = existing['shares'] + needed
            weighted_entry = (
                (existing['shares'] * existing['entry_price'] + needed * entry_price)
                / total_shares
            )
            new_positions[sym] = {
                **existing,
                'shares': total_shares,
                'entry_price': weighted_entry,
                'high_price': max(existing.get('high_price', entry_price), entry_price),
            }
            decisions.append({
                'date': date,
                'action': 'ADD',
                'symbol': sym,
                'shares_added': needed,
            })
        else:
            new_positions[sym] = {
                'symbol': sym,
                'entry_price': entry_price,
                'shares': needed,
                'entry_date': date,
                'entry_idx': i,
                'days_held': 0,
                'sub_strategy': 'trend',
                'sector': 'Catalyst',
                'entry_vol': 0.0,
                'entry_daily_vol': 0.0,
                'high_price': entry_price,
            }
            decisions.append({
                'date': date,
                'action': 'ENTRY',
                'symbol': sym,
                'shares': needed,
            })

    new_state = state._replace(cash=cash, positions=new_positions)
    return new_state, trades, decisions
