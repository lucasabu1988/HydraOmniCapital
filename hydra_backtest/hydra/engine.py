"""hydra_backtest.hydra.engine — full HYDRA integration orchestrator.

Composes the four pillar apply helpers via sub-state wrappers.
The wrappers slice the global state by `_strategy` tag, call the
existing v1.0-v1.3 helpers without modification, and merge results
back into the global state.
"""
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

# v1.0 dependencies (COMPASS)
from hydra_backtest.engine import (
    BacktestResult,
    BacktestState,
    _get_exec_price,
    _mark_to_market,
    _slice_history_to_date,
    apply_entries as compass_apply_entries,
    apply_exits as compass_apply_exits,
    compute_data_fingerprint,
    get_current_leverage_pure,
    get_max_positions_pure,
    get_tradeable_symbols,
)
from omnicapital_live import (
    compute_live_regime_score,
    compute_momentum_scores,
    compute_quality_filter,
)

# v1.1 dependencies (Rattlesnake)
from hydra_backtest.rattlesnake.engine import (
    _resolve_rattlesnake_universe,
    apply_rattlesnake_entries as rattle_apply_entries,
    apply_rattlesnake_exits as rattle_apply_exits,
)
from rattlesnake_signals import (
    R_MAX_POSITIONS,
    check_rattlesnake_regime,
    find_rattlesnake_candidates,
)

# v1.2 dependencies (Catalyst)
from catalyst_signals import (
    CATALYST_REBALANCE_DAYS,
    CATALYST_TREND_ASSETS,
)
from hydra_backtest.catalyst.engine import apply_catalyst_rebalance

# v1.3 dependencies (EFA)
from hydra_backtest.efa.engine import (
    EFA_SYMBOL,
    _efa_above_sma200,
    apply_efa_decision,
)

# v1.4 own modules
from hydra_backtest.hydra.capital import (
    EFA_DEPLOYMENT_CAP,
    EFA_MIN_BUY,
    HydraCapitalState,
    compute_allocation_pure,
    compute_budgets_from_snapshot,
    update_accounts_after_day_pure,
    update_catalyst_value_pure,
    update_efa_value_pure,
)
from hydra_backtest.hydra.state import (
    HydraBacktestState,
    compute_pillar_invested,
    compute_pillar_invested_at_prev_close,
    merge_pillar_substate,
    slice_positions_by_strategy,
    to_pillar_substate,
)


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


def apply_compass_exits_wrapper(
    state: HydraBacktestState,
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
) -> Tuple[HydraBacktestState, list, list]:
    """Wrap v1.0 apply_exits with sub-state slicing for the compass pillar.

    The capital_account_delta is 0 because exiting a position is an
    intra-bucket transfer (positions → cash, both within compass).
    The compass_account bucket only changes via update_accounts_after_day
    at end of day, applying the daily return.
    """
    substate = to_pillar_substate(state, 'compass')
    cash_before = substate.cash
    new_substate, trades, decisions = compass_apply_exits(
        substate, date, i, price_data, scores, tradeable,
        max_positions, config, sector_map, execution_mode, all_dates,
    )
    cash_delta = new_substate.cash - cash_before
    new_state = merge_pillar_substate(
        state, new_substate, 'compass',
        cash_delta=cash_delta, capital_account_delta=0.0,
    )
    return new_state, trades, decisions


def apply_compass_entries_wrapper(
    state: HydraBacktestState,
    compass_budget: float,
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
) -> Tuple[HydraBacktestState, list]:
    """Wrap v1.0 apply_entries with the NAV-derived budget hack.

    Option C: compass_budget is the TOTAL target capital for compass
    (base + recycled). The "free cash" compass can actually spend on
    NEW entries is budget - current_positions_value. That free cash
    is then capped at broker_cash to prevent over-spending physical
    cash. Mirrors the catalyst wrapper's fix for double-counting.
    """
    prices_now = {}
    for sym, pos in slice_positions_by_strategy(state.positions, 'compass').items():
        df = price_data.get(sym)
        if df is not None and date in df.index:
            prices_now[sym] = float(df.loc[date, 'Close'])
    compass_pos_value = compute_pillar_invested(
        state.positions, 'compass', prices_now,
    )
    free_cash_in_bucket = max(0.0, compass_budget - compass_pos_value)
    capped_budget = min(free_cash_in_bucket, max(state.cash, 0.0))
    substate = to_pillar_substate(state, 'compass', cash_override=capped_budget)

    # CRITICAL: filter tradeable + scores to exclude symbols held by ANY
    # other pillar. compass_apply_entries' internal filter only excludes
    # symbols already in substate.positions (compass-only), so without
    # this filter compass would happily buy a symbol already held by
    # rattle, causing a silent overwrite in merge_pillar_substate.
    other_pillar_held = {
        sym for sym, p in state.positions.items()
        if p.get('_strategy') != 'compass'
    }
    tradeable_filtered = [t for t in tradeable if t not in other_pillar_held]
    scores_filtered = {
        s: sc for s, sc in scores.items() if s not in other_pillar_held
    }
    new_substate, decisions = compass_apply_entries(
        substate, date, i, price_data, scores_filtered, tradeable_filtered,
        max_positions, leverage, config, sector_map, all_dates, execution_mode,
    )
    spent = capped_budget - new_substate.cash  # positive number
    cash_delta = -spent
    new_state = merge_pillar_substate(
        state, new_substate, 'compass',
        cash_delta=cash_delta, capital_account_delta=0.0,
    )
    return new_state, decisions


def apply_rattle_exits_wrapper(
    state: HydraBacktestState,
    date: pd.Timestamp,
    i: int,
    price_data: Dict[str, pd.DataFrame],
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[HydraBacktestState, list, list]:
    """Wrap v1.1 apply_rattlesnake_exits with sub-state slicing.

    capital_account_delta=0 — intra-bucket cash↔positions transfer.
    """
    substate = to_pillar_substate(state, 'rattle')
    cash_before = substate.cash
    new_substate, trades, decisions = rattle_apply_exits(
        substate, date, i, price_data, config, execution_mode, all_dates,
    )
    cash_delta = new_substate.cash - cash_before
    new_state = merge_pillar_substate(
        state, new_substate, 'rattle',
        cash_delta=cash_delta, capital_account_delta=0.0,
    )
    return new_state, trades, decisions


def apply_rattle_entries_wrapper(
    state: HydraBacktestState,
    rattle_budget: float,
    date: pd.Timestamp,
    i: int,
    price_data: Dict[str, pd.DataFrame],
    candidates: list,
    max_positions: int,
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[HydraBacktestState, list]:
    """Wrap v1.1 apply_rattlesnake_entries with the NAV-derived budget hack.

    Option C: rattle_budget is the TOTAL target for rattle (base -
    recycled_out). The free cash for NEW entries is budget -
    current_positions_value, capped at broker_cash. Mirrors compass
    and catalyst wrappers for consistency — no pillar may pass its
    raw target budget as deployable cash.
    """
    prices_now = {}
    for sym, pos in slice_positions_by_strategy(state.positions, 'rattle').items():
        df = price_data.get(sym)
        if df is not None and date in df.index:
            prices_now[sym] = float(df.loc[date, 'Close'])
    rattle_pos_value = compute_pillar_invested(
        state.positions, 'rattle', prices_now,
    )
    free_cash_in_bucket = max(0.0, rattle_budget - rattle_pos_value)
    capped_budget = min(free_cash_in_bucket, max(state.cash, 0.0))
    substate = to_pillar_substate(state, 'rattle', cash_override=capped_budget)
    new_substate, decisions = rattle_apply_entries(
        substate, date, i, price_data, candidates,
        max_positions, config, execution_mode, all_dates,
    )
    spent = capped_budget - new_substate.cash
    cash_delta = -spent
    new_state = merge_pillar_substate(
        state, new_substate, 'rattle',
        cash_delta=cash_delta, capital_account_delta=0.0,
    )
    return new_state, decisions


def apply_catalyst_wrapper(
    state: HydraBacktestState,
    catalyst_budget: float,
    date: pd.Timestamp,
    i: int,
    catalyst_assets: Dict[str, pd.DataFrame],
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[HydraBacktestState, list, list]:
    """Wrap v1.2 apply_catalyst_rebalance with the budget hack.

    Catalyst is ring-fenced — its budget is the catalyst_account,
    never recycles. capital_account_delta=0 because rebalance is an
    intra-bucket transfer (cash ↔ positions, both within catalyst).

    CRITICAL: apply_catalyst_rebalance uses _mark_to_market(substate)
    to compute the rebalance target, which is cash + positions_value.
    To avoid double-counting we pass cash_override = catalyst_budget
    MINUS the current value of catalyst positions held. Then
    _mark_to_market(substate) returns exactly catalyst_budget, which
    is the correct rebalance target. The cap by broker cash still
    applies to prevent over-spending the physical cash.
    """
    # Compute current catalyst positions market value at today's prices
    catalyst_prices = {}
    for sym in slice_positions_by_strategy(state.positions, 'catalyst').keys():
        df = catalyst_assets.get(sym)
        if df is not None and date in df.index:
            catalyst_prices[sym] = float(df.loc[date, 'Close'])
    catalyst_pos_value = compute_pillar_invested(
        state.positions, 'catalyst', catalyst_prices
    )
    free_cash_in_bucket = max(0.0, catalyst_budget - catalyst_pos_value)
    capped_free_cash = min(free_cash_in_bucket, max(state.cash, 0.0))

    substate = to_pillar_substate(state, 'catalyst', cash_override=capped_free_cash)
    cash_before = substate.cash
    new_substate, trades, decisions = apply_catalyst_rebalance(
        substate, date, i, catalyst_assets, config, execution_mode, all_dates,
    )
    cash_delta = new_substate.cash - cash_before  # may be positive (sells) or negative (buys)
    new_state = merge_pillar_substate(
        state, new_substate, 'catalyst',
        cash_delta=cash_delta, capital_account_delta=0.0,
    )
    return new_state, trades, decisions


def apply_efa_wrapper(
    state: HydraBacktestState,
    efa_idle: float,
    date: pd.Timestamp,
    i: int,
    efa_data: pd.DataFrame,
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[HydraBacktestState, list, list]:
    """Wrap v1.3 apply_efa_decision with the idle-cash gate.

    Live behavior:
      - Buy is gated by efa_idle from compute_allocation_pure
      - Min buy threshold $1k
      - 90% deployment cap on idle cash

    Unlike compass/rattle/catalyst, EFA is funded by transferring cash
    from rattle's idle pool. So a buy is an INTER-bucket transfer:
      - rattle_account decreases by `spent`
      - efa_value increases by `spent`
    Mirrors hydra_capital.HydraCapitalManager.buy_efa (line 139).
    A sell does the inverse, mirroring sell_efa (line 145).
    """
    held = EFA_SYMBOL in slice_positions_by_strategy(state.positions, 'efa')
    capped_idle = min(efa_idle, max(state.cash, 0.0)) * EFA_DEPLOYMENT_CAP

    if not held and capped_idle < EFA_MIN_BUY:
        # Not enough idle cash to attempt a buy AND nothing held → no-op
        return state, [], []

    # When held, the wrapper still calls apply_efa_decision so the SELL
    # path can fire if EFA dropped below SMA200. Use the full broker cash
    # for the held case (the SELL path adds to cash, doesn't spend).
    cash_for_substate = capped_idle if not held else state.cash
    substate = to_pillar_substate(state, 'efa', cash_override=cash_for_substate)
    cash_before = substate.cash
    new_substate, trades, decisions = apply_efa_decision(
        substate, date, i, efa_data, config, execution_mode, all_dates,
    )
    cash_delta = new_substate.cash - cash_before  # negative for buys, positive for sells

    # Inter-bucket transfer: |cash_delta| moves between rattle and efa.
    # cash_delta < 0 (buy) → rattle -= spent, efa += spent
    # cash_delta > 0 (sell) → efa -= proceeds, rattle += proceeds
    transfer = -cash_delta  # positive = buy magnitude, negative = sell magnitude
    new_capital = state.capital._replace(
        rattle_account=state.capital.rattle_account - transfer,
        efa_value=max(0.0, state.capital.efa_value + transfer),
    )

    # Now merge positions and update broker cash. We can't reuse
    # merge_pillar_substate because it only updates one bucket — we
    # already updated capital ourselves above.
    other_positions = {
        sym: pos for sym, pos in state.positions.items()
        if pos.get('_strategy') != 'efa'
    }
    new_efa_positions = {
        sym: {**pos, '_strategy': 'efa'}
        for sym, pos in new_substate.positions.items()
    }
    merged_positions = {**other_positions, **new_efa_positions}

    new_state = state._replace(
        cash=state.cash + cash_delta,
        positions=merged_positions,
        capital=new_capital,
    )
    return new_state, trades, decisions


def apply_efa_liquidation(
    state: HydraBacktestState,
    date: pd.Timestamp,
    i: int,
    efa_data: pd.DataFrame,
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[HydraBacktestState, list]:
    """Sell all EFA shares to free capital. Mirrors live
    omnicapital_live.py::_liquidate_efa_for_capital (line 2508).
    """
    efa_positions = slice_positions_by_strategy(state.positions, 'efa')
    if EFA_SYMBOL not in efa_positions:
        return state, []
    pos = efa_positions[EFA_SYMBOL]
    exit_price = _get_exec_price(
        EFA_SYMBOL, date, i, all_dates, {EFA_SYMBOL: efa_data}, execution_mode,
    )
    if exit_price is None:
        return state, []
    shares = pos['shares']
    commission = shares * config.get('COMMISSION_PER_SHARE', 0.0035)
    proceeds = shares * exit_price - commission
    pnl = (exit_price - pos['entry_price']) * shares - commission
    ret = (
        (exit_price / pos['entry_price'] - 1.0)
        if pos['entry_price'] > 0 else 0.0
    )
    trade = {
        'symbol': EFA_SYMBOL,
        'entry_date': pos['entry_date'],
        'exit_date': date,
        'exit_reason': 'EFA_LIQUIDATED_FOR_CAPITAL',
        'entry_price': pos['entry_price'],
        'exit_price': exit_price,
        'shares': shares,
        'pnl': pnl,
        'return': ret,
        'sector': 'International Equity',
    }
    new_positions = {
        s: p for s, p in state.positions.items()
        if not (s == EFA_SYMBOL and p.get('_strategy') == 'efa')
    }
    # Transfer the liquidated value from efa_value back to rattle_account.
    # Mirrors hydra_capital.sell_efa (line 145): efa_value -= sell;
    # rattle_account += sell.
    transfer = proceeds
    new_capital = state.capital._replace(
        efa_value=max(0.0, state.capital.efa_value - transfer),
        rattle_account=state.capital.rattle_account + transfer,
    )
    new_state = state._replace(
        cash=state.cash + proceeds,
        positions=new_positions,
        capital=new_capital,
    )
    return new_state, [trade]


def _needs_efa_liquidation(
    state: HydraBacktestState,
    portfolio_value: float,
    config: dict,
    n_compass_positions: int,
    n_compass_max: int,
    rattle_signal_pending: bool,
) -> bool:
    """Mirrors omnicapital_live.py::_liquidate_efa_for_capital decision logic.

    Liquidate when:
      - EFA is held
      - Active strategy needs capital (compass slots open OR rattle signals)
      - Broker cash < threshold% of portfolio value
    """
    threshold_pct = config.get('EFA_LIQUIDATION_CASH_THRESHOLD_PCT', 0.20)
    efa_held = EFA_SYMBOL in slice_positions_by_strategy(state.positions, 'efa')
    if not efa_held:
        return False
    needs_capital = (n_compass_positions < n_compass_max) or rattle_signal_pending
    if not needs_capital:
        return False
    return state.cash < threshold_pct * portfolio_value


def _rattle_exposure(state: HydraBacktestState, prices: Dict[str, float]) -> float:
    """Mirror rattlesnake_signals.compute_rattlesnake_exposure but use the
    HydraCapitalState rattle_account as the denominator.
    """
    if state.capital.rattle_account <= 0:
        return 0.0
    rattle_positions = slice_positions_by_strategy(state.positions, 'rattle')
    invested = sum(
        pos.get('shares', 0) * prices.get(sym, pos.get('entry_price', 0.0))
        for sym, pos in rattle_positions.items()
    )
    return min(invested / state.capital.rattle_account, 1.0)


def _build_asset_dict(
    sym: str,
    pos: dict,
    price_data: Dict[str, pd.DataFrame],
    catalyst_assets: Dict[str, pd.DataFrame],
    efa_data: pd.DataFrame,
) -> Optional[pd.DataFrame]:
    """Look up the right OHLCV DataFrame for a position based on its strategy tag."""
    strategy = pos.get('_strategy')
    if strategy == 'catalyst':
        return catalyst_assets.get(sym)
    if strategy == 'efa':
        return efa_data if sym == EFA_SYMBOL else None
    return price_data.get(sym)


def _mark_full_portfolio(
    state: HydraBacktestState,
    date: pd.Timestamp,
    price_data: Dict[str, pd.DataFrame],
    catalyst_assets: Dict[str, pd.DataFrame],
    efa_data: pd.DataFrame,
) -> float:
    """Compute total portfolio value at end of `date` across all 4 pillars."""
    pv = state.cash
    for sym, pos in state.positions.items():
        df = _build_asset_dict(sym, pos, price_data, catalyst_assets, efa_data)
        if df is not None and date in df.index:
            price = float(df.loc[date, 'Close'])
        else:
            price = float(pos.get('entry_price', 0.0))
        pv += float(pos.get('shares', 0)) * price
    return pv


def _current_prices_for_positions(
    state: HydraBacktestState,
    date: pd.Timestamp,
    price_data: Dict[str, pd.DataFrame],
    catalyst_assets: Dict[str, pd.DataFrame],
    efa_data: pd.DataFrame,
) -> Dict[str, float]:
    """Build a {symbol: price} dict for every currently-held position."""
    prices = {}
    for sym, pos in state.positions.items():
        df = _build_asset_dict(sym, pos, price_data, catalyst_assets, efa_data)
        if df is not None and date in df.index:
            prices[sym] = float(df.loc[date, 'Close'])
    return prices


def run_hydra_backtest(
    config: dict,
    price_data: Dict[str, pd.DataFrame],
    pit_universe: Dict[int, List[str]],
    spy_data: pd.DataFrame,
    vix_data: pd.Series,
    catalyst_assets: Dict[str, pd.DataFrame],
    efa_data: pd.DataFrame,
    cash_yield_daily: pd.Series,
    sector_map: Dict[str, str],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    execution_mode: str = 'same_close',
    progress_callback: Optional[callable] = None,
) -> BacktestResult:
    """Run the full HYDRA backtest from start_date to end_date.

    Mirrors omnicapital_live.py::execute_preclose_entries order of
    operations (line 2972).
    """
    started_at = datetime.now()

    # Build the union of all trading dates from all data sources
    all_dates_set = set()
    for df in price_data.values():
        all_dates_set.update(df.index)
    for df in catalyst_assets.values():
        all_dates_set.update(df.index)
    all_dates_set.update(efa_data.index)
    all_dates = sorted(all_dates_set)

    initial_capital = float(config['INITIAL_CAPITAL'])
    capital0 = HydraCapitalState(
        compass_account=initial_capital * config.get('BASE_COMPASS_ALLOC', 0.425),
        rattle_account=initial_capital * config.get('BASE_RATTLE_ALLOC', 0.425),
        catalyst_account=initial_capital * config.get('BASE_CATALYST_ALLOC', 0.15),
        efa_value=0.0,
    )
    state = HydraBacktestState(
        cash=initial_capital,
        positions={},
        peak_value=initial_capital,
        crash_cooldown=0,
        portfolio_value_history=(),
        capital=capital0,
    )

    trades: list = []
    decisions: list = []
    snapshots: list = []
    universe_size: dict = {}

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
                pv_now = _mark_full_portfolio(
                    state, date, price_data, catalyst_assets, efa_data
                )
                bars_done = sum(1 for d in dates_in_range if d < date)
                prices_now = _current_prices_for_positions(
                    state, date, price_data, catalyst_assets, efa_data
                )
                progress_callback({
                    'year': int(date.year),
                    'progress_pct': 100.0 * bars_done / total_bars,
                    'portfolio_value': float(pv_now),
                    'n_positions': len(state.positions),
                    'recycled_pct': compute_budgets_from_snapshot(
                        positions=state.positions,
                        cash=state.cash,
                        prices=prices_now,
                        nav=pv_now,
                        config=config,
                    )['recycled_pct'],
                })
            except Exception:
                pass

        # 1. Mark-to-market
        portfolio_value = _mark_full_portfolio(
            state, date, price_data, catalyst_assets, efa_data
        )

        # 1b. Update peak BEFORE drawdown
        if portfolio_value > state.peak_value:
            state = state._replace(peak_value=portfolio_value)

        drawdown = (
            (portfolio_value - state.peak_value) / state.peak_value
            if state.peak_value > 0 else 0.0
        )

        # 2. Daily cash yield (one call at HYDRA level — no leverage assumed)
        if len(cash_yield_daily) > 0:
            daily_yield = float(
                cash_yield_daily.get(date, cash_yield_daily.iloc[0])
            )
        else:
            daily_yield = 0.0
        if state.cash > 0 and daily_yield > 0:
            yield_amt = state.cash * (daily_yield / 100.0 / 252)
            new_cash = state.cash + yield_amt
            # Distribute the yield across the four logical buckets
            # proportionally to bucket weight, so the sub-account sum
            # invariant continues to hold.
            total_cap = state.capital.total_capital
            if total_cap > 0:
                cw = state.capital.compass_account / total_cap
                rw = state.capital.rattle_account / total_cap
                catw = state.capital.catalyst_account / total_cap
                ew = state.capital.efa_value / total_cap
                new_capital = state.capital._replace(
                    compass_account=state.capital.compass_account + yield_amt * cw,
                    rattle_account=state.capital.rattle_account + yield_amt * rw,
                    catalyst_account=state.capital.catalyst_account + yield_amt * catw,
                    efa_value=state.capital.efa_value + yield_amt * ew,
                )
                state = state._replace(cash=new_cash, capital=new_capital)
            else:
                state = state._replace(cash=new_cash)

        # 3. Compute COMPASS scoring inputs
        tradeable = get_tradeable_symbols(
            pit_universe, price_data, date, min_age_days=config['MIN_AGE_DAYS']
        )
        universe_size[date.year] = max(universe_size.get(date.year, 0), len(tradeable))

        spy_slice = spy_data.loc[:date]
        regime_score = compute_live_regime_score(spy_slice)
        leverage, _new_cooldown, _crash_active = get_current_leverage_pure(
            drawdown=drawdown,
            portfolio_value_history=state.portfolio_value_history + (portfolio_value,),
            crash_cooldown=state.crash_cooldown,
            config=config,
            spy_hist=spy_slice,
        )
        max_compass_pos = get_max_positions_pure(regime_score, spy_slice, config)

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

        # 4. Compute budgets from the CURRENT economic snapshot (Option C).
        # Budgets depend only on (positions + cash + prices + nav) — never
        # on accumulated HydraCapitalState buckets. This eliminates the
        # v1.4 T19 feedback loop by construction: calling this function
        # twice on the same snapshot always yields identical budgets
        # (replay determinism test in test_capital.py).
        prices_today = _current_prices_for_positions(
            state, date, price_data, catalyst_assets, efa_data
        )
        rattle_exposure = _rattle_exposure(state, prices_today)
        alloc = compute_budgets_from_snapshot(
            positions=state.positions,
            cash=state.cash,
            prices=prices_today,
            nav=portfolio_value,
            config=config,
        )

        # 5. Compute pure price-driven daily returns BEFORE any wrapper
        # mutates positions. The pattern is:
        #   invested_before = sum(shares * yesterday_close)  (via _prev_close)
        #   invested_at_today = sum(shares * today_close)    (same positions)
        #   ret = invested_at_today / invested_before - 1
        # This isolates price movement from trade-driven count changes.
        compass_invested_before = compute_pillar_invested_at_prev_close(
            state.positions, 'compass'
        )
        compass_invested_at_today = compute_pillar_invested(
            state.positions, 'compass', prices_today
        )
        c_ret = (
            (compass_invested_at_today / compass_invested_before - 1)
            if compass_invested_before > 0 else 0.0
        )

        rattle_invested_before = compute_pillar_invested_at_prev_close(
            state.positions, 'rattle'
        )
        rattle_invested_at_today = compute_pillar_invested(
            state.positions, 'rattle', prices_today
        )
        r_ret = (
            (rattle_invested_at_today / rattle_invested_before - 1)
            if rattle_invested_before > 0 else 0.0
        )

        catalyst_invested_before = compute_pillar_invested_at_prev_close(
            state.positions, 'catalyst'
        )
        catalyst_invested_at_today = compute_pillar_invested(
            state.positions, 'catalyst', prices_today
        )
        cat_ret = (
            (catalyst_invested_at_today / catalyst_invested_before - 1)
            if catalyst_invested_before > 0 else 0.0
        )

        efa_invested_before = compute_pillar_invested_at_prev_close(
            state.positions, 'efa'
        )
        efa_invested_at_today = compute_pillar_invested(
            state.positions, 'efa', prices_today
        )
        e_ret = (
            (efa_invested_at_today / efa_invested_before - 1)
            if efa_invested_before > 0 else 0.0
        )

        # ============================================================
        # COMPASS exits
        # ============================================================
        state, c_exit_trades, c_exit_decisions = apply_compass_exits_wrapper(
            state, date, i, price_data, scores, tradeable,
            max_compass_pos, config, sector_map, execution_mode, all_dates,
        )
        trades.extend(c_exit_trades)
        decisions.extend(c_exit_decisions)

        # ============================================================
        # EFA LIQUIDATION (if active strategies need capital)
        # ============================================================
        n_compass_now = len(slice_positions_by_strategy(state.positions, 'compass'))
        vix_value = float(vix_data.loc[date]) if date in vix_data.index else None
        rattle_regime = check_rattlesnake_regime(spy_slice, vix_value)
        rattle_signal_pending = (
            rattle_regime['entries_allowed']
            and len(slice_positions_by_strategy(state.positions, 'rattle')) < rattle_regime['max_positions']
        )
        if _needs_efa_liquidation(
            state, portfolio_value, config,
            n_compass_now, max_compass_pos, rattle_signal_pending,
        ):
            state, liq_trades = apply_efa_liquidation(
                state, date, i, efa_data, config, execution_mode, all_dates,
            )
            trades.extend(liq_trades)

        # ============================================================
        # COMPASS entries
        # ============================================================
        state, c_entry_decisions = apply_compass_entries_wrapper(
            state, alloc['compass_budget'], date, i, price_data, scores, tradeable,
            max_compass_pos, leverage, config, sector_map, all_dates, execution_mode,
        )
        decisions.extend(c_entry_decisions)

        # ============================================================
        # Rattlesnake exits + entries
        # ============================================================
        state, r_exit_trades, r_exit_decisions = apply_rattle_exits_wrapper(
            state, date, i, price_data, config, execution_mode, all_dates,
        )
        trades.extend(r_exit_trades)
        decisions.extend(r_exit_decisions)

        if rattle_regime['entries_allowed']:
            r_tradeable = _resolve_rattlesnake_universe(pit_universe, date.year)
            min_age = config.get('MIN_AGE_DAYS', 220)
            r_tradeable = [
                t for t in r_tradeable
                if t in price_data
                and date in price_data[t].index
                and len(price_data[t].loc[:date]) >= min_age
            ]
            if len(r_tradeable) >= 5:
                r_sliced = _slice_history_to_date(
                    price_data, date, symbols=r_tradeable
                )
                r_held = set(slice_positions_by_strategy(state.positions, 'rattle').keys())
                # CRITICAL: exclude symbols held by ANY pillar, not just rattle.
                # state.positions is keyed by symbol — if rattle buys a symbol
                # already held by compass (or any other pillar), the merge would
                # silently overwrite the existing position via dict spread,
                # vanishing the prior pillar's value from PV. This was the v1.4
                # T19 catastrophic loss bug (e.g., GE held by compass, then
                # rattle bought GE on the same day → -67% in 2000-H1).
                all_held = set(state.positions.keys())
                r_max = rattle_regime['max_positions']
                r_slots = r_max - len(r_held)
                if r_slots > 0:
                    r_current_prices = {
                        t: float(price_data[t].loc[date, 'Close'])
                        for t in r_tradeable
                    }
                    candidates = find_rattlesnake_candidates(
                        r_sliced, r_current_prices, all_held, max_candidates=r_slots,
                    )
                    state, r_entry_decisions = apply_rattle_entries_wrapper(
                        state, alloc['rattle_budget'], date, i, price_data,
                        candidates, r_max, config, execution_mode, all_dates,
                    )
                    decisions.extend(r_entry_decisions)

        # ============================================================
        # Catalyst rebalance (every 5 days or whenever empty)
        # ============================================================
        catalyst_day_counter += 1
        catalyst_held = slice_positions_by_strategy(state.positions, 'catalyst')
        if catalyst_day_counter >= CATALYST_REBALANCE_DAYS or not catalyst_held:
            catalyst_day_counter = 0
            state, cat_trades, cat_decisions = apply_catalyst_wrapper(
                state, alloc['catalyst_budget'], date, i, catalyst_assets,
                config, execution_mode, all_dates,
            )
            trades.extend(cat_trades)
            decisions.extend(cat_decisions)

        # ============================================================
        # EFA passive overflow
        # ============================================================
        # Recompute budgets from the updated snapshot to capture the
        # current efa_idle (positions/cash have shifted from the wrappers
        # above). Option C: pure snapshot, no state.capital dependency.
        prices_mid = _current_prices_for_positions(
            state, date, price_data, catalyst_assets, efa_data
        )
        nav_mid = _mark_full_portfolio(
            state, date, price_data, catalyst_assets, efa_data
        )
        alloc_post = compute_budgets_from_snapshot(
            positions=state.positions,
            cash=state.cash,
            prices=prices_mid,
            nav=nav_mid,
            config=config,
        )
        state, efa_trades, efa_decisions = apply_efa_wrapper(
            state, alloc_post['efa_idle'], date, i, efa_data,
            config, execution_mode, all_dates,
        )
        trades.extend(efa_trades)
        decisions.extend(efa_decisions)

        # ============================================================
        # Accounting — DERIVED buckets, recomputed every day from
        # positions + cash share. This is a deeper divergence from
        # live HCM than the dollar-return model: instead of tracking
        # bucket values via daily updates, we treat them as derived
        # quantities computed from the current state. The invariant
        # sub_sum == PV holds by construction, and recycling math is
        # handled correctly because rotated/recycled positions show
        # up in their owning pillar's positions market value.
        #
        # Cash is split among compass/rattle/catalyst by initial
        # weight (BASE_COMPASS / BASE_RATTLE / BASE_CATALYST). EFA
        # owns no cash share — its bucket is purely positions value.
        # ============================================================
        prices_eod_for_acct = _current_prices_for_positions(
            state, date, price_data, catalyst_assets, efa_data
        )
        compass_pos_value = compute_pillar_invested(
            state.positions, 'compass', prices_eod_for_acct
        )
        rattle_pos_value = compute_pillar_invested(
            state.positions, 'rattle', prices_eod_for_acct
        )
        catalyst_pos_value = compute_pillar_invested(
            state.positions, 'catalyst', prices_eod_for_acct
        )
        efa_pos_value = compute_pillar_invested(
            state.positions, 'efa', prices_eod_for_acct
        )
        cash_split_total = (
            config.get('BASE_COMPASS_ALLOC', 0.425)
            + config.get('BASE_RATTLE_ALLOC', 0.425)
            + config.get('BASE_CATALYST_ALLOC', 0.15)
        )
        compass_cash_w = config.get('BASE_COMPASS_ALLOC', 0.425) / cash_split_total
        rattle_cash_w = config.get('BASE_RATTLE_ALLOC', 0.425) / cash_split_total
        catalyst_cash_w = config.get('BASE_CATALYST_ALLOC', 0.15) / cash_split_total
        new_capital = state.capital._replace(
            compass_account=compass_pos_value + state.cash * compass_cash_w,
            rattle_account=rattle_pos_value + state.cash * rattle_cash_w,
            catalyst_account=catalyst_pos_value + state.cash * catalyst_cash_w,
            efa_value=efa_pos_value,
        )
        state = state._replace(capital=new_capital)

        # 6. Snapshot
        pv_after = _mark_full_portfolio(
            state, date, price_data, catalyst_assets, efa_data
        )
        snapshots.append({
            'date': date,
            'portfolio_value': pv_after,
            'cash': state.cash,
            'n_positions': len(state.positions),
            'leverage': leverage,
            'drawdown': drawdown,
            'regime_score': regime_score,
            'crash_active': False,
            'max_positions': max_compass_pos,
            'compass_account': state.capital.compass_account,
            'rattle_account': state.capital.rattle_account,
            'catalyst_account': state.capital.catalyst_account,
            'efa_value': state.capital.efa_value,
            'recycled_pct': alloc['recycled_pct'],
            'n_compass': len(slice_positions_by_strategy(state.positions, 'compass')),
            'n_rattle': len(slice_positions_by_strategy(state.positions, 'rattle')),
            'n_catalyst': len(slice_positions_by_strategy(state.positions, 'catalyst')),
            'n_efa': len(slice_positions_by_strategy(state.positions, 'efa')),
        })

        # 7. Update state tail: peak + days_held + _prev_close stamping.
        # _prev_close is the basis for the next day's daily return calculation
        # via compute_pillar_invested_at_prev_close.
        if pv_after > state.peak_value:
            state = state._replace(peak_value=pv_after)
        prices_eod = _current_prices_for_positions(
            state, date, price_data, catalyst_assets, efa_data
        )
        new_positions = {}
        for sym, p in state.positions.items():
            prev_close = prices_eod.get(
                sym, p.get('_prev_close', p.get('entry_price', 0.0))
            )
            new_positions[sym] = {
                **p,
                'days_held': p.get('days_held', 0) + 1,
                '_prev_close': prev_close,
            }
        state = state._replace(
            positions=new_positions,
            portfolio_value_history=state.portfolio_value_history + (pv_after,),
        )

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
        exit_events=trades,  # all closing trades
        universe_size=universe_size,
        started_at=started_at,
        finished_at=finished_at,
        git_sha=_capture_git_sha(),
        data_inputs_hash=compute_data_fingerprint(price_data),
    )
