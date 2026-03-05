#!/usr/bin/env python3
"""
EXP59: Cash Recycling entre COMPASS y Rattlesnake
When one strategy has idle cash, redirect it to the other.
"""
import pandas as pd
import numpy as np

# Load daily data
compass = pd.read_csv('backtests/exp55_baseline_774_daily.csv', index_col=0, parse_dates=True)
rattle = pd.read_csv('backtests/rattlesnake_daily.csv', index_col=0, parse_dates=True)

# Returns
c_ret = compass['value'].pct_change()
r_ret = rattle['rattlesnake'].pct_change()

# Build aligned dataframe
df = pd.DataFrame({
    'c_ret': c_ret,
    'r_ret': r_ret,
    'c_leverage': compass['leverage'],
}).dropna()

print(f"Common period: {df.index[0].date()} to {df.index[-1].date()} ({len(df)} days)")
years = len(df) / 252

# Estimate Rattlesnake idle: when return is near cash yield only
CASH_DAILY = 0.03 / 252
r_excess = (df['r_ret'] - CASH_DAILY).abs()
r_idle = r_excess < 0.0005  # ~idle (cash only + noise)
print(f"Rattlesnake idle days: {r_idle.sum()}/{len(df)} ({r_idle.mean()*100:.1f}%)")
print(f"COMPASS avg leverage: {df['c_leverage'].mean():.2f}")

def calc_metrics(ret_series, label):
    eq = (1 + ret_series).cumprod()
    cagr = (eq.iloc[-1] ** (1/years) - 1) * 100
    maxdd = (eq / eq.cummax() - 1).min() * 100
    sharpe = ret_series.mean() / ret_series.std() * np.sqrt(252)
    final = eq.iloc[-1] * 100000
    # Worst year
    eq_ts = eq.copy()
    eq_ts.index = pd.to_datetime(eq_ts.index)
    annual = eq_ts.resample('YE').last().pct_change().dropna()
    worst = annual.min() * 100
    print(f"  {label}: CAGR={cagr:.2f}%  MaxDD={maxdd:.2f}%  Sharpe={sharpe:.2f}  Final=${final:,.0f}  WorstYr={worst:.2f}%")
    return cagr, maxdd, sharpe

# === REFERENCE: Static 50/50 ===
print("\n=== REFERENCE ===")
blend0 = 0.50 * df['c_ret'] + 0.50 * df['r_ret']
calc_metrics(blend0, "Static 50/50")
calc_metrics(df['c_ret'], "COMPASS solo")

# === APPROACH 1: R idle -> all capital to C ===
print("\n=== APPROACH 1: R idle -> 100% COMPASS ===")
r_idle_frac = np.where(r_idle, 1.0, 0.0)
w_c1 = 0.50 + 0.50 * r_idle_frac
w_r1 = 0.50 * (1 - r_idle_frac)
blend1 = pd.Series(w_c1 * df['c_ret'].values + w_r1 * df['r_ret'].values, index=df.index)
calc_metrics(blend1, "R idle->C")

# === APPROACH 2: Bidirectional recycling ===
print("\n=== APPROACH 2: Bidirectional (R idle->C, C idle->R) ===")
c_idle_frac = 1 - df['c_leverage'].values
w_c2 = 0.50 + 0.50 * r_idle_frac - 0.50 * c_idle_frac * (1 - r_idle_frac)
w_r2 = 0.50 * (1 - r_idle_frac) + 0.50 * c_idle_frac * (1 - r_idle_frac)
w_c2 = np.clip(w_c2, 0, 1.5)
w_r2 = np.clip(w_r2, 0, 1.5)
blend2 = pd.Series(w_c2 * df['c_ret'].values + w_r2 * df['r_ret'].values, index=df.index)
calc_metrics(blend2, "Bidirectional")

# === APPROACH 3: Proportional R exposure ===
# Instead of binary idle/active, estimate R exposure from return magnitude
print("\n=== APPROACH 3: Proportional exposure estimate ===")
# Rattlesnake: max 5 positions * 20% = 100%. But usually fewer.
# Estimate exposure from return deviation vs market
# A rough proxy: if R ret deviates from cash yield, it has positions
r_exposure_est = np.clip(r_excess / 0.01, 0, 1.0)  # scale: 1% daily excess = full exposure
r_idle_cash = 0.50 * (1 - r_exposure_est)
w_c3 = 0.50 + r_idle_cash.values
w_r3 = 0.50 - r_idle_cash.values + 0.50 * r_exposure_est.values
# Normalize so total weight = 1.0
total_w = w_c3 + w_r3
w_c3 = w_c3 / total_w
w_r3 = w_r3 / total_w
blend3 = pd.Series(w_c3 * df['c_ret'].values + w_r3 * df['r_ret'].values, index=df.index)
calc_metrics(blend3, "Proportional")

# === APPROACH 4: Only R idle -> C (conservative, cap at 75% C) ===
print("\n=== APPROACH 4: R idle -> C, capped at 75% C ===")
w_c4 = np.where(r_idle, 0.75, 0.50)
w_r4 = np.where(r_idle, 0.25, 0.50)
blend4 = pd.Series(w_c4 * df['c_ret'].values + w_r4 * df['r_ret'].values, index=df.index)
calc_metrics(blend4, "Capped 75/25")

# === APPROACH 5: R idle -> C, capped at 65% C ===
print("\n=== APPROACH 5: R idle -> C, capped at 65% C ===")
w_c5 = np.where(r_idle, 0.65, 0.50)
w_r5 = np.where(r_idle, 0.35, 0.50)
blend5 = pd.Series(w_c5 * df['c_ret'].values + w_r5 * df['r_ret'].values, index=df.index)
calc_metrics(blend5, "Capped 65/35")
