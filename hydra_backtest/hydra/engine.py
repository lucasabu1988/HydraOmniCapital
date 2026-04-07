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
    update_accounts_after_day_pure,
    update_catalyst_value_pure,
    update_efa_value_pure,
)
from hydra_backtest.hydra.state import (
    HydraBacktestState,
    compute_pillar_invested,
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
    """Wrap v1.0 apply_exits with sub-state slicing for the compass pillar."""
    substate = to_pillar_substate(state, 'compass')
    cash_before = substate.cash
    new_substate, trades, decisions = compass_apply_exits(
        substate, date, i, price_data, scores, tradeable,
        max_positions, config, sector_map, execution_mode, all_dates,
    )
    cash_delta = new_substate.cash - cash_before
    new_state = merge_pillar_substate(
        state, new_substate, 'compass',
        cash_delta=cash_delta, capital_account_delta=cash_delta,
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
    """Wrap v1.0 apply_entries with the cash-budget hack.

    Builds a sub-state where cash = compass_budget (NOT broker cash),
    runs apply_entries, and merges the diff back. Real broker cash is
    only deducted by the amount actually spent.
    """
    substate = to_pillar_substate(state, 'compass', cash_override=compass_budget)
    new_substate, decisions = compass_apply_entries(
        substate, date, i, price_data, scores, tradeable,
        max_positions, leverage, config, sector_map, all_dates, execution_mode,
    )
    spent = compass_budget - new_substate.cash  # positive number
    cash_delta = -spent
    new_state = merge_pillar_substate(
        state, new_substate, 'compass',
        cash_delta=cash_delta, capital_account_delta=cash_delta,
    )
    return new_state, decisions
