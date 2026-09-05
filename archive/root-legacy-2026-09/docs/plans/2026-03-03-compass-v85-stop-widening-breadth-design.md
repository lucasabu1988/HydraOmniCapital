# Design: COMPASS v8.5 — Stop Widening + Market Breadth Regime

**Date**: 2026-03-03
**Status**: Approved
**Scope**: New file `omnicapital_v85_compass.py` (copy of v84 + improvements), tests

---

## Problem Statement

Analysis of v84 backtest (2000-2026, 6575 trading days) reveals two primary alpha leaks:

1. **Stop losses destroy $1.81M** — 274 trades (5.3%), 0% win rate, avg loss -$6,606 (-7.94%). Many fire during bull markets where stocks recover quickly after temporary dips.

2. **35.2% risk-off days** — The regime filter (trend 60% + vol 40%) produces excessive false positives. When SPY dips on vol spikes but most stocks remain in uptrend, the regime over-reduces positions.

### Current v84 Baseline
- CAGR: 12.02%
- Sharpe: 0.88
- MaxDD: -32.6% (Oct 2008)
- Win Rate: 54.9%
- Profit Factor: 1.35
- Losing years: 2001 (-1.3%), 2002 (-18.2%), 2008 (-17.0%), 2022 (-17.8%)

---

## Fix 1: Regime-Conditional Stop Widening

### Mechanism
Multiply the adaptive stop loss by a regime-dependent factor. In bull markets (high regime score), stops are widened to reduce whipsaws. In bear markets, stops remain tight.

### Implementation
```python
# In run_backtest(), before stop check:
regime_stop_mult = 1.0
if regime_score >= 0.65:
    regime_stop_mult = 1.4   # Bull: stop 40% wider
elif regime_score >= 0.50:
    regime_stop_mult = 1.2   # Mild bull: stop 20% wider
# Bear (< 0.50): no change

adaptive_stop = compute_adaptive_stop(entry_daily_vol) * regime_stop_mult
```

### Parameters
| Parameter | Value | Rationale |
|-----------|-------|-----------|
| STOP_BULL_MULT | 1.4 | Strong bull: -8% becomes -11.2%. Reduces whipsaw on momentum stocks. |
| STOP_MILD_BULL_MULT | 1.2 | Mild bull: -8% becomes -9.6%. Moderate widening. |
| Regime threshold (bull) | 0.65 | Existing tier from `regime_score_to_positions` |
| Regime threshold (mild) | 0.50 | Existing tier |

### Expected Impact
- Target: reduce 30-40% of bull-market stop losses (~80-110 trades)
- Expected recovery: $500K-$700K of the $1.81M in stop losses
- Risk: wider stops mean larger individual losses when stops DO fire in bull → offset by fewer total fires

---

## Fix 2: Market Breadth Component in Regime Score

### Mechanism
Add a third component to the regime score: the percentage of stocks in the trading universe that are above their 50-day SMA. This provides a cross-sectional view of market health.

### Implementation
```python
def compute_breadth_score(price_data, tradeable_symbols, date):
    """Fraction of tradeable stocks with price > SMA50."""
    above = 0
    total = 0
    for symbol in tradeable_symbols:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        idx = df.index.get_loc(date)
        if idx < 50:
            continue
        current = df['Close'].iloc[idx]
        sma50 = df['Close'].iloc[idx-49:idx+1].mean()
        total += 1
        if current > sma50:
            above += 1
    if total == 0:
        return 0.5
    breadth_pct = above / total
    return _sigmoid(breadth_pct - 0.50, k=8.0)
```

### Regime Reweighting
```python
# Current (v84):
composite = 0.60 * trend_score + 0.40 * vol_score

# New (v85):
breadth_score = compute_breadth_score(price_data, tradeable_symbols, date)
composite = 0.45 * trend_score + 0.30 * vol_score + 0.25 * breadth_score
```

### Parameters
| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Breadth weight | 0.25 | Meaningful but not dominant. Trend remains primary. |
| Trend weight | 0.45 | Reduced from 0.60 to make room for breadth. |
| Vol weight | 0.30 | Reduced from 0.40 proportionally. |
| Breadth sigmoid k | 8.0 | Moderate sensitivity around 50% threshold. |
| SMA window | 50 days | Standard intermediate-term trend indicator. |

### Expected Impact
- Reduce false risk-off days by 15-20%
- Earlier detection of broad deterioration (2022: breadth collapsed before SPY)
- No external data dependency — uses existing price data

### Interaction with Fix 1
When breadth keeps regime score higher → fewer regime_reduce exits AND wider stops → compound benefit in bull markets. In genuine bear markets, breadth collapses fast → regime score drops → tight stops + reduced positions (protective behavior preserved).

---

## Files to Create/Modify

1. **`omnicapital_v85_compass.py`** — New file (copy of v84 + both improvements)
   - New function: `compute_breadth_score()`
   - Modified: `compute_regime_score()` → accept price_data + tradeable_symbols, add breadth
   - Modified: `run_backtest()` → pass breadth data to regime, apply regime_stop_mult
   - New constants: `STOP_BULL_MULT`, `STOP_MILD_BULL_MULT`, `REGIME_BREADTH_WEIGHT`, etc.

2. **`tests/test_v85_improvements.py`** — Unit tests
   - Test breadth computation edge cases
   - Test stop widening at different regime levels
   - Test regime score with breadth component

---

## Kill Criteria

| Metric | Threshold | Action |
|--------|-----------|--------|
| CAGR delta | < -0.30% | KILL |
| MaxDD worsens | > 200bps | KILL |
| Sharpe | < 0.85 | KILL |

## Success Criteria

| Metric | Target |
|--------|--------|
| CAGR improvement | >= +50bps |
| MaxDD | No worse than -33.5% |
| Sharpe | >= 0.90 |
| Stop loss count | Reduced by >= 20% |

---

## Validation Plan

Run `omnicapital_v85_compass.py` and compare vs v84 baseline:
1. Full period metrics (2000-2026)
2. Annual returns comparison table
3. Stop loss count and PnL comparison
4. Regime time breakdown (risk-on vs risk-off days)
5. OOS period (2020-2026) check
