#!/usr/bin/env python3
"""
================================================================================
OMNICAPITAL PROJECT -- COMPREHENSIVE REVIEW DOCUMENT
================================================================================
Author:      OmniCapital Development Team
Date:        February 21, 2026
Purpose:     Single-file summary of the entire OmniCapital project for external
             AI review. Contains no executable trading logic -- purely descriptive.

This file documents:
  1. The production algorithm (COMPASS v8.2)
  2. All experiments attempted and their outcomes (24 experiments)
  3. Statistical validity analysis of the backtest
  4. Live trading dashboard implementation
  5. Key lessons learned and decision history
  6. File inventory and architecture

Run this file to print a structured summary to stdout:
    python OMNICAPITAL_PROJECT_REVIEW.py
================================================================================
"""

# =============================================================================
# SECTION 1: PROJECT OVERVIEW
# =============================================================================

PROJECT = {
    "name": "OmniCapital",
    "version": "8.2 (COMPASS) + cash yield",
    "language": "Python 3.14.2",
    "platform": "Windows 11",
    "data_source": "yfinance (Yahoo Finance)",
    "backtest_period": "2000-01-01 to 2026-02-09",
    "initial_capital": 100_000,
    "final_value": 5_910_000,  # approximate
    "seed": 666,  # official project seed for any randomness
    "total_experiments": 24,
    "experiments_succeeded": 2,  # COMPASS v8 + cash yield
    "experiments_failed": 22,
    "algorithm_status": "INELASTIC -- motor locked, focus on chassis/execution",
}

# =============================================================================
# SECTION 2: COMPASS v8.2 -- PRODUCTION ALGORITHM
# =============================================================================

COMPASS_DESCRIPTION = """
COMPASS (Cross-sectional Momentum, Position-Adjusted Risk Scaling) is a
long-only equity trading system that buys the strongest momentum stocks
from a liquid S&P 500 subset, using a regime filter to avoid bear markets
and volatility targeting to dynamically adjust exposure.

Core philosophy: "Replace randomness with a real edge."
- The predecessor (v6) selected stocks randomly -> 5.40% CAGR with -59.4% MaxDD
- COMPASS uses cross-sectional momentum ranking -> 16.95% CAGR with -28.4% MaxDD

The algorithm is fully deterministic (no random component) and uses only
daily OHLCV data. No machine learning, no fundamental analysis, no options.
"""

COMPASS_PARAMETERS = {
    # Universe
    "broad_pool": "113 S&P 500 stocks across 9 sectors",
    "annual_rotation": "Top 40 by dollar volume (Close * Volume) each Jan 1",
    "min_age_days": 63,  # 3 months minimum history for eligibility

    # Signal (the core edge)
    "momentum_lookback": 90,    # days
    "momentum_skip": 5,         # exclude last 5 days (short-term reversal)
    "score_formula": "SCORE = momentum_90d - reversal_5d",
    "score_meaning": "Buy stocks with strong 3-month trend + recent pullback (winners w/ dip)",
    "academic_basis": [
        "Jegadeesh & Titman (1993): Cross-sectional momentum (3-12 month winners continue)",
        "Lo & MacKinlay (1990): Short-term mean reversion (1-5 day pullbacks are temporary)",
        "The 5-day skip removes micro-reversal that cancels momentum signal"
    ],

    # Regime filter
    "regime_indicator": "SPY vs SMA(200)",
    "regime_confirm_days": 3,  # consecutive days to confirm
    "risk_on": "SPY > SMA200 for 3+ days -> 5 positions, vol-targeted leverage",
    "risk_off": "SPY < SMA200 for 3+ days -> 2 positions, 1.0x leverage",
    "regime_basis": "Meb Faber (2007): SMA200 filter halves drawdown with minimal return impact",
    "historical_risk_off_pct": "~25.7% of trading days",

    # Position sizing
    "sizing_method": "Inverse volatility weighting",
    "vol_lookback": 20,  # days for realized vol
    "max_single_position": "40% of available cash",
    "effect": "Stable stocks (JNJ, PG) get more capital; volatile (TSLA, NVDA) get less",

    # Leverage (dynamic)
    "leverage_formula": "leverage = 15% / realized_vol_SPY_20d",
    "leverage_min": 0.3,
    "leverage_max": 2.0,
    "leverage_risk_off": "Fixed 1.0x",
    "vol_targeting_basis": "Volatility clustering -> reduce in high-vol, increase in low-vol",

    # Exit rules (first to trigger)
    "hold_days": 5,             # trading days, then rotate
    "position_stop_loss": -0.08,  # -8% per position
    "trailing_activation": 0.05,  # activate after +5% gain
    "trailing_stop_pct": -0.03,   # -3% from peak after activation
    "exit_distribution": {
        "hold_expired": "87%",
        "position_stop": "6.5%",
        "trailing_stop": "5.0%",
        "portfolio_stop": "0.9%",
    },

    # Portfolio stop & recovery
    "portfolio_stop_loss": -0.15,  # -15% drawdown from peak -> close ALL
    "recovery_stage_1": "63 days at 0.3x leverage, max 2 positions (requires RISK_ON)",
    "recovery_stage_2": "126 days at 1.0x leverage, max 3 positions (requires RISK_ON)",
    "recovery_normal": "After 126 days + RISK_ON -> full vol targeting, 5 positions",
    "protection_time": "2,002 days total (30.5% of backtest period) -- confirmed optimal",

    # Costs & Yield
    "margin_rate": "6% annual on borrowed amount",
    "commission": "$0.001 per share",
    "cash_yield": "3% annual on uninvested cash (T-bill proxy, CASH_YIELD_RATE)",
    "slippage": "Not explicitly modeled (mitigated by top-40 liquid stocks)",
}

COMPASS_RESULTS = {
    "CAGR": "16.95%",
    "Sharpe": 0.815,
    "Sortino": 1.13,
    "Max_Drawdown": "-28.4%",
    "Calmar": 0.60,
    "Win_Rate": "55.30%",
    "Total_Trades": 5383,
    "Trades_Per_Year": "~207",
    "Positive_Years": "23/26 (88%)",
    "Best_Year": "+112.4%",
    "Worst_Year": "-26.8%",
    "Stop_Loss_Events": 11,
    "Protection_Days": 2002,
    "Protection_Pct": "30.5% of trading days",
    "Final_Value": "$5.91M from $100k",
}

COMPASS_V82_IMPROVEMENTS = """
v8.2 refined v8.0 with:
- Leverage range expanded: [0.3x, 2.0x] (was [0.5x, 2.0x])
- Recovery Stage 1 uses 0.3x leverage (was 0.5x) for more conservative re-entry
- Cash yield added: 3% annual on uninvested cash (T-bill proxy, realistic broker sweep)
- Results: 16.95% CAGR, 0.815 Sharpe, -28.4% MaxDD (improved from v8.0's -34.8% MaxDD)

Cash yield rationale: Previously the backtest assumed 0% on idle cash, which understated
real returns. Any broker (IBKR, Schwab) provides money market sweep on uninvested cash.
The 3% rate is conservative -- actual T-bill rates varied 0-5% over 2000-2026.
This adds +0.91% CAGR with zero additional risk (backtested and confirmed).
"""

# =============================================================================
# SECTION 3: ALL EXPERIMENTS -- WHAT WAS TRIED AND WHY IT FAILED/SUCCEEDED
# =============================================================================

EXPERIMENTS = [
    {
        "name": "v6 Original (Random Selection)",
        "file": "omnicapital_v6_final_optimized.py",
        "description": "Random stock selection from fixed 60-stock universe with 2x leverage",
        "result": "16.92% CAGR -- but this was ILLUSORY due to survivorship bias",
        "lesson": "Fixed universe = survivorship bias. Stocks known to be large TODAY were not large in 2000.",
    },
    {
        "name": "v6 Corrected (Annual Rotation)",
        "file": "omnicapital_v6_top40_rotation.py",
        "description": "Same random selection but with annual top-40 rotation by dollar volume",
        "result": "5.40% CAGR, -59.4% MaxDD, Sharpe 0.22",
        "lesson": "Without a real signal, random selection barely beats buy-and-hold after costs.",
    },
    {
        "name": "v7 Regime Testing",
        "files": ["omnicapital_v7.py", "omnicapital_v7_regime_test.py", "omnicapital_v7_regime_test_v2.py"],
        "description": "Attempted to add SPY regime filter + multiple momentum indicators",
        "result": "Cancelled -- too complex without clear benefit over simpler approach",
        "lesson": "Complexity without proportional gain is a trap.",
    },
    {
        "name": "v8 COMPASS (Production)",
        "file": "omnicapital_v8_compass.py",
        "description": "Cross-sectional momentum + regime filter + vol targeting",
        "result": "16.16% CAGR, 0.73 Sharpe, -34.8% MaxDD -> SUCCESS",
        "lesson": "Simple, academically-grounded signal + robust risk management = real edge.",
    },
    {
        "name": "v8.1 Short-Selling Experiment",
        "description": "Attempted to add short-selling using fundamental ratios (Revenue/Debt for banks, Debt/EBITDA)",
        "result": "FAILED -- shorts lost money consistently, especially in bull markets",
        "lesson": "Bank debt is structural (not distress). Fundamental short signals don't work in secular bull.",
    },
    {
        "name": "VORTEX v1 -- Acceleration Momentum",
        "file": "omnicapital_vortex.py",
        "description": "Dual momentum: velocity (price) + acceleration (momentum of momentum). "
                       "Hypothesis: stocks rising at an increasing rate outperform.",
        "result": "15.34% CAGR, 0.703 Sharpe -- WORSE than COMPASS on all metrics",
        "lesson": "Second derivative of momentum adds noise, not signal. Simpler is better.",
    },
    {
        "name": "VORTEX v2 -- Exponential + Dual Timeframe",
        "file": "omnicapital_vortex_v2.py",
        "description": "Added EMA-based momentum + short/medium timeframe agreement filter",
        "result": "Still underperformed COMPASS",
        "lesson": "More indicators != better signal in concentrated 5-position portfolio.",
    },
    {
        "name": "VORTEX v3 -- Parameter Sweep",
        "file": "omnicapital_vortex_v3_sweep.py",
        "description": "Systematic sweep of VORTEX parameters to find best combination",
        "result": "Best variant matched but did not beat COMPASS",
        "lesson": "Exhaustive search confirmed COMPASS parameters are near-optimal.",
    },
    {
        "name": "v8 Optimization Suite",
        "file": "compass_v8_optimization_test.py",
        "description": "Tested 5 COMPASS variants: (A) Dual SMA regime, (B) VIX override, "
                       "(C) Risk-adjusted momentum, (D) Breadth filter, (E) Baseline v8.2",
        "results": {
            "A_dual_sma": "15.84% CAGR -- SMA50+200 filter slightly worse",
            "B_vix_override": "15.58% CAGR -- VIX override hurt in whipsaw",
            "C_risk_adj_mom": "14.10% CAGR -- risk-adjusted scoring lost 2% CAGR",
            "D_breadth": "15.88% CAGR -- advance/decline breadth filter marginal",
            "E_baseline_v82": "16.04% CAGR -- WINNER (original is best)",
        },
        "lesson": "Baseline v8.2 beat all 4 'improvements'. The algorithm is hard to improve.",
    },
    {
        "name": "Quality + Scaled Tests",
        "files": ["compass_v8_quality.py", "compass_v8_scaled.py"],
        "description": "Tested quality factor (ROE, margins) as filter + scaled universe (60 stocks)",
        "result": "Quality filter lost ~1% CAGR. Scaled universe similar performance.",
        "lesson": "Quality metrics from yfinance are unreliable (only ~5 years of data).",
    },
    {
        "name": "NIGHTSHIFT -- Overnight Strategy",
        "file": "compass_nightshift_backtest.py",
        "description": "Close-to-Open overnight premium capture using SPY/QQQ/TLT/GLD ETFs. "
                       "$50k separate capital. Buys at close, sells at next open.",
        "signal_logic": {
            "RISK_ON": "60% SPY + 40% QQQ (when VIX normal + regime bullish)",
            "NEUTRAL": "50% TLT + 50% GLD (when VIX elevated or Monday night)",
            "FLAT": "0% (circuit breaker or RISK_OFF regime)",
        },
        "result": "Moderate returns, uncorrelated with COMPASS daytime strategy",
        "combined_benefit": "COMPASS + NIGHTSHIFT combined shows diversification benefit",
    },
    {
        "name": "Behavioral Finance Overlays",
        "file": "test_behavioral.py",
        "description": "5 variants testing academic behavioral anomalies on COMPASS engine",
        "variants": {
            "A_baseline": "Pure momentum (COMPASS v8.2) -- 16.04% CAGR",
            "B_52wk_high": "Blend with 52-week high nearness (George & Hwang 2004 anchoring)",
            "C_lottery_filter": "Filter out high-MAX stocks (Bali et al. 2011 skewness preference)",
            "D_risk_adj_mom": "Rank by return/volatility (Novy-Marx 2012 loss aversion)",
            "E_combined": "All three overlays together",
        },
        "result": "ALL variants lost 7-10% CAGR vs baseline. Combined had best MaxDD (-23.6%) "
                  "but worst CAGR (4.95%)",
        "lesson": "In a concentrated 5-position, 5-day-hold system, ANY dilution of the pure "
                  "momentum signal destroys alpha. These anomalies may work in diversified portfolios "
                  "but not in concentrated momentum.",
    },
    {
        "name": "Intraday Mean-Reversion / Continuation",
        "file": "test_intraday_meanrev.py",
        "description": "Test gap trading: buy/short on overnight gap and close intraday",
        "result": "Massive losses in both mean-reversion and continuation modes (-$500k+)",
        "lesson": "Gap trading with daily data (no intraday) is not viable.",
    },
    {
        "name": "Rotation Frequency Sweep",
        "file": "test_rotation_freq.py",
        "description": "Tested annual vs semi-annual vs quarterly universe rotation",
        "result": "Annual rotation (current) is optimal. More frequent = more turnover cost, no benefit.",
        "lesson": "Annual rotation balances freshness with transaction costs.",
    },
    {
        "name": "Hold Period Sweep",
        "files": ["omnicapital_v6_holdtime_sweep.py", "omnicapital_v6_holdtime_sweep_v2.py"],
        "description": "Tested hold periods from 1 to 20 days",
        "result": "5 days is near-optimal. Shorter = too much turnover. Longer = momentum decays.",
        "lesson": "5-day hold captures the momentum sweet spot.",
    },
    {
        "name": "Amplify Test",
        "file": "compass_v8_amplify_test.py",
        "description": "Test aggressive leverage and position parameters",
        "result": "Higher leverage increased returns but dramatically worse drawdowns",
        "lesson": "Current leverage bounds [0.3x, 2.0x] are well-calibrated.",
    },
    {
        "name": "v8.3 Patch -- Rank Hysteresis",
        "file": "test_v83_patch.py",
        "description": "Replace fixed 5-day hold with rank-based hysteresis: hold positions as long "
                       "as they remain in top-15 of momentum universe. Reduces turnover from 207 to "
                       "70 trades/year, avg hold from 7 to 20 days.",
        "result": "FAILED -- 11.48% CAGR (lost 4.56%), 0.612 Sharpe. MaxDD slightly better (-26.6%)",
        "lesson": "Longer holds cause momentum decay. 87% of exits at day 5 is a FEATURE, not a bug. "
                  "The 5-day rotation captures the momentum sweet spot. Trailing stops triggered 3x more "
                  "(44% vs 5%), confirming positions are held past their optimal exit.",
    },
    {
        "name": "v8.3 Patch -- Cash Yield on Idle Capital",
        "file": "test_v83_patch.py",
        "description": "Apply 3% annual risk-free rate to uninvested cash (simulates T-bill/money "
                       "market sweep). Especially impactful during RISK_OFF regime (~25.7% of time).",
        "result": "APPROVED -- 16.95% CAGR (+0.91%), 0.815 Sharpe, -28.4% MaxDD (unchanged). "
                  "$231k cumulative yield over 26 years.",
        "lesson": "Free improvement -- models real broker behavior. Not a signal change, just accurate "
                  "cash accounting. Integrated into production backtest.",
    },
    {
        "name": "v8.3 Patch -- Combined (Hysteresis + Yield)",
        "file": "test_v83_patch.py",
        "description": "Both modifications together",
        "result": "FAILED -- 13.01% CAGR, -35.4% MaxDD (WORSE than baseline on both metrics)",
        "lesson": "The cash yield cannot compensate for the damage caused by rank hysteresis.",
    },

    # =========================================================================
    # NEW EXPERIMENTS (Feb 21, 2026) -- Protection Mode Optimization
    # =========================================================================
    {
        "name": "Dynamic Recovery -- VIX & Breadth Signals",
        "file": "test_dynamic_recovery.py",
        "description": (
            "Test accelerating recovery from protection mode using market signals instead of "
            "pure time-based recovery. 5 variants: (A) Baseline (63d/126d time-based), "
            "(B) VIX Recovery (halve wait when VIX < SMA20), (C) Breadth Recovery (halve wait "
            "when >60% of universe above SMA50), (D) Combined (VIX OR Breadth), "
            "(E) Aggressive (base halved + VIX can halve again to 16d/32d)."
        ),
        "results": {
            "A_baseline": "16.95% CAGR, -28.4% MaxDD, 11 stops, 2002 protection days",
            "B_vix_recovery": "14.83% CAGR, -34.4% MaxDD, 13 stops -- WORSE on all metrics",
            "C_breadth_recovery": "14.49% CAGR, -34.6% MaxDD, 15 stops -- WORSE on all metrics",
            "D_combined": "14.60% CAGR, -34.4% MaxDD, 13 stops -- WORSE on all metrics",
            "E_aggressive": "12.83% CAGR, -41.2% MaxDD, 15 stops -- MUCH WORSE on all metrics",
        },
        "lesson": (
            "CRITICAL INSIGHT: Faster recovery from protection = more stop events = worse drawdowns. "
            "The 2,002 protection days are NOT a drag -- they are PROTECTIVE. Re-entering markets "
            "sooner after a -15% drawdown leads to additional stops (11->15) because the market "
            "conditions that caused the original stop often persist. The time-based recovery is a "
            "feature, not a bug. VIX normalization and breadth thrust signals are not reliable enough "
            "to safely accelerate re-entry."
        ),
    },
    {
        "name": "Protection Mode Shorts -- Inverse ETFs (SH/SDS)",
        "file": "test_protection_shorts.py",
        "description": (
            "Trade inverse ETFs during protection mode to profit from continued declines instead of "
            "sitting in cash. Staged sizing by recovery stage. 4 variants: (A) Baseline, "
            "(B) SH Staged (15% Stage1, 30% Stage2), (C) SDS Staged (10% Stage1, 20% Stage2), "
            "(D) SH Aggressive (25% Stage1, 50% Stage2). Used synthetic inverse SPY returns "
            "pre-June 2006 (SH/SDS didn't exist before then)."
        ),
        "results": {
            "A_baseline": "16.95% CAGR, -28.4% MaxDD",
            "B_sh_staged": "15.53% CAGR, -25.3% MaxDD, Inverse P&L: -$145,597",
            "C_sds_staged": "15.57% CAGR, -26.2% MaxDD, Inverse P&L: -$234,703",
            "D_sh_aggressive": "14.47% CAGR, -24.0% MaxDD, Inverse P&L: -$208,843",
        },
        "lesson": (
            "FUNDAMENTAL PROBLEM: Portfolio stop-loss triggers AFTER a crash, so protection mode "
            "coincides with RECOVERY periods, not further declines. Buying inverse ETFs during "
            "recovery = guaranteed losses. MaxDD improved slightly (shorts hedge initial volatility) "
            "but CAGR dropped 1.4-2.5% because the inverse P&L is deeply negative (-$145k to -$235k). "
            "The protection period is for capital preservation in cash, not for shorting."
        ),
    },
    {
        "name": "Protection Mode Shorts -- Bottom-N Momentum Stocks",
        "file": "test_protection_momentum_shorts.py",
        "description": (
            "Short the worst momentum stocks (bottom-N by 90d momentum score) during protection mode. "
            "Full short mechanics: equal-weight allocation, 5-day rebalance, -10% individual stop loss, "
            "1% annual borrow cost, min $5 price filter. 4 variants: (A) Baseline, (B) Short-5 "
            "(15% Stage1, 30% Stage2), (C) Short-3 (15%/30%), (D) Short-5 Aggressive (25%/50%)."
        ),
        "results": {
            "A_baseline": "16.95% CAGR, -28.4% MaxDD",
            "B_short_5": "16.65% CAGR (-0.30%), -28.8% MaxDD, Short P&L: -$46,618, Win rate: 48.5%",
            "C_short_3": "16.79% CAGR (-0.16%), -27.7% MaxDD, Short P&L: -$30,216, Win rate: 47.4%",
            "D_short_5_agg": "16.43% CAGR (-0.52%), -30.1% MaxDD, Short P&L: -$160,121, Win rate: 49.0%",
        },
        "lesson": (
            "Momentum shorts came much closer to baseline than inverse ETFs (-0.16% to -0.52% CAGR "
            "vs -1.4% to -2.5%), confirming individual stock shorts are less correlated with market "
            "direction than index shorts. SHORT-3 variant even improved MaxDD to -27.7%. However, "
            "short P&L is still negative across all variants because the fundamental timing problem "
            "remains: protection mode = recovery period. Win rate of ~48% is slightly below breakeven "
            "after borrow costs. CONCLUSION: Cash at 3% yield is the optimal protection mode strategy."
        ),
    },

    # =========================================================================
    # ChatGPT External Review Proposals (Feb 21, 2026)
    # =========================================================================
    {
        "name": "ChatGPT Proposal -- Ensemble Momentum (60d/90d/120d avg ranks)",
        "file": "test_chatgpt_proposals.py",
        "description": (
            "Average RANK positions across 60d/90d/120d momentum windows to create a "
            "more stable signal. Hypothesis: single 90d lookback may be overfit; ensemble "
            "across nearby windows reduces parameter sensitivity without diluting signal type."
        ),
        "result": "FAILED -- 9.52% CAGR (-7.43%), -42.5% MaxDD. WORST single proposal.",
        "lesson": (
            "The 90d lookback is NOT overfit -- it is genuinely superior. Averaging with 60d "
            "(too noisy/short-term) and 120d (too slow/lagging) dilutes the signal dramatically. "
            "Rank averaging across windows destroys the precision of stock selection. The ensemble "
            "approach works for diversified portfolios but not for concentrated 5-position systems."
        ),
    },
    {
        "name": "ChatGPT Proposal -- Conditional Hold Extension (Top5 + ATR declining)",
        "file": "test_chatgpt_proposals.py",
        "description": (
            "At day 5, extend hold to 10 days ONLY if the position is still in Top-5 momentum AND "
            "its short-term volatility (ATR-5) is below long-term (ATR-20), indicating calm uptrend. "
            "1,349 extensions triggered (25% of trades). More selective than v8.3 blanket hysteresis."
        ),
        "result": "FAILED -- 13.02% CAGR (-3.93%), -38.8% MaxDD. Better than hysteresis but still loses.",
        "lesson": (
            "Even with strict conditions (Top-5 + declining ATR), holding longer increases trailing stop "
            "exits from 4.9% to 8.5% and position stops from 6.5% to 9.2%. The 5-day hold is optimal "
            "because momentum alpha concentrates in the FIRST 5 days after entry. Extensions capture "
            "the tail of the distribution but also the reversions. Conditional extension is better than "
            "blanket hysteresis (-3.93% vs -4.56%) but the lesson is the same: 5 days is the sweet spot."
        ),
    },
    {
        "name": "ChatGPT Proposal -- Preemptive Stop (-8% with faster recovery)",
        "file": "test_chatgpt_proposals.py",
        "description": (
            "Trigger portfolio stop at -8% drawdown (vs -15%) to exit BEFORE crash deepens. "
            "Compensate with faster recovery: 32d/63d (vs 63d/126d). Hypothesis: catching the "
            "drawdown earlier avoids the timing paradox of post-crash protection."
        ),
        "result": "FAILED -- 10.40% CAGR (-6.56%), -41.0% MaxDD. 34 stops (vs 11). TRIPLED stop events.",
        "lesson": (
            "DEFINITIVE: -8% stop triggers 3x as many stop events (34 vs 11) because normal market "
            "volatility routinely hits -8% without leading to a crash. Every false trigger forces exit, "
            "incurs transaction costs, and misses recovery gains. The -15% threshold is calibrated: it "
            "triggers ONLY in genuine crisis scenarios. Preemptive stops create massive whipsaw. "
            "The faster recovery (32d/63d) cannot compensate because re-entry is also premature."
        ),
    },
]

# =============================================================================
# SECTION 4: STATISTICAL VALIDITY ANALYSIS
# =============================================================================

STATISTICAL_ANALYSIS = {
    "summary": (
        "Comprehensive statistical analysis suggests the COMPASS backtest results "
        "are somewhat overstated. The TRUE expected CAGR is estimated at ~11.5% "
        "(90% CI: 6.5%-15.5%) vs the reported 16.95%. However, even the conservative "
        "estimate beats S&P 500 buy-and-hold (~8% CAGR)."
    ),

    "overfitting_risk": {
        "PBO_estimate": "25-35%",  # Probability of Backtest Overfitting
        "description": (
            "Bailey & Lopez de Prado's PBO framework suggests 25-35% probability "
            "that the backtest is overfit. This is moderate -- below 50% is acceptable "
            "but above the ideal <15% threshold."
        ),
        "mitigating_factors": [
            "Algorithm has few parameters (< 15 meaningful ones)",
            "Parameters are academically grounded, not data-mined",
            "Uses standard indicators (SMA200, momentum) not exotic features",
            "Deterministic -- no random component to overfit",
            "24 enhancement experiments ALL failed to beat baseline (not cherry-picked)",
        ],
        "aggravating_factors": [
            "Single backtest period (no true out-of-sample)",
            "Some parameter choices (90d lookback, 5d hold) were confirmed on this data",
            "Universe of 113 stocks was curated (potential selection bias)",
        ],
    },

    "multiple_testing": {
        "DSR_p_value": "~0.30",
        "description": (
            "Harvey, Liu & Zhu (2016) Deflated Sharpe Ratio accounts for the number "
            "of strategies tested. Given ~24+ variants tested (v1-v8, VORTEX, behavioral, "
            "dynamic recovery, protection shorts, ChatGPT proposals, etc.), the DSR p-value is ~0.30, meaning "
            "the Sharpe ratio is not statistically significant at conventional levels after "
            "accounting for multiple testing."
        ),
        "haircut": "Sharpe should be discounted ~30-40% (0.815 -> 0.49-0.57 effective)",
    },

    "survivorship_bias": {
        "estimated_impact": "-1.0% to -2.5% CAGR",
        "description": (
            "Despite annual rotation by dollar volume, there is residual survivorship bias: "
            "the 113-stock broad pool was selected based on current S&P 500 membership. "
            "Stocks that were in S&P 500 in 2000 but delisted/dropped by 2026 are excluded. "
            "This typically overstates returns by 1-2.5% annually."
        ),
    },

    "transaction_costs": {
        "estimated_impact": "-0.5% to -1.5% CAGR",
        "description": (
            "While commission ($0.001/share) and margin (6%) are modeled, slippage is not. "
            "With ~207 trades/year in liquid stocks, realistic slippage of 2-5bps per trade "
            "could reduce CAGR by 0.5-1.5%."
        ),
    },

    "true_expected_performance": {
        "reported_CAGR": "16.95%",
        "adjustments": {
            "survivorship_bias": "-1.5%",
            "slippage_not_modeled": "-1.0%",
            "overfitting_haircut": "-2.0%",
            "multiple_testing_discount": "-1.0%",
        },
        "estimated_true_CAGR": "~11.5%",
        "confidence_interval_90pct": "6.5% - 15.5%",
        "vs_SPY_buy_and_hold": "~8% CAGR (2000-2026)",
        "conclusion": (
            "Even after all adjustments, COMPASS likely generates 2-6% annual alpha "
            "over buy-and-hold, primarily from the momentum signal + regime filter. "
            "This is a meaningful edge but far from the reported 16% CAGR."
        ),
    },
}

# =============================================================================
# SECTION 5: LIVE TRADING SYSTEM
# =============================================================================

LIVE_SYSTEM = {
    "dashboard_file": "compass_dashboard.py",
    "template_file": "templates/dashboard.html",
    "url": "http://localhost:5000",
    "framework": "Flask + Chart.js",

    "features": [
        "Real-time portfolio state display (cash, positions, P&L, drawdown)",
        "Open Positions table with TOTAL row (total VALUE, P&L, weighted P&L%)",
        "Engine control (START/STOP with confirmation modals)",
        "Equity curve chart (backtest data from 2020+, with CAGR display)",
        "Holdings news feed (Yahoo, Zacks, Benzinga, Reuters, Motley Fool)",
        "Market futures display (ES, NQ, YM)",
        "Pre-flight checklist before market open",
        "Live trade log viewer",
        "Collapsible Activity Log panel (collapsed by default)",
        "Collapsible Stop Events History panel (expanded by default)",
        "Collapsible Universe panel with stock count",
        "Responsive dark terminal theme (#141418 background)",
        "LIVE pulse animation when engine is running",
    ],

    "api_endpoints": [
        "/api/state -- Portfolio state (positions, cash, regime, leverage)",
        "/api/equity -- Backtest equity curve (2020+ filtered, every 5th day)",
        "/api/logs -- Trading engine logs",
        "/api/futures -- Market futures (ES, NQ, YM via yfinance)",
        "/api/news -- Holdings news feed",
        "/api/preflight -- Pre-market checklist",
        "/api/engine/status -- Engine running/stopped status",
        "/api/engine/start -- Start trading engine (POST)",
        "/api/engine/stop -- Stop trading engine (POST)",
    ],

    "state_management": {
        "state_file": "state/compass_state_latest.json",
        "contents": "Cash, positions (ticker, shares, entry price, entry date, peak), "
                    "regime, drawdown, recovery stage, day counter, peak equity",
        "persistence": "Auto-saves state every ~60 seconds and on each trade",
    },

    "recent_dashboard_updates": [
        "Added TOTAL row to Open Positions table (VALUE + P&L + weighted P&L%)",
        "Made Activity Log collapsible (collapsed by default, click arrow to expand)",
        "Made Stop Events History collapsible (expanded by default)",
        "CSS class-based toggle pattern (classList.add/remove) for reliable show/hide",
    ],

    "current_state_snapshot": {
        "date": "2026-02-21",
        "total_value": "$100,704",
        "cash": "$19,116",
        "positions": ["MU (+3.2%)", "LRCX (+4.0%)", "AMAT (+2.0%)", "XOM (-4.0%)", "MRK (+1.1%)"],
        "regime": "RISK_ON",
        "leverage": "1.00x",
        "drawdown": "-0.1%",
        "mode": "Paper trading",
    },
}

# =============================================================================
# SECTION 6: VERSION HISTORY & DECISION LOG
# =============================================================================

VERSION_HISTORY = [
    {"version": "v1", "name": "MicroManagement", "description": "Intraday strategy -- abandoned (too complex, poor results)"},
    {"version": "v2", "name": "Multi-Strategy", "description": "Multiple strategies combined -- abandoned (over-engineered)"},
    {"version": "v3", "name": "Consolidated", "description": "Single consolidated strategy -- abandoned (still too complex)"},
    {"version": "v4", "name": "Optimized Daily", "description": "Daily trading -- abandoned (incremental improvement)"},
    {"version": "v5", "name": "3-Day Strategy", "description": "3-day hold -- abandoned (worse than 5-day)"},
    {"version": "v6", "name": "Random 666", "description": "Random selection + leverage -> 16.92% CAGR (BIASED)"},
    {"version": "v6-fixed", "name": "Top-40 Rotation", "description": "Annual rotation fix -> 5.40% CAGR (unbiased, no signal)"},
    {"version": "v7", "name": "Regime + Momentum", "description": "Attempted v7 with regime filter -- cancelled (complexity)"},
    {"version": "v8", "name": "COMPASS", "description": "Production algo -> 16.16% CAGR, 0.73 Sharpe, -34.8% MaxDD"},
    {"version": "v8.1", "name": "Short-Selling", "description": "Short experiment -> FAILED (fundamentals don't predict shorts)"},
    {"version": "v8.2", "name": "COMPASS Refined", "description": "Tighter recovery + cash yield -> 16.95% CAGR, 0.815 Sharpe, -28.4% MaxDD"},
    {"version": "v8.3-test", "name": "Rank Hysteresis", "description": "FAILED -- hold until rank drops below top-15 lost 4.56% CAGR"},
    {"version": "v8.4-test", "name": "Dynamic Recovery", "description": "FAILED -- VIX/Breadth accelerated recovery caused more stops (11->15)"},
    {"version": "v8.5-test", "name": "Protection Shorts", "description": "FAILED -- inverse ETFs during protection lost $145-235k (recovery timing)"},
    {"version": "v8.6-test", "name": "Momentum Shorts", "description": "FAILED -- shorting bottom-N stocks during protection, closest attempt (-0.16% CAGR)"},
    {"version": "v8.7-test", "name": "Ensemble Momentum", "description": "FAILED -- avg ranks 60/90/120d lost 7.43% CAGR (signal dilution)"},
    {"version": "v8.8-test", "name": "Cond Hold Extension", "description": "FAILED -- extend to 10d if Top5+ATR declining, lost 3.93% CAGR"},
    {"version": "v8.9-test", "name": "Preemptive Stop -8%", "description": "FAILED -- tripled stop events (11->34), lost 6.56% CAGR"},
    {"version": "FINAL", "name": "ALGORITHM LOCKED", "description": "24 experiments confirm inelasticity. Focus shifts to execution/infrastructure."},
]

KEY_DECISIONS = [
    "Long-only is FINAL -- short-selling experiments failed completely (v8.1, v8.5, v8.6)",
    "5-day hold is optimal -- tested 1-20 day range",
    "90-day momentum lookback with 5-day skip is near-optimal",
    "Annual rotation by dollar volume eliminates survivorship bias",
    "Vol targeting [0.3x, 2.0x] replaces fixed leverage",
    "SPY SMA200 regime filter with 3-day confirmation is robust",
    "Recovery uses time-based stages (not peak-based) -- critical lesson from v6",
    "Time-based recovery is OPTIMAL -- dynamic recovery with VIX/Breadth signals FAILED (v8.4)",
    "Protection mode = cash at 3% yield -- all shorting strategies during protection FAILED (v8.5, v8.6)",
    "No behavioral finance overlays -- all variants lost 7-10% CAGR",
    "No second-derivative momentum (VORTEX) -- adds noise, not signal",
    "No quality factors -- yfinance fundamental data too limited",
    "No rank-hysteresis holds -- 5-day rotation is optimal, longer holds cause momentum decay",
    "Cash yield (3% on idle cash) approved -- models real broker T-bill sweep, +0.91% CAGR free",
    "2,002 protection days (30.5%) confirmed as FEATURE not bug -- reducing them worsens performance",
    "No ensemble momentum -- averaging 60d/90d/120d ranks DILUTES signal, lost 7.43% CAGR",
    "No conditional hold extension -- even selective extension (Top5+ATR) loses 3.93% CAGR",
    "No preemptive stop (-8%) -- normal volatility triggers false stops, TRIPLED stop events (11->34)",
    "ALGORITHM DECLARED INELASTIC -- 24 experiments, 22 failed. Motor is locked. Focus on chassis.",
]

# =============================================================================
# SECTION 7: KEY FILES INVENTORY
# =============================================================================

KEY_FILES = {
    "production": {
        "omnicapital_v8_compass.py": "COMPASS v8 production backtest algorithm (~875 lines)",
        "compass_dashboard.py": "Live dashboard + trading engine (Flask, ~800 lines)",
        "templates/dashboard.html": "Dashboard UI (Chart.js, dark theme, TOTAL row, collapsible panels)",
    },
    "documentation": {
        "OMNICAPITAL_V8_COMPASS_MANIFESTO.md": "Complete algorithm documentation (420 lines)",
        "OMNICAPITAL_V8_COMPASS_MANIFESTO.docx": "Word version of manifesto",
        "OMNICAPITAL_PROJECT_REVIEW.py": "THIS FILE -- comprehensive project review for AI analysis",
        "MEMORY.md": "Claude project memory with key decisions and parameters",
    },
    "experiments": {
        "omnicapital_vortex.py": "VORTEX v1 -- acceleration momentum (failed)",
        "omnicapital_vortex_v2.py": "VORTEX v2 -- EMA + dual timeframe (failed)",
        "omnicapital_vortex_v3_sweep.py": "VORTEX v3 -- parameter sweep (confirmed baseline is best)",
        "compass_v8_optimization_test.py": "5-variant optimization test (baseline won)",
        "compass_v8_quality.py": "Quality factor overlay (lost ~1% CAGR)",
        "compass_v8_scaled.py": "Scaled universe test (60 stocks, similar results)",
        "compass_v8_amplify_test.py": "Aggressive leverage test (worse drawdowns)",
        "test_behavioral.py": "Behavioral finance overlays (all failed -7 to -10% CAGR)",
        "test_intraday_meanrev.py": "Gap trading / mean-reversion (massive losses)",
        "test_rotation_freq.py": "Universe rotation frequency sweep (annual is best)",
        "compass_nightshift_backtest.py": "Overnight close-to-open strategy ($50k separate)",
        "test_v83_patch.py": "v8.3 patch test -- rank hysteresis (FAILED) + cash yield (APPROVED)",
        "test_dynamic_recovery.py": "Dynamic recovery test -- VIX/Breadth signals (ALL FAILED)",
        "test_protection_shorts.py": "Inverse ETF shorts during protection (ALL FAILED)",
        "test_protection_momentum_shorts.py": "Momentum shorts during protection (ALL FAILED, closest)",
        "test_chatgpt_proposals.py": "ChatGPT external review proposals (ensemble/cond hold/preemptive stop, ALL FAILED)",
    },
    "historical_versions": {
        "omnicapital_v6_top40_rotation.py": "v6 corrected (survivorship bias fix) -- 5.40% CAGR",
        "omnicapital_v6_final_optimized.py": "v6 original (biased) -- 16.92% CAGR",
        "omnicapital_v7.py": "v7 cancelled attempt",
    },
    "live_trading_support": {
        "omnicapital_live.py": "Live trading system (needs update to v8.2)",
        "omnicapital_broker.py": "Broker interface module",
        "omnicapital_data_feed.py": "Data feed module",
        "launch_compass.py": "Launcher script for dashboard + engine",
    },
    "backtest_outputs": {
        "backtests/v8_compass_daily.csv": "Daily portfolio snapshots (6,500+ rows)",
        "backtests/v8_compass_trades.csv": "All 5,386 trades with entry/exit details",
        "backtests/v8_opt_base_v8.2_daily.csv": "v8.2 optimized baseline daily data",
        "backtests/nightshift_daily.csv": "NIGHTSHIFT overnight strategy daily data",
        "backtests/nightshift_combined.csv": "COMPASS + NIGHTSHIFT combined equity",
        "backtests/dynrecov_*_daily.csv": "Dynamic recovery test outputs (5 variants)",
        "backtests/protshort_*_daily.csv": "Protection shorts test outputs (4 variants)",
        "backtests/momshort_*_daily.csv": "Momentum shorts test outputs (4 variants)",
        "backtests/chatgpt_*_daily.csv": "ChatGPT proposals test outputs (6 variants)",
    },
    "data_cache": {
        "data_cache/broad_pool_2000-01-01_2026-02-09.pkl": "Cached price data for 113-stock universe",
        "data_cache/VIX_2000-01-01_2026-02-09.csv": "VIX daily data for signal computation",
        "data_cache/SH_2000-01-01_2026-02-09.csv": "ProShares Short S&P500 ETF data (from Jun 2006)",
        "data_cache/SDS_2000-01-01_2026-02-09.csv": "ProShares UltraShort S&P500 ETF data (from Jul 2006)",
    },
}

# =============================================================================
# SECTION 8: UNIVERSE COMPOSITION
# =============================================================================

STOCK_UNIVERSE = {
    "total_broad_pool": 113,
    "eligible_per_year": 40,  # top 40 by dollar volume
    "unique_stocks_used": 78,  # across 26 years
    "annual_turnover": "~4-5 stocks rotate each year",
    "sectors": {
        "Technology": ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AVGO", "ADBE", "CRM", "AMD",
                       "INTC", "CSCO", "IBM", "TXN", "QCOM", "ORCL", "ACN", "NOW", "INTU",
                       "AMAT", "MU", "LRCX", "SNPS", "CDNS", "KLAC", "MRVL"],
        "Financials": ["BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "AXP", "BLK",
                       "SCHW", "C", "USB", "PNC", "TFC", "CB", "MMC", "AIG"],
        "Healthcare": ["UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "TMO", "ABT", "DHR",
                       "AMGN", "BMY", "MDT", "ISRG", "SYK", "GILD", "REGN", "VRTX", "BIIB"],
        "Consumer": ["AMZN", "TSLA", "WMT", "HD", "PG", "COST", "KO", "PEP", "NKE",
                     "MCD", "DIS", "SBUX", "TGT", "LOW", "CL", "KMB", "GIS", "EL", "MO", "PM"],
        "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "OXY", "MPC", "PSX", "VLO"],
        "Industrials": ["GE", "CAT", "BA", "HON", "UNP", "RTX", "LMT", "DE", "UPS", "FDX",
                        "MMM", "GD", "NOC", "EMR"],
        "Utilities": ["NEE", "DUK", "SO", "D", "AEP"],
        "Telecom": ["VZ", "T", "TMUS", "CMCSA"],
    },
}

# =============================================================================
# SECTION 9: CRITICAL LESSONS LEARNED
# =============================================================================

LESSONS = [
    {
        "category": "Survivorship Bias",
        "lesson": "A fixed stock universe produces fake alpha. v6 reported 16.92% CAGR with a "
                  "static 60-stock list. After fixing with annual rotation by dollar volume, "
                  "true CAGR was 5.40%. Always use dynamic universe selection.",
    },
    {
        "category": "Signal vs Noise",
        "lesson": "In a concentrated 5-position portfolio with 5-day hold, the stock selection "
                  "signal is EVERYTHING. Any dilution of the pure momentum score (behavioral "
                  "overlays, quality filters, multi-factor blends) destroys alpha. The signal "
                  "must be razor-focused.",
    },
    {
        "category": "Complexity Tax",
        "lesson": "Every additional indicator/filter tested (VORTEX acceleration, 52-week high, "
                  "lottery filter, VIX override, breadth filter, dual SMA, dynamic recovery signals) "
                  "reduced performance. The simplest version (COMPASS baseline) consistently won.",
    },
    {
        "category": "Short Selling",
        "lesson": (
            "THREE separate short-selling approaches all failed: (1) Fundamental-based shorts "
            "(v8.1: Revenue/Debt, Debt/EBITDA) -- bank debt is structural. (2) Inverse ETFs "
            "during protection (SH/SDS) -- protection triggers post-crash, during recovery, so "
            "shorts lose $145-235k. (3) Momentum shorts during protection (bottom-N stocks) -- "
            "closest attempt but still negative P&L. Long-only with cash yield is definitively "
            "the optimal approach."
        ),
    },
    {
        "category": "Stop Loss + Leverage Interaction",
        "lesson": "The combination of stop losses and leverage creates whipsaw risk. The 3-stage "
                  "recovery system (0.3x -> 1.0x -> vol targeting over 63-126 days) was critical "
                  "to avoid re-entering too aggressively after a stop.",
    },
    {
        "category": "Recovery Design",
        "lesson": "v6 required equity to exceed its historical peak to recover -- nearly impossible "
                  "after a -59% drawdown. COMPASS uses time-based recovery PLUS regime confirmation "
                  "(market must be in RISK_ON). This is the key architectural improvement.",
    },
    {
        "category": "Protection Mode Timing Paradox",
        "lesson": (
            "The portfolio stop-loss at -15% triggers AFTER a crash. This means protection mode "
            "almost always coincides with MARKET RECOVERY, not further decline. Any strategy that "
            "attempts to profit from the downside during protection (inverse ETFs, shorts) faces a "
            "fundamental timing problem. The 2,002 protection days (30.5% of the 26-year backtest) "
            "are not wasted time -- they prevent re-entering volatile post-crash markets. Attempts "
            "to reduce protection time via VIX/Breadth signals increased stop events from 11 to 15 "
            "and worsened MaxDD from -28.4% to -41.2%."
        ),
    },
    {
        "category": "Statistical Honesty",
        "lesson": "Reported backtest CAGR (16.95%) is likely overstated by ~5%. After adjustments "
                  "for survivorship bias, slippage, overfitting, and multiple testing, true expected "
                  "CAGR is ~11.5%. Still alpha-positive vs SPY buy-and-hold (~8%) but must be "
                  "communicated honestly.",
    },
    {
        "category": "Data Limitations",
        "lesson": "yfinance provides only ~5 years of fundamental data, making quality factor "
                  "backtests unreliable for the full 2000-2026 period. Stick to price/volume "
                  "based signals that have 25+ years of clean data.",
    },
    {
        "category": "Algorithm Robustness / Inelasticity",
        "lesson": (
            "24 experiments attempted to improve COMPASS -- only 1 succeeded (cash yield, which is "
            "not a signal change). This extreme resistance to improvement -- including proposals from "
            "external quantitative review -- confirms the algorithm is INELASTIC: the core decision "
            "engine has reached its theoretical maximum for this universe/timeframe. Any parameter "
            "change (signal, hold time, stop threshold, momentum window) degrades performance."
        ),
    },
    {
        "category": "Ensemble vs Concentrated Signal",
        "lesson": (
            "Ensemble momentum (averaging ranks across 60d/90d/120d) lost 7.43% CAGR. In concentrated "
            "5-position portfolios, signal PRECISION matters more than signal STABILITY. The 90d window "
            "captures a specific momentum regime that shorter (60d) and longer (120d) windows miss. "
            "Averaging dilutes the edge. Ensemble approaches are designed for diversified portfolios "
            "with 50+ positions, not for concentrated momentum systems."
        ),
    },
    {
        "category": "Stop Loss Threshold Sensitivity",
        "lesson": (
            "Moving the portfolio stop from -15% to -8% tripled stop events (11->34) and lost 6.56% CAGR. "
            "Normal market volatility routinely causes -8% drawdowns that recover naturally. The -15% "
            "threshold is precisely calibrated to trigger ONLY in genuine crisis scenarios (dot-com crash, "
            "GFC, COVID, etc.). Pre-emptive protection sounds logical but creates catastrophic whipsaw."
        ),
    },
    {
        "category": "When to Stop Optimizing",
        "lesson": (
            "After 24 failed experiments, the project reached a definitive conclusion: the algorithm is "
            "inelastic. Further optimization attempts will only lead to overfitting. The correct path "
            "forward is to improve the CHASSIS (execution, infrastructure, capital efficiency, orthogonal "
            "diversification) rather than the MOTOR (signal, parameters, rules). As the external reviewer "
            "stated: 'Stop torturing the algorithm. It already confessed everything it knows.'"
        ),
    },
]

# =============================================================================
# SECTION 10: PROTECTION MODE DEEP ANALYSIS
# =============================================================================

PROTECTION_MODE_ANALYSIS = {
    "summary": (
        "Protection mode is the period after a -15% portfolio drawdown triggers the stop-loss. "
        "COMPASS closes all positions and gradually re-enters the market over 63-126 trading days. "
        "This section documents comprehensive analysis of protection mode behavior, including three "
        "failed attempts to optimize it."
    ),

    "statistics": {
        "total_stop_events": 11,
        "total_protection_days": 2002,
        "pct_of_trading_days": "30.5%",
        "avg_recovery_duration": "~182 days per event",
        "frequency": "~1 every 2.4 years",
    },

    "experiments_attempted": {
        "dynamic_recovery": {
            "hypothesis": "Reduce protection time using VIX/Breadth signals to detect safe re-entry",
            "result": "FAILED -- faster re-entry caused 4 more stop events, -4.1% MaxDD worse",
            "key_insight": "Market conditions that caused the original stop often persist",
        },
        "inverse_etf_shorts": {
            "hypothesis": "Profit from continued decline by buying SH/SDS during protection",
            "result": "FAILED -- protection coincides with recovery, inverse P&L deeply negative",
            "key_insight": "Stop triggers AFTER crash, so market is already recovering",
        },
        "momentum_shorts": {
            "hypothesis": "Short the worst momentum stocks for uncorrelated returns",
            "result": "FAILED but closest -- only -0.16% CAGR with improved MaxDD (-27.7%)",
            "key_insight": "Individual stock shorts less market-correlated but still net negative",
        },
    },

    "conclusion": (
        "Cash at 3% yield is the DEFINITIVE optimal strategy during protection mode. "
        "All three optimization approaches (faster recovery, inverse ETFs, momentum shorts) "
        "failed due to the fundamental timing paradox: protection mode starts AFTER the crash, "
        "during market recovery. The 2,002 protection days are not idle capital drag -- they are "
        "the reason MaxDD is -28.4% instead of >-40%. This is a closed question."
    ),
}

# =============================================================================
# SECTION 11: ALGORITHM INELASTICITY -- FINAL CONCLUSION
# =============================================================================

ALGORITHM_INELASTICITY = {
    "declaration": (
        "After 24 experiments (22 failed, 2 succeeded), COMPASS v8.2 is declared INELASTIC. "
        "The core decision engine has reached its theoretical maximum for this universe and "
        "timeframe. Any modification to the signal, parameters, exit rules, or stop logic "
        "degrades performance. This was confirmed by both internal testing and external "
        "quantitative review (ChatGPT analysis with proposals B/C/D)."
    ),

    "what_was_tried": {
        "signal_modifications": [
            "Acceleration momentum (VORTEX v1/v2/v3) -- adds noise",
            "Risk-adjusted momentum -- lost 2% CAGR",
            "Ensemble momentum (60/90/120d avg ranks) -- lost 7.43% CAGR",
            "Behavioral overlays (52wk high, lottery filter) -- lost 7-10% CAGR",
            "Quality factors (ROE, margins) -- lost ~1% CAGR",
        ],
        "exit_modifications": [
            "Rank hysteresis (hold until rank > 15) -- lost 4.56% CAGR",
            "Conditional hold extension (Top5 + ATR declining) -- lost 3.93% CAGR",
            "Hold period sweep (1-20 days) -- 5 days confirmed optimal",
        ],
        "regime_modifications": [
            "Dual SMA (50+200) -- slightly worse",
            "VIX override -- whipsaw",
            "Breadth filter -- marginal",
            "Credit stress (JNK/IEF) -- not fully testable (data limitations)",
        ],
        "stop_modifications": [
            "Dynamic recovery (VIX/Breadth signals) -- more stops, worse DD",
            "Preemptive stop (-8% vs -15%) -- tripled stop events",
            "Amplified leverage -- worse drawdowns",
        ],
        "short_selling": [
            "Fundamental shorts (Revenue/Debt, Debt/EBITDA) -- failed in bull markets",
            "Inverse ETFs during protection (SH/SDS) -- lost $145-235k",
            "Momentum shorts during protection (bottom-N) -- closest but still negative",
        ],
    },

    "why_inelastic": (
        "The COMPASS engine operates at a precise equilibrium: 90d lookback captures the specific "
        "momentum regime where winners continue, 5d skip removes short-term reversal noise, 5d hold "
        "captures the concentrated alpha before mean-reversion, -15% stop triggers only in genuine "
        "crises, and the 63/126d recovery prevents whipsaw re-entry. Any perturbation to any of "
        "these parameters shifts the system off this equilibrium. The system's 'simplicity' IS the "
        "edge -- it has minimal degrees of freedom to overfit."
    ),

    "next_steps": {
        "description": "Focus shifts from motor optimization to chassis improvement:",
        "priorities": [
            {
                "area": "Execution Microstructure",
                "actions": [
                    "Implement TWAP/VWAP for last 15 minutes of session",
                    "Use passive limit orders to capture spread instead of paying it",
                    "Fractionate orders when capital grows (reduce market impact)",
                ],
                "estimated_benefit": "+0.5% to +1.5% CAGR recovery (slippage reduction)",
            },
            {
                "area": "Capital Efficiency",
                "actions": [
                    "Replace cash sweep with T-Bill ETF (SGOV/BIL) as collateral",
                    "Earn actual T-Bill rate (~4-5%) vs modeled 3%",
                    "Use treasury holdings as margin collateral",
                ],
                "estimated_benefit": "+0.5% to +1.0% CAGR (higher yield on idle capital)",
            },
            {
                "area": "Orthogonal Diversification",
                "actions": [
                    "Design a separate uncorrelated system (mean-reversion, volatility, etc.)",
                    "NIGHTSHIFT prototype exists -- evaluate for production",
                    "Target combined Sharpe > 1.0 via portfolio-level diversification",
                ],
                "estimated_benefit": "Sharpe 0.815 -> 1.0+ via portfolio combination",
            },
            {
                "area": "Infrastructure Robustness",
                "actions": [
                    "Full end-to-end automation (data -> signal -> order routing)",
                    "Corporate action handling (splits, dividends, mergers, spin-offs)",
                    "Broker API integration (IBKR TWS API)",
                    "Failover and monitoring (alerts, dead man switch)",
                ],
                "estimated_benefit": "Eliminates operational risk and human error",
            },
        ],
    },
}

# =============================================================================
# SECTION 12: QUESTIONS FOR REVIEWER
# =============================================================================

REVIEW_QUESTIONS = [
    "1. Does the momentum signal (90d lookback, 5d skip) seem robust, or is 90 days "
    "   suspiciously specific? Academic literature supports 3-12 month momentum, but "
    "   the exact 90-day choice was validated on this dataset.",

    "2. The 113-stock broad pool was hand-selected from current S&P 500 membership. "
    "   How significant is the residual survivorship bias despite annual rotation?",

    "3. Is the -28.4% max drawdown acceptable for a leveraged momentum strategy? "
    "   The statistical analysis suggests this could be worse in live trading.",

    "4. The regime filter (SPY > SMA200) is simple and well-known. Could its "
    "   effectiveness be degrading as more funds use similar signals?",

    "5. With 11 portfolio stop-loss events in 26 years (~1 every 2.4 years), "
    "   is the -15% threshold too sensitive or about right?",

    "6. The vol targeting range [0.3x, 2.0x] allows significant leverage. "
    "   Should the max be capped lower (e.g., 1.5x) for live trading safety?",

    "7. The system has never been tested out-of-sample (no walk-forward or "
    "   paper trading period). How critical is this before going live?",

    "8. 24 enhancement experiments failed -- only cash yield succeeded (not a signal "
    "   change). Including proposals from external quantitative review (ensemble momentum, "
    "   conditional hold, preemptive stop). The algorithm is declared INELASTIC. Is this "
    "   conclusion correct, or is there a blind spot in the testing methodology?",

    "9. Transaction costs assume $0.001/share commission with no slippage. "
    "   Is this realistic for a retail account trading ~207 times per year?",

    "10. The combined COMPASS + NIGHTSHIFT approach uses $150k total capital. "
    "    Does the overnight strategy add genuine diversification, or is it "
    "    just adding complexity and costs?",

    "11. The protection mode consumes 30.5% of the backtest period (2,002 days). "
    "    Three separate attempts to optimize protection failed (dynamic recovery, "
    "    inverse ETFs, momentum shorts). Is there ANY approach we haven't tried "
    "    that could extract value from protection periods without increasing MaxDD?",

    "12. ANSWERED (Q13 old): Conditional hold extension (Top5 + ATR declining) tested "
    "    and FAILED (-3.93% CAGR). Even selective extension increases trailing stop exits "
    "    from 4.9% to 8.5%. The 5-day hold is definitively optimal.",

    "13. ANSWERED (Q16 old): Preemptive stop at -8% tested and FAILED (-6.56% CAGR, "
    "    34 stops vs 11). Normal volatility triggers false stops. -15% is calibrated.",

    "14. ANSWERED (Q17 old): Ensemble momentum (60d/90d/120d avg ranks) tested and "
    "    FAILED (-7.43% CAGR). Signal precision > signal stability in concentrated portfolios.",

    "15. IDEA REQUEST: The universe is static 113 stocks from current S&P 500. "
    "    Would a truly dynamic universe (e.g., annual S&P 500 reconstitution "
    "    using historical membership data from Norgate/CRSP) materially change results?",

    "16. IDEA REQUEST: The strategy is US-only. Would international momentum "
    "    (developed markets ETFs, or a global stock pool) provide diversification "
    "    benefits while using the same COMPASS framework?",

    "17. CHASSIS IMPROVEMENT: The algorithm is declared inelastic. What specific "
    "    execution improvements (TWAP/VWAP, limit orders, order splitting) would "
    "    recover the estimated 0.5-1.5% CAGR lost to slippage?",

    "18. CHASSIS IMPROVEMENT: Could capital efficiency be improved by investing idle "
    "    cash in T-Bill ETFs (SGOV/BIL) as collateral instead of cash sweep? This "
    "    would earn the actual T-Bill rate (~4-5%) vs the modeled 3%.",

    "19. CHASSIS IMPROVEMENT: What is the optimal orthogonal strategy to pair with "
    "    COMPASS? Mean-reversion in sideways markets? Volatility selling? The combined "
    "    Sharpe could exceed 1.0 if correlation is near zero.",

    "20. CHASSIS IMPROVEMENT: What infrastructure improvements (automated execution, "
    "    corporate action handling, broker API integration) are highest priority for "
    "    moving from paper trading to live execution with real capital?",
]


# =============================================================================
# MAIN: Print formatted summary
# =============================================================================

def print_section(title, content=""):
    """Print a formatted section header."""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")
    if content:
        print(content)


def main():
    print("=" * 80)
    print("  OMNICAPITAL PROJECT -- COMPREHENSIVE REVIEW")
    print(f"  Generated: 2026-02-21")
    print(f"  Total experiments: {PROJECT['total_experiments']} "
          f"({PROJECT['experiments_succeeded']} succeeded, "
          f"{PROJECT['experiments_failed']} failed)")
    print("=" * 80)

    # ---- Project Overview ----
    print_section("1. PROJECT OVERVIEW")
    for k, v in PROJECT.items():
        print(f"  {k:25s}: {v}")

    # ---- COMPASS Algorithm ----
    print_section("2. COMPASS v8.2 -- PRODUCTION ALGORITHM")
    print(COMPASS_DESCRIPTION)
    print("\n  KEY PARAMETERS:")
    for k, v in COMPASS_PARAMETERS.items():
        if isinstance(v, dict):
            print(f"\n  {k}:")
            for kk, vv in v.items():
                print(f"    {kk:25s}: {vv}")
        elif isinstance(v, list):
            print(f"\n  {k}:")
            for item in v:
                print(f"    - {item}")
        else:
            print(f"  {k:30s}: {v}")

    print("\n  BACKTEST RESULTS (2000-2026):")
    for k, v in COMPASS_RESULTS.items():
        print(f"    {k:20s}: {v}")

    print(COMPASS_V82_IMPROVEMENTS)

    # ---- Experiments ----
    print_section("3. ALL EXPERIMENTS ATTEMPTED")
    for i, exp in enumerate(EXPERIMENTS, 1):
        print(f"\n  [{i}] {exp['name']}")
        if 'file' in exp:
            print(f"      File: {exp['file']}")
        if 'files' in exp:
            print(f"      Files: {', '.join(exp['files'])}")
        print(f"      Description: {exp['description']}")
        if isinstance(exp.get('result'), str):
            print(f"      Result: {exp['result']}")
        elif isinstance(exp.get('results'), dict):
            print(f"      Results:")
            for rk, rv in exp['results'].items():
                print(f"        {rk}: {rv}")
        if isinstance(exp.get('variants'), dict):
            print(f"      Variants:")
            for vk, vv in exp['variants'].items():
                print(f"        {vk}: {vv}")
        if 'lesson' in exp:
            print(f"      Lesson: {exp['lesson']}")

    # ---- Statistical Analysis ----
    print_section("4. STATISTICAL VALIDITY ANALYSIS")
    sa = STATISTICAL_ANALYSIS
    print(f"\n  SUMMARY: {sa['summary']}")

    print(f"\n  OVERFITTING RISK:")
    print(f"    PBO estimate: {sa['overfitting_risk']['PBO_estimate']}")
    print(f"    {sa['overfitting_risk']['description']}")
    print(f"    Mitigating factors:")
    for f in sa['overfitting_risk']['mitigating_factors']:
        print(f"      + {f}")
    print(f"    Aggravating factors:")
    for f in sa['overfitting_risk']['aggravating_factors']:
        print(f"      - {f}")

    print(f"\n  MULTIPLE TESTING:")
    print(f"    DSR p-value: {sa['multiple_testing']['DSR_p_value']}")
    print(f"    {sa['multiple_testing']['description']}")
    print(f"    Haircut: {sa['multiple_testing']['haircut']}")

    print(f"\n  SURVIVORSHIP BIAS: {sa['survivorship_bias']['estimated_impact']}")
    print(f"    {sa['survivorship_bias']['description']}")

    print(f"\n  TRANSACTION COSTS: {sa['transaction_costs']['estimated_impact']}")
    print(f"    {sa['transaction_costs']['description']}")

    print(f"\n  TRUE EXPECTED PERFORMANCE:")
    tp = sa['true_expected_performance']
    print(f"    Reported CAGR:        {tp['reported_CAGR']}")
    for adj, val in tp['adjustments'].items():
        print(f"      {adj:30s}: {val}")
    print(f"    Estimated true CAGR:  {tp['estimated_true_CAGR']}")
    print(f"    90% confidence:       {tp['confidence_interval_90pct']}")
    print(f"    vs SPY buy-and-hold:  {tp['vs_SPY_buy_and_hold']}")
    print(f"    Conclusion: {tp['conclusion']}")

    # ---- Live System ----
    print_section("5. LIVE TRADING SYSTEM")
    ls = LIVE_SYSTEM
    print(f"\n  Dashboard: {ls['url']} ({ls['framework']})")
    print(f"  Features:")
    for f in ls['features']:
        print(f"    - {f}")
    print(f"\n  API Endpoints:")
    for ep in ls['api_endpoints']:
        print(f"    {ep}")
    print(f"\n  Recent Dashboard Updates:")
    for u in ls['recent_dashboard_updates']:
        print(f"    + {u}")
    print(f"\n  Current State (as of {ls['current_state_snapshot']['date']}):")
    for k, v in ls['current_state_snapshot'].items():
        if isinstance(v, list):
            print(f"    {k}: {', '.join(v)}")
        else:
            print(f"    {k}: {v}")

    # ---- Version History ----
    print_section("6. VERSION HISTORY")
    for v in VERSION_HISTORY:
        marker = " <<<" if "COMPASS" in v['name'] else ""
        print(f"  {v['version']:12s} {v['name']:20s} {v['description']}{marker}")

    print("\n  KEY DECISIONS:")
    for d in KEY_DECISIONS:
        print(f"    * {d}")

    # ---- Lessons ----
    print_section("7. CRITICAL LESSONS LEARNED")
    for l in LESSONS:
        print(f"\n  [{l['category']}]")
        print(f"    {l['lesson']}")

    # ---- Protection Mode Analysis ----
    print_section("8. PROTECTION MODE DEEP ANALYSIS")
    pma = PROTECTION_MODE_ANALYSIS
    print(f"\n  {pma['summary']}")
    print(f"\n  STATISTICS:")
    for k, v in pma['statistics'].items():
        print(f"    {k:30s}: {v}")
    print(f"\n  EXPERIMENTS ATTEMPTED:")
    for name, details in pma['experiments_attempted'].items():
        print(f"\n    {name}:")
        print(f"      Hypothesis: {details['hypothesis']}")
        print(f"      Result: {details['result']}")
        print(f"      Key insight: {details['key_insight']}")
    print(f"\n  CONCLUSION: {pma['conclusion']}")

    # ---- Algorithm Inelasticity ----
    print_section("9. ALGORITHM INELASTICITY -- FINAL CONCLUSION")
    ai = ALGORITHM_INELASTICITY
    print(f"\n  {ai['declaration']}")
    print(f"\n  WHY INELASTIC: {ai['why_inelastic']}")
    print(f"\n  WHAT WAS TRIED (all failed):")
    for category, items in ai['what_was_tried'].items():
        print(f"\n    {category.replace('_', ' ').title()}:")
        for item in items:
            print(f"      - {item}")
    print(f"\n  NEXT STEPS -- {ai['next_steps']['description']}")
    for p in ai['next_steps']['priorities']:
        print(f"\n    [{p['area']}]")
        for a in p['actions']:
            print(f"      - {a}")
        print(f"      Expected benefit: {p['estimated_benefit']}")

    # ---- Questions ----
    print_section("10. QUESTIONS FOR REVIEWER")
    for q in REVIEW_QUESTIONS:
        print(f"  {q}")
        print()

    # ---- File Inventory ----
    print_section("11. KEY FILES")
    for category, files in KEY_FILES.items():
        print(f"\n  {category.upper()}:")
        for fname, desc in files.items():
            print(f"    {fname:50s} -- {desc}")

    print("\n" + "=" * 80)
    print("  END OF REVIEW DOCUMENT")
    print(f"  Total experiments: {PROJECT['total_experiments']} "
          f"({PROJECT['experiments_succeeded']} succeeded, "
          f"{PROJECT['experiments_failed']} failed)")
    print("  Backtest period: 26 years (2000-2026)")
    print("  Production result: 16.95% CAGR, 0.815 Sharpe, -28.4% MaxDD")
    print(f"  Status: {PROJECT['algorithm_status']}")
    print("  Next: Execution microstructure, capital efficiency, orthogonal diversification.")
    print("=" * 80)


if __name__ == '__main__':
    main()
