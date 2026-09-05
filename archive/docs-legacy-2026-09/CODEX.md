# Codex Agent — HYDRA Project Work Assignment

## Who You Are
You are a new team member on the HYDRA quantitative trading system. Your role is **additive and read-only** relative to the live trading engine. You write tests, analytics scripts, and monitoring tools. You do NOT touch the live engine, state files, or signal logic.

## Project Context
HYDRA is a multi-strategy momentum trading system for S&P 500 large-caps, live paper trading since March 2026. Read `CLAUDE.md` for full project guidelines. The critical points for you:

- **Algorithm is LOCKED** — do NOT modify `omnicapital_live.py`, `omnicapital_v84_compass.py`, `omnicapital_v8_compass.py`
- **State files are sacred** — never write to `state/` directory
- **No leverage** — `LEVERAGE_MAX = 1.0` always
- **Seed 666** — use whenever randomness is needed
- **Python 3.14.2**, PEP 8, snake_case, no type annotations on existing code

## Your Work Areas

### 1. Test Coverage (Priority: HIGH)

The following modules have **zero or minimal test coverage**. Write pytest test files for each.

#### A. `tests/test_hydra_capital.py` — Test `hydra_capital.py` (227 lines)
The `HydraCapitalManager` class manages segregated capital accounts and cash recycling.

Test these scenarios:
- Initial allocation splits correctly: COMPASS 42.5%, Rattlesnake 42.5%, Catalyst 15%
- Cash recycling from idle Rattlesnake → COMPASS (capped at 75% of total)
- Cash recycling returns when Rattlesnake needs capital back
- Edge case: zero idle cash, all capital deployed
- Edge case: negative returns reducing account below zero
- Account rebalancing after position exits
- `get_effective_capital()` returns correct values per strategy

#### B. `tests/test_rattlesnake.py` — Test `rattlesnake_signals.py` (201 lines)
Mean-reversion signal generator for S&P 100 stocks.

Test these scenarios:
- Buy signal fires when: stock drops ≥8% in 5 days AND RSI(5) < 25 AND price > SMA200
- No signal when drop < 8%
- No signal when RSI(5) ≥ 25
- No signal when price < SMA200 (broken trend)
- Exit at +4% profit target
- Exit at -5% stop loss
- Exit at 8-day max hold (time exit)
- Multiple simultaneous signals ranked correctly
- Empty universe returns empty signal list

#### C. `tests/test_catalyst.py` — Test `catalyst_signals.py` (100 lines)
Cross-asset trend following + permanent gold allocation.

Test these scenarios:
- TLT signal: TLT > SMA200 → include, TLT < SMA200 → exclude
- GLD signal: GLD > SMA200 → include (always has base allocation)
- DBC signal: DBC > SMA200 → include
- Permanent gold floor (GLD always gets minimum allocation)
- All ETFs below SMA200 → minimal/defensive positioning
- Capital allocation percentages across active signals

#### D. `tests/test_regime_score.py` — Test regime score computation in `omnicapital_live.py`
Functions: `compute_live_regime_score()`, `regime_score_to_positions()`, `_sigmoid()`

Test these scenarios:
- Sigmoid function: `_sigmoid(0) == 0.5`, `_sigmoid(large_positive) ≈ 1.0`, `_sigmoid(large_negative) ≈ 0.0`
- Sigmoid clipping: extreme inputs don't overflow (`_sigmoid(100)` doesn't raise)
- Regime score with strong bull data → score > 0.65
- Regime score with bear data (price < SMA200, high vol) → score < 0.35
- Insufficient history (< 252 days) → returns 0.5
- Division by zero guard: sma200 = 0 → returns 0.5
- Position mapping: score 0.70 → 5 positions, 0.55 → 4, 0.40 → 3, 0.20 → 2
- Bull override: SPY > SMA200*1.03 AND score > 0.40 → +1 position
- Bull override capped at NUM_POSITIONS (5)
- Trend/vol weighting: 60% trend + 40% vol = 100%

#### E. `tests/test_cycle_log.py` — Test cycle log management
The cycle log tracks 5-day rotation cycles. Test:
- New cycle creation with correct fields (cycle_number, start_date, spy_start, positions)
- Cycle closure after 5 trading days
- SPY return calculation within a cycle
- HYDRA return calculation within a cycle
- Cycle log JSON serialization/deserialization
- Empty cycle log handling
- Multiple cycles accumulating correctly

### 2. Backtest Analytics Scripts (Priority: MEDIUM)

Create scripts in `scripts/` directory. Each should be runnable standalone and output to `backtests/`.

#### A. `scripts/analyze_drawdowns.py`
Read backtest CSV results and produce:
- Max drawdown depth and duration (in trading days)
- Top 5 drawdown periods with start/end dates
- Recovery time for each major drawdown
- Underwater equity curve (days below previous peak)
- Output: `backtests/drawdown_analysis.csv` + printed summary

Input file: `backtests/backtest_v84_compass_results.csv` (or accept path as CLI argument)
Expected columns in CSV: `date`, `portfolio_value`, `benchmark_value` (or similar — read the actual CSV headers first)

#### B. `scripts/monthly_heatmap.py`
Read backtest CSV and produce:
- Monthly returns matrix (rows = years, columns = months)
- Best/worst months highlighted
- Rolling 12-month return
- Output: `backtests/monthly_returns.csv` + printed table

#### C. `scripts/sector_attribution.py`
Read backtest trade log and produce:
- P&L by sector (GICS sectors)
- Win rate by sector
- Average holding period by sector
- Sector concentration over time
- Output: `backtests/sector_attribution.csv`

### 3. Data Validation Scripts (Priority: MEDIUM)

#### A. `scripts/validate_state_integrity.py`
Read `state/compass_state_latest.json` (READ-ONLY) and check:
- JSON is valid
- Required fields present: `cash`, `positions`, `position_meta`, `current_regime_score`, `trading_day`
- Cash is non-negative
- Position quantities are positive integers
- `position_meta` has entries for every position in `positions`
- Each position_meta has: `entry_price`, `entry_date`, `sector`, `entry_vol`
- No duplicate symbols across COMPASS and Rattlesnake positions
- Total invested + cash ≈ portfolio value (within 5% tolerance for price drift)
- Output: PASS/FAIL with details

#### B. `scripts/check_data_freshness.py`
Check Yahoo Finance data cache and FRED cache:
- List cached files with last-modified timestamps
- Flag any cache file older than 7 days
- Verify Yahoo Finance API is responsive (fetch SPY last close)
- Verify FRED API is responsive (fetch DFF latest)
- Output: status report with warnings

### 4. Overlay Unit Tests (Priority: LOW — overlays are currently disabled)

#### `tests/test_overlay_state_persistence.py`
We found bugs in the overlay system where stateful signals reset daily. Write tests to document these:
- `FedEmergencySignal._emergency_start` persists across calls within same instance
- `FedEmergencySignal._emergency_start` is LOST when instance is recreated (document as known bug)
- `FOMCSurpriseSignal._last_surprise_date` persists within instance
- `FOMCSurpriseSignal._last_surprise_date` is LOST on recreation (document as known bug)
- Damping discontinuity: `dd_lev=0.999` vs `dd_lev=1.001` produces large capital jump

## Files You Must NOT Modify

```
omnicapital_live.py          — live trading engine (LOCKED)
omnicapital_v84_compass.py   — backtest algorithm (LOCKED)
omnicapital_v8_compass.py    — legacy algorithm (LOCKED)
compass_dashboard.py         — live dashboard
compass_dashboard_cloud.py   — cloud dashboard
state/*                      — runtime state files
.env                         — secrets
omnicapital_config.json      — credentials
```

## Files You CAN Create/Modify

```
tests/test_*.py              — new test files
scripts/*.py                 — new analytics/validation scripts
backtests/*.csv              — analytics output
docs/*.md                    — documentation
```

## How to Write Tests

```python
import pytest
import pandas as pd
import numpy as np

# Import the module under test
from hydra_capital import HydraCapitalManager  # adjust import path as needed

class TestHydraCapitalManager:
    def test_initial_allocation(self):
        mgr = HydraCapitalManager(total_capital=100_000)
        assert mgr.compass_capital == 42_500
        assert mgr.rattlesnake_capital == 42_500
        assert mgr.catalyst_capital == 15_000

    def test_cash_recycling_cap(self):
        # Recycled cash from Rattlesnake to COMPASS capped at 75%
        mgr = HydraCapitalManager(total_capital=100_000)
        mgr.rattlesnake_idle = 42_500  # all idle
        effective = mgr.get_effective_capital('compass')
        assert effective <= 100_000 * 0.75
```

Run tests with: `pytest tests/test_<name>.py -v`

## How to Write Scripts

```python
"""Drawdown analysis for HYDRA backtest results."""
import argparse
import pandas as pd
import sys

def main():
    parser = argparse.ArgumentParser(description='Analyze drawdowns')
    parser.add_argument('csv_path', nargs='?', default='backtests/backtest_v84_compass_results.csv')
    args = parser.parse_args()

    df = pd.read_csv(args.csv_path, parse_dates=['date'])
    # ... analysis logic ...
    print(f"Max Drawdown: {max_dd:.2%}")
    df_results.to_csv('backtests/drawdown_analysis.csv', index=False)

if __name__ == '__main__':
    main()
```

## Definition of Done

For each deliverable:
1. Code passes `python -c "import py_compile; py_compile.compile('file.py')"`
2. Tests pass: `pytest tests/test_<name>.py -v`
3. Scripts run without error on sample data
4. No modifications to locked files
5. PEP 8 style, snake_case, no type annotations on existing code
6. Conventional commit: `test: add hydra_capital unit tests` or `feat: add drawdown analysis script`
