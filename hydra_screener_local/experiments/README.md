# Experimental / one-off scripts

Lab and research scripts — **not** part of the v9 daily production path.

Production ritual lives at the package root: `daily.py`, `portfolio_v9.py`, `confirm_fills.py`, `dashboard_v9.py`, `warm_sectors.py`. See root [`README.md`](../../README.md) and [`../docs/RUNBOOK.md`](../docs/RUNBOOK.md).

If a script here becomes core, promote it with docs and a main CLI entry — do not document TradingView / hybrid paste flows from this folder.

Measurement scripts worth knowing: `stale_policy_ab.py` (TASK-411 / H-005: the write-off clock with and without production's forward fill, PIT panel; only measures, rule 6 intact).
