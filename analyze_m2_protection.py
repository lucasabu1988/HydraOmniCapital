"""
Full analysis of M2 scalar and protection/regime behavior across the entire backtest.
"""

import pandas as pd
import numpy as np

# -- Load data ------------------------------------------------------------------
df = pd.read_csv("C:/Users/caslu/Desktop/NuevoProyecto/backtests/v84_overlay_daily.csv",
                 parse_dates=["date"])
df = df.sort_values("date").reset_index(drop=True)

spy = pd.read_csv("C:/Users/caslu/Desktop/NuevoProyecto/backtests/spy_benchmark.csv",
                  parse_dates=["date"])
spy = spy.sort_values("date").reset_index(drop=True)
spy["spy_ret"] = spy["close"].pct_change()

# Merge SPY into main df
df = df.merge(spy[["date", "close", "spy_ret"]], on="date", how="left")
df.rename(columns={"close": "spy_close"}, inplace=True)

# Ensure boolean columns
df["in_protection"] = df["in_protection"].astype(str).str.strip().str.lower().isin(["true", "1"])
df["risk_on"] = df["risk_on"].astype(str).str.strip().str.lower().isin(["true", "1"])

# ══════════════════════════════════════════════════════════════════════════════
# Helper: extract contiguous episodes where condition is True
# ══════════════════════════════════════════════════════════════════════════════

def find_episodes(series, condition_func=None):
    """
    Find contiguous episodes where condition_func(series) is True.
    Returns list of (start_idx, end_idx) tuples (inclusive).
    """
    if condition_func is not None:
        mask = condition_func(series)
    else:
        mask = series.astype(bool)

    episodes = []
    in_ep = False
    start = None
    for i, val in enumerate(mask):
        if val and not in_ep:
            in_ep = True
            start = i
        elif not val and in_ep:
            in_ep = False
            episodes.append((start, i - 1))
    if in_ep:
        episodes.append((start, len(mask) - 1))
    return episodes


SEP = "=" * 80

# ══════════════════════════════════════════════════════════════════════════════
# 1. M2 SCALAR EPISODES (m2_scalar < 1.0)
# ══════════════════════════════════════════════════════════════════════════════
print(SEP)
print("ANALYSIS 1: ALL EPISODES WHERE m2_scalar < 1.0")
print(SEP)

episodes_m2 = find_episodes(df["m2_scalar"], lambda s: s < 1.0)
print(f"Total episodes found: {len(episodes_m2)}\n")

print(f"{'#':<4} {'Start':^12} {'End':^12} {'Days':^6} {'Min M2':^10} {'SPY Start':^10} {'SPY End':^10} {'SPY Ret':^10}")
print("-" * 80)
for n, (s, e) in enumerate(episodes_m2, 1):
    sub = df.iloc[s:e+1]
    start_date = sub["date"].iloc[0].date()
    end_date   = sub["date"].iloc[-1].date()
    duration   = (sub["date"].iloc[-1] - sub["date"].iloc[0]).days + 1
    min_m2     = sub["m2_scalar"].min()
    spy_start  = sub["spy_close"].iloc[0]
    spy_end    = sub["spy_close"].iloc[-1]
    # Avoid NaN
    if pd.notna(spy_start) and pd.notna(spy_end) and spy_start != 0:
        spy_ret = (spy_end / spy_start - 1) * 100
        spy_ret_str = f"{spy_ret:+.1f}%"
    else:
        spy_ret_str = "N/A"
    spy_start_str = f"{spy_start:.2f}" if pd.notna(spy_start) else "N/A"
    spy_end_str   = f"{spy_end:.2f}"   if pd.notna(spy_end)   else "N/A"
    print(f"{n:<4} {str(start_date):^12} {str(end_date):^12} {duration:^6} {min_m2:^10.3f} "
          f"{spy_start_str:^10} {spy_end_str:^10} {spy_ret_str:^10}")

# ══════════════════════════════════════════════════════════════════════════════
# 2. M2 AROUND 2010 — WEEKLY FROM 2009-06 TO 2010-12
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("ANALYSIS 2: m2_scalar WEEKLY — 2009-06-01 to 2010-12-31")
print(SEP)

mask_2010 = (df["date"] >= "2009-06-01") & (df["date"] <= "2010-12-31")
sub2010 = df[mask_2010].copy()

# Resample to weekly (Friday end-of-week)
sub2010 = sub2010.set_index("date")
weekly = sub2010["m2_scalar"].resample("W-FRI").last().dropna()

print(f"\n{'Week Ending':^14} {'m2_scalar':^12} {'Status':^15}")
print("-" * 45)
for wdate, m2val in weekly.items():
    status = "BELOW 1.0" if m2val < 1.0 else "at 1.0"
    marker = " <--" if m2val < 1.0 else ""
    print(f"  {str(wdate.date()):^14} {m2val:^12.4f} {status:^15}{marker}")

# ══════════════════════════════════════════════════════════════════════════════
# 3. PROTECTION MODE EPISODES
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("ANALYSIS 3: ALL PROTECTION MODE EPISODES (in_protection = True)")
print(SEP)

episodes_prot = find_episodes(df["in_protection"])
print(f"Total protection episodes: {len(episodes_prot)}\n")

print(f"{'#':<4} {'Start':^12} {'End':^12} {'Days':^6} {'MaxDD%':^10} {'SPY Ret':^10} {'Positions':^12}")
print("-" * 80)
for n, (s, e) in enumerate(episodes_prot, 1):
    sub = df.iloc[s:e+1]
    start_date = sub["date"].iloc[0].date()
    end_date   = sub["date"].iloc[-1].date()
    duration   = (sub["date"].iloc[-1] - sub["date"].iloc[0]).days + 1
    max_dd     = sub["drawdown"].min() * 100  # drawdown is likely negative fraction
    spy_s      = sub["spy_close"].iloc[0]
    spy_e      = sub["spy_close"].iloc[-1]
    spy_ret    = (spy_e / spy_s - 1) * 100 if pd.notna(spy_s) and pd.notna(spy_e) and spy_s != 0 else float("nan")
    avg_pos    = sub["positions"].mean()
    spy_ret_str = f"{spy_ret:+.1f}%" if not np.isnan(spy_ret) else "N/A"
    print(f"{n:<4} {str(start_date):^12} {str(end_date):^12} {duration:^6} {max_dd:^10.2f} "
          f"{spy_ret_str:^10} {avg_pos:^12.1f}")

# ══════════════════════════════════════════════════════════════════════════════
# 4. REGIME RECOVERY SPEED
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("ANALYSIS 4: REGIME RECOVERY SPEED — days from protection END to risk_on=True")
print("            and days from SPY trough to COMPASS returning to full positions (5)")
print(SEP)

print(f"\n{'#':<4} {'Prot End':^12} {'risk_on Date':^14} {'->risk_on':^10} "
      f"{'SPY Trough':^12} {'Pos=5 Date':^14} {'->Full Pos':^11}")
print("-" * 90)

for n, (s, e) in enumerate(episodes_prot, 1):
    sub = df.iloc[s:e+1]
    prot_end_date = sub["date"].iloc[-1]

    # Look ahead window: up to 252 trading days after protection ends
    lookahead = df[df["date"] > prot_end_date].head(252)

    # Days from protection end until risk_on=True
    risk_on_dates = lookahead[lookahead["risk_on"] == True]["date"]
    if len(risk_on_dates) > 0:
        first_risk_on = risk_on_dates.iloc[0]
        days_to_risk_on = (first_risk_on - prot_end_date).days
        risk_on_str = str(first_risk_on.date())
    else:
        days_to_risk_on = None
        risk_on_str = "Never"

    # SPY trough during the episode (look from 10 days before protection start)
    lookback_start = max(0, s - 10)
    lookback_end   = min(len(df) - 1, e + 60)
    sub_trough = df.iloc[lookback_start:lookback_end+1]
    spy_trough_idx = sub_trough["spy_close"].idxmin()
    spy_trough_date = df.loc[spy_trough_idx, "date"]

    # Days from SPY trough until positions reach 5
    lookahead_pos = df[df["date"] > spy_trough_date].head(252)
    full_pos_dates = lookahead_pos[lookahead_pos["positions"] >= 5]["date"]
    if len(full_pos_dates) > 0:
        first_full_pos = full_pos_dates.iloc[0]
        days_to_full_pos = (first_full_pos - spy_trough_date).days
        full_pos_str = str(first_full_pos.date())
    else:
        days_to_full_pos = None
        full_pos_str = "Never (in window)"

    # Format
    prot_end_str = str(prot_end_date.date())
    spy_trough_str = str(spy_trough_date.date())
    days_risk_str = str(days_to_risk_on) if days_to_risk_on is not None else "N/A"
    days_pos_str  = str(days_to_full_pos) if days_to_full_pos is not None else "N/A"

    print(f"{n:<4} {prot_end_str:^12} {risk_on_str:^14} {days_risk_str:^10} "
          f"{spy_trough_str:^12} {full_pos_str:^14} {days_pos_str:^11}")

# Summary stats
all_days_risk_on = []
all_days_full_pos = []
for n, (s, e) in enumerate(episodes_prot, 1):
    sub = df.iloc[s:e+1]
    prot_end_date = sub["date"].iloc[-1]
    lookahead = df[df["date"] > prot_end_date].head(252)
    risk_on_dates = lookahead[lookahead["risk_on"] == True]["date"]
    if len(risk_on_dates) > 0:
        all_days_risk_on.append((risk_on_dates.iloc[0] - prot_end_date).days)
    lookback_start = max(0, s - 10)
    lookback_end   = min(len(df) - 1, e + 60)
    sub_trough = df.iloc[lookback_start:lookback_end+1]
    spy_trough_idx = sub_trough["spy_close"].idxmin()
    spy_trough_date = df.loc[spy_trough_idx, "date"]
    lookahead_pos = df[df["date"] > spy_trough_date].head(252)
    full_pos_dates = lookahead_pos[lookahead_pos["positions"] >= 5]["date"]
    if len(full_pos_dates) > 0:
        all_days_full_pos.append((full_pos_dates.iloc[0] - spy_trough_date).days)

print(f"\nSUMMARY STATISTICS:")
if all_days_risk_on:
    print(f"  Days to risk_on after prot end  : "
          f"median={np.median(all_days_risk_on):.0f}, "
          f"mean={np.mean(all_days_risk_on):.0f}, "
          f"min={min(all_days_risk_on)}, "
          f"max={max(all_days_risk_on)}")
if all_days_full_pos:
    print(f"  Days SPY trough -> positions=5   : "
          f"median={np.median(all_days_full_pos):.0f}, "
          f"mean={np.mean(all_days_full_pos):.0f}, "
          f"min={min(all_days_full_pos)}, "
          f"max={max(all_days_full_pos)}")

# ══════════════════════════════════════════════════════════════════════════════
# 5. V-RECOVERY DETECTION — 2007, 2019, 2025
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("ANALYSIS 5: V-RECOVERY DETECTION — 10 days before to 20 days after SPY trough")
print(SEP)

target_years = {
    2007: ("2007-06-01", "2009-06-30"),   # GFC onset
    2019: ("2018-10-01", "2019-06-30"),   # Q4 2018 / early 2019 recovery
    2025: ("2025-01-01", "2026-02-24"),   # recent period
}

for year, (start_s, end_s) in target_years.items():
    print(f"\n{'-' * 70}")
    print(f"YEAR {year}  (search window: {start_s} -> {end_s})")
    print(f"{'-' * 70}")

    window = df[(df["date"] >= start_s) & (df["date"] <= end_s)].copy()
    if window.empty:
        print("  No data in window.")
        continue

    # Find SPY trough
    spy_trough_idx_local = window["spy_close"].idxmin()
    spy_trough_date = df.loc[spy_trough_idx_local, "date"]
    spy_trough_val  = df.loc[spy_trough_idx_local, "spy_close"]
    print(f"  SPY trough: {spy_trough_date.date()}  close={spy_trough_val:.2f}")

    # ±window in the FULL dataframe
    global_idx = df[df["date"] == spy_trough_date].index[0]
    start_i = max(0, global_idx - 10)
    end_i   = min(len(df) - 1, global_idx + 20)
    sub5 = df.iloc[start_i:end_i+1].copy()

    print(f"\n  {'Date':^12} {'Pos':^5} {'risk_on':^8} {'regime':^8} {'DD%':^8} "
          f"{'SPY Ret%':^10} {'m2_sc':^8} {'in_prot':^8} {'overlay_sc':^11}")
    print("  " + "-" * 84)

    for _, row in sub5.iterrows():
        marker = " <-- TROUGH" if row["date"] == spy_trough_date else ""
        pos_str     = f"{int(row['positions'])}" if pd.notna(row["positions"]) else "N/A"
        risk_on_str = "True " if row["risk_on"] else "False"
        regime_str  = f"{row['regime_score']:.2f}" if pd.notna(row["regime_score"]) else "N/A"
        dd_str      = f"{row['drawdown']*100:.2f}%" if pd.notna(row["drawdown"]) else "N/A"
        spy_ret_str = f"{row['spy_ret']*100:+.2f}%" if pd.notna(row["spy_ret"]) else "N/A"
        m2_str      = f"{row['m2_scalar']:.4f}" if pd.notna(row["m2_scalar"]) else "N/A"
        prot_str    = "True " if row["in_protection"] else "False"
        ov_str      = f"{row['overlay_scalar']:.4f}" if pd.notna(row["overlay_scalar"]) else "N/A"
        print(f"  {str(row['date'].date()):^12} {pos_str:^5} {risk_on_str:^8} {regime_str:^8} "
              f"{dd_str:^8} {spy_ret_str:^10} {m2_str:^8} {prot_str:^8} {ov_str:^11}{marker}")

print(f"\n{SEP}")
print("ANALYSIS COMPLETE")
print(SEP)
