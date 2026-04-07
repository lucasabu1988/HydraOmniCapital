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


def run_rattlesnake_backtest(
    config: dict,
    price_data: Dict[str, pd.DataFrame],
    pit_universe: Dict[int, List[str]],
    spy_data: pd.DataFrame,
    vix_data: pd.Series,
    cash_yield_daily: pd.Series,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    execution_mode: str = 'same_close',
    progress_callback: Optional[callable] = None,
) -> BacktestResult:
    """Run a Rattlesnake mean-reversion backtest from start_date to end_date.

    Pure function: no side effects. Returns a BacktestResult compatible
    with v1.0 reporting/methodology layers (drop-in for build_waterfall).
    """
    started_at = datetime.now()

    # Aggregate all trading dates from price_data
    all_dates_set = set()
    for df in price_data.values():
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
                pv_now = _mark_to_market(state, price_data, date)
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
        portfolio_value = _mark_to_market(state, price_data, date)

        # 1b. Update peak BEFORE drawdown
        if portfolio_value > state.peak_value:
            state = state._replace(peak_value=portfolio_value)

        # 2. Resolve PIT universe (intersection with R_UNIVERSE)
        tradeable = _resolve_rattlesnake_universe(pit_universe, date.year)
        # Filter further by tickers that have price data on this date
        # AND meet MIN_AGE_DAYS history requirement
        min_age = config.get('MIN_AGE_DAYS', 220)
        tradeable = [
            t for t in tradeable
            if t in price_data
            and date in price_data[t].index
            and len(price_data[t].loc[:date]) >= min_age
        ]
        universe_size[date.year] = max(universe_size.get(date.year, 0), len(tradeable))

        # 3. Drawdown
        drawdown = (
            (portfolio_value - state.peak_value) / state.peak_value
            if state.peak_value > 0 else 0.0
        )

        # 4. Regime + VIX
        spy_slice = spy_data.loc[:date]
        vix_value = float(vix_data.loc[date]) if date in vix_data.index else None
        regime_info = check_rattlesnake_regime(spy_slice, vix_value)
        max_positions = regime_info['max_positions']
        entries_allowed = regime_info['entries_allowed']
        vix_panic = regime_info['vix_panic']

        # 5. Daily costs (cash yield only)
        daily_yield = float(
            cash_yield_daily.get(date, cash_yield_daily.iloc[0])
            if len(cash_yield_daily) > 0 else 0.0
        )
        state = _apply_rattlesnake_daily_costs(state, daily_yield)

        # 6. Apply exits
        state, exit_trades, exit_decisions = apply_rattlesnake_exits(
            state, date, i, price_data, config, execution_mode, all_dates,
        )
        trades.extend(exit_trades)
        decisions.extend(exit_decisions)

        # 7. Apply entries (if regime allows)
        if entries_allowed and len(tradeable) >= 5:
            sliced = _slice_history_to_date(price_data, date, symbols=tradeable)
            current_prices = {
                t: float(price_data[t].loc[date, 'Close'])
                for t in tradeable
            }
            held = set(state.positions.keys())
            slots = max_positions - len(state.positions)
            if slots > 0:
                candidates = find_rattlesnake_candidates(
                    sliced, current_prices, held, max_candidates=slots,
                )
                state, entry_decisions = apply_rattlesnake_entries(
                    state, date, i, price_data, candidates,
                    max_positions, config, execution_mode, all_dates,
                )
                decisions.extend(entry_decisions)

        # 8. Snapshot AFTER exits and entries
        pv_after = _mark_to_market(state, price_data, date)
        snapshots.append({
            'date': date,
            'portfolio_value': pv_after,
            'cash': state.cash,
            'n_positions': len(state.positions),
            'leverage': 1.0,         # Rattlesnake never uses leverage
            'drawdown': drawdown,
            'regime_score': 1.0 if regime_info['regime'] == 'RISK_ON' else 0.0,
            'crash_active': vix_panic,  # repurpose this column for VIX panic
            'max_positions': max_positions,
        })

        # 9. Update state tail: peak (if pv_after exceeded), increment days_held
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

    finished_at = datetime.now()

    trade_cols = ['symbol', 'entry_date', 'exit_date', 'exit_reason',
                  'entry_price', 'exit_price', 'shares', 'pnl', 'return', 'sector']
    return BacktestResult(
        config=dict(config),
        daily_values=pd.DataFrame(snapshots),
        trades=pd.DataFrame(trades) if trades else pd.DataFrame(columns=trade_cols),
        decisions=decisions,
        exit_events=[t for t in trades if t['exit_reason'] in ('R_STOP', 'R_PROFIT')],
        universe_size=universe_size,
        started_at=started_at,
        finished_at=finished_at,
        git_sha=_capture_git_sha(),
        data_inputs_hash=compute_data_fingerprint(price_data),
    )
