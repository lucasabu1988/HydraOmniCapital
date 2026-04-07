"""hydra_backtest.efa — EFA passive international trend standalone backtest.

Single-asset (EFA, iShares MSCI EAFE), long when above SMA200, cash
otherwise. No rebalance cadence, no PIT, no other-strategy interaction.

See:
- docs/superpowers/specs/2026-04-07-hydra-backtest-v1.3-efa-design.md
- docs/superpowers/plans/2026-04-07-hydra-backtest-v1.3-efa.md
"""
from hydra_backtest.efa.engine import (
    EFA_SMA_PERIOD,
    EFA_SYMBOL,
    apply_efa_decision,
    run_efa_backtest,
)
from hydra_backtest.efa.validation import run_efa_smoke_tests

__all__ = [
    'EFA_SYMBOL',
    'EFA_SMA_PERIOD',
    'apply_efa_decision',
    'run_efa_backtest',
    'run_efa_smoke_tests',
]
