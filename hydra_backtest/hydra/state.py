"""hydra_backtest.hydra.state — combined state model for the full HYDRA backtest.

HydraBacktestState wraps v1.0's BacktestState concept (cash, positions,
peak_value, etc.) with sub-account accounting via HydraCapitalState
and a position-tagging convention.

Position tag convention:
    Every position dict in state.positions MUST include
    `'_strategy'` set to one of:
        'compass' | 'rattle' | 'catalyst' | 'efa'

The sub-state slicers below use this tag to extract per-pillar views
of the state for routing through the existing v1.0-v1.3 apply helpers.
"""
from dataclasses import dataclass, replace
from typing import Dict

from hydra_backtest.engine import BacktestState
from hydra_backtest.hydra.capital import HydraCapitalState

VALID_STRATEGIES = ('compass', 'rattle', 'catalyst', 'efa')


@dataclass(frozen=True)
class HydraBacktestState:
    """Combined state for the full HYDRA backtest."""
    cash: float                       # ONE shared broker cash pool
    positions: dict                   # ALL positions, tagged by _strategy
    peak_value: float
    crash_cooldown: int
    portfolio_value_history: tuple
    capital: HydraCapitalState

    def _replace(self, **kwargs) -> 'HydraBacktestState':
        return replace(self, **kwargs)


def slice_positions_by_strategy(
    positions: dict,
    strategy: str,
) -> dict:
    """Return a dict of positions belonging to one strategy.

    Filters by the `_strategy` tag. Positions without a tag are
    silently excluded — the position tag completeness invariant
    catches any orphans.
    """
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"Invalid strategy: {strategy!r}")
    return {
        sym: pos for sym, pos in positions.items()
        if pos.get('_strategy') == strategy
    }


def to_pillar_substate(
    state: HydraBacktestState,
    strategy: str,
    cash_override: float = None,
) -> BacktestState:
    """Build a v1.0 BacktestState containing only one pillar's positions.

    If `cash_override` is None, uses the full broker cash. Otherwise
    uses the override (typical use: cash_override=pillar_budget for
    entry calls so the apply helper sees the budget cap).
    """
    pillar_positions = slice_positions_by_strategy(state.positions, strategy)
    return BacktestState(
        cash=cash_override if cash_override is not None else state.cash,
        positions=pillar_positions,
        peak_value=state.peak_value,
        crash_cooldown=state.crash_cooldown,
        portfolio_value_history=state.portfolio_value_history,
    )


def merge_pillar_substate(
    state: HydraBacktestState,
    new_substate: BacktestState,
    strategy: str,
    cash_delta: float,
    capital_account_delta: float,
) -> HydraBacktestState:
    """Merge changes from a pillar substate back into the full state.

    `cash_delta`: how the broker cash changed (negative for spend,
        positive for sell proceeds).
    `capital_account_delta`: how the corresponding capital sub-account
        changed (typically equal to cash_delta for entries/exits).

    All NEW positions in new_substate are tagged with `_strategy` so
    the position tag completeness invariant holds.
    """
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"Invalid strategy: {strategy!r}")

    other_positions = {
        sym: pos for sym, pos in state.positions.items()
        if pos.get('_strategy') != strategy
    }
    new_pillar_positions = {
        sym: {**pos, '_strategy': strategy}
        for sym, pos in new_substate.positions.items()
    }
    merged_positions = {**other_positions, **new_pillar_positions}

    if strategy == 'compass':
        new_capital = state.capital._replace(
            compass_account=state.capital.compass_account + capital_account_delta
        )
    elif strategy == 'rattle':
        new_capital = state.capital._replace(
            rattle_account=state.capital.rattle_account + capital_account_delta
        )
    elif strategy == 'catalyst':
        new_capital = state.capital._replace(
            catalyst_account=state.capital.catalyst_account + capital_account_delta
        )
    else:  # efa
        new_capital = state.capital._replace(
            efa_value=state.capital.efa_value + capital_account_delta
        )

    return state._replace(
        cash=state.cash + cash_delta,
        positions=merged_positions,
        capital=new_capital,
    )


def compute_pillar_invested(
    positions: dict,
    strategy: str,
    current_prices: Dict[str, float],
) -> float:
    """Sum the market value of one pillar's positions at current prices.

    Used by the engine to compute c_ret and r_ret for
    update_accounts_after_day_pure (mirrors omnicapital_live.py:2882-2893).
    """
    pillar_positions = slice_positions_by_strategy(positions, strategy)
    total = 0.0
    for sym, pos in pillar_positions.items():
        price = current_prices.get(sym, pos.get('entry_price', 0.0))
        total += pos.get('shares', 0) * price
    return total
