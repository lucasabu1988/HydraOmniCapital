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


def _apply_catalyst_daily_costs(
    state: BacktestState,
    cash_yield_annual_pct: float,
) -> BacktestState:
    """Apply one trading day's cash yield. Catalyst has no leverage,
    no margin cost. Negative yields are ignored (fail-safe — see v1.0
    design §13.4).
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


def run_catalyst_backtest(
    config: dict,
    asset_data: Dict[str, pd.DataFrame],
    cash_yield_daily: pd.Series,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    execution_mode: str = 'same_close',
    progress_callback: Optional[callable] = None,
) -> BacktestResult:
    """Run a Catalyst cross-asset trend backtest from start_date to end_date.

    Pure function: no side effects. Returns a BacktestResult compatible
    with v1.0 reporting/methodology layers (drop-in for build_waterfall).

    Universe is hardcoded as CATALYST_TREND_ASSETS (no PIT parameter).
    """
    started_at = datetime.now()

    # Aggregate trading dates from the union of all 4 ETFs
    all_dates_set = set()
    for df in asset_data.values():
        all_dates_set.update(df.index)
    all_dates = sorted(all_dates_set)

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
    universe_size: Dict[int, int] = {}

    catalyst_day_counter = 0
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
                pv_now = _mark_to_market(state, asset_data, date)
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
        portfolio_value = _mark_to_market(state, asset_data, date)

        # 1b. Update peak BEFORE drawdown
        if portfolio_value > state.peak_value:
            state = state._replace(peak_value=portfolio_value)

        # 2. Universe size = count of assets with enough history today
        eligible_today = sum(
            1 for t in CATALYST_TREND_ASSETS
            if _has_enough_history(asset_data, t, date)
        )
        universe_size[date.year] = max(
            universe_size.get(date.year, 0), eligible_today
        )

        # 3. Drawdown
        drawdown = (
            (portfolio_value - state.peak_value) / state.peak_value
            if state.peak_value > 0 else 0.0
        )

        # 4. Daily costs (cash yield only — Catalyst has no leverage)
        if len(cash_yield_daily) > 0:
            daily_yield = float(cash_yield_daily.get(date, cash_yield_daily.iloc[0]))
        else:
            daily_yield = 0.0
        state = _apply_catalyst_daily_costs(state, daily_yield)

        # 5. Rebalance check (every CATALYST_REBALANCE_DAYS or on first run)
        catalyst_day_counter += 1
        rebalance_today = False
        if catalyst_day_counter >= CATALYST_REBALANCE_DAYS or not state.positions:
            catalyst_day_counter = 0
            rebalance_today = True
            state, rb_trades, rb_decisions = apply_catalyst_rebalance(
                state, date, i, asset_data, config, execution_mode, all_dates,
            )
            trades.extend(rb_trades)
            decisions.extend(rb_decisions)

        # 6. Snapshot AFTER rebalance
        pv_after = _mark_to_market(state, asset_data, date)
        snapshots.append({
            'date': date,
            'portfolio_value': pv_after,
            'cash': state.cash,
            'n_positions': len(state.positions),
            'leverage': 1.0,            # Catalyst never uses leverage
            'drawdown': drawdown,
            'regime_score': 1.0,        # No regime gate
            'crash_active': False,
            'max_positions': len(CATALYST_TREND_ASSETS),
            'rebalance_today': rebalance_today,
            'n_trend_holdings': len(state.positions),
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

    # 8. Synthetic-close any remaining open positions at the end of the backtest
    if state.positions and dates_in_range:
        last_date = dates_in_range[-1]
        last_i = all_dates.index(last_date)
        for sym in sorted(state.positions.keys()):
            pos = state.positions[sym]
            exit_price = _get_exec_price(
                sym, last_date, last_i, all_dates, asset_data, execution_mode
            )
            if exit_price is None:
                # Fall back to entry_price as a last resort so the trade
                # appears in the log; PnL will be 0.
                exit_price = float(pos['entry_price'])
            shares = pos['shares']
            commission = shares * config.get('COMMISSION_PER_SHARE', 0.0035)
            pnl = (exit_price - pos['entry_price']) * shares - commission
            ret = (
                (exit_price / pos['entry_price'] - 1.0)
                if pos['entry_price'] > 0 else 0.0
            )
            trades.append({
                'symbol': sym,
                'entry_date': pos['entry_date'],
                'exit_date': last_date,
                'exit_reason': 'CATALYST_BACKTEST_END',
                'entry_price': pos['entry_price'],
                'exit_price': exit_price,
                'shares': shares,
                'pnl': pnl,
                'return': ret,
                'sector': 'Catalyst',
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
        exit_events=[t for t in trades if t['exit_reason'] == 'CATALYST_TREND_OFF'],
        universe_size=universe_size,
        started_at=started_at,
        finished_at=finished_at,
        git_sha=_capture_git_sha(),
        data_inputs_hash=compute_data_fingerprint(asset_data),
    )
