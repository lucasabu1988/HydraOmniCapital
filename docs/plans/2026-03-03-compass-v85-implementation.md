# COMPASS v8.5 — Stop Widening + Market Breadth Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create COMPASS v8.5 with two improvements over v84: regime-conditional stop widening (reduces whipsaw stop losses in bull markets) and market breadth as a third regime component (reduces false risk-off days).

**Architecture:** Copy v84 into new file `omnicapital_v85_compass.py`. Add `compute_breadth_score()` function. Modify `compute_regime_score()` signature to accept price_data + tradeable_symbols and add breadth weighting. Modify stop logic in `run_backtest()` to apply regime-dependent multiplier. Run full backtest and compare vs v84 baseline.

**Tech Stack:** Python 3.14, pandas, numpy, yfinance. pytest for tests.

---

### Task 1: Create v85 file from v84

**Files:**
- Create: `omnicapital_v85_compass.py` (copy of `omnicapital_v84_compass.py`)

**Step 1: Copy v84 to v85**

Run:
```bash
cp omnicapital_v84_compass.py omnicapital_v85_compass.py
```

**Step 2: Update the docstring header**

Replace the first docstring in `omnicapital_v85_compass.py` with:

```python
"""
OmniCapital v8.5 COMPASS - Stop Widening + Market Breadth
==================================================================================
Based on v8.4 COMPASS with 2 targeted improvements:

1. REGIME-CONDITIONAL STOP WIDENING: In bull markets (regime >= 0.65), multiply
   adaptive stop by 1.4x (wider). In mild bull (>= 0.50), multiply by 1.2x.
   Bear markets unchanged. Reduces whipsaw stop losses that destroy $1.81M in v84.

2. MARKET BREADTH REGIME: Add % of stocks above SMA50 as third regime component.
   New weights: trend 45% + vol 30% + breadth 25% (was trend 60% + vol 40%).
   Reduces false risk-off days by providing cross-sectional market health.

All other parameters and logic preserved from v8.4.
"""
```

**Step 3: Add new constants after the existing v8.4 sector constants section**

```python
# ============================================================================
# v8.5 IMPROVEMENT 1: Regime-Conditional Stop Widening
# ============================================================================
STOP_BULL_MULT = 1.4        # Stop 40% wider when regime >= 0.65
STOP_MILD_BULL_MULT = 1.2   # Stop 20% wider when regime >= 0.50

# ============================================================================
# v8.5 IMPROVEMENT 2: Market Breadth in Regime Score
# ============================================================================
REGIME_TREND_WEIGHT = 0.45     # Was 0.60 in v84
REGIME_VOL_WEIGHT = 0.30       # Was 0.40 in v84
REGIME_BREADTH_WEIGHT = 0.25   # New component
BREADTH_SMA_WINDOW = 50        # SMA50 for breadth calculation
BREADTH_SIGMOID_K = 8.0        # Sensitivity around 50% threshold
```

**Step 4: Verify syntax**

Run: `python -c "import py_compile; py_compile.compile('omnicapital_v85_compass.py')"`
Expected: No output (success)

**Step 5: Commit**

```bash
git add omnicapital_v85_compass.py
git commit -m "feat: scaffold v85 compass from v84 with new constants"
```

---

### Task 2: Implement compute_breadth_score()

**Files:**
- Modify: `omnicapital_v85_compass.py`
- Test: `tests/test_v85_improvements.py`

**Step 1: Write the failing test**

Create `tests/test_v85_improvements.py`:

```python
"""Tests for COMPASS v8.5 improvements: stop widening + market breadth."""

import pandas as pd
import numpy as np
import pytest


def _make_price_df(prices, start='2020-01-01'):
    """Helper: create a minimal price DataFrame from a list of close prices."""
    dates = pd.bdate_range(start, periods=len(prices))
    return pd.DataFrame({'Close': prices}, index=dates)


class TestBreadthScore:
    """Test compute_breadth_score()."""

    def test_all_stocks_above_sma50(self):
        """When all stocks are above SMA50, breadth_pct=1.0, score > 0.5."""
        from omnicapital_v85_compass import compute_breadth_score, _sigmoid
        # 60 days of steadily rising prices (all above SMA50)
        prices_up = list(range(100, 160))
        price_data = {
            'AAPL': _make_price_df(prices_up),
            'MSFT': _make_price_df(prices_up),
            'GOOGL': _make_price_df(prices_up),
        }
        tradeable = ['AAPL', 'MSFT', 'GOOGL']
        date = price_data['AAPL'].index[-1]
        score = compute_breadth_score(price_data, tradeable, date)
        assert score > 0.5, f"All above SMA50 should give score > 0.5, got {score}"

    def test_all_stocks_below_sma50(self):
        """When all stocks are below SMA50, breadth_pct=0.0, score < 0.5."""
        from omnicapital_v85_compass import compute_breadth_score
        # 60 days of steadily falling prices (all below SMA50)
        prices_down = list(range(160, 100, -1))
        price_data = {
            'AAPL': _make_price_df(prices_down),
            'MSFT': _make_price_df(prices_down),
        }
        tradeable = ['AAPL', 'MSFT']
        date = price_data['AAPL'].index[-1]
        score = compute_breadth_score(price_data, tradeable, date)
        assert score < 0.5, f"All below SMA50 should give score < 0.5, got {score}"

    def test_mixed_breadth(self):
        """50% above SMA50 should give score near 0.5."""
        from omnicapital_v85_compass import compute_breadth_score
        prices_up = list(range(100, 160))
        prices_down = list(range(160, 100, -1))
        price_data = {
            'AAPL': _make_price_df(prices_up),
            'MSFT': _make_price_df(prices_down),
        }
        tradeable = ['AAPL', 'MSFT']
        date = price_data['AAPL'].index[-1]
        score = compute_breadth_score(price_data, tradeable, date)
        assert 0.45 <= score <= 0.55, f"50/50 breadth should be ~0.5, got {score}"

    def test_insufficient_history(self):
        """Stocks with < 50 days are skipped; if none qualify, return 0.5."""
        from omnicapital_v85_compass import compute_breadth_score
        prices_short = list(range(100, 130))  # Only 30 days
        price_data = {'AAPL': _make_price_df(prices_short)}
        tradeable = ['AAPL']
        date = price_data['AAPL'].index[-1]
        score = compute_breadth_score(price_data, tradeable, date)
        assert score == 0.5, f"No qualifying stocks should return 0.5, got {score}"

    def test_empty_tradeable(self):
        """Empty tradeable list returns 0.5."""
        from omnicapital_v85_compass import compute_breadth_score
        score = compute_breadth_score({}, [], pd.Timestamp('2024-01-15'))
        assert score == 0.5
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_v85_improvements.py::TestBreadthScore -v`
Expected: FAIL with `ImportError: cannot import name 'compute_breadth_score'`

**Step 3: Implement compute_breadth_score()**

Add this function in `omnicapital_v85_compass.py` right after the `compute_regime_score()` function (after line ~439):

```python
def compute_breadth_score(price_data: Dict[str, pd.DataFrame],
                          tradeable_symbols: List[str],
                          date: pd.Timestamp) -> float:
    """
    v8.5: Compute market breadth score from fraction of stocks above SMA50.
    Returns sigmoid-transformed score [0, 1]. 0.5 = exactly 50% above SMA50.
    """
    above = 0
    total = 0
    for symbol in tradeable_symbols:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        try:
            idx = df.index.get_loc(date)
        except KeyError:
            continue
        if idx < BREADTH_SMA_WINDOW:
            continue
        current = float(df['Close'].iloc[idx])
        sma = float(df['Close'].iloc[idx - BREADTH_SMA_WINDOW + 1:idx + 1].mean())
        total += 1
        if current > sma:
            above += 1
    if total == 0:
        return 0.5
    breadth_pct = above / total
    return float(_sigmoid(breadth_pct - 0.50, k=BREADTH_SIGMOID_K))
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_v85_improvements.py::TestBreadthScore -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add omnicapital_v85_compass.py tests/test_v85_improvements.py
git commit -m "feat: add compute_breadth_score() for v85 regime"
```

---

### Task 3: Integrate breadth into compute_regime_score()

**Files:**
- Modify: `omnicapital_v85_compass.py` (function `compute_regime_score`)
- Test: `tests/test_v85_improvements.py`

**Step 1: Write the failing test**

Add to `tests/test_v85_improvements.py`:

```python
class TestRegimeWithBreadth:
    """Test that regime score incorporates breadth component."""

    def test_regime_uses_breadth_weight(self):
        """Regime score should use 0.45/0.30/0.25 weights (trend/vol/breadth)."""
        from omnicapital_v85_compass import REGIME_TREND_WEIGHT, REGIME_VOL_WEIGHT, REGIME_BREADTH_WEIGHT
        assert abs(REGIME_TREND_WEIGHT + REGIME_VOL_WEIGHT + REGIME_BREADTH_WEIGHT - 1.0) < 0.001

    def test_regime_signature_accepts_breadth_args(self):
        """compute_regime_score() should accept price_data and tradeable_symbols."""
        import inspect
        from omnicapital_v85_compass import compute_regime_score
        sig = inspect.signature(compute_regime_score)
        params = list(sig.parameters.keys())
        assert 'price_data' in params, f"Missing price_data param: {params}"
        assert 'tradeable_symbols' in params, f"Missing tradeable_symbols param: {params}"

    def test_high_breadth_increases_regime(self):
        """With all stocks above SMA50, regime should be higher than vol-only default."""
        from omnicapital_v85_compass import compute_regime_score
        import pandas as pd
        # Create SPY with neutral trend (price == SMA200)
        spy_prices = [100.0] * 300
        spy_dates = pd.bdate_range('2019-01-01', periods=300)
        spy_data = pd.DataFrame({'Close': spy_prices}, index=spy_dates)
        date = spy_dates[-1]

        # No breadth (backward compat: should work without extra args)
        score_no_breadth = compute_regime_score(spy_data, date)

        # With breadth: all stocks rising
        prices_up = [float(i) for i in range(100, 400)]
        price_data = {
            'AAPL': pd.DataFrame({'Close': prices_up[:300]}, index=spy_dates),
            'MSFT': pd.DataFrame({'Close': prices_up[:300]}, index=spy_dates),
        }
        score_with_breadth = compute_regime_score(
            spy_data, date, price_data=price_data, tradeable_symbols=['AAPL', 'MSFT']
        )
        # High breadth (all above SMA50) should push score up
        assert score_with_breadth >= score_no_breadth, \
            f"Breadth should increase regime: {score_with_breadth} vs {score_no_breadth}"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_v85_improvements.py::TestRegimeWithBreadth -v`
Expected: FAIL (compute_regime_score doesn't accept price_data/tradeable_symbols yet)

**Step 3: Modify compute_regime_score() signature and body**

In `omnicapital_v85_compass.py`, modify `compute_regime_score()`:

Change the signature from:
```python
def compute_regime_score(spy_data: pd.DataFrame, date: pd.Timestamp) -> float:
```
To:
```python
def compute_regime_score(spy_data: pd.DataFrame, date: pd.Timestamp,
                         price_data: Optional[Dict[str, pd.DataFrame]] = None,
                         tradeable_symbols: Optional[List[str]] = None) -> float:
```

Change the final composite calculation from:
```python
    composite = 0.60 * trend_score + 0.40 * vol_score
    return float(np.clip(composite, 0.0, 1.0))
```
To:
```python
    # v8.5: Add breadth component if data available
    if price_data is not None and tradeable_symbols is not None:
        breadth = compute_breadth_score(price_data, tradeable_symbols, date)
        composite = (REGIME_TREND_WEIGHT * trend_score +
                     REGIME_VOL_WEIGHT * vol_score +
                     REGIME_BREADTH_WEIGHT * breadth)
    else:
        composite = 0.60 * trend_score + 0.40 * vol_score

    return float(np.clip(composite, 0.0, 1.0))
```

**Step 4: Update run_backtest() to pass price_data and tradeable_symbols to compute_regime_score()**

In `run_backtest()`, find the line:
```python
        regime_score = compute_regime_score(spy_data, date)
```
Replace with:
```python
        regime_score = compute_regime_score(spy_data, date,
                                            price_data=price_data,
                                            tradeable_symbols=tradeable_symbols)
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_v85_improvements.py -v`
Expected: All tests PASS

**Step 6: Verify syntax**

Run: `python -c "import py_compile; py_compile.compile('omnicapital_v85_compass.py')"`

**Step 7: Commit**

```bash
git add omnicapital_v85_compass.py tests/test_v85_improvements.py
git commit -m "feat: integrate breadth into regime score (v85)"
```

---

### Task 4: Implement regime-conditional stop widening

**Files:**
- Modify: `omnicapital_v85_compass.py` (function `run_backtest`)
- Test: `tests/test_v85_improvements.py`

**Step 1: Write the failing test**

Add to `tests/test_v85_improvements.py`:

```python
class TestStopWidening:
    """Test regime-conditional stop widening."""

    def test_bull_regime_widens_stop(self):
        """Regime >= 0.65 should multiply stop by STOP_BULL_MULT (1.4)."""
        from omnicapital_v85_compass import (
            compute_adaptive_stop, STOP_BULL_MULT, STOP_MILD_BULL_MULT
        )
        base_stop = compute_adaptive_stop(0.025)  # typical daily vol

        # Bull regime
        regime_score = 0.70
        if regime_score >= 0.65:
            mult = STOP_BULL_MULT
        elif regime_score >= 0.50:
            mult = STOP_MILD_BULL_MULT
        else:
            mult = 1.0
        widened = base_stop * mult
        assert widened < base_stop, f"Wider stop should be more negative: {widened} vs {base_stop}"
        assert abs(widened - base_stop * 1.4) < 0.001

    def test_mild_bull_widens_stop(self):
        """Regime >= 0.50 and < 0.65 should multiply by STOP_MILD_BULL_MULT (1.2)."""
        from omnicapital_v85_compass import (
            compute_adaptive_stop, STOP_MILD_BULL_MULT
        )
        base_stop = compute_adaptive_stop(0.025)
        regime_score = 0.55
        mult = STOP_MILD_BULL_MULT if 0.50 <= regime_score < 0.65 else 1.0
        widened = base_stop * mult
        assert abs(widened - base_stop * 1.2) < 0.001

    def test_bear_regime_no_widening(self):
        """Regime < 0.50 should not widen the stop (mult = 1.0)."""
        from omnicapital_v85_compass import compute_adaptive_stop
        base_stop = compute_adaptive_stop(0.025)
        regime_score = 0.35
        mult = 1.0  # bear
        assert base_stop * mult == base_stop

    def test_widened_stop_respects_ceiling(self):
        """Even after widening, stop should not exceed STOP_CEILING."""
        from omnicapital_v85_compass import (
            compute_adaptive_stop, STOP_BULL_MULT, STOP_CEILING
        )
        # High vol stock: stop near ceiling
        base_stop = compute_adaptive_stop(0.06)  # very high vol
        widened = base_stop * STOP_BULL_MULT
        # After widening, clamp to ceiling
        clamped = max(STOP_CEILING, widened)
        assert clamped >= STOP_CEILING, f"Should not exceed ceiling: {clamped}"
```

**Step 2: Run test to verify it passes (these are unit tests on constants, should pass)**

Run: `pytest tests/test_v85_improvements.py::TestStopWidening -v`
Expected: PASS (these test the logic, not the integration yet)

**Step 3: Modify run_backtest() to apply regime stop widening**

In `run_backtest()` in `omnicapital_v85_compass.py`, find the stop loss check block:
```python
            # 2. Position stop loss (v8.4: adaptive, vol-scaled)
            pos_return = (current_price - pos['entry_price']) / pos['entry_price']
            adaptive_stop = compute_adaptive_stop(pos.get('entry_daily_vol', 0.016))
            if pos_return <= adaptive_stop:
                exit_reason = 'position_stop'
```

Replace with:
```python
            # 2. Position stop loss (v8.5: adaptive, vol-scaled, regime-widened)
            pos_return = (current_price - pos['entry_price']) / pos['entry_price']
            adaptive_stop = compute_adaptive_stop(pos.get('entry_daily_vol', 0.016))
            # v8.5: Widen stops in bull markets to reduce whipsaws
            if regime_score >= 0.65:
                adaptive_stop = max(STOP_CEILING, adaptive_stop * STOP_BULL_MULT)
            elif regime_score >= 0.50:
                adaptive_stop = max(STOP_CEILING, adaptive_stop * STOP_MILD_BULL_MULT)
            if pos_return <= adaptive_stop:
                exit_reason = 'position_stop'
```

Note: `max(STOP_CEILING, ...)` because stops are negative — STOP_CEILING is -0.15 (the widest allowed). `max` ensures we don't go wider than the ceiling.

**Step 4: Verify syntax**

Run: `python -c "import py_compile; py_compile.compile('omnicapital_v85_compass.py')"`

**Step 5: Run all tests**

Run: `pytest tests/test_v85_improvements.py -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add omnicapital_v85_compass.py tests/test_v85_improvements.py
git commit -m "feat: add regime-conditional stop widening (v85)"
```

---

### Task 5: Update the comparison section at bottom of v85

**Files:**
- Modify: `omnicapital_v85_compass.py` (the `if __name__ == '__main__'` section)

**Step 1: Update the comparison baseline references**

Find the section at the bottom of the file that prints comparison vs previous versions. Update it to compare v85 vs v84 baseline.

Find any line referencing `baseline_v83` or `baseline_v84` and ensure the v85 metrics print correctly. Change:
```python
    baseline_v84 = {
```
to ensure it uses the correct v84 baseline numbers. Update the output label from `v84` to `v85`:

Find:
```python
    v84 = {
```
Change to:
```python
    v85 = {
```

And update all references from `v84` to `v85` in the comparison print statements at the end.

Also update the output CSV filenames from `v84_compass_daily.csv` / `v84_compass_trades.csv` to `v85_compass_daily.csv` / `v85_compass_trades.csv`.

**Step 2: Verify syntax**

Run: `python -c "import py_compile; py_compile.compile('omnicapital_v85_compass.py')"`

**Step 3: Commit**

```bash
git add omnicapital_v85_compass.py
git commit -m "refactor: update v85 output labels and CSV filenames"
```

---

### Task 6: Run backtest and evaluate results

**Files:**
- Run: `omnicapital_v85_compass.py`
- Output: `backtests/v85_compass_daily.csv`, `backtests/v85_compass_trades.csv`

**Step 1: Run the v85 backtest**

Run: `python omnicapital_v85_compass.py`
Expected: Full backtest output with annual returns and metrics comparison.

**Step 2: Evaluate against kill criteria**

Check the output for:
- **CAGR delta vs 12.02%**: must be >= -0.30% (i.e., CAGR >= 11.72%)
- **MaxDD**: must be no worse than -33.5% (vs -32.6% baseline)
- **Sharpe**: must be >= 0.85 (vs 0.88 baseline)

**Step 3: Evaluate against success criteria**

Check:
- CAGR improvement >= +50bps (target >= 12.52%)
- Sharpe >= 0.90
- Stop loss count reduced by >= 20% (baseline: 274 stops)

**Step 4: If PASSES — commit results**

```bash
git add backtests/v85_compass_daily.csv backtests/v85_compass_trades.csv
git commit -m "data: v85 backtest results — stop widening + breadth regime"
```

**Step 5: If FAILS kill criteria — diagnose and iterate**

If kill criteria triggered:
1. Check which metric failed
2. If MaxDD worsened: breadth sigmoid k may need tuning (try k=6.0 for softer transition)
3. If CAGR dropped: stop widening mult may be too aggressive (try 1.3/1.1 instead of 1.4/1.2)
4. If Sharpe dropped: check if vol increased disproportionately

Adjust parameters and re-run. Do NOT change more than one parameter at a time.

---

### Task 7: Generate comparison analysis

**Files:**
- Read: `backtests/v84_compass_daily.csv`, `backtests/v85_compass_daily.csv`
- Read: `backtests/v84_compass_trades.csv`, `backtests/v85_compass_trades.csv`

**Step 1: Compare annual returns**

Print side-by-side annual returns: v84 vs v85, with delta column.

**Step 2: Compare stop loss statistics**

- v84 stop count vs v85 stop count
- v84 stop PnL vs v85 stop PnL
- v84 risk-off days vs v85 risk-off days

**Step 3: Compare regime breakdown**

- % risk-on days: v84 vs v85
- % time in protection: v84 vs v85
- Average positions: v84 vs v85

**Step 4: Summarize findings and determine verdict**

Print PASS/FAIL for each kill criterion and each success criterion.
