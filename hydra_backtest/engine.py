"""Backtest engine — pure function consumer of live signal logic.

This module imports signal-computation functions directly from
omnicapital_live.py (the live production engine). When a live function
depends on class state (self.broker, threads, etc.) we reimplement a
pure equivalent here with a docstring pointing to the source line.

The engine is state-machine-free: each backtest run is a single call
to run_backtest() that produces a BacktestResult. No globals, no I/O,
no mutation of shared state.
"""
import subprocess
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

from hydra_backtest.data import compute_data_fingerprint
from omnicapital_live import (
    _dd_leverage,
    compute_adaptive_stop,
    compute_dynamic_leverage,
    compute_entry_vol,
    compute_live_regime_score,
    compute_momentum_scores,
    compute_quality_filter,
    compute_volatility_weights,
    regime_score_to_positions,
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


def _filter_by_sector_concentration_pure(
    ranked_candidates: List[Tuple[str, float]],
    current_positions: dict,
    sector_map: Dict[str, str],
    max_per_sector: int,
) -> List[str]:
    """Pure equivalent of filter_by_sector_concentration (omnicapital_live.py:770).

    The live version uses a module-level SECTOR_MAP; this version takes
    sector_map explicitly so the backtest is reproducible with any universe
    (including synthetic test tickers).
    """
    from collections import defaultdict
    sector_counts: Dict[str, int] = defaultdict(int)
    for sym in current_positions:
        sector = sector_map.get(sym, 'Unknown')
        sector_counts[sector] += 1

    selected: List[str] = []
    for symbol, _score in ranked_candidates:
        sector = sector_map.get(symbol, 'Unknown')
        if sector_counts[sector] < max_per_sector:
            selected.append(symbol)
            sector_counts[sector] += 1
    return selected


def _slice_history_to_date(
    price_data: Dict[str, pd.DataFrame],
    date: pd.Timestamp,
    symbols: Optional[List[str]] = None,
) -> Dict[str, pd.DataFrame]:
    """Return a new dict where each ticker's DataFrame is sliced to end at `date`.

    Required because live engine functions (compute_momentum_scores,
    compute_quality_filter, compute_entry_vol, compute_volatility_weights)
    use .iloc[-1] under the assumption that the hist_cache is already
    "real-time" (only contains data up to today). In a backtest we have
    full history, so we must slice explicitly or leak future info.

    If `symbols` is provided, only slices those tickers (optimization for
    callers that only need a subset).
    """
    keys = symbols if symbols is not None else price_data.keys()
    out: Dict[str, pd.DataFrame] = {}
    for sym in keys:
        df = price_data.get(sym)
        if df is None:
            continue
        out[sym] = df.loc[:date]
    return out


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


def get_max_positions_pure(
    regime_score: float,
    spy_hist: pd.DataFrame,
    config: dict,
) -> int:
    """Pure equivalent of COMPASSLive.get_max_positions (omnicapital_live.py:1448).

    Uses the top-level regime_score_to_positions from the live engine,
    passing SPY close/SMA200 for the bull override.

    Fed Emergency overlay is NOT applied in v1 (documented in spec §12).
    """
    spy_close = None
    sma200 = None
    if spy_hist is not None and len(spy_hist) >= 200:
        spy_close = float(spy_hist['Close'].iloc[-1])
        sma200 = float(spy_hist['Close'].iloc[-200:].mean())
    return regime_score_to_positions(
        regime_score,
        config['NUM_POSITIONS'],
        config['NUM_POSITIONS_RISK_OFF'],
        spy_close=spy_close,
        sma200=sma200,
        bull_threshold=config['BULL_OVERRIDE_THRESHOLD'],
        bull_min_score=config['BULL_OVERRIDE_MIN_SCORE'],
    )


def apply_daily_costs(
    state: BacktestState,
    leverage: float,
    cash_yield_annual_pct: float,
    portfolio_value: float,
    config: dict,
) -> BacktestState:
    """Apply one trading day's margin cost (if leveraged) and cash yield.

    `cash_yield_annual_pct` is in percent (e.g. 3.5 for 3.5% annual).
    Margin cost uses `config['MARGIN_RATE']` (default 6%).
    """
    cash = state.cash

    # Margin cost on borrowed amount (leverage > 1.0)
    if leverage > 1.0 and portfolio_value > 0:
        borrowed = portfolio_value * (leverage - 1.0) / leverage
        daily_margin = config['MARGIN_RATE'] / 252 * borrowed
        cash -= daily_margin

    # Cash yield on positive idle cash
    if cash > 0 and cash_yield_annual_pct > 0:
        daily_rate = cash_yield_annual_pct / 100.0 / 252
        cash += cash * daily_rate

    return state._replace(cash=cash)


def _get_exec_price(
    symbol: str,
    date: pd.Timestamp,
    i: int,
    all_dates: list,
    price_data: Dict[str, pd.DataFrame],
    execution_mode: str,
) -> Optional[float]:
    """Single source of truth for execution pricing.

    - same_close: fill at price_data[symbol].loc[date, 'Close']
    - next_open:  fill at price_data[symbol].loc[all_dates[i+1], 'Open']

    Returns None if the trade cannot be executed (last bar, symbol doesn't
    trade next day, etc.). Callers must handle None by skipping the action.
    """
    if execution_mode == 'same_close':
        df = price_data.get(symbol)
        if df is None or date not in df.index:
            return None
        price = float(df.loc[date, 'Close'])
        return price if price > 0 else None
    if execution_mode == 'next_open':
        if i + 1 >= len(all_dates):
            return None  # last bar — no next day
        next_date = all_dates[i + 1]
        df = price_data.get(symbol)
        if df is None or next_date not in df.index:
            return None
        price = float(df.loc[next_date, 'Open'])
        return price if price > 0 else None
    raise ValueError(f"Unknown execution_mode: {execution_mode!r}")


def apply_exits(
    state: BacktestState,
    date: pd.Timestamp,
    i: int,
    price_data: Dict[str, pd.DataFrame],
    scores: Dict[str, float],
    tradeable: List[str],
    max_positions: int,
    config: dict,
    sector_map: Dict[str, str],
    execution_mode: str,
    all_dates: list,
) -> Tuple[BacktestState, list, list]:
    """Evaluate and apply all exit conditions for open positions.

    Priority order (mirrors COMPASSLive._check_exits):
      1. hold_expired (no renewal in v1 — see spec §3 non-goals)
      2. position_stop (adaptive, vol-scaled)
      3. trailing_stop (vol-scaled activation)
      4. universe_rotation (symbol not in tradeable)
      5. regime_reduce (worst performer if len(positions) > max_positions)

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
        exit_reason = None

        # 1. Hold expired
        days_held = i - pos['entry_idx']
        if days_held >= config['HOLD_DAYS']:
            # v1 scope: position renewal (keeping winners) is intentionally
            # omitted. See spec §3 non-goals.
            exit_reason = 'hold_expired'

        # 2. Position stop (adaptive, vol-scaled)
        pos_return = (current_price - pos['entry_price']) / pos['entry_price']
        adaptive_stop = compute_adaptive_stop(pos.get('entry_daily_vol', 0.016), config)
        if pos_return <= adaptive_stop:
            exit_reason = 'position_stop'

        # 3. Trailing stop (vol-scaled)
        if current_price > pos['high_price']:
            pos = {**pos, 'high_price': current_price}
            positions[symbol] = pos
        if pos['high_price'] > pos['entry_price'] * (1 + config['TRAILING_ACTIVATION']):
            vol_ratio = pos.get('entry_vol', config['TRAILING_VOL_BASELINE']) / config['TRAILING_VOL_BASELINE']
            scaled_trailing = config['TRAILING_STOP_PCT'] * vol_ratio
            trailing_level = pos['high_price'] * (1 - scaled_trailing)
            if current_price <= trailing_level:
                exit_reason = 'trailing_stop'

        # 4. Universe rotation
        if symbol not in tradeable:
            exit_reason = 'universe_rotation'

        # 5. Regime reduce (excess position)
        if exit_reason is None and len(positions) > max_positions:
            pos_returns = {}
            for s, p in positions.items():
                sdf = price_data.get(s)
                if sdf is not None and date in sdf.index:
                    cp = float(sdf.loc[date, 'Close'])
                    pos_returns[s] = (cp - p['entry_price']) / p['entry_price']
            if pos_returns:
                worst = min(pos_returns, key=pos_returns.get)
                if symbol == worst:
                    exit_reason = 'regime_reduce'

        if exit_reason is None:
            continue

        # Resolve execution price given the execution_mode
        exit_price = _get_exec_price(symbol, date, i, all_dates, price_data, execution_mode)
        if exit_price is None:
            continue  # cannot execute — position carries

        shares = pos['shares']
        proceeds = shares * exit_price
        commission = shares * config['COMMISSION_PER_SHARE']
        cash += proceeds - commission
        pnl = (exit_price - pos['entry_price']) * shares - commission
        exit_date = date if execution_mode == 'same_close' else all_dates[i + 1]

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
            'sector': sector_map.get(symbol, pos.get('sector', 'Unknown')),
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


def apply_entries(
    state: BacktestState,
    date: pd.Timestamp,
    i: int,
    price_data: Dict[str, pd.DataFrame],
    scores: Dict[str, float],
    tradeable: List[str],
    max_positions: int,
    leverage: float,
    config: dict,
    sector_map: Dict[str, str],
    all_dates: list,
    execution_mode: str,
) -> Tuple[BacktestState, list]:
    """Evaluate and apply all entry decisions for this bar.

    Mirrors the entry loop in COMPASSLive._run_cycle. Filters by score,
    sector concentration, cash buffer, sizing, then opens positions.
    """
    decisions: list = []
    cash = state.cash
    positions = dict(state.positions)

    needed = max_positions - len(positions)
    if needed <= 0 or cash < 1000 or len(tradeable) < 5:
        return state, decisions

    available_scores = {s: sc for s, sc in scores.items() if s not in positions}
    if len(scores) < config['MIN_MOMENTUM_STOCKS'] or len(available_scores) < needed:
        return state, decisions

    # Rank and apply sector concentration filter against existing positions.
    # Uses our pure equivalent that takes sector_map explicitly (not the live
    # engine's global SECTOR_MAP) so the backtest is reproducible with any
    # universe including synthetic test tickers.
    ranked = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
    sector_filtered = _filter_by_sector_concentration_pure(
        ranked, positions, sector_map, max_per_sector=config['MAX_PER_SECTOR']
    )
    selected = sector_filtered[:needed]
    if not selected:
        return state, decisions

    # Slice per-symbol history to `date` so the live engine vol helpers
    # (which use .iloc[-1]) see the correct "as-of" view and not future data.
    sliced_for_sizing = _slice_history_to_date(price_data, date, symbols=selected)
    weights = compute_volatility_weights(
        sliced_for_sizing, selected, vol_lookback=config.get('VOL_LOOKBACK', 20)
    )
    effective_capital = cash * leverage * 0.95  # 5% buffer

    for symbol in selected:
        df = price_data.get(symbol)
        if df is None or date not in df.index:
            continue

        entry_price = _get_exec_price(symbol, date, i, all_dates, price_data, execution_mode)
        if entry_price is None:
            continue

        weight = weights.get(symbol, 1.0 / len(selected))
        position_value = effective_capital * weight
        position_value = min(position_value, cash * 0.40)  # max 40% per position

        shares = position_value / entry_price
        cost = shares * entry_price
        commission = shares * config['COMMISSION_PER_SHARE']
        if cost + commission > cash * 0.90:
            continue  # respects the 0.90 cash buffer

        entry_vol, entry_daily_vol = compute_entry_vol(
            sliced_for_sizing, symbol, lookback=config.get('VOL_LOOKBACK', 20)
        )

        # In next_open mode, the position is created at the fill bar (i+1),
        # so the hold counter runs correctly from the fill day.
        if execution_mode == 'next_open':
            effective_entry_date = all_dates[i + 1]
            effective_entry_idx = i + 1
        else:
            effective_entry_date = date
            effective_entry_idx = i

        positions[symbol] = {
            'entry_price': entry_price,
            'shares': shares,
            'entry_date': effective_entry_date,
            'entry_idx': effective_entry_idx,
            'original_entry_idx': effective_entry_idx,
            'high_price': entry_price,
            'entry_vol': entry_vol,
            'entry_daily_vol': entry_daily_vol,
            'sector': sector_map.get(symbol, 'Unknown'),
        }
        cash -= cost + commission
        decisions.append({
            'type': 'entry',
            'symbol': symbol,
            'date': str(effective_entry_date),
            'entry_price': entry_price,
            'shares': shares,
            'score': scores[symbol],
        })

    return state._replace(cash=cash, positions=positions), decisions


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


def run_backtest(
    config: dict,
    price_data: Dict[str, pd.DataFrame],
    pit_universe: Dict[int, List[str]],
    spy_data: pd.DataFrame,
    cash_yield_daily: pd.Series,
    sector_map: Dict[str, str],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    execution_mode: str = 'same_close',
) -> BacktestResult:
    """Run a COMPASS backtest from start_date to end_date.

    Produces a BacktestResult with daily equity curve, all trades, and
    the full decision log. This function has no side effects — pure in
    / pure out.
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

    for i, date in enumerate(all_dates):
        if date < start_date or date > end_date:
            continue

        # 1. Mark-to-market
        portfolio_value = _mark_to_market(state, price_data, date)

        # 2. Universe resolution
        tradeable = get_tradeable_symbols(
            pit_universe, price_data, date, min_age_days=config['MIN_AGE_DAYS']
        )
        universe_size[date.year] = max(universe_size.get(date.year, 0), len(tradeable))

        # 3. Regime + drawdown + leverage
        spy_slice = spy_data.loc[:date]
        regime_score = compute_live_regime_score(spy_slice)
        drawdown = (portfolio_value - state.peak_value) / state.peak_value if state.peak_value > 0 else 0.0

        leverage, new_cooldown, crash_active = get_current_leverage_pure(
            drawdown=drawdown,
            portfolio_value_history=state.portfolio_value_history + (portfolio_value,),
            crash_cooldown=state.crash_cooldown,
            config=config,
            spy_hist=spy_slice,
        )
        max_positions = get_max_positions_pure(regime_score, spy_slice, config)

        # 4. Daily costs (margin + cash yield)
        daily_yield = float(
            cash_yield_daily.get(date, cash_yield_daily.iloc[0])
            if len(cash_yield_daily) > 0 else 0.0
        )
        state = apply_daily_costs(state, leverage, daily_yield, portfolio_value, config)

        # 5. Signals (computed once, reused by exits and entries).
        # Slice history to `date` before calling live-engine helpers that
        # use .iloc[-1] on a "real-time" hist_cache assumption.
        sliced = _slice_history_to_date(price_data, date, symbols=tradeable)
        quality_syms = compute_quality_filter(
            sliced, tradeable,
            vol_max=config['QUALITY_VOL_MAX'],
            vol_lookback=config['QUALITY_VOL_LOOKBACK'],
            max_single_day=config['QUALITY_MAX_SINGLE_DAY'],
        )
        scores = compute_momentum_scores(
            sliced, quality_syms,
            lookback=config['MOMENTUM_LOOKBACK'],
            skip=config['MOMENTUM_SKIP'],
        )

        # 6. Exits
        state, exit_trades, exit_decisions = apply_exits(
            state, date, i, price_data, scores, tradeable,
            max_positions, config, sector_map, execution_mode, all_dates,
        )
        trades.extend(exit_trades)
        decisions.extend(exit_decisions)

        # 7. Entries
        state, entry_decisions = apply_entries(
            state, date, i, price_data, scores, tradeable,
            max_positions, leverage, config, sector_map, all_dates, execution_mode,
        )
        decisions.extend(entry_decisions)

        # 8. Record snapshot (after exits+entries reflects end-of-day)
        pv_after = _mark_to_market(state, price_data, date)
        snapshots.append({
            'date': date,
            'portfolio_value': pv_after,
            'cash': state.cash,
            'n_positions': len(state.positions),
            'leverage': leverage,
            'drawdown': drawdown,
            'regime_score': regime_score,
            'crash_active': crash_active,
            'max_positions': max_positions,
        })

        # 9. Update state tail (history, cooldown, peak)
        new_peak = max(state.peak_value, pv_after)
        decayed_cooldown = max(new_cooldown - 1, 0) if not crash_active else new_cooldown
        state = state._replace(
            peak_value=new_peak,
            crash_cooldown=decayed_cooldown,
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
        exit_events=[t for t in trades if t['exit_reason'] in ('position_stop', 'trailing_stop')],
        universe_size=universe_size,
        started_at=started_at,
        finished_at=finished_at,
        git_sha=_capture_git_sha(),
        data_inputs_hash=compute_data_fingerprint(price_data),
    )
