# HYDRA Meta-Layer v1 — Regime-Aware Dynamic Allocator — Design Spec

**Date**: 2026-06-05  
**Status**: Draft — awaiting user review before writing implementation plan  
**Context**: Brainstorming session (May–June 2026) to achieve +10% annualized alpha over S&P 500 in rigorous long-horizon backtests.  
**Predecessors**: Regime-aware capital allocation work (May 2026), COMPASS v8.4 (locked), HydraCapitalManager, existing 4-pillar HYDRA architecture.

---

## 1. Problem Statement

Current HYDRA (COMPASS v8.4 + Rattlesnake + Catalyst + EFA with cash recycling) delivers approximately **15.6% CAGR** (2000-2026) with MaxDD around -22% and Sharpe ~1.08. This represents roughly **+5% annualized alpha** versus the S&P 500.

The user requires a step-change to **+10% annualized alpha** (~20-22% CAGR) while keeping risk within acceptable bounds (willing to accept MaxDD up to 28-30% if Calmar ratio improves meaningfully and drawdown duration is reduced).

After 40+ experiments on the core momentum engine, **COMPASS v8.4 signal logic is locked**. Further gains must come from higher-level architecture: significantly richer regime awareness and a new dynamic meta-allocator layer that modulates overall risk and capital allocation.

---

## 2. Objectives & Success Criteria

### Primary Objective
Achieve **~20-22% CAGR** (target +10% alpha over S&P 500) in a rigorous, bias-controlled backtest from 2000 onward, using only improvements to regime detection and a new meta-layer (no modifications to locked COMPASS v8.4 signals).

### Risk Tolerance (Approved)
- Maximum historical MaxDD: up to **28-30%** acceptable.
- Primary goal: Meaningful improvement in **Calmar ratio** (target ≥ 0.75–0.80) and reduction in drawdown duration compared to current HYDRA.
- Asymmetric preference: More aggressive in favorable regimes, strongly defensive in stress regimes.

### Validation Standard
The improvement must survive a multi-layer rigorous validation process (detailed in Section 6) including walk-forward, purged cross-validation, regime-specific testing, Monte Carlo, and strict bias controls. The edge must be credible under academic-level scrutiny.

---

## 3. Scope (Decided)

### In Scope for v1
- New **Regime OS**: Multi-dimensional regime detection system producing continuous scores + discrete Meta-Modes.
- New **Meta-Layer v1**: Dynamic portfolio allocator responsible for:
  - Gross exposure control
  - Pillar allocation multipliers
  - Cash recycling intensity modulation
  - Activation of special behavioral modes (Crisis, Recovery, Aggressive Momentum, etc.)
- Integration with existing `HydraCapitalManager` (extending the regime-aware work from May 2026).
- Strict fail-safe design and feature-flag rollout path for live deployment.
- Comprehensive backtesting and validation framework.
- Logging, state persistence, and monitoring hooks.

### Explicitly Out of Scope (v1)
- Any modification to COMPASS v8.4 signal logic (`omnicapital_v84_compass.py` and equivalents).
- Changes to individual strategy entry/exit rules (Rattlesnake, Catalyst).
- New data sources beyond price/volume + existing FRED overlays (future versions may expand).
- Full reinforcement learning controller (only limited, heavily regularized adaptive components).
- Real-money execution or IBKR integration changes.
- Dashboard UI work (deferred).

### Non-Goals
- Chasing raw CAGR at the expense of credible validation.
- Overfitting the meta-layer to historical data.
- Making the Meta-Layer a black box.

---

## 4. Architecture

### 4.1 High-Level Position

```
┌─────────────────────────────────────────────────────────────┐
│                    HYDRA Meta-Layer v1                      │
│  (New component — Regime OS + Dynamic Allocator)            │
├─────────────────────────────────────────────────────────────┤
│  • Regime OS (multi-dimensional scores + Meta-Modes)        │
│  • Risk Budgeting Engine                                    │
│  • Dynamic Exposure & Allocation Controller                 │
│  • Special Mode Logic (Crisis / Recovery / Momentum)        │
│  • Controlled adaptive / ML components (ensembles + limited │
│    online learning with strict regularization)              │
└────────────────────────────┬────────────────────────────────┘
                             │ High-level decisions (daily)
                             ▼
┌─────────────────────────────────────────────────────────────┐
│         HydraCapitalManager (enhanced)                      │
│  - Receives richer regime context and allocation directives │
└────────────────────────────┬────────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
   COMPASS v8.4       Rattlesnake         Catalyst + EFA
   (LOCKED)           (existing)          (existing)
```

### 4.2 Core Principles

1. The Meta-Layer operates **above** the four strategies. It does not generate individual stock signals.
2. All behavior must be **fail-safe**. If the Meta-Layer is uncertain or errors, the system degrades gracefully to conservative defaults.
3. Strong preference for **interpretable + regularized** models over single complex black boxes.
4. Every major decision must be logged with sufficient context for later analysis.
5. The system must be **deactivatable** via configuration or state flag for safe rollout and rollback.

---

## 5. Regime OS Design

### 5.1 Current State (May 2026)
Simple 3-state detector (`regime.py`) based on SPY vs SMA200 + 20d return + VIX threshold. Used to modulate recycling and gate Catalyst/EFA.

### 5.2 Proposed Regime OS (v1)

**Output Format**:
- Vector of continuous **Regime Scores** (0-1 or normalized).
- One or more active **Meta-Modes** (can be composite).

**Recommended Dimensions** (initial set):

| Dimension                        | Purpose                                      | Key Inputs                     |
|----------------------------------|----------------------------------------------|--------------------------------|
| Equity Momentum Strength         | How strong/persistent is the broad uptrend   | SPY returns, slope, duration   |
| Volatility Regime                | Current vol environment                      | VIX, realized vol, VVIX        |
| Liquidity / Macro Stance         | Monetary & liquidity conditions              | FRED series, TLT, credit spreads |
| Breadth & Participation          | Health of the rally (narrow vs broad)        | % stocks above moving averages |
| Stress / Crisis Probability      | Acute market stress detection                | VIX spike, drawdown velocity, credit |
| Mean-Reversion Opportunity       | Environment favorability for dip-buying      | Aggregate RSI, distances to MA |

**Meta-Modes** (examples):
- `Strong_Broad_Momentum`
- `Narrow_Momentum`
- `Elevated_Vol_Defensive`
- `Liquidity_Stress`
- `Crisis_Acute`
- `Post_Crisis_Recovery`
- `Mean_Reversion_Rich`

The Regime OS should be relatively stable day-to-day (avoid excessive flipping) while still detecting meaningful regime shifts.

---

## 6. Meta-Layer Design

### 6.1 Core Responsibilities

The Meta-Layer is responsible **only** for high-level portfolio decisions:

- Gross exposure target (e.g., 65% – 140%)
- Pillar allocation multipliers (COMPASS, Rattlesnake, Catalyst, EFA)
- Cash recycling aggressiveness
- Activation of special behavioral modes

### 6.2 Risk Logic Principles (Approved)

- **Asymmetric aggression**: Significantly more aggressive in high-conviction favorable regimes than defensive in unfavorable ones (within hard limits).
- **Recovery Mode**: After material drawdowns, the system is allowed (and encouraged) to become more aggressive to shorten recovery time.
- **Drawdown Velocity Control**: Rapid portfolio declines trigger faster de-risking than slow grind-downs.
- **Regime-dependent risk budgets**: Hard exposure caps that vary strongly by Meta-Mode (especially Crisis modes).

### 6.3 Modeling Approach

- Primary: **Ensembles of regularized models** with strong shrinkage and stability constraints.
- Selective use of limited adaptive / online learning components where they demonstrably improve out-of-sample regime detection or allocation decisions.
- Heavy emphasis on **validation discipline** — no component graduates to production logic without surviving the full validation framework.

---

## 7. Validation & Backtesting Framework

### 7.1 Multi-Layer Validation (Mandatory)

**Layer 1 — Structural**
- Multiple walk-forward windows
- Purged cross-validation
- Regime-stratified performance analysis

**Layer 2 — Robustness**
- Full period + all major stress sub-periods (2000-02, 2008, 2018, 2020, 2022+)
- Monte Carlo / block bootstrap
- Sensitivity to transaction costs and slippage

**Layer 3 — Bias & Overfitting Controls**
- Strict point-in-time universe handling
- Multiple testing correction awareness
- Strong regularization + stability penalties on any learned components

**Layer 4 — Success Gate**
Proposed minimum bar for considering the system successful:
- CAGR ≥ 19.5–20% over full period
- MaxDD ≤ 30%
- Calmar ratio ≥ 0.75 (ideally 0.80+)
- Clear improvement vs current HYDRA in worst historical regimes and drawdown duration

---

## 8. Integration, Deployment & Operations

### 8.1 Integration Principles
- New module(s) (proposed: `hydra_meta_layer.py` or package).
- `omnicapital_live.py` acts as orchestrator.
- Extends (does not replace) the existing `HydraCapitalManager`.
- New fields in `compass_state_latest.json` for Meta-Layer state and regime context.

### 8.2 Safety & Rollout
- Meta-Layer must be **feature-flagged** and default-off in first production deployment.
- Full graceful degradation path if disabled or errored.
- Comprehensive decision logging.
- Manual override capability.

### 8.3 Monitoring
- Expose key regime scores, active modes, exposure targets, and multiplier decisions via existing `/api/ml` or new endpoints.
- Integration with current interpretation system where practical.

---

## 9. Risks & Open Questions

**Major Risks**
- Overfitting of the Meta-Layer despite strict validation.
- Regime shifts in the future that were not well represented in 2000-2026 history.
- Increased operational complexity in the live engine.
- Difficulty maintaining discipline once live performance begins to diverge from backtest.

**Open Questions (to be addressed during implementation planning)**
- Exact set of regime dimensions and Meta-Modes after initial research.
- Specific ensemble techniques and regularization methods.
- Precise definition of Recovery Mode triggers and aggression parameters.
- Performance attribution framework for the Meta-Layer itself.

---

## 10. Next Steps (Proposed)

1. User review and approval of this design spec.
2. Creation of detailed implementation plan via `writing-plans` skill (broken into small, reviewable increments).
3. Research & prototyping phase focused first on Regime OS (isolated validation).
4. Meta-Layer core logic + risk budgeting.
5. Full integrated backtest with strict validation gates.
6. Controlled live shadow / paper deployment with feature flag.

---

**Document Status**: Ready for user review.

Please review the full spec and let me know if you want any adjustments, additions, or clarifications before we move to the implementation planning phase.