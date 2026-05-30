# Regime Feature Definitions — HYDRA Meta-Layer v1 (Task 0.2)

**Date**: 2026-05-30 (initial exploratory set)  
**Context**: Task 0.2 of the HYDRA Meta-Layer v1 Implementation Plan. Purely research-oriented identification of stable, regime-predictive features using *only* data available in the existing project pipeline (`data_cache_parquet/`, yfinance on-demand for VIX, etc.).  
**Goal**: Rich multi-dimensional Regime OS inputs for later Meta-Layer that targets +10% alpha over current HYDRA while respecting all constraints (COMPASS v8.4 locked, fail-safe, etc.).  
**Source of truth for implementation**: `regime_feature_research.py` (computes these as of latest date + provides historical series for analysis).

All features below are **continuous where possible** (preferred for downstream models) and designed for reasonable day-to-day stability (avoiding excessive flipping).

---

## 1. Equity Momentum Strength

### 1.1 `equity_mom_63d_ret`
- **Dimension**: Equity Momentum Strength
- **Description**: Total return of SPY over the trailing 63 trading days (~3 months).
- **Computation (skeleton)**: `Close[-1] / Close[-63] - 1`
- **Inputs**: SPY daily Close from `data_cache_parquet/SPY.parquet`
- **Regime signal hypothesis**: Strong positive values indicate persistent broad uptrend (favors higher gross exposure / COMPASS tilt). Negative or low values flag weakening momentum.
- **Stability notes**: 63d window is a compromise between responsiveness and noise. Used in current `regime.py` indirectly via 20d returns.
- **Status**: Implemented and computed daily in skeleton.

### 1.2 `equity_mom_252d_ret`
- **Dimension**: Equity Momentum Strength
- **Description**: Total return of SPY over the trailing 252 trading days (~1 year).
- **Computation (skeleton)**: `Close[-1] / Close[-252] - 1`
- **Inputs**: SPY daily Close
- **Regime signal hypothesis**: Longer-horizon trend strength. Helps distinguish secular bull markets from short-term bounces.
- **Stability notes**: Very stable; changes slowly. Excellent for high-level Meta-Mode classification (e.g., "Strong_Broad_Momentum").
- **Status**: Implemented in skeleton.

### 1.3 `equity_trend_sma200_dist`
- **Dimension**: Equity Momentum Strength + Breadth proxy
- **Description**: Percentage distance of SPY Close from its 200-day simple moving average.
- **Computation (skeleton)**: `(Close[-1] / SMA200[-1] - 1)`
- **Inputs**: SPY Close
- **Regime signal hypothesis**: Classic trend filter. Large positive distance + rising = healthy participation. Large negative = distribution / bearish regime.
- **Stability notes**: SMA200 is slow; the distance metric flips less often than price-based rules.
- **Status**: Implemented in skeleton (also produces the boolean `equity_above_sma200` flag).

---

## 2. Volatility Regime

### 2.1 `vol_realized_20d`
- **Dimension**: Volatility Regime
- **Description**: 20-day realized volatility of SPY daily returns, annualized.
- **Computation (skeleton)**: `std(returns.tail(20)) * sqrt(252)`
- **Inputs**: SPY Close (pct_change)
- **Regime signal hypothesis**: Elevated realized vol often precedes or coincides with stress regimes. Low vol environments have historically supported higher risk budgets.
- **Stability notes**: 20d is responsive but still smoother than 5-10d measures.
- **Status**: Implemented in skeleton.

### 2.2 `vol_vix_current`
- **Dimension**: Volatility Regime
- **Description**: Latest closing level of the VIX index.
- **Computation (skeleton)**: Direct from yfinance `^VIX` Close (cached locally under `research/regime_features/`).
- **Inputs**: ^VIX daily (on-demand download + research cache)
- **Regime signal hypothesis**: VIX is the market's "fear gauge". Levels >25-30 have strong historical association with defensive regimes; sustained <15 supports aggressive modes.
- **Stability notes**: Raw level is noisy day-to-day; best used in conjunction with z-score or regime thresholds.
- **Status**: Implemented (requires network on first run; thereafter cached).

### 2.3 `vol_vix_zscore_252`
- **Dimension**: Volatility Regime
- **Description**: How many standard deviations the current VIX is from its own trailing 252-day mean.
- **Computation (skeleton)**: `(current_VIX - mean(VIX.tail(252))) / std(VIX.tail(252))`
- **Inputs**: VIX series + alignment to SPY dates
- **Regime signal hypothesis**: Normalizes the fear gauge to its recent history. A +1.5 z-score is far more meaningful in a 2023 low-vol world than in 2008.
- **Stability notes**: Smoother than raw VIX for mode transitions.
- **Status**: Implemented in skeleton.

---

## 3. Breadth & Participation

### 3.1 `breadth_pct_above_sma200_proxy`
- **Dimension**: Breadth & Participation
- **Description**: Percentage of the fixed large-cap proxy universe (30 tickers) whose latest Close is above their own 200-day SMA.
- **Computation (skeleton)**: For each ticker in `BREADTH_PROXY_TICKERS` that has >=300 days history in parquet cache, load tail(300), compute SMA200, count fraction where Close > SMA200.
- **Inputs**: Individual ticker `.parquet` files from `data_cache_parquet/` (no full PIT S&P 500 constituents required at this stage).
- **Regime signal hypothesis**: Healthy rallies are broad (high % participation). Narrow rallies (low %) are fragile even if SPY looks strong — classic warning for Mean-Reversion or Defensive modes.
- **Stability notes**: Proxy of 30 names is deliberately stable and fast to compute. Thresholds (e.g., <40% = narrow) can be tuned later.
- **Status**: Fully implemented and reported in skeleton run.

### 3.2 `breadth_pct_pos_20d_ret_proxy`
- **Dimension**: Breadth & Participation
- **Description**: Percentage of proxy tickers showing positive 20-day returns.
- **Computation (skeleton)**: Same proxy load; fraction where `Close[-1] > Close[-20]`.
- **Inputs**: Parquet cache
- **Regime signal hypothesis**: Complements the SMA200 breadth measure. Captures shorter-term participation breadth.
- **Stability notes**: More responsive than 200d version; useful in combination.
- **Status**: Implemented in skeleton.

---

## 4. Stress / Crisis Probability

### 4.1 `stress_spy_dd_6m`
- **Dimension**: Stress / Crisis Probability
- **Description**: Current drawdown of SPY from its peak over the trailing ~126 trading days (6 months).
- **Computation (skeleton)**: `Close[-1] / cummax(Close.tail(126))[-1] - 1`
- **Inputs**: SPY Close
- **Regime signal hypothesis**: Rapid or deep drawdowns (even within a bull market) are strong regime signals. Used for Drawdown Velocity Control logic in the Meta-Layer design.
- **Stability notes**: Peak-based metrics are inherently somewhat "sticky" until new highs.
- **Status**: Implemented.

### 4.2 `stress_10d_ret`
- **Dimension**: Stress / Crisis Probability
- **Description**: SPY total return over the most recent 10 trading days (short-term crash velocity proxy).
- **Computation (skeleton)**: `Close[-1] / Close[-10] - 1`
- **Inputs**: SPY Close
- **Regime signal hypothesis**: Large negative 10d moves (e.g., < -5%) are early acute stress indicators, even before VIX fully reacts.
- **Stability notes**: Short window → noisier; best used with hard thresholds or in conjunction with VIX z-score.
- **Status**: Implemented.

---

## 5. Mean-Reversion Opportunity

### 5.1 `meanrev_pct_deep_below_ma50_proxy`
- **Dimension**: Mean-Reversion Opportunity
- **Description**: Percentage of the breadth proxy universe trading at least 8% below their own 50-day SMA.
- **Computation (skeleton)**: Same proxy loader; count where `(Close / SMA50 - 1) < -0.08`.
- **Inputs**: Parquet cache (tail 300 rows sufficient)
- **Regime signal hypothesis**: High values indicate a "dip-rich" environment that may favor Rattlesnake mean-reversion activity or post-crash Recovery Mode aggression.
- **Stability notes**: 50d window + 8% threshold chosen for reasonable frequency without excessive noise.
- **Status**: Implemented in skeleton (directly supports "Mean_Reversion_Rich" Meta-Mode).

---

## 6. Liquidity / Macro Stance (Light Proxy)

### 6.1 `liq_spy_vol_zscore_20d`
- **Dimension**: Liquidity / Macro Stance (volume-based proxy)
- **Description**: Z-score of the latest SPY trading volume versus the trailing 20-day mean and std.
- **Computation (skeleton)**: `(Volume[-1] - mean(Volume.tail(20))) / std(Volume.tail(20))`
- **Inputs**: SPY Volume from parquet
- **Regime signal hypothesis**: Volume spikes often accompany stress or capitulation. Persistently low volume can indicate complacency in strong momentum regimes. (Future versions can replace/augment with actual FRED series such as NFCI, credit spreads, or M2 via `compass_fred_data.py`.)
- **Stability notes**: Volume is inherently bursty; z-score helps.
- **Status**: TEMPORARY THIN PROXY ONLY. Implemented as the thinnest possible volume z-score stand-in for Task 0.2. Explicitly NOT a production liquidity/macro dimension; will be superseded by richer data sources in Phase 1+. See also script comments in regime_feature_research.py.

---

## Summary Table (Initial Candidate Set)

| Feature                              | Dimension                    | Type     | In Skeleton? | Primary Use Case                     |
|--------------------------------------|------------------------------|----------|--------------|--------------------------------------|
| equity_mom_63d_ret                   | Equity Momentum              | Return   | Yes          | Short-term trend conviction          |
| equity_mom_252d_ret                  | Equity Momentum              | Return   | Yes          | Secular trend strength               |
| equity_trend_sma200_dist             | Equity Momentum / Breadth    | Distance | Yes          | Classic trend filter                 |
| vol_realized_20d                     | Volatility Regime            | Vol      | Yes          | Risk environment                     |
| vol_vix_current                      | Volatility Regime            | Level    | Yes          | Fear gauge (raw)                     |
| vol_vix_zscore_252                   | Volatility Regime            | Z-score  | Yes          | Normalized fear                      |
| breadth_pct_above_sma200_proxy       | Breadth & Participation      | %        | Yes          | Rally health / narrowness            |
| breadth_pct_pos_20d_ret_proxy        | Breadth & Participation      | %        | Yes          | Short-term participation             |
| stress_spy_dd_6m                     | Stress / Crisis              | DD       | Yes          | Drawdown velocity control            |
| stress_10d_ret                       | Stress / Crisis              | Return   | Yes          | Acute move detection                 |
| meanrev_pct_deep_below_ma50_proxy    | Mean-Reversion Opportunity   | %        | Yes          | Dip-buying / Recovery environment    |
| liq_spy_vol_zscore_20d               | Liquidity / Macro (proxy)    | Z-score  | Yes          | Volume stress / complacency          |

**Total**: 12 candidates (exceeds minimum 8-10 requirement).

---

## Next Steps / Open Items (Post Task 0.2)

- Add richer Liquidity/Macro features using `compass_fred_data.py` (NFCI, credit spreads, M2 momentum, etc.) once `data_cache/fred/` is populated.
- Expand breadth to true point-in-time S&P 500 constituents when `data_cache/sp500_*` files become available (hydra_backtest integration).
- Compute full historical time series of all features (not just latest snapshot) for the Phase 1 validation harness.
- Correlation / mutual information analysis + forward-return stratified statistics (regime-specific edge).
- Stability / flip frequency metrics for each feature (critical for Meta-Mode design).
- Decision: which 6–8 features graduate to the initial `RegimeScores` dataclass.

---

**References**:
- Design Spec: `docs/superpowers/specs/2026-06-05-hydra-meta-layer-v1-design.md` (Section 5 — Regime OS)
- Implementation Plan: `docs/superpowers/plans/2026-06-05-hydra-meta-layer-v1-implementation.md` (Task 0.2)
- Current lightweight regime: `regime.py`
- Data pipeline: `compass_data_pipeline.py`, `refresh_parquet_cache.py`, `hydra_backtest/data.py`

*This document is living research output. Update as features are refined or discarded during validation.*