# State Reset Investigation: March 16, 2026
**Date**: 2026-03-16
**Analyst**: Gemini
**Status**: Complete

## Executive Summary
On March 16, 2026, the HYDRA engine experienced two critical "fast-forward" events where it re-simulated 5 days of trading (March 10–16) in less than 1 second, effectively wiping out the true live trading history from March 6–9. This caused the portfolio to reset to $100,000 initial capital twice.

## Incident Timeline (from logs)

### Event 1: 12:32:46 PM
- **Action**: Engine started up.
- **State**: Detected "Paper broker connected. Cash initial: $100,000.00".
- **Behavior**:
  - `12:32:46.699`: Processed **Day 1** (Mar 10) — Bought AAPL, MSFT, NVDA.
  - `12:32:46.726`: Processed **Day 2** (Mar 11).
  - `12:32:46.735`: Processed **Day 3** (Mar 12).
  - `12:32:46.743`: Processed **Day 4** (Mar 13) — Sold MSFT, Bought AMZN.
  - `12:32:46.765`: Processed **Day 5** (Mar 16) — Sold AAPL/NVDA, Bought LLY/META.
- **Outcome**: Cycle #1 completed, Cycle #2 opened. State saved.

### Event 2: 12:56:36 PM
- **Action**: Engine restarted.
- **State**: Again detected "Cash initial: $100,000.00" (Reset!).
- **Behavior**: Identical replay of the 12:32 run.
- **Outcome**: Overwrote the previous state files.

## Root Cause Analysis
1.  **Missing or Invalid State File**: The engine failed to load `state/compass_state_latest.json` or deemed it invalid/stale, triggering a fresh start (`_build_default_state`).
2.  **Mock Broker Behavior**: The `PaperBroker` in `omnicapital_live.py` (or `MockBroker`) appears to have a "backfill" or "catch-up" mode enabled, where it iterates through missing days if it detects a gap between `start_date` and `today`.
3.  **Data Persistence**: The fact that it happened *twice* indicates the state saved at 12:32 was NOT persisted or was overwritten/deleted before 12:56.

## Impact
- **Data Loss**: Real trading data from March 6–9 is lost in the current state.
- **P&L Distortion**: The "simulated" trades used mocked or historical prices, potentially diverging from where the live portfolio actually was.
- **Cycle Count**: Reset to Cycle #1, whereas previous logs showed Cycle #219 (likely from a long-running backtest or persistent state).

## Recommendations
1.  **State Backup**: Implement a "safe mode" that refuses to start from $100k if `state/` directory contains *any* historical files.
2.  **Catch-Up Limit**: Disable automatic multi-day catch-up in `omnicapital_live.py`. The engine should process *one* day and wait, or require manual intervention for gaps > 1 day.
3.  **Investigate Broker Init**: specific logic in `omnicapital_live.py` lines 800-900 regarding `load_state()` needs auditing.

## Data Sources
- `logs/compass_live_20260316.log`
- `state/compass_state_latest.json`
