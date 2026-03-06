# Experiment 60: HYDRA Third Pillar — Idle Cash into EFA

**Date:** 2026-03-06
**Status:** Designed, awaiting implementation
**Baseline:** HYDRA v1 (COMPASS + Rattlesnake) — 13.28% CAGR, -23.49% MaxDD, 1.04 Sharpe

---

## 1. Hypothesis

COMPASS sits on ~30% cash on average (35% RISK_OFF + 23% protection time).
Rattlesnake is idle 51% of the time with only 18% avg exposure.
Combined, a significant portion of capital earns 0% return.

Parking idle cash in EFA (MSCI EAFE — developed ex-US equities) turns dead
capital into passive international exposure, orthogonal to the US-only
active strategies.

## 2. The Rule

Simple three-part rule:

1. Every day, calculate total idle cash across COMPASS + Rattlesnake
2. Buy EFA with all idle cash
3. When COMPASS or Rattlesnake need capital for a new trade, sell enough
   EFA shares to fund it

EFA is never sold voluntarily. It only liquidates to service active
strategy capital needs.

## 3. Why EFA

- **Orthogonal:** Developed ex-US (Japan, UK, Europe, Australia) vs
  COMPASS/Rattlesnake (US large-cap). Different markets, different cycles.
- **Data availability:** Inception Aug 2001. Covers 24 of 26 backtest years.
  First ~18 months (Jan 2000 - Aug 2001) cash stays uninvested or use
  proxy (MSCI EAFE index data).
- **Liquid:** One of the largest international ETFs. No slippage concern.
- **Passive:** No signal, no parameters, no overfitting risk. Zero degrees
  of freedom added.

## 4. Mechanics

```
EACH DAY:

  1. Run COMPASS and Rattlesnake as normal (signals, entries, exits)

  2. Calculate idle_cash:
     idle_cash = total_portfolio_value
                 - compass_invested
                 - rattlesnake_invested
                 - min_cash_buffer (e.g., $0 — no buffer needed since
                   we sell EFA when capital is required)

  3. If idle_cash > current_efa_value:
       Buy EFA with (idle_cash - current_efa_value)

  4. If idle_cash < current_efa_value:
       Sell EFA shares worth (current_efa_value - idle_cash)
       to return capital to active strategies

  5. EFA position marked to market daily
```

## 5. What This Changes

| Aspect | HYDRA v1 | HYDRA + EFA |
|--------|----------|-------------|
| Idle cash return | 0% | EFA return (~6-8% CAGR historically) |
| International exposure | None | Developed ex-US via EFA |
| Added parameters | — | 0 (no signals, no tuning) |
| Overfitting risk | — | Zero (passive allocation) |
| Complexity | Low | Low (one buy/sell rule) |

## 6. Expected Impact

- **CAGR boost:** If ~30-40% of capital is idle on average, and EFA returns
  ~6% CAGR, the blended boost is roughly +1.8% to +2.4% CAGR.
- **MaxDD risk:** EFA can draw down -40%+ (2008). But idle cash is largest
  during RISK_OFF periods, which often coincide with global drawdowns.
  This could WORSEN MaxDD. Key risk to monitor.
- **Sharpe:** Depends on correlation. If EFA drawdowns don't align perfectly
  with COMPASS drawdowns, diversification improves Sharpe.

## 7. Key Risk

The biggest risk: COMPASS goes RISK_OFF because US equities are crashing.
Idle cash flows into EFA. But global markets are also crashing. Now the
"safe" idle cash is losing money in EFA.

Mitigation options (test as variants):
- **No mitigation:** Accept it. Over 26 years, the extra return from
  EFA during normal times may outweigh crisis losses.
- **Regime-aware:** Only buy EFA when EFA itself is above its SMA200.
  Adds one parameter but protects against global bear markets.

## 8. Backtest Variants

| Variant | Description |
|---------|-------------|
| **A: Pure** | All idle cash into EFA, no filter |
| **B: Regime-filtered** | Only buy EFA when EFA > SMA(200) |

Total: 2 backtests.

## 9. Success Criteria

### vs Baseline (HYDRA v1: 13.28% CAGR, -23.49% MaxDD, 1.04 Sharpe)

| Verdict | Criteria |
|---------|----------|
| STRONG PASS | CAGR >= 14.5% AND MaxDD no worse than -25% |
| PASS | CAGR >= 14% AND Sharpe >= 1.04 (at least match) |
| MARGINAL | CAGR improves but MaxDD worsens by > 3% |
| FAIL | CAGR < 13.28% OR MaxDD worse than -30% |

### Abort Conditions

- MaxDD worse than -35% in any variant
- CAGR below 12%

## 10. Multiple Testing

- Classification: **Structural** (new capital utilization, not parameter tweak)
- Parameters added: 0 (variant A) or 1 (variant B: SMA period)
- Overfitting risk: Near zero for variant A (no degrees of freedom)
- Deflation gate: Advisory only

## 11. Implementation

### Files to Create

- `exp60_hydra_efa.py` — Backtest script

### Dependencies (read-only)

- `exp59_hydra_v2.py` — HYDRA v1 reference
- `omnicapital_v84_compass.py` — COMPASS engine
- `rattlesnake_v1.py` — Rattlesnake engine

### Data Required

- EFA daily OHLCV (2001-08 to present, via yfinance)
- Proxy for 2000-01 to 2001-08: either skip or use MSCI EAFE index

### Output Files

- `backtests/exp60_hydra_efa_pure.csv`
- `backtests/exp60_hydra_efa_filtered.csv`
- `backtests/exp60_summary.md`

### Execution

```bash
python exp60_hydra_efa.py
```

## 12. Beauty of This Approach

- Zero parameters added (variant A)
- Zero overfitting risk
- Uses capital that's currently earning nothing
- Orthogonal to existing strategies (different continent)
- If it works, the "Lego" thesis is validated: stack orthogonal
  strategies, recycle idle cash, and the whole exceeds the parts
