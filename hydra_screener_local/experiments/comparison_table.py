#!/usr/bin/env python
"""
Simple comparison table: HYDRA Screener parameters vs common industry implementations.
Run this to print a clean Markdown table.
"""

import pandas as pd

data = [
    ["Momentum Horizon (core)", "90 days return / 63-day vol (risk-adjusted)", "6m + 12m price mom (excl. recent 1m)", "12m total return excl. last month (12-1)", "Common: 3-12 months, often 6-12m or 12-1. Risk-adjusted (ret/vol) frequent in research/ETFs."],
    ["Risk Adjustment", "Yes (return / 63d vol)", "Yes: / 3-year weekly vol std dev", "No (pure price in basic index); discussed in research", "Very common enhancement for Sharpe and crash reduction (MSCI, many papers)."],
    ["Short-term / Acceleration", "10-day ret + 20-day high proximity (max 3% dist, 0.35 boost)", "None (pure 6/12m)", "None", "Practitioner/active systems sometimes add short-term 'fresh momentum' or acceleration filters; not standard in passive indexes."],
    ["Volume Confirmation / Strict Filter", "vol_ratio >1.5 (dynamic, min 1.0); Strict: ret_5d>15% + near highs + vol surge (bonus ~18%)", "None (price-only)", "None", "Common in active momentum trading/breakout systems (1.5x-5x volume surges for conviction). Rare in major factor indexes. Academic support for momentum + high vol combos."],
    ["Regime Detection", "Rich: SMA200 trend + vol ratio + mom + dd velocity + breadth proxy. Thresholds strong 0.62 / weak 0.38", "Minimal / static construction", "Minimal / static", "Common in institutional overlays, tactical allocation, and multi-strategy funds. Regime-switching models widely used for dynamic factor/strategy weighting."],
    ["Dynamic Weighting / Special Modes (Pillar Multipliers)", "Yes: 4 Special Modes (Crisis, Recovery, Strong Broad Mom, High Vol Defensive) + regime-based multipliers (e.g. COMPASS +18% in strong broad; Catalyst/EFA down to 0.6). Base 14 recs * aggression * COMPASS mult (clamped 6-28)", "Static selection/weighting (momentum score * mkt cap + caps)", "Static (top 33% mkt cap weighted)", "Very common in professional multi-strategy / overlay approaches (regime-conditioned allocation across premia like momentum vs mean-reversion). Matches 'factor momentum + regime overlay' research."],
    ["Sector / Concentration Control", "Max 8 per coarse bucket + 15% soft penalty on composite; re-rank. Explicit buckets (Semis, Software/Cyber, etc.)", "Issuer cap 5%; some diversification rules; sector balance in some variants", "Market cap weighted (no hard sector cap)", "Standard risk management. Issuer caps (5%) and sector neutralization/balance very common in factor ETFs and long-short products to avoid crowding. Your bucket limit is a practical active screener version."],
    ["Rebalance / Update Frequency", "Daily candidate generation (for 5-day cycle system)", "Semi-annual (May/Nov) + ad-hoc buffers", "Quarterly", "Indexes: quarterly/semi. Screeners for active use: daily/weekly common."],
    ["Selection / # Holdings", "Dynamic 6-28 recommended (top by composite after adjustments); full universe ~500 filtered", "Fixed ~125 (US large/mid example); top by score", "Top 33% of universe (e.g. 333 from top 1000)", "Varies: indexes often fixed or %; active screeners dynamic."],
    ["Min Price / Liquidity Filter", "Min price $5; volume filter disabled (0)", "Liquidity screens in parent index", "Liquidity screens", "Standard. Your min price is conservative; volume often required in practice (you have it in Strict but disabled in base filters)."],
]

df = pd.DataFrame(data, columns=[
    "Parameter / Feature",
    "Your HYDRA Screener",
    "MSCI Momentum (MTUM / iShares)",
    "AQR Momentum Indices",
    "Common Industry / Practitioner Notes"
])

print("## HYDRA Screener vs Industry Implementations - Simple Comparison Table\n")

# Manual Markdown table for compatibility (no tabulate needed)
headers = df.columns.tolist()
print("| " + " | ".join(headers) + " |")
print("| " + " | ".join(["---"] * len(headers)) + " |")
for _, row in df.iterrows():
    row_str = [str(x).replace("|", "-") for x in row]
    print("| " + " | ".join(row_str) + " |")

print("\nNotes:")
print("- Your screener is a *daily candidate generator* for a multi-strategy system (not a passive index), so it has more tactical/dynamic elements (shorter horizons, volume strict, explicit sector caps, regime multipliers).")
print("- Passive indexes (MSCI, AQR) prioritize transparency, capacity, low turnover.")
print("- Active quant / trading systems align more with your volume confirmation, short-term boosts, and concentration controls.")
print("- Regime/dynamic pillars are a pro strength, matching institutional overlays.")