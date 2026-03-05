"""
COMPASS Underperformance Analysis: 2010, 2012, 2013, 2014
Analyzes why COMPASS lagged the S&P 500 in these bull market years.
"""

import pandas as pd
import numpy as np

# ── Load data ─────────────────────────────────────────────────────────────────
daily = pd.read_csv("backtests/v84_overlay_daily.csv", parse_dates=["date"])
trades = pd.read_csv("backtests/v84_overlay_trades.csv", parse_dates=["entry_date", "exit_date"])
spy = pd.read_csv("backtests/spy_benchmark.csv", parse_dates=["date"])

daily = daily.sort_values("date").reset_index(drop=True)
spy = spy.sort_values("date").reset_index(drop=True)

# Boolean cleanup
daily["in_protection"] = daily["in_protection"].astype(str).str.strip().str.lower() == "true"
daily["risk_on"] = daily["risk_on"].astype(str).str.strip().str.lower() == "true"

# Merge SPY into daily for side-by-side comparison
spy_merged = spy.rename(columns={"close": "spy_close"})
daily = daily.merge(spy_merged, on="date", how="left")

# Daily SPY returns
daily["spy_ret"] = daily["spy_close"].pct_change()

# Daily COMPASS returns
daily["compass_ret"] = daily["value"].pct_change()

# ── Helper functions ──────────────────────────────────────────────────────────

def year_slice(df, year):
    return df[df["date"].dt.year == year].copy()

def monthly_returns(df_year):
    """Compute monthly returns for COMPASS and SPY from the daily slice."""
    df = df_year.copy()
    df["month"] = df["date"].dt.month

    results = []
    for m in range(1, 13):
        m_data = df[df["month"] == m]
        if m_data.empty:
            continue
        # Compound return = last_value / first_value - 1
        comp_ret = m_data["value"].iloc[-1] / m_data["value"].iloc[0] - 1
        spy_ret  = m_data["spy_close"].iloc[-1] / m_data["spy_close"].iloc[0] - 1
        results.append({
            "month": pd.Timestamp(f"{df['date'].dt.year.iloc[0]}-{m:02d}-01").strftime("%b"),
            "compass": comp_ret * 100,
            "spy": spy_ret * 100,
            "gap": (comp_ret - spy_ret) * 100
        })
    return pd.DataFrame(results)

def protection_pct(df_year):
    return df_year["in_protection"].mean() * 100

def risk_on_pct(df_year):
    return df_year["risk_on"].mean() * 100

def avg_positions(df_year):
    return df_year["positions"].mean()

def regime_distribution(df_year):
    return df_year["regime_score"].describe()

def overlay_stats(df_year):
    cols = ["overlay_scalar", "damped_scalar", "bso_scalar", "m2_scalar", "fomc_scalar", "fed_emergency"]
    return df_year[cols].describe()

def year_trades(trades_df, year):
    mask = (trades_df["entry_date"].dt.year == year) | (trades_df["exit_date"].dt.year == year)
    return trades_df[mask].copy()

def trade_stats(t):
    if t.empty:
        return {}
    win_rate = (t["return"] > 0).mean() * 100
    avg_ret  = t["return"].mean() * 100
    top5_win = t.nlargest(5, "return")[["symbol", "entry_date", "exit_date", "return", "pnl"]]
    top5_los = t.nsmallest(5, "return")[["symbol", "entry_date", "exit_date", "return", "pnl"]]
    return {
        "count": len(t),
        "win_rate": win_rate,
        "avg_return": avg_ret,
        "total_pnl": t["pnl"].sum(),
        "top5_winners": top5_win,
        "top5_losers": top5_los,
    }

def rolling_gap(df_year):
    """Compute cumulative COMPASS vs SPY gap through the year."""
    df = df_year.copy()
    df["cum_compass"] = (1 + df["compass_ret"].fillna(0)).cumprod() - 1
    df["cum_spy"]     = (1 + df["spy_ret"].fillna(0)).cumprod() - 1
    df["gap"]         = df["cum_compass"] - df["cum_spy"]
    return df[["date", "cum_compass", "cum_spy", "gap"]].dropna()

def find_key_divergence_periods(df_year, n=3):
    """Find the n periods (weekly buckets) where COMPASS fell furthest behind SPY."""
    df = df_year.copy().dropna(subset=["compass_ret", "spy_ret"])
    df["daily_gap"] = df["compass_ret"] - df["spy_ret"]
    df["week"] = df["date"].dt.to_period("W")
    weekly = df.groupby("week").agg(
        week_gap=("daily_gap", "sum"),
        avg_positions=("positions", "mean"),
        prot=("in_protection", "mean"),
        risk_on=("risk_on", "mean"),
        avg_overlay=("overlay_scalar", "mean"),
    ).reset_index()
    return weekly.nsmallest(n, "week_gap")

# ── Main analysis per year ────────────────────────────────────────────────────

TARGET_YEARS = {
    2010: {"compass": 7.94,  "spy": 13.14, "gap": -5.20},
    2012: {"compass": 5.48,  "spy": 14.17, "gap": -8.70},
    2013: {"compass": 19.34, "spy": 29.00, "gap": -9.66},
    2014: {"compass": 4.67,  "spy": 14.56, "gap": -9.89},
}

DIVIDER = "=" * 80

for year, benchmarks in TARGET_YEARS.items():
    print(f"\n{DIVIDER}")
    print(f"  YEAR {year}: COMPASS {benchmarks['compass']:+.2f}% vs SPY {benchmarks['spy']:+.2f}%  "
          f"(Gap: {benchmarks['gap']:+.2f}%)")
    print(DIVIDER)

    dy = year_slice(daily, year)
    ty = year_trades(trades, year)

    # ── 1. Position count ─────────────────────────────────────────────────────
    print(f"\n--- 1. POSITION COUNT ---")
    avg_pos = avg_positions(dy)
    print(f"Average daily positions held : {avg_pos:.2f}")
    print(f"Min positions               : {dy['positions'].min():.0f}")
    print(f"Max positions               : {dy['positions'].max():.0f}")
    print(f"Days with 0 positions       : {(dy['positions'] == 0).sum()} ({(dy['positions'] == 0).mean()*100:.1f}%)")
    print(f"Days with <= 2 positions    : {(dy['positions'] <= 2).sum()} ({(dy['positions'] <= 2).mean()*100:.1f}%)")
    print(f"Universe size (avg)         : {dy['universe_size'].mean():.1f}")

    # ── 2. Protection mode ────────────────────────────────────────────────────
    print(f"\n--- 2. PROTECTION MODE ---")
    prot_pct = protection_pct(dy)
    print(f"Time in protection mode     : {prot_pct:.1f}%")
    print(f"Time risk_on=True           : {risk_on_pct(dy):.1f}%")

    # ── 3. Regime score ───────────────────────────────────────────────────────
    print(f"\n--- 3. REGIME SCORE DISTRIBUTION ---")
    rs = dy["regime_score"]
    print(f"Mean: {rs.mean():.3f} | Median: {rs.median():.3f} | Std: {rs.std():.3f}")
    print(f"Min:  {rs.min():.3f} | Max:    {rs.max():.3f}")
    # Quartile breakdown
    bins = [0, 0.25, 0.5, 0.75, 1.01]
    labels = ["0–0.25 (bearish)", "0.25–0.5 (cautious)", "0.5–0.75 (neutral)", "0.75–1.0 (bullish)"]
    counts = pd.cut(rs, bins=bins, labels=labels, right=False).value_counts().sort_index()
    for lbl, cnt in counts.items():
        print(f"  {lbl}: {cnt} days ({cnt/len(dy)*100:.1f}%)")

    # ── 4. Overlay scalars ────────────────────────────────────────────────────
    print(f"\n--- 4. OVERLAY SCALARS ---")
    print(f"overlay_scalar  mean={dy['overlay_scalar'].mean():.3f}  min={dy['overlay_scalar'].min():.3f}  max={dy['overlay_scalar'].max():.3f}")
    print(f"damped_scalar   mean={dy['damped_scalar'].mean():.3f}  min={dy['damped_scalar'].min():.3f}  max={dy['damped_scalar'].max():.3f}")
    print(f"bso_scalar      mean={dy['bso_scalar'].mean():.3f}  min={dy['bso_scalar'].min():.3f}  max={dy['bso_scalar'].max():.3f}")
    print(f"m2_scalar       mean={dy['m2_scalar'].mean():.3f}  min={dy['m2_scalar'].min():.3f}  max={dy['m2_scalar'].max():.3f}")
    print(f"fomc_scalar     mean={dy['fomc_scalar'].mean():.3f}  min={dy['fomc_scalar'].min():.3f}  max={dy['fomc_scalar'].max():.3f}")
    print(f"fed_emergency   mean={dy['fed_emergency'].mean():.3f}")
    # Days where overlay was dampening (< 1.0) vs neutral (1.0)
    damp_days = (dy["overlay_scalar"] < 0.99).sum()
    print(f"Days overlay was dampening  : {damp_days} ({damp_days/len(dy)*100:.1f}%)")
    # Correlation of overlay_scalar with gap
    # We measure this as: on high-SPY days (spy_ret > 0.5%), how much did overlay_scalar drag?
    up_days = dy[dy["spy_ret"] > 0.005]
    if not up_days.empty:
        corr = up_days["overlay_scalar"].corr(up_days["compass_ret"])
        print(f"On SPY up-days (>0.5%), corr(overlay_scalar, compass_ret): {corr:.3f}")

    # ── 5. Trades ─────────────────────────────────────────────────────────────
    print(f"\n--- 5. TRADES ---")
    ts = trade_stats(ty)
    if ts:
        print(f"Total trades     : {ts['count']}")
        print(f"Win rate         : {ts['win_rate']:.1f}%")
        print(f"Avg trade return : {ts['avg_return']:.2f}%")
        print(f"Total PnL        : ${ts['total_pnl']:,.0f}")
        print(f"\nTop 5 Winners:")
        print(ts["top5_winners"].to_string(index=False))
        print(f"\nTop 5 Losers:")
        print(ts["top5_losers"].to_string(index=False))
    else:
        print("No trades found for this year.")

    # ── 6. Monthly return comparison ──────────────────────────────────────────
    print(f"\n--- 6. MONTHLY RETURNS vs SPY ---")
    mr = monthly_returns(dy)
    if not mr.empty:
        print(f"{'Month':<6} {'COMPASS':>8} {'SPY':>8} {'Gap':>8}")
        print("-" * 35)
        for _, row in mr.iterrows():
            flag = " <-- WORST" if row["gap"] == mr["gap"].min() else ""
            print(f"{row['month']:<6} {row['compass']:>7.2f}% {row['spy']:>7.2f}% {row['gap']:>7.2f}%{flag}")
        worst_months = mr.nsmallest(3, "gap")
        print(f"\nWorst 3 months for COMPASS vs SPY: {', '.join(worst_months['month'].tolist())}")

    # ── 7. Key divergence weeks ────────────────────────────────────────────────
    print(f"\n--- 7. WORST WEEKS (COMPASS fell furthest behind SPY) ---")
    worst_weeks = find_key_divergence_periods(dy, n=5)
    print(worst_weeks.to_string(index=False))

    # ── 8. Cumulative gap trajectory ─────────────────────────────────────────
    print(f"\n--- 8. CUMULATIVE GAP TRAJECTORY (quarterly) ---")
    cg = rolling_gap(dy)
    if not cg.empty:
        cg["quarter"] = cg["date"].dt.quarter
        qtr_end = cg.groupby("quarter").last().reset_index()
        print(f"{'Qtr':<5} {'COMPASS':>10} {'SPY':>10} {'Gap':>10}")
        for _, row in qtr_end.iterrows():
            print(f"Q{row['quarter']:<4} {row['cum_compass']*100:>9.2f}% {row['cum_spy']*100:>9.2f}% {row['gap']*100:>9.2f}%")

# ── Cross-year summary ────────────────────────────────────────────────────────
print(f"\n{DIVIDER}")
print("  CROSS-YEAR STRUCTURAL SUMMARY")
print(DIVIDER)

print("\nKey metric comparison across underperforming years:")
print(f"{'Year':<6} {'AvgPos':>8} {'Prot%':>8} {'RiskOn%':>9} {'RegScore':>10} {'OverlayAvg':>12} {'TradeWin%':>11}")
print("-" * 70)

for year in TARGET_YEARS:
    dy = year_slice(daily, year)
    ty = year_trades(trades, year)
    win_rate = (ty["return"] > 0).mean() * 100 if not ty.empty else 0
    print(f"{year:<6} {avg_positions(dy):>8.2f} {protection_pct(dy):>7.1f}% {risk_on_pct(dy):>8.1f}% "
          f"{dy['regime_score'].mean():>10.3f} {dy['overlay_scalar'].mean():>12.3f} {win_rate:>10.1f}%")

# ── vs a "normal" bull year – compare to 2017 ────────────────────────────────
print("\n\nFor reference — 2017 (COMPASS performed well vs SPY):")
dy17 = year_slice(daily, 2017)
ty17 = year_trades(trades, 2017)
wr17 = (ty17["return"] > 0).mean() * 100 if not ty17.empty else 0
print(f"{'2017':<6} {avg_positions(dy17):>8.2f} {protection_pct(dy17):>7.1f}% {risk_on_pct(dy17):>8.1f}% "
      f"{dy17['regime_score'].mean():>10.3f} {dy17['overlay_scalar'].mean():>12.3f} {wr17:>10.1f}%")

# ── Regime score: how often was COMPASS in "low regime" mode? ─────────────────
print("\n\nRegime score breakdown — fraction of days below key thresholds:")
print(f"{'Year':<6} {'<0.3 (very bear)':>17} {'<0.5 (below mid)':>18} {'>=0.7 (bullish)':>17}")
print("-" * 60)
for year in list(TARGET_YEARS.keys()) + [2017]:
    dy = year_slice(daily, year)
    rs = dy["regime_score"]
    lt03  = (rs < 0.3).mean() * 100
    lt05  = (rs < 0.5).mean() * 100
    gte07 = (rs >= 0.7).mean() * 100
    print(f"{year:<6} {lt03:>16.1f}% {lt05:>17.1f}% {gte07:>16.1f}%")

# ── Leverage analysis ─────────────────────────────────────────────────────────
print("\n\nLeverage stats (effective market exposure):")
print(f"{'Year':<6} {'LevMean':>9} {'LevMin':>8} {'LevMax':>8}")
print("-" * 35)
for year in list(TARGET_YEARS.keys()) + [2017]:
    dy = year_slice(daily, year)
    print(f"{year:<6} {dy['leverage'].mean():>9.3f} {dy['leverage'].min():>8.3f} {dy['leverage'].max():>8.3f}")

print("\n\nAnalysis complete.")
