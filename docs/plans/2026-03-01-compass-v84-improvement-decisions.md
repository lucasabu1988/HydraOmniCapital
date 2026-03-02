# COMPASS v8.4 Improvement Research — Final Decision Document
**Date:** 2026-03-01
**Decision Authority:** Quant-ML Engineer + Financial Algo Expert
**Status:** FINAL — Approved for research execution
**Context:** 75 experiments already conducted. Corrected baseline CAGR = 13.90% (survivorship-bias adjusted). Best single improvement = +134 bps (MOM_105d). Best 2-param combo = 15.42% CAGR.

---

## Preamble: The Null Hypothesis Is That All Three Ideas Fail

Before stating the verdicts, I need to establish the intellectual frame for this entire document.

We have run 75 experiments. The deflated Sharpe penalty for multiple testing is severe. Using the Bailey-López de Prado framework, with 75 trials and a typical cross-trial correlation of 0.7, the minimum Sharpe required for a new result to be statistically credible at 95% confidence is approximately:

    SR_min ≈ SR_observed * sqrt(1 - rho) * sqrt(ln(N) / N)
    SR_min(deflated) ≈ SR_naive * 0.61  (rough factor for N=75, rho=0.7)

This means a backtest improvement that looks like +120 bps CAGR should be treated as +73 bps after deflation before we even discuss transaction costs. Every CAGR estimate in this document should be mentally halved before acting on it. The team consensus estimates are optimistic.

Every new parameter added is an overfitting vector. The strategy is inelastic. These constraints are not negotiable.

With that framing, here are the verdicts.

---

## IDEA 1: Omori/HAR-RV Adaptive Recovery

### VERDICT: RESEARCH FIRST — Implement only if pre-specified criteria met

**Decision:** Do NOT implement immediately. Run one isolated backtest experiment first, with a pre-registered hypothesis.

**Rationale:**

The core problem this idea solves is real and well-documented: the current fixed 126-day portfolio recovery window after a drawdown tier breach is mechanically arbitrary. The History Expert is correct that actual recovery durations vary between 45 days (2018 Q4) and 540 days (2008-2009). A fixed 126-day window will statistically be wrong in nearly all episodes — either too short (re-entering during a bear market, causing whipsaw) or too long (missing a fast recovery and leaving 2-4% CAGR on the table).

However, I am choosing HAR-RV over pure Omori for the following reasons:
- HAR-RV (Corsi 2009) has vastly superior out-of-sample evidence for volatility forecasting across multiple asset classes and frequency regimes. The academic literature on HAR-RV is one of the most robust empirical regularities in financial econometrics.
- Omori's law applied to financial markets is a useful descriptive analogy but has far weaker predictive out-of-sample evidence.
- HAR-RV gives us a forecasted volatility level, which maps cleanly onto a re-entry condition: resume full trading when 5-day forward vol forecast drops below the pre-event baseline by a specified threshold.
- Dr. Axiom's recommendation is correct.

**The precise mechanism:**

The 126-day window is replaced by a VOLATILITY-GATED re-entry condition. After a portfolio stop (drawdown tier breach), the engine stays in reduced-exposure mode until BOTH of the following conditions are met simultaneously:

    Condition A (vol normalization):
        HAR_vol_forecast_5d < vol_threshold * pre_event_realized_vol_21d
        where pre_event_realized_vol_21d is computed at the time of the stop trigger
        vol_threshold = 1.35  (pre-specified, NOT optimized)

    Condition B (minimum floor, regardless of vol):
        days_since_stop >= 21
        (prevents re-entry during the first whipsaw bounce — addresses 2020 March-April)

    Hard ceiling (emergency override, existing parameter — do not touch):
        days_since_stop <= 252
        (if vol never normalizes in a year, we re-enter anyway)

The HAR-RV computation uses:
    RV_daily = realized variance from daily returns (proxy: squared daily returns)
    RV_weekly = 5-day rolling average of RV_daily
    RV_monthly = 21-day rolling average of RV_daily
    HAR_forecast = alpha + beta_d * RV_daily + beta_w * RV_weekly + beta_m * RV_monthly
    Coefficients estimated via OLS on rolling 252-day window of past data

This adds ZERO new optimized parameters. The threshold 1.35 and floor 21 days are pre-specified from first principles, not selected by searching.

**Data source:** SPY daily returns (already used in the engine). No new data required.

**Pre-registration requirement (CRITICAL):**
Before running the backtest, write down the specific CAGR range and Sharpe range that would constitute success. This must be done BEFORE seeing the result. Changing the criteria post-hoc is data snooping.

    Pre-registered success criteria:
        - OOS CAGR improvement >= +60 bps vs baseline 13.90%
        - Max drawdown does not worsen by more than 100 bps
        - Sharpe ratio >= 1.20 (baseline estimated at 1.18-1.22)
        - The improvement must come primarily from fewer false-alarm stops, not from
          a specific historical episode (test by removing 2008 from the evaluation period)

    Pre-registered kill criteria (IMMEDIATE STOP):
        - OOS CAGR improvement < +20 bps (noise territory — not worth 2 added parameters)
        - Max drawdown worsens by more than 150 bps
        - The improvement disappears entirely when 2008-2009 is excluded from test window
          (this would indicate the result is a single-event artifact)
        - Vol condition causes re-entry during any of: early 2009, June 2020, Oct 2022
          within 30 days of the portfolio stop (would indicate threshold too loose)

**Parameters added:** 2 pre-specified values (vol_threshold=1.35, min_days=21). The 252-day hard ceiling already exists. Net new free parameters = 0 (both pre-specified).

**CAGR impact revised estimate:** +45 to +90 bps after multiple-testing deflation (team estimate was +80 to +150, which is pre-deflation).

---

## IDEA 7: Crowding-Adjusted Position Sizing

### VERDICT: DEFER INDEFINITELY — Revisit only after 2+ years of live data

**Decision:** Do NOT run the backtest. This idea is architecturally sound but empirically untestable given current constraints.

**Rationale:**

This is the hardest verdict to give because the mechanism is intellectually compelling. September 2019 and November 2020 momentum crashes were real events caused by real crowding dynamics. The team correctly identifies the risk. However, I am deferring this for the following reasons that are individually sufficient and collectively decisive:

**Problem 1 — Backtesting period is fundamentally truncated.**
MTUM launched in October 2013. Any backtest including 2000-2013 cannot use this signal for that period. Options:
- (a) Test only 2013-2025: 12 years, ~2 relevant crowding episodes. This is statistically meaningless. N=2 is not a sample; it is a pair of anecdotes.
- (b) Use an alternative crowding proxy pre-2013 (e.g., AUM-weighted momentum ETF basket reconstruction): we would be constructing a synthetic data series specifically to make our hypothesis testable. This is a form of data mining.
- (c) Test the full period with a regime dummy: clean, but we are then testing whether crowding in the POST-2013 period explains variability that we already knew about from those specific events. This is reverse engineering.

None of these options produces a credible out-of-sample test.

**Problem 2 — The 0.8x multiplier is a story, not a derived value.**
Why 0.8x and not 0.7x or 0.85x? The CAGR Optimizer notes this is "orthogonal to existing parameters" — this is true but irrelevant. Orthogonality to other parameters does not protect against fitting the multiplier to the 2 episodes that motivated the idea. With N=2 episodes, the 0.8x will look exactly right in-sample because it was implicitly chosen based on those 2 episodes.

**Problem 3 — Data availability in live trading is operationally uncertain.**
MTUM AUM data is not in yfinance. It requires an ETF AUM data feed (e.g., ETF.com, Bloomberg). We have not confirmed this is reliably available. Implementing a live trading signal that depends on a data feed we haven't stress-tested is an operational risk.

**What would change this verdict:**
- 3+ additional momentum crash episodes occur post-2026 that are attributable to crowding (adding live data)
- OR we accumulate 5+ years of COMPASS live data and can test whether crowding state at entry predicts 5-day return degradation (cross-sectional test on live history)
- OR a published paper demonstrates clean OOS evidence for MTUM-flow-based position sizing specifically for 5-day momentum strategies (peer-reviewed, replication available)

Until one of these conditions is met: DEFER.

---

## IDEA 10: Vol Compression Regime Flag

### VERDICT: RESEARCH FIRST — Lower priority than Idea 1, run second

**Decision:** Run a backtest after Idea 1 experiment is complete and evaluated. Do NOT run simultaneously with Idea 1.

**Rationale:**

The mechanism is theoretically sound. VIX tends to exhibit mean-reverting (Ornstein-Uhlenbeck) dynamics with bounded support. Extended periods of compression (VIX < 15 for > 30 days) historically precede volatility expansions, though the lead time is highly variable (weeks to 24 months). The 2006-2007 period is the strongest historical case. The mathematician's framing is correct.

However, I rank this below Idea 1 because:
- The lead time variability (2 weeks to 24 months) means this signal will produce a large number of false early warnings where we tighten crash brake sensitivity for months before nothing happens — directly costing CAGR by reducing position size unnecessarily.
- The 2006-2007 case is compelling, but 2014-2015, 2017, and 2024 all had extended VIX compression without the catalyst materializing on the expected timescale. The false alarm rate is high.
- The History Expert's own characterization is "weak as standalone timing signal, moderate as regime modifier." Moderate is not compelling given we have spent 75 experiments trying to find things that are better than moderate.

**IF run, the precise specification:**

    VIX_compression_flag = 1 if:
        VIX < 15.0 AND
        days_consecutive_below_15 >= 30

    When flag = 1:
        crash_brake_5d_threshold = -5% (tightened from -6%)
        crash_brake_10d_threshold = -8% (tightened from -10%)
        No change to position sizing, stops, or hold periods

    When flag returns to 0 (VIX >= 15):
        Reset crash brake to standard parameters
        No hysteresis on exit (prevents oscillation)

Parameters: 3 pre-specified (VIX_threshold=15.0, days_floor=30, flag reset with no hysteresis). VIX threshold is not optimized — 15 is a widely-documented regime boundary in the empirical literature (Whaley 2000, among others). The 30-day floor is the minimum duration needed to distinguish a vol compression regime from a transient VIX dip.

    Pre-registered success criteria:
        - OOS CAGR improvement >= +40 bps
        - Max drawdown improves or is neutral (within +/- 50 bps)
        - The result must hold when 2008 is excluded (2006-2007 must do work)
        - Sharpe ratio must not degrade

    Pre-registered kill criteria:
        - OOS CAGR improvement < +15 bps
        - Max drawdown worsens by more than 100 bps
        - When we count the number of "false alarm" activations (flag fires but no crash follows
          within 90 days), if false alarm rate > 60%, the signal is noise
        - The improvement is driven entirely by the 2006-2007 episode (single-episode artifact)

**CAGR impact revised estimate:** +20 to +60 bps after deflation (team estimate was +40 to +100, which is pre-deflation and optimistic given the false-alarm rate).

---

## Implementation Order and Sequencing Protocol

### Phase 1 (Weeks 1-2): Idea 1 — HAR-RV Adaptive Recovery
Run the isolated backtest. Evaluate against pre-registered criteria above.

**Decision gate:** If Idea 1 passes, flag it as a v8.5 candidate. If it fails, do not combine with anything. Move to Phase 2 regardless.

### Phase 2 (Weeks 3-4): Idea 10 — Vol Compression Regime Flag
Run only after Phase 1 is evaluated. Do not begin while Phase 1 experiment is in progress.

**Decision gate:** If Idea 10 passes in isolation, flag it as a v8.5 candidate.

### Phase 3 (Weeks 5-6, CONDITIONAL): Combination test
Run Idea 1 + Idea 10 TOGETHER only if BOTH passed in isolation AND the sum of their individual CAGR improvements exceeds +100 bps (enough signal to justify the combined complexity).

**Interaction risk assessment (Idea 1 + Idea 10):**
These two ideas have LOW interaction risk in the favorable direction and MODERATE interaction risk in the unfavorable direction.

Favorable: Idea 1 (adaptive recovery) reduces time spent in the portfolio stop penalty phase. Idea 10 (vol compression flag) tightens crash brakes when vol is low — which is a DIFFERENT regime than the high-vol crash recovery phase Idea 1 addresses. Their activation conditions are largely mutually exclusive: Idea 10 fires in low-vol environments; Idea 1 fires during high-vol post-crash recoveries. This suggests approximate additivity.

Unfavorable interaction scenario: March 2020 — VIX spikes from below 15 to above 80 in two weeks. Idea 10 is irrelevant (VIX already above 15). Idea 1 governs recovery. These should be orthogonal in this scenario. No obvious adverse interaction.

The primary interaction risk is NOT between ideas 1 and 10 but between BOTH of them and the existing regime score. Both ideas modify behavior conditional on market conditions that the regime score already partially captures. There is a risk of double-counting the same information signal, resulting in an overcorrection. Monitor this by checking whether the combined backtest shows excessive regime-sensitivity (too few trades in 2009-2011 or 2020-2021 recoveries).

**Idea 7 interaction:** Irrelevant — Idea 7 is deferred.

### Total New Parameters Introduced
- Idea 1: 0 free parameters (both values pre-specified)
- Idea 10: 0 free parameters (all values pre-specified from literature)
- Combined: 0 net new optimized parameters

This is the key protective decision. By pre-specifying all parameter values from first principles or published research (rather than searching), we do not increment the experiment counter. The backtest is a VALIDATION run, not an optimization run.

---

## Experiment Count and Data Snooping Budget

Current count: 75 experiments.

Adding 2-3 validation runs (Idea 1 solo, Idea 10 solo, optional combo) brings us to 77-78. The marginal data snooping cost of 2-3 validation-mode runs (no parameter search) is substantially lower than 2-3 optimization runs. The deflated Sharpe adjustment for validation-mode experiments uses a smaller N_effective because we are not searching a parameter space.

**Hard stop rule:** If either validation fails, we do NOT try alternative parameter values for that idea. The pre-specified values stand. This is the only way to avoid the "just try one more configuration" trap that inflates the effective N.

---

## Final Priority Stack (Ranked by Expected Deflated CAGR / Risk ratio)

| Rank | Idea | Action | Expected Deflated CAGR | Free Params Added | Sequence |
|------|------|--------|----------------------|-------------------|----------|
| 1 | #1 HAR-RV Adaptive Recovery | Research first, run experiment | +45 to +90 bps | 0 | Week 1-2 |
| 2 | #10 Vol Compression Flag | Research first, run experiment | +20 to +60 bps | 0 | Week 3-4 |
| 3 | #7 Crowding Sizing | Defer indefinitely | Unknown (untestable) | 1 | 2028+ |

---

## What v8.5 Looks Like (If Both Pass)

v8.5 would be v8.4 with exactly two behavioral changes:
1. Portfolio recovery window: Replace fixed 126-day timer with HAR-RV gated re-entry (vol_threshold=1.35, min_days=21, max_days=252)
2. Crash brake sensitivity: Tighten by 1% on 5d and 2% on 10d thresholds when VIX < 15 for 30+ consecutive days

Zero new optimized free parameters. Full data available from 2000. Testable on the same 2000-2025 backtest window as v8.4.

**If only Idea 1 passes:** v8.5 = v8.4 + HAR-RV recovery only. This is the most likely outcome.

**If neither passes:** v8.4 remains the production algorithm indefinitely. This is the null hypothesis outcome and should not be seen as a failure — it means the algorithm is already near the efficient frontier given available data.

---

## Administrative Notes

- All three backtest experiments must be logged in the backtests/ directory with the naming convention `v85_idea{N}_[description]_daily.csv`
- Pre-registration documents must be written to `docs/plans/` BEFORE the backtest is run
- The pre-registration document must contain: exact parameter values, evaluation period, success criteria, kill criteria, and the date it was written
- Idea 7 deferral decision is logged here. Do not re-raise Idea 7 before 2028 without at least 2 years of additional live data showing crowding-correlated drawdowns in COMPASS positions
- v8.4 remains LOCKED in `omnicapital_v84_compass.py` and `omnicapital_live.py` throughout this research phase. Any v8.5 work is in a separate file: `omnicapital_v85_candidate.py`
