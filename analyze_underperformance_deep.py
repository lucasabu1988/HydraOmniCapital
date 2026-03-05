"""
Deep-dive analysis: structural causes of COMPASS underperformance in bull years.
Focuses on: concentration drag, regime filter mechanics, stock selection vs index.
"""

import pandas as pd
import numpy as np

daily = pd.read_csv("backtests/v84_overlay_daily.csv", parse_dates=["date"])
trades = pd.read_csv("backtests/v84_overlay_trades.csv", parse_dates=["entry_date", "exit_date"])
spy = pd.read_csv("backtests/spy_benchmark.csv", parse_dates=["date"])

daily = daily.sort_values("date").reset_index(drop=True)
spy = spy.sort_values("date").reset_index(drop=True)
daily["in_protection"] = daily["in_protection"].astype(str).str.lower() == "true"
daily["risk_on"] = daily["risk_on"].astype(str).str.lower() == "true"

spy_merged = spy.rename(columns={"close": "spy_close"})
daily = daily.merge(spy_merged, on="date", how="left")
daily["spy_ret"] = daily["spy_close"].pct_change()
daily["compass_ret"] = daily["value"].pct_change()

def yslice(year):
    return daily[daily["date"].dt.year == year].copy()

DIVIDER = "=" * 80

# ── SECTION A: The "5-stock cap" drag on bull market exposure ─────────────────
print(f"\n{DIVIDER}")
print("SECTION A: CONCENTRATION vs BROAD MARKET PARTICIPATION (max 5 positions)")
print(DIVIDER)

# If COMPASS runs at most 5 positions from a 40-stock universe,
# on big SPY up-days it can easily miss the leaders.
# Measure: on days SPY > 1%, how did COMPASS perform relative?

for year in [2010, 2012, 2013, 2014]:
    dy = yslice(year)
    big_up = dy[dy["spy_ret"] > 0.01]
    big_dn = dy[dy["spy_ret"] < -0.01]
    flat   = dy[(dy["spy_ret"] >= -0.005) & (dy["spy_ret"] <= 0.005)]

    def avg_gap(subset):
        if subset.empty:
            return float("nan")
        return (subset["compass_ret"] - subset["spy_ret"]).mean() * 100

    print(f"\n{year}:")
    print(f"  SPY >1% days  ({len(big_up):3d} days): avg daily gap = {avg_gap(big_up):+.3f}%  "
          f"(avg positions: {big_up['positions'].mean():.2f})")
    print(f"  SPY <-1% days ({len(big_dn):3d} days): avg daily gap = {avg_gap(big_dn):+.3f}%  "
          f"(avg positions: {big_dn['positions'].mean():.2f})")
    print(f"  Flat days     ({len(flat):3d} days): avg daily gap = {avg_gap(flat):+.3f}%")

    # How much of the annual gap came from big up-days?
    total_gap_bps = (dy["compass_ret"] - dy["spy_ret"]).sum() * 100
    up_gap_bps    = (big_up["compass_ret"] - big_up["spy_ret"]).sum() * 100
    dn_gap_bps    = (big_dn["compass_ret"] - big_dn["spy_ret"]).sum() * 100
    flat_gap_bps  = (flat["compass_ret"] - flat["spy_ret"]).sum() * 100
    print(f"  Cumul gap breakdown: up-days {up_gap_bps:+.2f}% | dn-days {dn_gap_bps:+.2f}% | "
          f"flat-days {flat_gap_bps:+.2f}%  (total: {total_gap_bps:+.2f}%)")

# ── SECTION B: Risk_on=False days — what did this cost? ───────────────────────
print(f"\n{DIVIDER}")
print("SECTION B: COST OF risk_on=FALSE DAYS (regime filter disengaging from market)")
print(DIVIDER)

# When risk_on=False, COMPASS likely holds fewer/no long positions
# On these days, if SPY is rising, that's opportunity cost.

for year in [2010, 2012, 2013, 2014]:
    dy = yslice(year)
    risk_off = dy[~dy["risk_on"]]
    risk_on  = dy[dy["risk_on"]]

    risk_off_spy_cumret = (1 + risk_off["spy_ret"].fillna(0)).prod() - 1
    risk_on_spy_cumret  = (1 + risk_on["spy_ret"].fillna(0)).prod() - 1

    risk_off_compass = (1 + risk_off["compass_ret"].fillna(0)).prod() - 1
    risk_on_compass  = (1 + risk_on["compass_ret"].fillna(0)).prod() - 1

    n_off = len(risk_off)
    n_on  = len(risk_on)

    print(f"\n{year}: risk_on=False on {n_off} days ({n_off/len(dy)*100:.1f}%)")
    if n_off > 0:
        print(f"  During risk_off days — SPY gained: {risk_off_spy_cumret*100:+.2f}%")
        print(f"  During risk_off days — COMPASS returned: {risk_off_compass*100:+.2f}%")
        print(f"  Opportunity cost of risk_off days: {(risk_off_compass - risk_off_spy_cumret)*100:+.2f}%")
        print(f"  Avg positions during risk_off: {risk_off['positions'].mean():.2f}")
    print(f"  During risk_on days — SPY gained: {risk_on_spy_cumret*100:+.2f}%")
    print(f"  During risk_on days — COMPASS returned: {risk_on_compass*100:+.2f}%")
    print(f"  Avg positions during risk_on: {risk_on['positions'].mean():.2f}")

# ── SECTION C: 2010 M2 scalar drag — specific impact ─────────────────────────
print(f"\n{DIVIDER}")
print("SECTION C: 2010 OVERLAY SCALAR DRAG — M2 Scalar Analysis")
print(DIVIDER)

dy10 = yslice(2010)
# m2_scalar < 1.0 days
m2_dragging = dy10[dy10["m2_scalar"] < 0.99]
m2_neutral  = dy10[dy10["m2_scalar"] >= 0.99]

print(f"\n2010: M2 scalar < 1.0 on {len(m2_dragging)} days ({len(m2_dragging)/len(dy10)*100:.1f}%)")
print(f"  M2 scalar range: {dy10['m2_scalar'].min():.3f} to {dy10['m2_scalar'].max():.3f}")
print(f"  When M2 dragging (avg scalar={m2_dragging['m2_scalar'].mean():.3f}):")
print(f"    SPY cumret: {((1+m2_dragging['spy_ret'].fillna(0)).prod()-1)*100:+.2f}%")
print(f"    COMPASS cumret: {((1+m2_dragging['compass_ret'].fillna(0)).prod()-1)*100:+.2f}%")
print(f"  When M2 neutral:")
print(f"    SPY cumret: {((1+m2_neutral['spy_ret'].fillna(0)).prod()-1)*100:+.2f}%")
print(f"    COMPASS cumret: {((1+m2_neutral['compass_ret'].fillna(0)).prod()-1)*100:+.2f}%")

# Show the period(s) where m2_scalar was dampened
if not m2_dragging.empty:
    print(f"\n  M2 dampening periods in 2010:")
    # Find consecutive runs
    dy10_sorted = m2_dragging.sort_values("date")
    dy10_sorted["prev_date"] = dy10_sorted["date"].shift(1)
    dy10_sorted["gap"] = (dy10_sorted["date"] - dy10_sorted["prev_date"]).dt.days
    dy10_sorted["new_run"] = (dy10_sorted["gap"] > 5) | dy10_sorted["gap"].isna()
    dy10_sorted["run_id"] = dy10_sorted["new_run"].cumsum()
    for run_id, grp in dy10_sorted.groupby("run_id"):
        print(f"    {grp['date'].iloc[0].date()} to {grp['date'].iloc[-1].date()} "
              f"({len(grp)} days, avg scalar={grp['m2_scalar'].mean():.3f})")

# ── SECTION D: 2010 "Jan & Feb" extreme week — deep dive ─────────────────────
print(f"\n{DIVIDER}")
print("SECTION D: 2010 WORST WEEK — Jan 4-10 (overlay=0.4, full risk_on, SPY rallied hard)")
print(DIVIDER)

jan10_week = dy10[(dy10["date"] >= "2010-01-04") & (dy10["date"] <= "2010-01-10")]
print(jan10_week[["date","value","positions","regime_score","overlay_scalar",
                    "m2_scalar","risk_on","compass_ret","spy_ret"]].to_string(index=False))

# ── SECTION E: Position count — was 5 the binding constraint? ─────────────────
print(f"\n{DIVIDER}")
print("SECTION E: POSITION COUNT ANALYSIS — was the cap binding?")
print(DIVIDER)

for year in [2010, 2012, 2013, 2014]:
    dy = yslice(year)
    print(f"\n{year}:")
    dist = dy["positions"].value_counts().sort_index()
    for pos, cnt in dist.items():
        bar = "#" * int(cnt / len(dy) * 50)
        print(f"  {int(pos)} positions: {cnt:3d} days ({cnt/len(dy)*100:5.1f}%) {bar}")
    # Efficiency: on max-position days vs constrained days
    max_pos = dy["positions"].max()
    at_max  = dy[dy["positions"] == max_pos]
    below   = dy[dy["positions"] < max_pos]
    if not at_max.empty and not below.empty:
        gap_at_max  = (at_max["compass_ret"] - at_max["spy_ret"]).mean() * 100
        gap_below   = (below["compass_ret"] - below["spy_ret"]).mean() * 100
        spy_at_max  = at_max["spy_ret"].mean() * 100
        spy_below   = below["spy_ret"].mean() * 100
        print(f"  At max ({int(max_pos)}) positions: avg daily gap vs SPY = {gap_at_max:+.3f}% "
              f"(SPY avg={spy_at_max:+.3f}%)")
        print(f"  Below max positions:       avg daily gap vs SPY = {gap_below:+.3f}% "
              f"(SPY avg={spy_below:+.3f}%)")

# ── SECTION F: Trade holding period & timing — was COMPASS churning in bull? ──
print(f"\n{DIVIDER}")
print("SECTION F: TRADE HOLDING PERIOD & TURNOVER — were exits too early?")
print(DIVIDER)

for year in [2010, 2012, 2013, 2014, 2017]:
    ty = trades[(trades["entry_date"].dt.year == year) | (trades["exit_date"].dt.year == year)].copy()
    # filter to trades that started in the year
    ty = trades[trades["entry_date"].dt.year == year].copy()
    if ty.empty:
        continue
    ty["hold_days"] = (ty["exit_date"] - ty["entry_date"]).dt.days
    print(f"\n{year}:")
    print(f"  Trades: {len(ty)}  |  Avg hold: {ty['hold_days'].mean():.1f} days  "
          f"|  Med hold: {ty['hold_days'].median():.0f} days")
    print(f"  Hold < 5 days: {(ty['hold_days'] < 5).sum()} ({(ty['hold_days'] < 5).mean()*100:.1f}%)")
    print(f"  Hold 5-14 days: {((ty['hold_days'] >= 5) & (ty['hold_days'] < 15)).sum()}")
    print(f"  Hold >= 15 days: {(ty['hold_days'] >= 15).sum()}")
    # Exit reason breakdown
    print(f"  Exit reasons: {ty['exit_reason'].value_counts().to_dict()}")
    # Avg return by exit reason
    for reason, grp in ty.groupby("exit_reason"):
        print(f"    {reason}: {len(grp)} trades, avg_ret={grp['return'].mean()*100:+.3f}%")

# ── SECTION G: 2013 — structural underinvestment? No overlay, good regime ──────
print(f"\n{DIVIDER}")
print("SECTION G: 2013 DEEP DIVE — why -9.66% gap with no overlay drag and strong regime?")
print(DIVIDER)

dy13 = yslice(2013)
print(f"2013 regime_score >=0.7 (bullish) on {(dy13['regime_score']>=0.7).mean()*100:.1f}% of days")
print(f"Overlay scalar = 1.0 on ALL days (no dampening)")
print(f"Avg positions: {dy13['positions'].mean():.2f} (max=5)")

# The core issue: 5 stocks from a 40-name universe in a 500-stock bull market
# COMPASS was +19% but SPY +29% — that's a 10% gap with full deployment
# This means stock selection was worse than the index

# Let's check if risk_off days were the issue
risk_off_13 = dy13[~dy13["risk_on"]]
print(f"\nrisk_on=False days: {len(risk_off_13)} ({len(risk_off_13)/len(dy13)*100:.1f}%)")
print(f"  SPY return during risk_off days: {((1+risk_off_13['spy_ret'].fillna(0)).prod()-1)*100:+.2f}%")
print(f"  COMPASS return during risk_off days: {((1+risk_off_13['compass_ret'].fillna(0)).prod()-1)*100:+.2f}%")

# Q4 2013 was the biggest gap quarter (-10.28%)
q4_13 = dy13[dy13["date"].dt.quarter == 4]
print(f"\nQ4 2013 deep-dive:")
print(f"  COMPASS: {(q4_13['value'].iloc[-1]/q4_13['value'].iloc[0]-1)*100:+.2f}%")
print(f"  SPY:     {(q4_13['spy_close'].iloc[-1]/q4_13['spy_close'].iloc[0]-1)*100:+.2f}%")
print(f"  risk_off days in Q4: {(~q4_13['risk_on']).sum()} ({(~q4_13['risk_on']).mean()*100:.1f}%)")

# Monthly detail for Q4 2013
for month in [10, 11, 12]:
    m = dy13[dy13["date"].dt.month == month]
    print(f"  {pd.Timestamp(2013, month, 1).strftime('%b')}: COMPASS {(m['value'].iloc[-1]/m['value'].iloc[0]-1)*100:+.2f}% "
          f"vs SPY {(m['spy_close'].iloc[-1]/m['spy_close'].iloc[0]-1)*100:+.2f}%  "
          f"| risk_off: {(~m['risk_on']).mean()*100:.0f}% | pos: {m['positions'].mean():.2f}")

# ── SECTION H: 2014 — Feb-Mar collapse and Oct miss ──────────────────────────
print(f"\n{DIVIDER}")
print("SECTION H: 2014 DEEP DIVE — Feb (-6.50% gap), Mar (-5.38% gap), Oct (-4.39% gap)")
print(DIVIDER)

dy14 = yslice(2014)

for month, mname in [(2, "Feb"), (3, "Mar"), (10, "Oct")]:
    m = dy14[dy14["date"].dt.month == month]
    print(f"\n{mname} 2014:")
    print(f"  COMPASS: {(m['value'].iloc[-1]/m['value'].iloc[0]-1)*100:+.2f}%  "
          f"SPY: {(m['spy_close'].iloc[-1]/m['spy_close'].iloc[0]-1)*100:+.2f}%")
    print(f"  risk_off days: {(~m['risk_on']).sum()} ({(~m['risk_on']).mean()*100:.1f}%)")
    print(f"  in_protection days: {m['in_protection'].sum()}")
    print(f"  avg positions: {m['positions'].mean():.2f}")
    print(f"  regime_score: mean={m['regime_score'].mean():.3f}")
    # Week-by-week within month
    m["week"] = m["date"].dt.isocalendar().week
    for wk, wdata in m.groupby("week"):
        c_ret = (wdata["compass_ret"].fillna(0)).sum() * 100
        s_ret = (wdata["spy_ret"].fillna(0)).sum() * 100
        pos   = wdata["positions"].mean()
        print(f"    Week {wk}: COMPASS {c_ret:+.2f}% vs SPY {s_ret:+.2f}%  pos={pos:.1f}  "
              f"risk_on={wdata['risk_on'].mean():.1%}")

# Oct 2014: SPY crashed then rallied
oct14 = dy14[dy14["date"].dt.month == 10]
print(f"\nOct 2014 mid-month detail:")
first_half = oct14[oct14["date"].dt.day <= 15]
second_half = oct14[oct14["date"].dt.day > 15]
print(f"  Oct 1-15: COMPASS {(first_half['compass_ret'].fillna(0)).sum()*100:+.2f}% "
      f"vs SPY {(first_half['spy_ret'].fillna(0)).sum()*100:+.2f}%  "
      f"pos={first_half['positions'].mean():.2f}  risk_on={first_half['risk_on'].mean():.1%}")
print(f"  Oct 16-31: COMPASS {(second_half['compass_ret'].fillna(0)).sum()*100:+.2f}% "
      f"vs SPY {(second_half['spy_ret'].fillna(0)).sum()*100:+.2f}%  "
      f"pos={second_half['positions'].mean():.2f}  risk_on={second_half['risk_on'].mean():.1%}")

# ── SECTION I: 2012 H1 — massive -10.46% gap by end of Q2 ─────────────────────
print(f"\n{DIVIDER}")
print("SECTION I: 2012 DEEP DIVE — Q1+Q2 built -10.46% gap (never recovered)")
print(DIVIDER)

dy12 = yslice(2012)
for q in [1, 2, 3, 4]:
    qdata = dy12[dy12["date"].dt.quarter == q]
    print(f"Q{q} 2012: COMPASS {(qdata['value'].iloc[-1]/qdata['value'].iloc[0]-1)*100:+.2f}% "
          f"vs SPY {(qdata['spy_close'].iloc[-1]/qdata['spy_close'].iloc[0]-1)*100:+.2f}%  "
          f"| prot_days: {qdata['in_protection'].sum()}  risk_off: {(~qdata['risk_on']).sum()}  "
          f"overlay: {qdata['overlay_scalar'].mean():.3f}")

print()
# Month-by-month H1 2012
for month in range(1, 7):
    m = dy12[dy12["date"].dt.month == month]
    risk_off_pct = (~m["risk_on"]).mean() * 100
    prot_pct = m["in_protection"].mean() * 100
    print(f"  {pd.Timestamp(2012, month, 1).strftime('%b')}: COMPASS {(m['value'].iloc[-1]/m['value'].iloc[0]-1)*100:+.2f}% "
          f"vs SPY {(m['spy_close'].iloc[-1]/m['spy_close'].iloc[0]-1)*100:+.2f}%  "
          f"risk_off={risk_off_pct:.0f}%  prot={prot_pct:.0f}%  pos={m['positions'].mean():.2f}  "
          f"overlay={m['overlay_scalar'].mean():.3f}")

# ── SECTION J: Counterfactual — pure index return if COMPASS held SPY ─────────
print(f"\n{DIVIDER}")
print("SECTION J: ATTRIBUTION SUMMARY — Where did each year's gap come from?")
print(DIVIDER)

for year in [2010, 2012, 2013, 2014]:
    dy = yslice(year)
    print(f"\n{year} Attribution:")

    # 1. Days where risk_on=False — COMPASS missed market gains
    risk_off = dy[~dy["risk_on"]]
    risk_off_opp_cost = 0.0
    if not risk_off.empty:
        spy_gain_while_off = (1 + risk_off["spy_ret"].fillna(0)).prod() - 1
        compass_gain_while_off = (1 + risk_off["compass_ret"].fillna(0)).prod() - 1
        risk_off_opp_cost = (compass_gain_while_off - spy_gain_while_off) * 100
        print(f"  [A] risk_off opportunity cost: {risk_off_opp_cost:+.2f}% "
              f"({len(risk_off)} days, SPY gained {spy_gain_while_off*100:+.2f}% during those days)")

    # 2. Overlay scalar drag
    drag_days = dy[dy["overlay_scalar"] < 0.99]
    overlay_drag = 0.0
    if not drag_days.empty:
        # On big SPY days where overlay was dampening, estimate lost exposure
        spy_on_drag_days = (1 + drag_days["spy_ret"].fillna(0)).prod() - 1
        compass_on_drag_days = (1 + drag_days["compass_ret"].fillna(0)).prod() - 1
        overlay_drag = (compass_on_drag_days - spy_on_drag_days) * 100
        print(f"  [B] Overlay dampening impact: {overlay_drag:+.2f}% "
              f"({len(drag_days)} days, avg scalar={drag_days['overlay_scalar'].mean():.3f})")
    else:
        print(f"  [B] Overlay dampening impact: 0.0% (no dampening this year)")

    # 3. Stock selection — on risk_on days with full overlay, how did COMPASS do vs SPY?
    on_full = dy[dy["risk_on"] & (dy["overlay_scalar"] >= 0.99)]
    if not on_full.empty:
        compass_sel = (1 + on_full["compass_ret"].fillna(0)).prod() - 1
        spy_sel     = (1 + on_full["spy_ret"].fillna(0)).prod() - 1
        selection_effect = (compass_sel - spy_sel) * 100
        print(f"  [C] Stock selection effect (risk_on, no overlay drag): {selection_effect:+.2f}% "
              f"({len(on_full)} days)")

    total_measured = risk_off_opp_cost + overlay_drag
    known_gaps = {2010: -5.20, 2012: -8.70, 2013: -9.66, 2014: -9.89}
    print(f"  --- Measured sources sum: {total_measured:+.2f}% (total known gap: ~{known_gaps[year]:+.2f}%)")

print("\nDone.")
