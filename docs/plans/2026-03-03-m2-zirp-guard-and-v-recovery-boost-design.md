# Design: M2 ZIRP Guard + V-Recovery Momentum Boost

**Date**: 2026-03-03
**Status**: Approved
**Scope**: compass_overlays.py, compass_fred_data.py, omnicapital_v84_compass.py, tests/

---

## Problem Statement

Two identified flaws in COMPASS v84:

1. **M2 Overlay False Positives During QE**: The M2MomentumIndicator (M2MI) measures 3-month acceleration of M2 YoY growth. During QE periods, M2 grows rapidly then decelerates — triggering the scalar to 0.40 (severe contraction signal) when the actual risk is low. Cost: -7.23% in Q1 2010, -9.8% SPY missed in 2021, -9.4% SPY missed in Q4 2003.

2. **V-Recovery Re-entry Lag**: After crashes, the regime_score recovers slowly because it depends on SMA200/SMA50 (inherently laggy). Protection mode holds positions at 2 while SPY rallies sharply. Cost: -7.51% in Jan 2019, -5.81% on Apr 9 2025 alone.

---

## Fix 1: M2 ZIRP Guard

### Mechanism
Add Federal Funds Rate context to M2MomentumIndicator. When Fed Funds < 1.0% (ZIRP environment), the M2 scalar is forced to 1.0, disabling the M2 overlay.

### Rationale
During ZIRP, M2 growth is driven by deliberate Fed policy (QE), not by organic credit expansion that could signal overheating. The M2MI deceleration signal is meaningless in this context.

### Implementation
- **compass_fred_data.py**: Add `FEDFUNDS` series (Federal Funds Effective Rate, daily)
- **compass_overlays.py** (`M2MomentumIndicator`):
  - Accept `fed_funds_data` in constructor
  - In `compute_scalar()`: if latest Fed Funds < 1.0%, return 1.0 immediately
  - Else: existing M2MI logic unchanged

### Threshold: Fed Funds < 1.0%
- Covers ZIRP periods: 2001-2004 (~1.0%), 2008-2015 (0.07-0.25%), 2020-2022 (0.07-0.33%)
- Does NOT cover 2022-2023 tightening (4.33-5.33%) — M2 contraction signal remains active

### Episodes Affected
| Episode | Fed Funds | Current scalar | New scalar | SPY during |
|---------|-----------|---------------|------------|------------|
| 2009-10 to 2010-03 | 0.12% | 0.40 | **1.0** | +6.1% |
| 2021 Apr-Jul | 0.07% | 0.40 | **1.0** | +9.8% |
| 2003-Q4 | 1.00% | 0.63 | **1.0** | +9.4% |
| 2022-23 (480d) | 4.33-5.33% | 0.40 | **0.40** (unchanged) | -5.4% |

---

## Fix 2: SPY Momentum Boost for V-Recovery

### Mechanism
When COMPASS is in protection mode (drawdown > -10%), inject a temporary boost to the regime_score based on short-term SPY momentum. This accelerates the transition to risk_on and more positions.

### Logic
```
if in_protection (dd_leverage < 1.0):
    spy_ret_10d = SPY 10-day return
    spy_ret_20d = SPY 20-day return

    if spy_ret_10d >= 0.08:    boost = 0.20  (strong V-recovery)
    elif spy_ret_20d >= 0.10:  boost = 0.15  (sustained recovery)
    elif spy_ret_10d >= 0.05:  boost = 0.10  (moderate recovery)
    else:                      boost = 0.00

    effective_regime = min(1.0, regime_score + boost)
```

### Constraints
- **Only fires during protection** — zero impact on normal operation
- **Does not modify DD-scaling leverage** — only affects position count via regime score
- **Capped at 1.0** — cannot create over-exposure
- **Does not persist** — boost is recalculated daily, not cumulative

### Expected Impact
| Year | Event | SPY 10d ret | Boost | Effect |
|------|-------|-------------|-------|--------|
| 2019 Jan | V-recovery Q4 2018 | ~+8% | +0.20 | regime 0.13→0.33, 2→3 pos faster |
| 2025 Apr 9 | Tariff pause | +15% in 10d | +0.20 | regime 0.30→0.50, risk_on ~2wk earlier |
| 2007 Mar | Post-Shanghai | +5% in 10d | +0.10 | regime 0.40→0.50, risk_on in days |
| 2020 Mar | COVID bounce | +17% in 10d | +0.20 | More aggressive in recovery |

---

## Kill Criteria

Both fixes must pass:
- Full period CAGR delta: >= -0.20%
- Full period Sharpe delta: >= -0.008
- OOS 2020-2026 MaxDD: <= -22.13% (no worse than current)
- No degradation in years COMPASS already wins

---

## Files to Modify

1. `compass_fred_data.py` — Add FEDFUNDS series
2. `compass_overlays.py` — M2MomentumIndicator ZIRP guard
3. `omnicapital_v84_compass.py` — V-recovery boost in regime score calculation
4. `compass_overlay_backtest.py` — Pass fed_funds_data to M2 overlay
5. `tests/test_overlays.py` — Tests for ZIRP guard
6. New: `tests/test_v_recovery_boost.py` — Tests for momentum boost

## Validation

Run `compass_overlay_backtest.py` A/B comparison:
- Baseline: current v84 overlay
- Treatment: v84 + ZIRP guard + V-recovery boost
- Compare annual returns table, especially 2010, 2019, 2021, 2025
