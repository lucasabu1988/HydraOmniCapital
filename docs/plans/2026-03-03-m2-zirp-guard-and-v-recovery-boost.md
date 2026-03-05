# M2 ZIRP Guard + V-Recovery Momentum Boost — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix two identified COMPASS flaws: (1) M2 overlay false-triggers during QE/ZIRP by adding Fed Funds context, (2) slow V-recovery re-entry by boosting regime score when SPY shows strong short-term momentum during protection mode.

**Architecture:** Both fixes are implemented in the overlay layer (`compass_overlays.py`, `compass_overlay_backtest.py`) and FRED data layer (`compass_fred_data.py`). The locked algorithm (`omnicapital_v84_compass.py`) is NOT modified — the V-recovery boost operates on the regime score *after* it's computed by the imported function, inside the overlay backtest loop.

**Tech Stack:** Python 3.14, pandas, numpy, pytest. FRED API (no key required).

---

### Task 1: Add FEDFUNDS to FRED Data Fetcher

**Files:**
- Modify: `compass_fred_data.py:18-33` (FRED_SERIES registry)

**Step 1: Write the failing test**

Create test in `tests/test_overlays.py`:

```python
# Add to imports at top of file (line 14):
from compass_fred_data import download_all_overlay_data, download_fred_series

# Add new test class after TestCashOptimization (after line 163):
class TestFedFundsData:
    def test_fedfunds_in_registry(self, fred_data):
        """FEDFUNDS should be downloaded as part of overlay data."""
        assert 'FEDFUNDS' in fred_data, "FEDFUNDS missing from fred_data dict"
        assert fred_data['FEDFUNDS'] is not None, "FEDFUNDS series is None"

    def test_fedfunds_zirp_2010(self, fred_data):
        """Fed Funds should be near-zero in 2010 (ZIRP)."""
        ff = fred_data['FEDFUNDS']
        val = ff[ff.index <= pd.Timestamp('2010-01-15')].iloc[-1]
        assert val < 0.25, f"Fed Funds should be <0.25% in Jan 2010, got {val}"

    def test_fedfunds_hiking_2023(self, fred_data):
        """Fed Funds should be >4% in 2023 (hiking cycle)."""
        ff = fred_data['FEDFUNDS']
        val = ff[ff.index <= pd.Timestamp('2023-06-15')].iloc[-1]
        assert val > 4.0, f"Fed Funds should be >4% in Jun 2023, got {val}"
```

**Step 2: Run test to verify it fails**

Run: `cd C:/Users/caslu/Desktop/NuevoProyecto && python -m pytest tests/test_overlays.py::TestFedFundsData -v`
Expected: FAIL — `FEDFUNDS` not in `fred_data` dict.

**Step 3: Add FEDFUNDS to the FRED series registry**

In `compass_fred_data.py`, add to `FRED_SERIES` dict after the `DFF` entry (line 26):

```python
    # M2 ZIRP Guard (context for M2 overlay)
    'FEDFUNDS':      {'start': '1954-07-01', 'desc': 'Federal Funds Effective Rate Monthly (%)'},
```

Note: `FEDFUNDS` is the monthly effective rate. `DFF` (already present) is daily. We use `FEDFUNDS` because it's cleaner for the monthly ZIRP check — but `DFF` would also work. Since `DFF` is already fetched, we can actually reuse it. However, `FEDFUNDS` is the canonical monthly series and avoids daily noise. Both get forward-filled to daily by `download_fred_series()`.

**Step 4: Run test to verify it passes**

Run: `cd C:/Users/caslu/Desktop/NuevoProyecto && python -m pytest tests/test_overlays.py::TestFedFundsData -v`
Expected: PASS (all 3 tests)

**Step 5: Commit**

```bash
cd C:/Users/caslu/Desktop/NuevoProyecto
git add compass_fred_data.py tests/test_overlays.py
git commit -m "feat: add FEDFUNDS series to FRED data fetcher for M2 ZIRP guard"
```

---

### Task 2: Add ZIRP Guard to M2MomentumIndicator

**Files:**
- Modify: `compass_overlays.py:96-147` (M2MomentumIndicator class)
- Test: `tests/test_overlays.py`

**Step 1: Write the failing tests**

Add to `tests/test_overlays.py` inside `TestM2MomentumIndicator`:

```python
    def test_zirp_guard_2010_q1(self, fred_data):
        """During ZIRP (Jan 2010, Fed Funds ~0.12%), M2 scalar should be 1.0."""
        m2 = M2MomentumIndicator(fred_data)
        scalar = m2.compute_scalar(pd.Timestamp('2010-01-15'))
        assert scalar == 1.0, f"ZIRP guard should disable M2 in Jan 2010, got {scalar}"

    def test_zirp_guard_2021(self, fred_data):
        """During ZIRP (May 2021, Fed Funds ~0.06%), M2 scalar should be 1.0."""
        m2 = M2MomentumIndicator(fred_data)
        scalar = m2.compute_scalar(pd.Timestamp('2021-05-15'))
        assert scalar == 1.0, f"ZIRP guard should disable M2 in May 2021, got {scalar}"

    def test_no_zirp_guard_2023(self, fred_data):
        """During tightening (Mar 2023, Fed Funds ~4.6%), M2 scalar should still fire."""
        m2 = M2MomentumIndicator(fred_data)
        scalar = m2.compute_scalar(pd.Timestamp('2023-03-15'))
        assert scalar < 1.0, f"M2 should still restrict in Mar 2023 (no ZIRP), got {scalar}"
```

**Step 2: Run tests to verify they fail**

Run: `cd C:/Users/caslu/Desktop/NuevoProyecto && python -m pytest tests/test_overlays.py::TestM2MomentumIndicator::test_zirp_guard_2010_q1 tests/test_overlays.py::TestM2MomentumIndicator::test_zirp_guard_2021 -v`
Expected: FAIL — scalar will be 0.40, not 1.0.

**Step 3: Implement ZIRP guard in M2MomentumIndicator**

In `compass_overlays.py`, modify the `M2MomentumIndicator` class:

Change the `__init__` method (line 103-104) to:
```python
    def __init__(self, fred_data: dict):
        self.m2 = fred_data.get('M2SL')
        self.fed_funds = fred_data.get('FEDFUNDS') or fred_data.get('DFF')
```

Add ZIRP guard at the top of `compute_scalar` (after line 113, before the M2MI calculation). Insert after the `len(prior) < 460` check:

```python
        # ZIRP Guard: disable M2 overlay when Fed Funds < 1.0%
        # During ZIRP, M2 growth is Fed policy (QE), not an organic risk signal.
        ZIRP_THRESHOLD = 1.0
        if self.fed_funds is not None:
            ff_val = _get_latest(self.fed_funds, date)
            if ff_val is not None and ff_val < ZIRP_THRESHOLD:
                return 1.0
```

Full method after changes:
```python
    def compute_scalar(self, date: pd.Timestamp) -> float:
        if self.m2 is None or len(self.m2) == 0:
            return 1.0

        date_n = pd.Timestamp(date).normalize()
        prior = self.m2[self.m2.index <= date_n]
        if len(prior) < 460:
            return 1.0

        # ZIRP Guard: disable M2 overlay when Fed Funds < 1.0%
        # During ZIRP, M2 growth is Fed policy (QE), not an organic risk signal.
        ZIRP_THRESHOLD = 1.0
        if self.fed_funds is not None:
            ff_val = _get_latest(self.fed_funds, date)
            if ff_val is not None and ff_val < ZIRP_THRESHOLD:
                return 1.0

        idx = len(prior) - 1
        current_m2 = prior.iloc[idx]

        # YoY growth rate: now vs 365 days ago
        idx_12m = max(0, idx - 365)
        m2_12m_ago = prior.iloc[idx_12m]
        if m2_12m_ago <= 0:
            return 1.0
        yoy_now = (current_m2 / m2_12m_ago - 1.0) * 100

        # YoY growth rate: 3 months ago vs 15 months ago
        idx_3m = max(0, idx - 90)
        idx_15m = max(0, idx - 90 - 365)
        m2_3m = prior.iloc[idx_3m]
        m2_15m = prior.iloc[idx_15m]
        if m2_15m <= 0:
            return 1.0
        yoy_3m_ago = (m2_3m / m2_15m - 1.0) * 100

        m2mi = yoy_now - yoy_3m_ago

        if m2mi < -3.0:
            return 0.40
        elif m2mi < -1.5:
            return 0.60 + (m2mi + 3.0) / 1.5 * 0.20
        else:
            return 1.0
```

**Step 4: Run all M2 tests**

Run: `cd C:/Users/caslu/Desktop/NuevoProyecto && python -m pytest tests/test_overlays.py::TestM2MomentumIndicator -v`
Expected: ALL PASS (3 existing + 3 new = 6 tests)

**Step 5: Commit**

```bash
cd C:/Users/caslu/Desktop/NuevoProyecto
git add compass_overlays.py tests/test_overlays.py
git commit -m "feat: add ZIRP guard to M2 overlay — disable when Fed Funds < 1%"
```

---

### Task 3: Add V-Recovery Momentum Boost

**Files:**
- Modify: `compass_overlay_backtest.py:165-191` (regime score section in main loop)
- Test: `tests/test_overlays.py`

**Step 1: Write the failing tests**

Add new test class in `tests/test_overlays.py`:

```python
class TestVRecoveryBoost:
    """Test the V-recovery momentum boost logic."""

    def test_strong_v_recovery_boost(self):
        """10d return >= 8% during protection should give +0.20 boost."""
        from compass_overlay_backtest import compute_v_recovery_boost
        boost = compute_v_recovery_boost(spy_ret_10d=0.09, spy_ret_20d=0.12, in_protection=True)
        assert boost == 0.20, f"Expected 0.20 boost for 9% 10d return, got {boost}"

    def test_moderate_recovery_boost(self):
        """10d return 5-8% during protection should give +0.10 boost."""
        from compass_overlay_backtest import compute_v_recovery_boost
        boost = compute_v_recovery_boost(spy_ret_10d=0.06, spy_ret_20d=0.08, in_protection=True)
        assert boost == 0.10, f"Expected 0.10 boost for 6% 10d return, got {boost}"

    def test_sustained_recovery_boost(self):
        """20d return >= 10% (but 10d < 8%) should give +0.15 boost."""
        from compass_overlay_backtest import compute_v_recovery_boost
        boost = compute_v_recovery_boost(spy_ret_10d=0.04, spy_ret_20d=0.11, in_protection=True)
        assert boost == 0.15, f"Expected 0.15 boost for 11% 20d return, got {boost}"

    def test_no_boost_outside_protection(self):
        """No boost when not in protection mode."""
        from compass_overlay_backtest import compute_v_recovery_boost
        boost = compute_v_recovery_boost(spy_ret_10d=0.15, spy_ret_20d=0.20, in_protection=False)
        assert boost == 0.0, f"Should be 0 outside protection, got {boost}"

    def test_no_boost_weak_recovery(self):
        """No boost for weak recoveries (<5% in 10d, <10% in 20d)."""
        from compass_overlay_backtest import compute_v_recovery_boost
        boost = compute_v_recovery_boost(spy_ret_10d=0.03, spy_ret_20d=0.06, in_protection=True)
        assert boost == 0.0, f"Should be 0 for weak recovery, got {boost}"

    def test_regime_score_capped_at_1(self):
        """Boosted regime score should never exceed 1.0."""
        from compass_overlay_backtest import compute_v_recovery_boost
        boost = compute_v_recovery_boost(spy_ret_10d=0.20, spy_ret_20d=0.25, in_protection=True)
        effective = min(1.0, 0.90 + boost)  # regime_score=0.90 + boost=0.20
        assert effective == 1.0, f"Should cap at 1.0, got {effective}"
```

**Step 2: Run tests to verify they fail**

Run: `cd C:/Users/caslu/Desktop/NuevoProyecto && python -m pytest tests/test_overlays.py::TestVRecoveryBoost -v`
Expected: FAIL — `compute_v_recovery_boost` does not exist yet.

**Step 3: Implement the V-recovery boost function**

In `compass_overlay_backtest.py`, add this function after the imports block (after line 66, before line 69):

```python
# =============================================================================
# V-RECOVERY MOMENTUM BOOST
# =============================================================================

# Thresholds for SPY momentum that triggers regime score boost
V_RECOVERY_10D_STRONG = 0.08   # +8% in 10 days = strong V-recovery
V_RECOVERY_10D_MODERATE = 0.05  # +5% in 10 days = moderate recovery
V_RECOVERY_20D_SUSTAINED = 0.10 # +10% in 20 days = sustained recovery

# Boost values added to regime_score
V_RECOVERY_BOOST_STRONG = 0.20
V_RECOVERY_BOOST_SUSTAINED = 0.15
V_RECOVERY_BOOST_MODERATE = 0.10


def compute_v_recovery_boost(spy_ret_10d: float, spy_ret_20d: float,
                              in_protection: bool) -> float:
    """Compute regime score boost based on SPY short-term momentum.

    Only active during protection mode (drawdown > -10%).
    Returns a value to ADD to regime_score (0.0 to 0.20).
    """
    if not in_protection:
        return 0.0

    if spy_ret_10d >= V_RECOVERY_10D_STRONG:
        return V_RECOVERY_BOOST_STRONG
    elif spy_ret_20d >= V_RECOVERY_20D_SUSTAINED:
        return V_RECOVERY_BOOST_SUSTAINED
    elif spy_ret_10d >= V_RECOVERY_10D_MODERATE:
        return V_RECOVERY_BOOST_MODERATE
    else:
        return 0.0
```

**Step 4: Run tests to verify they pass**

Run: `cd C:/Users/caslu/Desktop/NuevoProyecto && python -m pytest tests/test_overlays.py::TestVRecoveryBoost -v`
Expected: ALL PASS (6 tests)

**Step 5: Commit**

```bash
cd C:/Users/caslu/Desktop/NuevoProyecto
git add compass_overlay_backtest.py tests/test_overlays.py
git commit -m "feat: add compute_v_recovery_boost function for V-recovery detection"
```

---

### Task 4: Integrate V-Recovery Boost into Overlay Backtest Loop

**Files:**
- Modify: `compass_overlay_backtest.py:165-191` (regime score + max_positions section)

**Step 1: Understand the integration point**

The current code at lines 168-191 does:
```python
regime_score = compute_regime_score(spy_data, date)  # Line 168
is_risk_on = regime_score >= 0.50                     # Line 169
...
max_positions = regime_score_to_positions(regime_score, ...)  # Lines 186-190
```

We need to insert the boost AFTER `compute_regime_score` but BEFORE `regime_score_to_positions`, and ONLY when in protection mode. The `dd_leverage_val` is already computed at line 176-180.

**Step 2: Modify the backtest loop**

In `compass_overlay_backtest.py`, replace lines 168-191 with the following. The change is: compute SPY 10d/20d returns, call `compute_v_recovery_boost`, and apply the boost to `regime_score` before it's used for `is_risk_on` and `max_positions`.

Find this block (lines 167-191):
```python
        # Regime
        regime_score = compute_regime_score(spy_data, date)
        is_risk_on = regime_score >= 0.50
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        # Leverage
        dd_leverage_val, crash_cooldown = compute_smooth_leverage(
            drawdown, portfolio_values, max(i - 1, 0), crash_cooldown
        )
        vol_leverage = compute_dynamic_leverage(spy_data, date)
        current_leverage = max(min(dd_leverage_val, vol_leverage), LEV_FLOOR)

        # Max positions from regime score
        spy_trend = get_spy_trend_data(spy_data, date)
        if spy_trend is not None:
            spy_close_now, sma200_now = spy_trend
            max_positions = regime_score_to_positions(regime_score,
                                                      spy_close=spy_close_now,
                                                      sma200=sma200_now)
        else:
            max_positions = regime_score_to_positions(regime_score)
```

Replace with:
```python
        # Regime
        regime_score_raw = compute_regime_score(spy_data, date)

        # Leverage (compute BEFORE boost so we know if we're in protection)
        dd_leverage_val, crash_cooldown = compute_smooth_leverage(
            drawdown, portfolio_values, max(i - 1, 0), crash_cooldown
        )
        vol_leverage = compute_dynamic_leverage(spy_data, date)
        current_leverage = max(min(dd_leverage_val, vol_leverage), LEV_FLOOR)

        # V-Recovery Momentum Boost: accelerate re-entry when SPY shows strong momentum
        in_protection = dd_leverage_val < LEV_FULL
        v_recovery_boost = 0.0
        if in_protection and date in spy_data.index and i >= 20:
            spy_closes = spy_data.loc[:date, 'Close']
            if len(spy_closes) >= 21:
                spy_ret_10d = (spy_closes.iloc[-1] / spy_closes.iloc[-11]) - 1.0
                spy_ret_20d = (spy_closes.iloc[-1] / spy_closes.iloc[-21]) - 1.0
                v_recovery_boost = compute_v_recovery_boost(spy_ret_10d, spy_ret_20d, in_protection)

        regime_score = min(1.0, regime_score_raw + v_recovery_boost)
        is_risk_on = regime_score >= 0.50
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        # Max positions from regime score (with boost applied)
        spy_trend = get_spy_trend_data(spy_data, date)
        if spy_trend is not None:
            spy_close_now, sma200_now = spy_trend
            max_positions = regime_score_to_positions(regime_score,
                                                      spy_close=spy_close_now,
                                                      sma200=sma200_now)
        else:
            max_positions = regime_score_to_positions(regime_score)
```

**Step 3: Add v_recovery_boost to the daily snapshot**

In the same file, find the portfolio_values.append block (line 348-367). Add a new column after `'cash_rate_daily'`:

```python
            'v_recovery_boost': v_recovery_boost,
```

**Step 4: Syntax check**

Run: `cd C:/Users/caslu/Desktop/NuevoProyecto && python -c "import py_compile; py_compile.compile('compass_overlay_backtest.py')"`
Expected: No errors.

**Step 5: Run all tests**

Run: `cd C:/Users/caslu/Desktop/NuevoProyecto && python -m pytest tests/test_overlays.py -v`
Expected: ALL PASS (existing 20 + 9 new = 29 tests)

**Step 6: Commit**

```bash
cd C:/Users/caslu/Desktop/NuevoProyecto
git add compass_overlay_backtest.py
git commit -m "feat: integrate V-recovery boost into overlay backtest loop"
```

---

### Task 5: Run A/B Backtest and Validate

**Files:**
- Run: `compass_overlay_backtest.py` (full A/B comparison)
- Verify: kill criteria from design doc

**Step 1: Run the full overlay backtest**

Run: `cd C:/Users/caslu/Desktop/NuevoProyecto && python compass_overlay_backtest.py`
Expected: ~5-10 minutes. Will print A/B comparison, kill criteria check, and overlay activity analysis.

**Step 2: Verify kill criteria pass**

Check output for:
- `PASS: CAGR delta` (should be >= -0.20%, likely positive since we fixed M2 and V-recovery)
- `PASS: MaxDD delta` (should be <= +2.00%)
- `Sharpe delta` (should be >= 0, or at worst >= -0.008)

**Step 3: Verify annual returns improvement**

After backtest completes, run this verification script:

```python
cd C:/Users/caslu/Desktop/NuevoProyecto && python3 -c "
import pandas as pd

# Load NEW overlay results
df = pd.read_csv('backtests/v84_overlay_daily.csv', parse_dates=['date'])
df['year'] = df['date'].dt.year

# Load SPY
spy = pd.read_csv('backtests/spy_benchmark.csv', parse_dates=['date'])
spy['year'] = spy['date'].dt.year

# Target years to check improvement
target_years = [2010, 2019, 2021, 2025]

print('Year     COMPASS    S&P 500     Diff')
print('-' * 45)
for year, grp in df.groupby('year'):
    c_start, c_end = float(grp['value'].iloc[0]), float(grp['value'].iloc[-1])
    c_ret = ((c_end / c_start) - 1) * 100

    spy_grp = spy[spy['year'] == year]
    if len(spy_grp) > 0:
        s_start, s_end = float(spy_grp['close'].iloc[0]), float(spy_grp['close'].iloc[-1])
        s_ret = ((s_end / s_start) - 1) * 100
    else:
        s_ret = float('nan')

    marker = ' <<<' if year in target_years else ''
    print(f'{year}   {c_ret:+8.2f}%  {s_ret:+8.2f}%  {c_ret-s_ret:+8.2f}%{marker}')
"
```

Expected improvements in target years:
- **2010**: M2 scalar no longer at 0.40 in Q1 → COMPASS return should increase ~3-5%
- **2019**: V-recovery boost in January → faster position rebuild → gap should narrow
- **2021**: M2 ZIRP guard → scalar = 1.0 instead of 0.40 for Apr-Jul → COMPASS return should increase
- **2025**: V-recovery boost after Apr 9 → faster exit from protection → gap should narrow

**Step 4: Check that winning years are not degraded**

Verify that years where COMPASS already beats S&P (2008, 2018, 2020, 2022, etc.) are not significantly worse.

**Step 5: Commit results**

```bash
cd C:/Users/caslu/Desktop/NuevoProyecto
git add backtests/v84_overlay_daily.csv backtests/v84_overlay_trades.csv
git commit -m "feat: backtest results with M2 ZIRP guard + V-recovery boost"
```

---

### Task 6: Verify V-Recovery Boost Activity in Output

**Files:**
- Analyze: `backtests/v84_overlay_daily.csv` (new column: `v_recovery_boost`)

**Step 1: Check boost activation history**

```python
cd C:/Users/caslu/Desktop/NuevoProyecto && python3 -c "
import pandas as pd
df = pd.read_csv('backtests/v84_overlay_daily.csv', parse_dates=['date'])

# V-recovery boost episodes
boosted = df[df['v_recovery_boost'] > 0]
print(f'V-recovery boost active: {len(boosted)} days out of {len(df)} total')
print()

if len(boosted) > 0:
    # Group into episodes
    boosted = boosted.copy()
    boosted['gap'] = boosted['date'].diff().dt.days > 3
    boosted['episode'] = boosted['gap'].cumsum()

    for ep, grp in boosted.groupby('episode'):
        start = grp['date'].iloc[0].strftime('%Y-%m-%d')
        end = grp['date'].iloc[-1].strftime('%Y-%m-%d')
        days = len(grp)
        avg_boost = grp['v_recovery_boost'].mean()
        max_boost = grp['v_recovery_boost'].max()
        print(f'  {start} to {end}: {days} days, avg boost={avg_boost:.3f}, max={max_boost:.2f}')
"
```

Expected: Boost episodes should appear around 2007 Mar, 2009 Mar, 2019 Jan, 2020 Mar, 2025 Apr.

**Step 2: Verify boost didn't fire in normal markets**

The boost should ONLY appear when `in_protection=True`. Verify:

```python
cd C:/Users/caslu/Desktop/NuevoProyecto && python3 -c "
import pandas as pd
df = pd.read_csv('backtests/v84_overlay_daily.csv', parse_dates=['date'])
bad = df[(df['v_recovery_boost'] > 0) & (df['in_protection'] == False)]
print(f'Boost fired outside protection: {len(bad)} days (should be 0)')
"
```

Expected: 0 days.

**Step 3: Final commit with all changes**

```bash
cd C:/Users/caslu/Desktop/NuevoProyecto
git add -A
git commit -m "feat: complete M2 ZIRP guard + V-recovery boost implementation

- M2 overlay disabled when Fed Funds < 1% (ZIRP periods)
- V-recovery boost adds +0.10 to +0.20 to regime score during protection mode
  when SPY shows strong short-term momentum (5-8%+ in 10-20 days)
- 9 new tests covering both features
- Backtest results updated with new overlay columns"
```

---

## Summary of All Changes

| File | Change | Lines |
|------|--------|-------|
| `compass_fred_data.py` | Add `FEDFUNDS` to FRED_SERIES | ~line 27 |
| `compass_overlays.py` | Add `self.fed_funds` to M2 `__init__`, add ZIRP guard in `compute_scalar` | lines 103-113 |
| `compass_overlay_backtest.py` | Add `compute_v_recovery_boost()` function | new, after line 66 |
| `compass_overlay_backtest.py` | Integrate boost into main loop (regime score section) | lines 168-191 |
| `compass_overlay_backtest.py` | Add `v_recovery_boost` column to daily snapshot | line 367 |
| `tests/test_overlays.py` | Add `TestFedFundsData` (3 tests) | new class |
| `tests/test_overlays.py` | Add 3 ZIRP tests to `TestM2MomentumIndicator` | existing class |
| `tests/test_overlays.py` | Add `TestVRecoveryBoost` (6 tests) | new class |
