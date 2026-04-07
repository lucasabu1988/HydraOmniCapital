"""hydra_backtest.hydra — full HYDRA integration backtest.

Composes COMPASS + Rattlesnake + Catalyst + EFA with cash recycling
and the Catalyst ring-fence. Mirrors omnicapital_live order of
operations.

See:
- docs/superpowers/specs/2026-04-07-hydra-backtest-v1.4-hydra-design.md
- docs/superpowers/plans/2026-04-07-hydra-backtest-v1.4-hydra.md

Public API symbols are wired in Task 11 once engine and validation exist.
"""
