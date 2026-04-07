"""hydra_backtest.hydra — full HYDRA integration backtest.

Composes COMPASS + Rattlesnake + Catalyst + EFA with cash recycling
and the Catalyst ring-fence. Mirrors omnicapital_live order of
operations.

See:
- docs/superpowers/specs/2026-04-07-hydra-backtest-v1.4-hydra-design.md
- docs/superpowers/plans/2026-04-07-hydra-backtest-v1.4-hydra.md
"""
from hydra_backtest.hydra.capital import (
    BASE_CATALYST_ALLOC,
    BASE_COMPASS_ALLOC,
    BASE_RATTLE_ALLOC,
    EFA_DEPLOYMENT_CAP,
    EFA_MIN_BUY,
    MAX_COMPASS_ALLOC,
    HydraCapitalState,
    compute_allocation_pure,
    update_accounts_after_day_pure,
    update_catalyst_value_pure,
    update_efa_value_pure,
)
from hydra_backtest.hydra.engine import (
    apply_catalyst_wrapper,
    apply_compass_entries_wrapper,
    apply_compass_exits_wrapper,
    apply_efa_liquidation,
    apply_efa_wrapper,
    apply_rattle_entries_wrapper,
    apply_rattle_exits_wrapper,
    run_hydra_backtest,
)
from hydra_backtest.hydra.layer_b import compute_layer_b_report
from hydra_backtest.hydra.state import (
    HydraBacktestState,
    compute_pillar_invested,
    merge_pillar_substate,
    slice_positions_by_strategy,
    to_pillar_substate,
)
from hydra_backtest.hydra.validation import run_hydra_smoke_tests

__all__ = [
    # capital
    'HydraCapitalState',
    'compute_allocation_pure',
    'update_accounts_after_day_pure',
    'update_efa_value_pure',
    'update_catalyst_value_pure',
    'BASE_COMPASS_ALLOC',
    'BASE_RATTLE_ALLOC',
    'BASE_CATALYST_ALLOC',
    'MAX_COMPASS_ALLOC',
    'EFA_MIN_BUY',
    'EFA_DEPLOYMENT_CAP',
    # state
    'HydraBacktestState',
    'slice_positions_by_strategy',
    'to_pillar_substate',
    'merge_pillar_substate',
    'compute_pillar_invested',
    # engine
    'run_hydra_backtest',
    'apply_compass_exits_wrapper',
    'apply_compass_entries_wrapper',
    'apply_rattle_exits_wrapper',
    'apply_rattle_entries_wrapper',
    'apply_catalyst_wrapper',
    'apply_efa_wrapper',
    'apply_efa_liquidation',
    # validation + layer b
    'run_hydra_smoke_tests',
    'compute_layer_b_report',
]
