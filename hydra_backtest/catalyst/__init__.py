"""hydra_backtest.catalyst — Catalyst cross-asset trend standalone backtest.

Trend-following on TLT/ZROZ/GLD/DBC, equal-weight among assets above
their 200-day SMA, rebalancing every 5 days.

See:
- docs/superpowers/specs/2026-04-07-hydra-backtest-v1.2-catalyst-design.md
- docs/superpowers/plans/2026-04-07-hydra-backtest-v1.2-catalyst.md

Public API symbols are wired in Task 6 once engine and validation exist.
"""
