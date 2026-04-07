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


def run_efa_backtest(
    config: dict,
    efa_data: pd.DataFrame,
    cash_yield_daily: pd.Series,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    execution_mode: str = 'same_close',
    progress_callback: Optional[callable] = None,
) -> BacktestResult:
    """Run an EFA passive trend backtest from start_date to end_date.

    Pure function: no side effects. Returns a BacktestResult compatible
    with v1.0 reporting/methodology layers (drop-in for build_waterfall).

    Universe is the single hardcoded ticker EFA_SYMBOL.
    """
    started_at = datetime.now()

    all_dates = sorted(efa_data.index)
    asset_dict = {EFA_SYMBOL: efa_data}  # _mark_to_market interface

    state = BacktestState(
        cash=float(config['INITIAL_CAPITAL']),
        positions={},
        peak_value=float(config['INITIAL_CAPITAL']),
        crash_cooldown=0,
        portfolio_value_history=(),
    )

    trades: list = []
    decisions: list = []
    snapshots: list = []
    universe_size: dict = {}

    last_progress_year: Optional[int] = None
    dates_in_range = [d for d in all_dates if start_date <= d <= end_date]
    total_bars = max(len(dates_in_range), 1)

    for i, date in enumerate(all_dates):
        if date < start_date or date > end_date:
            continue

        # Progress callback (first bar of each year)
        if progress_callback is not None and date.year != last_progress_year:
            last_progress_year = date.year
            try:
                pv_now = _mark_to_market(state, asset_dict, date)
                bars_done = sum(1 for d in dates_in_range if d < date)
                progress_callback({
                    'year': int(date.year),
                    'progress_pct': 100.0 * bars_done / total_bars,
                    'portfolio_value': float(pv_now),
                    'n_positions': len(state.positions),
                })
            except Exception:
                pass

        # 1. Mark-to-market
        portfolio_value = _mark_to_market(state, asset_dict, date)

        # 1b. Update peak BEFORE drawdown
        if portfolio_value > state.peak_value:
            state = state._replace(peak_value=portfolio_value)

        # 2. Universe size: 1 once SMA200 is computable, 0 before
        eligible = 1 if len(efa_data.loc[:date]) >= EFA_SMA_PERIOD else 0
        universe_size[date.year] = max(
            universe_size.get(date.year, 0), eligible
        )

        # 3. Drawdown
        drawdown = (
            (portfolio_value - state.peak_value) / state.peak_value
            if state.peak_value > 0 else 0.0
        )

        # 4. Daily cash yield
        if len(cash_yield_daily) > 0:
            daily_yield = float(
                cash_yield_daily.get(date, cash_yield_daily.iloc[0])
            )
        else:
            daily_yield = 0.0
        state = _apply_efa_daily_costs(state, daily_yield)

        # 5. Apply EFA decision (state-driven, daily, no cadence)
        above_sma_today = _efa_above_sma200(efa_data, date)
        state, day_trades, day_decisions = apply_efa_decision(
            state, date, i, efa_data, config, execution_mode, all_dates,
        )
        trades.extend(day_trades)
        decisions.extend(day_decisions)

        # 6. Snapshot AFTER decision
        pv_after = _mark_to_market(state, asset_dict, date)
        snapshots.append({
            'date': date,
            'portfolio_value': pv_after,
            'cash': state.cash,
            'n_positions': len(state.positions),
            'leverage': 1.0,            # EFA never uses leverage
            'drawdown': drawdown,
            'regime_score': 1.0 if above_sma_today else 0.0,
            'crash_active': False,
            'max_positions': 1,
            'above_sma_today': above_sma_today,
        })

        # 7. Update state tail: peak + days_held
        if pv_after > state.peak_value:
            state = state._replace(peak_value=pv_after)
        new_positions = {
            sym: {**p, 'days_held': p.get('days_held', 0) + 1}
            for sym, p in state.positions.items()
        }
        state = state._replace(
            positions=new_positions,
            portfolio_value_history=state.portfolio_value_history + (pv_after,),
        )

    # 8. Synthetic-close any remaining open position at backtest end
    if EFA_SYMBOL in state.positions and dates_in_range:
        last_date = dates_in_range[-1]
        last_i = all_dates.index(last_date)
        pos = state.positions[EFA_SYMBOL]
        exit_price = _get_exec_price(
            EFA_SYMBOL, last_date, last_i, all_dates, asset_dict, execution_mode,
        )
        if exit_price is None:
            exit_price = float(pos['entry_price'])
        shares = pos['shares']
        commission = shares * config.get('COMMISSION_PER_SHARE', 0.0035)
        pnl = (exit_price - pos['entry_price']) * shares - commission
        ret = (
            (exit_price / pos['entry_price'] - 1.0)
            if pos['entry_price'] > 0 else 0.0
        )
        trades.append({
            'symbol': EFA_SYMBOL,
            'entry_date': pos['entry_date'],
            'exit_date': last_date,
            'exit_reason': 'EFA_BACKTEST_END',
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'shares': shares,
            'pnl': pnl,
            'return': ret,
            'sector': 'International Equity',
        })

    finished_at = datetime.now()

    result_config = dict(config)
    result_config['_execution_mode'] = execution_mode

    trade_cols = [
        'symbol', 'entry_date', 'exit_date', 'exit_reason',
        'entry_price', 'exit_price', 'shares', 'pnl', 'return', 'sector',
    ]
    return BacktestResult(
        config=result_config,
        daily_values=pd.DataFrame(snapshots),
        trades=pd.DataFrame(trades) if trades else pd.DataFrame(columns=trade_cols),
        decisions=decisions,
        exit_events=[t for t in trades if t['exit_reason'] == 'EFA_BELOW_SMA200'],
        universe_size=universe_size,
        started_at=started_at,
        finished_at=finished_at,
        git_sha=_capture_git_sha(),
        data_inputs_hash=compute_data_fingerprint(asset_dict),
    )
