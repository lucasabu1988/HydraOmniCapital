# Experiment 42: COMPASS v8.3 "666 Framework" - Execution Plan

## Team Members

- **Senior Backend Engineer (Sarah)**: Core algorithm, momentum logic, rebalancing system
- **Data Engineer (Marcus)**: GICS sector classification, data pipeline
- **Testing/QA Engineer (Jennifer)**: Validation framework, comparison metrics

---

## Implementation Summary

### Tier 1 Changes (v8.2 → v8.3)

| Parameter | v8.2 Baseline | v8.3 "666 Framework" | Change |
|-----------|---------------|----------------------|--------|
| **Lookback Period** | 90 days (~180 trading days) | 666 trading days | +470% |
| **Stock Selection** | Top 40 by volume | Top 66 by volume | +65% |
| **Portfolio Size** | 5 positions | 66 positions | +1,220% |
| **Sector Constraint** | None | Max 11 per GICS sector | NEW |
| **Rebalancing** | Fixed 5-day hold | 6.66% drift threshold | NEW |
| **Hold Period** | 5 trading days | None (drift-based) | REMOVED |

### Baseline to Beat (Exp41 - v8.2)

```
CAGR:          11.31%
Sharpe Ratio:  0.528
Max Drawdown:  -63.41%
Total Trades:  6,480
Period:        1996-2026 (30 years)
Universe:      S&P 500 point-in-time (survivorship-bias corrected)
```

---

## Technical Architecture

### 1. Data Pipeline (Marcus)

#### GICS Sector Classification
- **Primary Source**: Wikipedia S&P 500 list (current constituents)
- **Fallback**: yfinance `ticker.info['sector']` for delisted stocks
- **Manual Mappings**: Known bankruptcies (LEH, BSC, ENE, etc.)
- **Cache**: `data_cache/gics_sectors.pkl`

#### Sector Distribution Validation
```python
# Expected ~11 stocks per sector for 66-stock portfolio
# 11 GICS sectors total
expected_sectors = [
    'Information Technology',
    'Financials',
    'Health Care',
    'Consumer Discretionary',
    'Communication Services',
    'Industrials',
    'Consumer Staples',
    'Energy',
    'Utilities',
    'Real Estate',
    'Materials'
]
```

#### Historical Data (Reused from Exp41)
- S&P 500 constituents: `data_cache/sp500_constituents_history.pkl`
- Price data: `data_cache/survivorship_bias_pool.pkl`
- SPY regime filter: `data_cache/SPY_1996-01-02_2027-01-01.csv`
- Cash yield: `data_cache/moody_aaa_yield.csv`

### 2. Core Algorithm (Sarah)

#### 666-Day Momentum Calculation
```python
def compute_momentum_scores_666(price_data, tradeable, date, all_dates, date_idx):
    """
    Score = momentum_666d (excluding last 5 days) - skip_5d_return

    Adaptive lookback:
    - Early period (< 666 days of data): Use max(available, 180)
    - Full period: Use 666 trading days

    Returns: {ticker: momentum_score}
    """
    # 666 trading days ≈ 2.6 calendar years
    # Captures multi-year trends, filters noise
```

#### Sector-Constrained Selection
```python
def select_stocks_with_sector_constraint(scores, gics_sectors):
    """
    Algorithm:
    1. Rank all stocks by momentum score (descending)
    2. Iterate through ranked list
    3. Add stock if sector count < SECTOR_MAX (11)
    4. Stop when TOP_N (66) reached

    Returns: List of selected tickers (max 66)
    """
```

#### Drift-Based Rebalancing
```python
def check_rebalance_needed(positions, price_data, date, target_weights, portfolio_value):
    """
    Target weight: 1/66 = 1.515% per stock
    Drift threshold: 6.66% relative to target

    Bounds:
    - Lower: 1.515% × (1 - 0.0666) = 1.414%
    - Upper: 1.515% × (1 + 0.0666) = 1.616%

    Triggers:
    - Any position drifts outside bounds
    - Position count ≠ target (66, 33, or 11 depending on regime)
    - Annual universe rotation
    - Regime change (RISK_ON ↔ RISK_OFF)
    - Portfolio stop loss

    Returns: True if rebalance needed
    """
```

### 3. Risk Management (Unchanged from v8.2)

- **Position Stops**: -8% hard stop
- **Trailing Stops**: 3% from high after +5% gain
- **Portfolio Stop**: -15% drawdown → Protection Mode
- **Protection Stage 1**: 2 positions, 0.3x leverage, 63 days
- **Protection Stage 2**: 3 positions, 1.0x leverage, 126 days
- **Regime Filter**: SPY vs SMA200
- **Vol Targeting**: 15% annualized, leverage [0.3, 1.0]

### 4. Regime Adjustments (Modified)

| Regime | v8.2 Positions | v8.3 Positions | Rationale |
|--------|----------------|----------------|-----------|
| **RISK_ON** | 5 | 66 | Full diversification |
| **RISK_OFF** | 2 | 11 | 1/6 of normal (666 theme) |
| **Protection S1** | 2 | 11 | Conservative |
| **Protection S2** | 3 | 33 | Half of normal |

---

## Output Files

### Daily Equity Curve
**File**: `backtests/exp42_compass_666_daily.csv`

Columns:
```
date, value, cash, positions, drawdown, leverage, in_protection, risk_on, universe_size
```

### Trade Log
**File**: `backtests/exp42_compass_666_trades.csv`

Columns:
```
symbol, entry_date, exit_date, exit_reason, pnl, return
```

Exit reasons:
- `position_stop`: -8% stop loss hit
- `trailing_stop`: 3% trailing stop hit
- `rebalance`: Drift threshold triggered
- `universe_rotation`: Stock left top-66
- `portfolio_stop`: -15% portfolio drawdown
- `regime_reduce`: Regime change forced reduction

### Rebalance Events
**File**: `backtests/exp42_compass_666_rebalances.csv`

Columns:
```
date, reason, positions_before, portfolio_value
```

### Performance Comparison
**File**: `backtests/exp42_comparison_v82_v83.txt`

Metrics:
- Final Value
- CAGR
- Sharpe Ratio
- Max Drawdown
- Total Trades
- Commissions Paid
- Improvement vs baseline

---

## Validation Checklist (Jennifer)

### Pre-Execution Checks
- [ ] Exp41 baseline files exist (`exp41_corrected_daily.csv`, `exp41_corrected_trades.csv`)
- [ ] Data cache populated (constituents, price data, SPY, cash yield)
- [ ] GICS sector data downloaded and cached
- [ ] Parameters correctly set (TOP_N=66, MOMENTUM_LOOKBACK=666, etc.)

### During Execution Monitoring
- [ ] GICS sectors loaded (expect ~500+ tickers mapped)
- [ ] Annual universe computed (66 stocks per year)
- [ ] First momentum scores calculated (check adaptive lookback)
- [ ] First portfolio opened (66 positions with sector constraint)
- [ ] Sector constraint enforced (max 11 per sector)
- [ ] Rebalancing triggers (track frequency)

### Post-Execution Validation
- [ ] Backtest completed without errors
- [ ] Final portfolio value > 0
- [ ] Total trades > 0
- [ ] Equity curve shows reasonable path (no wild jumps)
- [ ] Max drawdown within expected range (-40% to -80%)
- [ ] Sector constraint never violated (validate in trades log)
- [ ] Comparison vs Exp41 generated

### Data Quality Checks
```python
# 1. Sector constraint validation
trades_df = pd.read_csv('backtests/exp42_compass_666_trades.csv')
# Group by entry_date, check unique sectors per date
# Should never exceed 11 stocks in any single sector

# 2. Position count validation
daily_df = pd.read_csv('backtests/exp42_compass_666_daily.csv')
# Positions column should be:
# - 66 in RISK_ON (most common)
# - 11 in RISK_OFF
# - 11 in Protection S1
# - 33 in Protection S2

# 3. Drift threshold validation
rebal_df = pd.read_csv('backtests/exp42_compass_666_rebalances.csv')
# Rebalancing should be LESS frequent than v8.2 (no 5-day forced holds)
# Expected: ~50-150 rebalances over 30 years (vs 6,480 trades in v8.2)
```

---

## Execution Steps

### 1. Environment Setup (5 minutes)
```bash
cd C:\Users\caslu\Desktop\NuevoProyecto
python --version  # Verify Python 3.8+
pip install pandas numpy yfinance requests  # If needed
```

### 2. Pre-flight Checks (2 minutes)
```python
# Verify baseline exists
import os
assert os.path.exists('backtests/exp41_corrected_daily.csv'), "Run exp41_extended_1996.py first!"

# Verify data cache
assert os.path.exists('data_cache/sp500_constituents_history.pkl'), "Missing constituents data"
assert os.path.exists('data_cache/survivorship_bias_pool.pkl'), "Missing price data"
```

### 3. Run Backtest (30-60 minutes)
```bash
python exp42_compass_666.py
```

Expected output:
```
================================================================================
EXPERIMENT 42: COMPASS v8.3 '666 FRAMEWORK' BACKTEST
================================================================================

Step 1: LOAD HISTORICAL DATA (FROM EXP41 CACHE)
  [Cache] Loading S&P 500 constituents history...
  [Cache] Loading expanded pool data...

Step 2: DOWNLOAD GICS SECTOR DATA
  [Cache] Loading GICS sector data...
  OR
  [Download] Downloading GICS sector classifications...

Step 3: COMPUTE ANNUAL TOP-66 UNIVERSE
  1996: Initial top-66 = 66 stocks
  1997: Top-66 | +12 added, -12 removed
  ...

Step 4: RUN COMPASS v8.3 '666 FRAMEWORK' BACKTEST
  [1996-12-31] Year 1.0 | Value: $105,234 | Positions: 66 | DD: -2.3%
  [1997-12-31] Year 2.0 | Value: $142,567 | Positions: 66 | DD: -5.1%
  ...
  [2025-12-31] Year 30.0 | Value: $X,XXX,XXX | Positions: 66 | DD: -X.X%

Step 5: SAVE RESULTS
  Saved: backtests/exp42_compass_666_daily.csv
  Saved: backtests/exp42_compass_666_trades.csv
  Saved: backtests/exp42_compass_666_rebalances.csv

Step 6: COMPARE vs BASELINE (EXP41)
  PERFORMANCE COMPARISON: v8.2 (Baseline) vs v8.3 (666 Framework)

  IMPROVEMENT: +X.XX% CAGR  OR  REGRESSION: -X.XX% CAGR
```

### 4. Review Results (10 minutes)
```bash
# Open comparison file
notepad backtests/exp42_comparison_v82_v83.txt

# Visualize equity curve (optional)
python -c "
import pandas as pd
import matplotlib.pyplot as plt

v82 = pd.read_csv('backtests/exp41_corrected_daily.csv')
v83 = pd.read_csv('backtests/exp42_compass_666_daily.csv')

plt.figure(figsize=(12, 6))
plt.plot(v82['date'], v82['value'], label='v8.2 Baseline', alpha=0.7)
plt.plot(v83['date'], v83['value'], label='v8.3 (666)', alpha=0.7)
plt.xlabel('Date')
plt.ylabel('Portfolio Value ($)')
plt.title('COMPASS v8.2 vs v8.3 (666 Framework)')
plt.legend()
plt.grid(True, alpha=0.3)
plt.savefig('backtests/exp42_comparison_chart.png', dpi=150)
print('Saved: backtests/exp42_comparison_chart.png')
"
```

---

## Expected Performance Scenarios

### Scenario A: Improvement (+2% to +5% CAGR)
**Drivers**:
- 666-day lookback captures sustained multi-year trends (tech 2010s, energy 2000s)
- 66-stock diversification reduces blow-up risk from individual position stops
- Sector constraint prevents tech bubble concentration (1999-2000)
- Drift rebalancing reduces unnecessary turnover costs

**Risks**:
- May still underperform in mean-reverting markets (2015-2020)
- Commission costs higher with 66 positions

### Scenario B: Neutral (-1% to +1% CAGR)
**Drivers**:
- Longer lookback offsets diversification benefits
- Sector constraint blocks some top performers
- Lower turnover saves commissions but misses rebalancing alpha

### Scenario C: Regression (-2% to -5% CAGR)
**Drivers**:
- 666-day lookback too slow for 2010s momentum regime
- Over-diversification dilutes alpha from top 5-10 stocks
- Sector constraint systematically excludes FAANG concentration
- Higher commission drag from 66 positions vs 5

---

## Troubleshooting

### Issue: "Missing Exp41 baseline"
**Solution**: Run `python exp41_extended_1996.py` first

### Issue: "GICS sector download fails"
**Solution**: Manual fallback in code will use yfinance. May take 30+ minutes for delisted stocks.

### Issue: "Not enough stocks with 666-day history"
**Solution**: Adaptive lookback will use min(available, 666) with floor at 180 days. This is expected for 1996-1998 period.

### Issue: "Sector constraint limiting selection"
**Solution**: Expected in some years (e.g., 1999 tech bubble). The constraint is working as designed.

### Issue: "Rebalancing too frequent"
**Solution**: Check REBALANCE_DRIFT_PCT = 0.0666 (6.66%). May need to widen if triggering daily.

---

## Post-Experiment Analysis (Team Discussion)

### Questions to Answer

1. **Did the 666-day lookback improve signal quality?**
   - Compare momentum score distributions (v8.2 90d vs v8.3 666d)
   - Analyze win rate by hold period duration
   - Check correlation with SPY regime

2. **Did 66-stock diversification reduce risk?**
   - Compare max drawdown (v8.2: -63.41% vs v8.3: ?)
   - Calculate standard deviation of daily returns
   - Measure Sharpe ratio improvement

3. **Did sector constraint prevent bubbles?**
   - Analyze 1999-2000 tech bubble period
   - Count technology stocks held (v8.2 vs v8.3)
   - Measure 2000-2002 drawdown difference

4. **Did drift rebalancing reduce turnover?**
   - Compare total trades (v8.2: 6,480 vs v8.3: ?)
   - Calculate average holding period
   - Measure commission drag

5. **What's the optimal configuration?**
   - If v8.3 underperforms: Which parameter to revert?
   - If v8.3 outperforms: Is there room for Tier 2 improvements?
   - Sensitivity analysis: Which parameter has biggest impact?

---

## Next Steps (After Exp42)

### If v8.3 Outperforms (+2% CAGR or better)
- **Exp43**: Implement Tier 2 recommendations (if any from forum)
- **Production**: Deploy v8.3 for live paper trading
- **Research**: Publish findings to math PhD forum

### If v8.3 Underperforms or Neutral
- **Exp43**: Hybrid approach (cherry-pick best parameters)
- **Exp44**: Parameter sweep (find optimal lookback, portfolio size, drift threshold)
- **Analysis**: Regime-specific performance (which market conditions favor 666 vs v8.2?)

### Regardless of Outcome
- **Documentation**: Update COMPASS manifesto with findings
- **Validation**: Monte Carlo simulation of v8.3
- **Benchmarking**: Compare vs SPY, 60/40, other momentum strategies

---

## Team Sign-Off

- [ ] **Sarah (Backend)**: Code reviewed, algorithm logic verified
- [ ] **Marcus (Data)**: GICS sectors validated, cache populated
- [ ] **Jennifer (QA)**: Test suite passed, baseline comparison ready

**Ready to Execute**: YES / NO

**Estimated Runtime**: 30-60 minutes
**Confidence Level**: HIGH (reusing proven Exp41 infrastructure)
**Risk Assessment**: LOW (reversible, no live capital)

---

*Document Created: 2026-02-27*
*Experiment: 42 (COMPASS v8.3 "666 Framework")*
*Team: Sarah, Marcus, Jennifer*
*Target: Beat 11.31% CAGR baseline (Exp41)*
