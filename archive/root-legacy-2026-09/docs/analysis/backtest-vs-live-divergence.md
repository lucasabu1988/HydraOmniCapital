# Backtest vs Live Divergence Analysis
**Date**: 2026-03-16
**Analyst**: Gemini
**Status**: Complete

## Executive Summary
This report analyzes the performance and structural differences between the HYDRA v8.4 backtest and the live paper trading results since March 6, 2026. While the core algorithm remains aligned, significant universe divergence and recent state inconsistencies pose risks to long-term performance tracking.

## Findings

### 1. Universe Divergence — [HIGH]
- **Backtest Universe**: The backtest (`hydra_clean_daily.csv`) was performed on a survivor-bias-corrected pool of ~1,128 unique historical constituents (1996-2026).
- **Live Universe**: The live engine is currently restricted to a dynamic "Top 40" of the current S&P 500.
- **Impact**: The live system faces "Live Bias" (selecting from today's winners). While the backtest corrects for survivorship bias, the live system's narrower focus (40 vs 800+) increases idiosyncratic risk and may not capture the full breadth of momentum available in the broader market.

### 2. Parameter Alignment — [LOW]
- **Status**: **Matched**.
- Core parameters in `omnicapital_v84_compass.py` and `omnicapital_live.py` are identical:
    - `MOMENTUM_LOOKBACK`: 90d
    - `HOLD_DAYS`: 5d
    - `NUM_POSITIONS`: 5 (Risk-On) / 2 (Risk-Off)
    - `STOP_DAILY_VOL_MULT`: 2.5x
- All v8.4 improvements (Bull Override, Adaptive Stops, Sector Limits) are correctly implemented in the live environment.

### 3. Expected vs Actual Returns (Mar 6 – Mar 16) — [MEDIUM]
- **Live Performance**:
    - Mar 6 – Mar 13: The portfolio grew from $100,000 to $101,462 (+1.46%).
    - Mar 16: The portfolio reset to $100,000 in `compass_state_latest.json`.
- **Divergence**: A critical state reset or "fast-forward" run occurred on March 16th, as evidenced by `logs/compass_live_20260316.log`. This run processed Day 1 (Mar 10) through Day 5 (Mar 16) in seconds, overwriting the real history from Mar 6.
- **Expected Return**: The backtest shows an average daily return of ~0.05-0.08%. The 1.46% gain in the first week was above average but consistent with a momentum surge.

### 4. State File Inconsistency — [CRITICAL]
- `compass_state_20260313.json` shows positions: JNJ, MRK, WMT, XOM, EFA.
- `compass_live_20260316.log` shows the engine trading: AAPL, MSFT, NVDA.
- This suggests the live engine is out of sync with its own state files or multiple instances are running.

## Recommendations
1. **Sync State**: Immediately reconcile the live broker positions with the state file. The current "empty" positions in `latest.json` while the log shows active entries is a major risk.
2. **Universe Expansion**: Evaluate the feasibility of expanding the live universe to the full S&P 500 (500 tickers) instead of just the Top 40 to better match backtest breadth.
3. **Audit State Resets**: Investigate why the `trading_day_counter` reset to 1 on March 16th.

## Data Sources
- `backtests/hydra_clean_daily.csv`
- `state/compass_state_latest.json`
- `state/compass_state_20260313.json`
- `logs/compass_live_20260316.log`
- `omnicapital_v84_compass.py`
