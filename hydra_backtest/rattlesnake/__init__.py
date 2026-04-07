"""hydra_backtest.rattlesnake — Rattlesnake mean-reversion standalone backtest.

See docs/superpowers/specs/2026-04-07-hydra-backtest-v1.1-rattlesnake-design.md
for the design and docs/superpowers/plans/2026-04-07-hydra-backtest-v1.1-rattlesnake.md
for the implementation plan.
"""
from hydra_backtest.rattlesnake.engine import (
    apply_rattlesnake_entries,
    apply_rattlesnake_exits,
    run_rattlesnake_backtest,
)
from hydra_backtest.rattlesnake.validation import run_rattlesnake_smoke_tests

__all__ = [
    'run_rattlesnake_backtest',
    'apply_rattlesnake_exits',
    'apply_rattlesnake_entries',
    'run_rattlesnake_smoke_tests',
]
