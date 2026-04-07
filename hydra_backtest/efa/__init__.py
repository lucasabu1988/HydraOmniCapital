"""hydra_backtest.efa — EFA passive international trend standalone backtest.

Single-asset (EFA, iShares MSCI EAFE), long when above SMA200, cash
otherwise. No rebalance cadence, no PIT, no other-strategy interaction.

See:
- docs/superpowers/specs/2026-04-07-hydra-backtest-v1.3-efa-design.md
- docs/superpowers/plans/2026-04-07-hydra-backtest-v1.3-efa.md

Public API symbols are wired in Task 7 once engine and validation exist.
"""
