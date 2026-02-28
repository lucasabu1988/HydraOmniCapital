"""
Chassis Impact Analysis: Box Spreads (#1) and Puts OTM (#3)
============================================================
Estimates the theoretical impact of two institutional-grade improvements
WITHOUT running a full backtest. Uses existing daily data from v8 COMPASS.

Proposal #1: Box Spreads (cheaper leverage financing)
  - Replace 6% margin rate with SOFR+20bps (~historical Fed Funds + 0.20%)
  - Only matters when leverage > 1.0x

Proposal #3: Puts OTM (replace portfolio stop with tail-risk hedge)
  - Replace hard -15% stop + 126-day recovery with systematic put buying
  - Cost: ~0.5-1.0% of portfolio per year
  - Benefit: avoid 2,002 protection days, stay invested during V-recoveries
"""

import pandas as pd
import numpy as np

# Load daily backtest data (original v8.2 COMPASS)
daily = pd.read_csv('backtests/v8_compass_daily.csv', parse_dates=['date'])
daily = daily.set_index('date')

print("=" * 80)
print("CHASSIS IMPACT ANALYSIS: BOX SPREADS + PUTS OTM")
print("=" * 80)
print(f"Period: {daily.index[0].strftime('%Y-%m-%d')} to {daily.index[-1].strftime('%Y-%m-%d')}")
print(f"Trading days: {len(daily)}")

# ============================================================================
# PROPOSAL #1: BOX SPREADS (cheaper leverage)
# ============================================================================
print("\n" + "=" * 80)
print("PROPOSAL #1: BOX SPREADS (SOFR + 20bps vs 6% broker margin)")
print("=" * 80)

# Historical Fed Funds Rate (approximate annual averages)
FED_FUNDS_BY_YEAR = {
    2000: 0.0624, 2001: 0.0362, 2002: 0.0167, 2003: 0.0101, 2004: 0.0135,
    2005: 0.0322, 2006: 0.0497, 2007: 0.0502, 2008: 0.0193, 2009: 0.0016,
    2010: 0.0018, 2011: 0.0010, 2012: 0.0014, 2013: 0.0011, 2014: 0.0009,
    2015: 0.0013, 2016: 0.0039, 2017: 0.0100, 2018: 0.0191, 2019: 0.0216,
    2020: 0.0009, 2021: 0.0008, 2022: 0.0177, 2023: 0.0533, 2024: 0.0533,
    2025: 0.0450, 2026: 0.0400,
}

BROKER_MARGIN_RATE = 0.06  # Current assumption in backtest
BOX_SPREAD_PREMIUM = 0.0020  # 20bps above risk-free rate

# Calculate daily margin cost under both regimes
leveraged_days = daily[daily['leverage'] > 1.0].copy()
total_days = len(daily)
leveraged_count = len(leveraged_days)

print(f"\n  Days with leverage > 1.0x: {leveraged_count:,} ({leveraged_count/total_days*100:.1f}%)")
print(f"  Days with leverage <= 1.0x: {total_days - leveraged_count:,} ({(total_days-leveraged_count)/total_days*100:.1f}%)")

# Leverage distribution
print(f"\n  Leverage distribution (all days):")
print(f"    Mean:   {daily['leverage'].mean():.3f}x")
print(f"    Median: {daily['leverage'].median():.3f}x")
print(f"    Max:    {daily['leverage'].max():.3f}x")
print(f"    Min:    {daily['leverage'].min():.3f}x")

# Only for leveraged days
if leveraged_count > 0:
    print(f"\n  Leverage distribution (leveraged days only):")
    print(f"    Mean:   {leveraged_days['leverage'].mean():.3f}x")
    print(f"    Median: {leveraged_days['leverage'].median():.3f}x")

# Calculate total margin cost under both regimes
total_broker_margin = 0.0
total_box_spread_cost = 0.0
margin_savings_by_year = {}

for idx, row in daily.iterrows():
    if row['leverage'] <= 1.0:
        continue

    year = idx.year
    portfolio_value = row['value']
    leverage = row['leverage']

    # Borrowed amount = portfolio_value * (leverage - 1) / leverage
    borrowed = portfolio_value * (leverage - 1) / leverage

    # Broker margin cost (6% annual, daily)
    broker_daily = BROKER_MARGIN_RATE / 252 * borrowed

    # Box spread cost (Fed Funds + 20bps, daily)
    ff_rate = FED_FUNDS_BY_YEAR.get(year, 0.04)
    box_rate = ff_rate + BOX_SPREAD_PREMIUM
    box_daily = box_rate / 252 * borrowed

    total_broker_margin += broker_daily
    total_box_spread_cost += box_daily

    if year not in margin_savings_by_year:
        margin_savings_by_year[year] = {'broker': 0, 'box': 0, 'borrowed_avg': 0, 'days': 0}
    margin_savings_by_year[year]['broker'] += broker_daily
    margin_savings_by_year[year]['box'] += box_daily
    margin_savings_by_year[year]['borrowed_avg'] += borrowed
    margin_savings_by_year[year]['days'] += 1

total_savings = total_broker_margin - total_box_spread_cost

print(f"\n  TOTAL MARGIN COST COMPARISON:")
print(f"  {'Metric':<35} {'Broker 6%':>15} {'Box Spread':>15}")
print(f"  {'-'*65}")
print(f"  {'Total cost over backtest':<35} ${total_broker_margin:>14,.0f} ${total_box_spread_cost:>14,.0f}")
print(f"  {'Total savings':<35} ${total_savings:>14,.0f}")
print(f"  {'Savings as % of final value':<35} {total_savings/daily['value'].iloc[-1]*100:>14.2f}%")

# Year-by-year breakdown (show most impactful years)
print(f"\n  YEAR-BY-YEAR MARGIN SAVINGS (top 10):")
print(f"  {'Year':<6} {'Broker 6%':>12} {'Box Spread':>12} {'Savings':>12} {'Avg Borrowed':>14} {'Lev Days':>10}")
print(f"  {'-'*70}")

sorted_years = sorted(margin_savings_by_year.items(),
                       key=lambda x: x[1]['broker'] - x[1]['box'], reverse=True)
for year, data in sorted_years[:10]:
    savings = data['broker'] - data['box']
    avg_borrow = data['borrowed_avg'] / data['days'] if data['days'] > 0 else 0
    print(f"  {year:<6} ${data['broker']:>11,.0f} ${data['box']:>11,.0f} ${savings:>11,.0f} ${avg_borrow:>13,.0f} {data['days']:>10}")

# Estimate CAGR impact
# The savings compound over time, so we need to estimate the incremental CAGR
final_value = daily['value'].iloc[-1]
years = len(daily) / 252

# Simple estimate: savings / avg portfolio value = annual drag reduction
avg_portfolio = daily['value'].mean()
annual_savings = total_savings / years
annual_drag_reduction = annual_savings / avg_portfolio

print(f"\n  ESTIMATED CAGR IMPACT:")
print(f"  Average annual margin savings:  ${annual_savings:>12,.0f}")
print(f"  Average portfolio value:        ${avg_portfolio:>12,.0f}")
print(f"  Estimated CAGR improvement:     +{annual_drag_reduction*100:.2f}%")

# Key insight: when was leverage most expensive?
print(f"\n  KEY INSIGHT:")
zirp_years = [y for y in margin_savings_by_year if 2009 <= y <= 2021]
zirp_savings = sum(margin_savings_by_year[y]['broker'] - margin_savings_by_year[y]['box']
                   for y in zirp_years)
print(f"  ZIRP era (2009-2021) savings: ${zirp_savings:,.0f}")
print(f"  During ZIRP, Box Spread rate ~= 0.2%-0.4% vs broker's 6.0%")
print(f"  This is where Box Spreads provide MASSIVE advantage")

# ============================================================================
# PROPOSAL #3: PUTS OTM (replace portfolio stop)
# ============================================================================
print("\n\n" + "=" * 80)
print("PROPOSAL #3: PUTS OTM (REPLACE PORTFOLIO STOP WITH TAIL-RISK HEDGE)")
print("=" * 80)

# Analyze protection mode data
protection_days = daily[daily['in_protection'] == True]
non_protection_days = daily[daily['in_protection'] == False]

print(f"\n  CURRENT PROTECTION MODE ANALYSIS:")
print(f"  Total protection days:          {len(protection_days):,} ({len(protection_days)/len(daily)*100:.1f}%)")
print(f"  Non-protection days:            {len(non_protection_days):,}")

# Find each protection period (contiguous blocks)
protection_periods = []
in_block = False
block_start = None
block_start_value = None

for i, (idx, row) in enumerate(daily.iterrows()):
    if row['in_protection'] and not in_block:
        in_block = True
        block_start = idx
        block_start_value = row['value']
    elif not row['in_protection'] and in_block:
        in_block = False
        block_end = idx
        block_end_value = row['value']
        days_in_block = (block_end - block_start).days
        trading_days = len(daily.loc[block_start:block_end]) - 1
        protection_periods.append({
            'start': block_start,
            'end': block_end,
            'calendar_days': days_in_block,
            'trading_days': trading_days,
            'entry_value': block_start_value,
            'exit_value': block_end_value,
            'return': (block_end_value / block_start_value - 1) * 100
        })

# Close any open block
if in_block:
    block_end = daily.index[-1]
    block_end_value = daily['value'].iloc[-1]
    days_in_block = (block_end - block_start).days
    trading_days = len(daily.loc[block_start:block_end])
    protection_periods.append({
        'start': block_start,
        'end': block_end,
        'calendar_days': days_in_block,
        'trading_days': trading_days,
        'entry_value': block_start_value,
        'exit_value': block_end_value,
        'return': (block_end_value / block_start_value - 1) * 100
    })

print(f"\n  PROTECTION PERIODS ({len(protection_periods)} events):")
print(f"  {'#':<3} {'Start':<12} {'End':<12} {'Trad Days':>10} {'Entry Value':>14} {'Exit Value':>14} {'Return':>8}")
print(f"  {'-'*80}")
for i, p in enumerate(protection_periods):
    print(f"  {i+1:<3} {p['start'].strftime('%Y-%m-%d'):<12} {p['end'].strftime('%Y-%m-%d'):<12} "
          f"{p['trading_days']:>10} ${p['entry_value']:>13,.0f} ${p['exit_value']:>13,.0f} {p['return']:>+7.1f}%")

# What return did the MARKET generate during protection periods?
# This tells us the opportunity cost of being in protection mode
print(f"\n  OPPORTUNITY COST OF PROTECTION MODE:")
print(f"  (What SPY did while COMPASS was in protection)")

# Load SPY benchmark
try:
    spy_bench = pd.read_csv('backtests/spy_benchmark.csv', parse_dates=['date']).set_index('date')
    has_spy = True
except:
    has_spy = False

# Calculate returns during non-protection vs protection
if len(protection_days) > 0:
    prot_returns = daily.loc[daily['in_protection'] == True, 'value'].pct_change().dropna()
    non_prot_returns = daily.loc[daily['in_protection'] == False, 'value'].pct_change().dropna()

    prot_annual = prot_returns.mean() * 252
    non_prot_annual = non_prot_returns.mean() * 252

    print(f"  Annualized return during protection:     {prot_annual:>+8.2%}")
    print(f"  Annualized return during non-protection: {non_prot_annual:>+8.2%}")
    print(f"  Difference:                              {prot_annual - non_prot_annual:>+8.2%}")

# Estimate PUT cost vs protection drag
print(f"\n  PUT HEDGE COST ESTIMATION:")

# Typical cost of 15-20% OTM SPY puts, 60-90 DTE
# In normal vol (~15%): ~0.3-0.5% per quarter, ~1.2-2.0% annual
# In high vol (~25%+): ~0.8-1.5% per quarter, ~3.2-6.0% annual
# Weighted average for a systematic roll: ~1.5-2.5% annual

# But we only need to hedge during RISK-ON (when we're fully invested)
risk_on_pct = len(daily[daily['risk_on'] == True]) / len(daily)
print(f"  Risk-on days (when hedge needed):  {risk_on_pct*100:.1f}%")

# Cost scenarios
for annual_cost_pct in [0.005, 0.0075, 0.01, 0.015, 0.02]:
    total_cost = 0
    for idx, row in daily.iterrows():
        if row['risk_on'] and not row['in_protection']:
            daily_cost = row['value'] * annual_cost_pct / 252
            total_cost += daily_cost

    cost_as_pct_final = total_cost / daily['value'].iloc[-1] * 100
    annual_drag = annual_cost_pct * risk_on_pct * 100  # only pay during risk-on
    print(f"  At {annual_cost_pct*100:.1f}% annual: total cost ${total_cost:>12,.0f} "
          f"({cost_as_pct_final:.1f}% of final) | "
          f"annual drag ~{annual_drag:.2f}%")

# What we gain: elimination of protection mode
# During protection, COMPASS is at 0.3x-1.0x leverage with only 2-3 positions
# The opportunity cost is the missed returns on full deployment
print(f"\n  WHAT WE GAIN (elimination of protection mode):")
print(f"  Protection days eliminated:    {len(protection_days):,}")
print(f"  Avg leverage during protection: {protection_days['leverage'].mean():.2f}x")
print(f"  Avg positions during protection: {protection_days['positions'].mean():.1f}")
print(f"  Normal leverage (non-prot):    {non_protection_days['leverage'].mean():.2f}x")
print(f"  Normal positions (non-prot):   {non_protection_days['positions'].mean():.1f}")

# The key question: what is the ACTUAL penalty of protection mode?
# If protection mode earns X% annualized and normal mode earns Y%,
# the penalty is (Y - X) * (protection_time_fraction)
if len(protection_days) > 0:
    prot_frac = len(protection_days) / len(daily)
    penalty = (non_prot_annual - prot_annual) * prot_frac

    print(f"\n  PROTECTION MODE PENALTY:")
    print(f"  Time in protection:    {prot_frac*100:.1f}%")
    print(f"  Annual return gap:     {non_prot_annual - prot_annual:.2%} (non-prot - prot)")
    print(f"  Weighted annual penalty: {penalty:.2%}")
    print(f"  This is the MAXIMUM we could gain by eliminating protection mode")

# ============================================================================
# COMBINED VERDICT
# ============================================================================
print("\n\n" + "=" * 80)
print("COMBINED VERDICT")
print("=" * 80)

print(f"""
  PROPOSAL #1: BOX SPREADS
  -------------------------
  Estimated CAGR gain:    +{annual_drag_reduction*100:.2f}%
  Implementation:         Moderate (need options trading approval, SPX access)
  Risk:                   Near-zero (box spread = synthetic T-bill loan)
  Backtestable:           YES (just change margin rate formula)
  Biggest impact during:  ZIRP era (2009-2021) when broker charged 6% vs 0.2% risk-free

  PROPOSAL #3: PUTS OTM
  -------------------------
  Estimated CAGR gain:    Up to +{penalty*100:.1f}% (minus put cost)
  Put cost range:         -0.5% to -2.0% annual (depends on vol regime)
  Net estimated gain:     +{max(0, penalty*100 - 1.0):.1f}% to +{max(0, penalty*100 - 0.5):.1f}% CAGR
  Implementation:         Complex (need options data, roll logic, vol modeling)
  Risk:                   HIGHER than current system (puts can expire worthless
                          in slow-grinding bears where -15% takes months)
  Backtestable:           PARTIALLY (need historical options prices for accuracy)

  CRITICAL CAVEAT FOR PROPOSAL #3:
  The current -15% stop + 126-day recovery is PROVEN to work across 5 crises.
  Replacing it with puts introduces new risks:
    1. Put cost is high when vol is already elevated (worst time to buy)
    2. Slow-grind bears (2001-2002) won't trigger put payoff quickly
    3. Roll timing creates path dependency
    4. The "V-recovery" argument assumes all crashes are V-shaped
       (2001-2002 was NOT V-shaped -- it took 5+ years to recover)
""")

# Final recommendation
print("  RECOMMENDATION:")
print("  =" * 30)
print("  #1 Box Spreads: WORTH BACKTESTING (low risk, clear savings)")
print("  #3 Puts OTM: RISKY -- the protection mode penalty may be smaller")
print("     than the put cost + new risks introduced. Needs more data.")
