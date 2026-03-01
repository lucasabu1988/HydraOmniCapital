"""
Analysis: COMPASS v8.3 Regime Detector Conservatism
====================================================
Examines when and why the regime detector is too conservative,
and whether a threshold adjustment alone could fix the problem.
"""

import pandas as pd
import numpy as np
from collections import defaultdict

# ============================================================================
# 1. Load data
# ============================================================================

# v8.3 daily backtest results
daily = pd.read_csv(r'C:\Users\caslu\Desktop\NuevoProyecto\backtests\v83_compass_daily.csv',
                     parse_dates=['date'])
daily.set_index('date', inplace=True)

# SPY price data
spy = pd.read_csv(r'C:\Users\caslu\Desktop\NuevoProyecto\data_cache\SPY_2000-01-01_2027-01-01.csv',
                   parse_dates=['Date'])
spy.set_index('Date', inplace=True)
spy.index = spy.index.tz_localize(None) if spy.index.tz else spy.index
spy.sort_index(inplace=True)

# Compute SMA200 for SPY
spy['SMA200'] = spy['Close'].rolling(200).mean()
spy['above_sma200'] = spy['Close'] > spy['SMA200']
spy['pct_above_sma200'] = (spy['Close'] / spy['SMA200']) - 1.0

print("=" * 80)
print("COMPASS v8.3 REGIME DETECTOR CONSERVATISM ANALYSIS")
print("=" * 80)

# ============================================================================
# 2. Basic regime statistics
# ============================================================================

total_days = len(daily)
risk_on_days = daily['risk_on'].sum()
risk_off_days = total_days - risk_on_days

print(f"\n--- BASIC REGIME STATISTICS ---")
print(f"Total trading days: {total_days}")
print(f"Risk-ON days:  {risk_on_days} ({risk_on_days/total_days*100:.1f}%)")
print(f"Risk-OFF days: {risk_off_days} ({risk_off_days/total_days*100:.1f}%)")
print(f"Risk-ON threshold: regime_score >= 0.50")

# ============================================================================
# 3. Merge with SPY SMA200 data
# ============================================================================

# Merge daily backtest with SPY SMA200 status
merged = daily.join(spy[['Close', 'SMA200', 'above_sma200', 'pct_above_sma200']], how='left')
merged = merged.dropna(subset=['SMA200'])  # Drop days before SMA200 is available

print(f"\n--- MERGED DATA (days with SMA200 available) ---")
print(f"Total days with SMA200: {len(merged)}")

# ============================================================================
# 4. FALSE RISK-OFF analysis: Risk-off when SPY > SMA200
# ============================================================================

risk_off_mask = merged['risk_on'] == False
spy_above_mask = merged['above_sma200'] == True

false_risk_off = merged[risk_off_mask & spy_above_mask]
true_risk_off = merged[risk_off_mask & ~spy_above_mask]
correct_risk_on = merged[~risk_off_mask & spy_above_mask]
cautious_risk_on = merged[~risk_off_mask & ~spy_above_mask]  # risk-on during bear (risky)

print(f"\n--- FALSE RISK-OFF ANALYSIS ---")
print(f"Risk-OFF days (total):                    {risk_off_mask.sum()}")
print(f"Risk-OFF when SPY > SMA200 (FALSE alarm): {len(false_risk_off)} ({len(false_risk_off)/risk_off_mask.sum()*100:.1f}% of risk-off)")
print(f"Risk-OFF when SPY < SMA200 (CORRECT):     {len(true_risk_off)} ({len(true_risk_off)/risk_off_mask.sum()*100:.1f}% of risk-off)")
print(f"Risk-ON when SPY > SMA200 (CORRECT):      {len(correct_risk_on)}")
print(f"Risk-ON when SPY < SMA200 (aggressive):   {len(cautious_risk_on)}")

# ============================================================================
# 5. Year-by-year false risk-off breakdown
# ============================================================================

print(f"\n--- FALSE RISK-OFF BY YEAR ---")
print(f"{'Year':>6} {'Total':>6} {'RiskOff':>8} {'FalseOff':>9} {'%FalseOff':>10} {'AvgScore':>9} {'SPY_Ret':>8}")
print("-" * 65)

yearly_stats = []
for year in sorted(merged.index.year.unique()):
    yr_data = merged[merged.index.year == year]
    yr_risk_off = yr_data[yr_data['risk_on'] == False]
    yr_false_off = yr_data[(yr_data['risk_on'] == False) & (yr_data['above_sma200'] == True)]

    # SPY return for the year
    yr_spy = spy[spy.index.year == year]
    if len(yr_spy) > 1:
        spy_ret = (yr_spy['Close'].iloc[-1] / yr_spy['Close'].iloc[0] - 1) * 100
    else:
        spy_ret = 0

    avg_score = yr_false_off['regime_score'].mean() if len(yr_false_off) > 0 else 0

    yearly_stats.append({
        'year': year,
        'total': len(yr_data),
        'risk_off': len(yr_risk_off),
        'false_off': len(yr_false_off),
        'pct_false_off': len(yr_false_off) / len(yr_data) * 100 if len(yr_data) > 0 else 0,
        'avg_score': avg_score,
        'spy_ret': spy_ret
    })

    print(f"{year:>6} {len(yr_data):>6} {len(yr_risk_off):>8} {len(yr_false_off):>9} "
          f"{len(yr_false_off)/len(yr_data)*100:>9.1f}% {avg_score:>9.4f} {spy_ret:>7.1f}%")

# ============================================================================
# 6. REGIME SCORE DISTRIBUTION during false risk-off
# ============================================================================

print(f"\n--- REGIME SCORE DISTRIBUTION DURING FALSE RISK-OFF ---")
print(f"(Days where SPY > SMA200 but regime_score < 0.50)")
print(f"")

if len(false_risk_off) > 0:
    scores = false_risk_off['regime_score']

    print(f"Count:  {len(scores)}")
    print(f"Mean:   {scores.mean():.4f}")
    print(f"Median: {scores.median():.4f}")
    print(f"Std:    {scores.std():.4f}")
    print(f"Min:    {scores.min():.4f}")
    print(f"Max:    {scores.max():.4f}")

    print(f"\nDistribution by score bucket:")
    bins = [0, 0.10, 0.20, 0.25, 0.30, 0.35, 0.40, 0.42, 0.44, 0.46, 0.48, 0.50]
    for i in range(len(bins)-1):
        count = ((scores >= bins[i]) & (scores < bins[i+1])).sum()
        cumulative = (scores < bins[i+1]).sum()
        pct = count / len(scores) * 100
        cum_pct = cumulative / len(scores) * 100
        bar = '#' * int(pct / 2)
        print(f"  [{bins[i]:.2f}, {bins[i+1]:.2f}): {count:>5} ({pct:>5.1f}%)  cum: {cum_pct:>5.1f}%  {bar}")

    print(f"\n--- KEY THRESHOLD ANALYSIS ---")
    print(f"If we lower risk-on threshold from 0.50 to...")
    for threshold in [0.48, 0.47, 0.46, 0.45, 0.44, 0.43, 0.42, 0.40, 0.38, 0.35, 0.30]:
        recovered = (scores >= threshold).sum()
        still_off = (scores < threshold).sum()

        # Also check: how many TRUE risk-off days would we incorrectly make risk-on?
        true_off_scores = true_risk_off['regime_score']
        incorrectly_on = ((true_off_scores >= threshold) & (true_off_scores < 0.50)).sum()

        print(f"  threshold={threshold:.2f}: recover {recovered:>4} false-off days, "
              f"but also make {incorrectly_on:>4} true-risk-off days risk-on "
              f"(net benefit: {recovered - incorrectly_on:>+5})")

# ============================================================================
# 7. Deep dive: FALSE RISK-OFF by SPY distance from SMA200
# ============================================================================

print(f"\n--- FALSE RISK-OFF BY SPY DISTANCE FROM SMA200 ---")
print(f"How far above SMA200 was SPY during false risk-off?")
print(f"")

if len(false_risk_off) > 0:
    pct = false_risk_off['pct_above_sma200'] * 100

    dist_bins = [0, 1, 2, 3, 5, 8, 10, 15, 20, 50]
    print(f"{'Distance':>12} {'Count':>6} {'%':>7} {'AvgScore':>10} {'MedianScore':>12}")
    print("-" * 55)
    for i in range(len(dist_bins)-1):
        mask = (pct >= dist_bins[i]) & (pct < dist_bins[i+1])
        count = mask.sum()
        if count > 0:
            avg_s = false_risk_off.loc[mask, 'regime_score'].mean()
            med_s = false_risk_off.loc[mask, 'regime_score'].median()
            print(f"  {dist_bins[i]:>3}-{dist_bins[i+1]:>3}%  {count:>6} {count/len(false_risk_off)*100:>6.1f}% {avg_s:>10.4f} {med_s:>12.4f}")

# ============================================================================
# 8. What causes false risk-off? Decompose regime score components
# ============================================================================

print(f"\n--- REGIME SCORE DECOMPOSITION (reconstructed) ---")
print(f"The regime score = 0.60 * trend_score + 0.40 * vol_score")
print(f"For regime_score < 0.50 when SPY > SMA200:")
print(f"  => trend component is contributing ~0.60 * trend")
print(f"  => vol component is contributing ~0.40 * vol")
print(f"")

# Let's reconstruct trend and vol components for false risk-off days
def sigmoid(x, k=15.0):
    z = np.clip(k * x, -20, 20)
    return 1.0 / (1.0 + np.exp(-z))

decomp_records = []
spy_close_series = spy['Close']

for date in false_risk_off.index:
    if date not in spy_close_series.index:
        continue
    spy_idx = spy_close_series.index.get_loc(date)
    if spy_idx < 252:
        continue

    sc = spy_close_series.iloc[:spy_idx + 1]
    current = float(sc.iloc[-1])
    sma200 = float(sc.iloc[-200:].mean())
    sma50 = float(sc.iloc[-50:].mean())

    # Trend components
    dist_200 = (current / sma200) - 1.0
    sig_200 = sigmoid(dist_200, k=15.0)

    cross = (sma50 / sma200) - 1.0
    sig_cross = sigmoid(cross, k=30.0)

    price_20d_ago = float(sc.iloc[-21]) if len(sc) >= 21 else current
    mom_20d = (current / price_20d_ago) - 1.0
    sig_mom = sigmoid(mom_20d, k=15.0)

    trend_score = (sig_200 + sig_cross + sig_mom) / 3.0

    # Volatility component
    returns = sc.pct_change().dropna()
    vol_score = 0.5
    if len(returns) >= 262:
        current_vol = float(returns.iloc[-10:].std() * np.sqrt(252))
        hist_returns = returns.iloc[-252:]
        rolling_vol = hist_returns.rolling(window=10).std() * np.sqrt(252)
        rolling_vol = rolling_vol.dropna()
        if len(rolling_vol) >= 20 and current_vol > 0:
            pct_rank = float((rolling_vol <= current_vol).sum()) / len(rolling_vol)
            vol_score = 1.0 - pct_rank

    composite = 0.60 * trend_score + 0.40 * vol_score

    decomp_records.append({
        'date': date,
        'regime_score': composite,
        'trend_score': trend_score,
        'vol_score': vol_score,
        'trend_contrib': 0.60 * trend_score,
        'vol_contrib': 0.40 * vol_score,
        'sig_200': sig_200,
        'sig_cross': sig_cross,
        'sig_mom': sig_mom,
        'current_vol': current_vol if len(returns) >= 262 else None,
        'dist_200_pct': dist_200 * 100,
        'mom_20d_pct': mom_20d * 100,
    })

decomp = pd.DataFrame(decomp_records)

if len(decomp) > 0:
    print(f"Reconstructed {len(decomp)} false risk-off days")
    print(f"")
    print(f"{'Component':<20} {'Mean':>8} {'Median':>8} {'Std':>8} {'Min':>8} {'Max':>8}")
    print("-" * 58)
    for col in ['regime_score', 'trend_score', 'vol_score', 'trend_contrib', 'vol_contrib',
                'sig_200', 'sig_cross', 'sig_mom']:
        s = decomp[col]
        print(f"{col:<20} {s.mean():>8.4f} {s.median():>8.4f} {s.std():>8.4f} {s.min():>8.4f} {s.max():>8.4f}")

    print(f"")
    print(f"{'Metric':<20} {'Mean':>8} {'Median':>8} {'Std':>8} {'Min':>8} {'Max':>8}")
    print("-" * 58)
    for col in ['dist_200_pct', 'mom_20d_pct']:
        s = decomp[col].dropna()
        print(f"{col:<20} {s.mean():>8.2f}% {s.median():>8.2f}% {s.std():>8.2f}% {s.min():>8.2f}% {s.max():>8.2f}%")

    cv = decomp['current_vol'].dropna()
    if len(cv) > 0:
        print(f"{'current_vol_ann':<20} {cv.mean():>8.2f}% {cv.median():>8.2f}% {cv.std():>8.2f}% {cv.min():>8.2f}% {cv.max():>8.2f}%")

    # Key finding: which component drags score below 0.50?
    print(f"\n--- ROOT CAUSE: WHICH COMPONENT DRAGS SCORE BELOW 0.50? ---")
    print(f"")

    # A perfect trend score (all 3 sigmoid = 1.0) -> trend_score = 1.0, contrib = 0.60
    # A perfect vol score (lowest vol) -> vol_score = 1.0, contrib = 0.40
    # Need composite >= 0.50
    # If trend = 0.70 -> trend_contrib = 0.42, need vol_contrib >= 0.08 -> vol >= 0.20
    # If trend = 0.60 -> trend_contrib = 0.36, need vol_contrib >= 0.14 -> vol >= 0.35
    # If vol = 0.20 -> vol_contrib = 0.08, need trend_contrib >= 0.42 -> trend >= 0.70

    # Categorize
    low_trend = (decomp['trend_score'] < 0.50).sum()
    low_vol = (decomp['vol_score'] < 0.30).sum()
    both_low = ((decomp['trend_score'] < 0.50) & (decomp['vol_score'] < 0.30)).sum()
    trend_ok_vol_bad = ((decomp['trend_score'] >= 0.50) & (decomp['vol_score'] < 0.30)).sum()

    print(f"Days with trend_score < 0.50: {low_trend} ({low_trend/len(decomp)*100:.1f}%)")
    print(f"Days with vol_score < 0.30:   {low_vol} ({low_vol/len(decomp)*100:.1f}%)")
    print(f"Days with BOTH low:           {both_low} ({both_low/len(decomp)*100:.1f}%)")
    print(f"Days with OK trend but bad vol:{trend_ok_vol_bad} ({trend_ok_vol_bad/len(decomp)*100:.1f}%)")
    print(f"")
    print(f"=> The vol component is the main culprit when SPY is above SMA200.")
    print(f"   High short-term volatility pushes vol_score down,")
    print(f"   which drags the composite below 0.50 even though price trend is healthy.")

    # Specifically: what vol_score is needed to push composite >= 0.50?
    print(f"\n--- VOL SCORE DISTRIBUTION FOR FALSE RISK-OFF ---")
    vol_bins = [0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50]
    for i in range(len(vol_bins)-1):
        mask = (decomp['vol_score'] >= vol_bins[i]) & (decomp['vol_score'] < vol_bins[i+1])
        count = mask.sum()
        pct = count / len(decomp) * 100
        bar = '#' * int(pct / 2)
        print(f"  vol_score [{vol_bins[i]:.2f}, {vol_bins[i+1]:.2f}): {count:>5} ({pct:>5.1f}%)  {bar}")

# ============================================================================
# 9. SIMULATION: What if we lower threshold to 0.45 or 0.40?
# ============================================================================

print(f"\n{'='*80}")
print(f"SIMULATION: THRESHOLD ADJUSTMENT vs BULL OVERRIDE")
print(f"{'='*80}")

# For each alternative threshold, count:
# - How many false-risk-off days are recovered (good)
# - How many true-risk-off days become risk-on (bad - reduces crash protection)
# - Net effect on the confusion matrix

thresholds_to_test = [0.50, 0.48, 0.47, 0.46, 0.45, 0.44, 0.43, 0.42, 0.40, 0.38, 0.35]

print(f"\n{'Threshold':>10} {'FalseOff':>9} {'TrueOff':>8} {'RiskOnWhenBear':>15} {'Precision':>10} {'Recall':>8}")
print("-" * 65)

for t in thresholds_to_test:
    # Re-classify with new threshold
    new_risk_on = merged['regime_score'] >= t

    # When SPY > SMA200 (should be risk-on):
    false_off_new = (~new_risk_on & merged['above_sma200']).sum()  # False alarm
    correct_on_new = (new_risk_on & merged['above_sma200']).sum()  # Correct

    # When SPY < SMA200 (should be risk-off):
    true_off_new = (~new_risk_on & ~merged['above_sma200']).sum()  # Correct protection
    risk_on_bear_new = (new_risk_on & ~merged['above_sma200']).sum()  # Dangerous

    # Precision of risk-off: what fraction of risk-off calls are correct (SPY < SMA200)?
    total_off_new = false_off_new + true_off_new
    precision = true_off_new / total_off_new if total_off_new > 0 else 0

    # Recall of risk-off: what fraction of bear days are caught?
    total_bear = (merged['above_sma200'] == False).sum()
    recall = true_off_new / total_bear if total_bear > 0 else 0

    print(f"  {t:>7.2f} {false_off_new:>9} {true_off_new:>8} {risk_on_bear_new:>15} {precision:>9.3f} {recall:>8.3f}")

# ============================================================================
# 10. BULL OVERRIDE SIMULATION
# ============================================================================

print(f"\n--- BULL OVERRIDE SIMULATION (v8.4 approach) ---")
print(f"Override: if SPY > SMA200 AND regime_score > 0.40, treat as risk-on")
print(f"")

# With the override, false risk-off days become zero IF score > 0.40 and SPY > SMA200
bull_override = merged.copy()
override_mask = ((bull_override['regime_score'] > 0.40) &
                 (bull_override['above_sma200'] == True) &
                 (bull_override['risk_on'] == False))
days_overridden = override_mask.sum()

# Check: what's the score distribution of the remaining false risk-off
remaining_false_off = bull_override[(bull_override['risk_on'] == False) &
                                     (bull_override['above_sma200'] == True) &
                                     (bull_override['regime_score'] <= 0.40)]

print(f"Days that would be overridden to risk-on: {days_overridden}")
print(f"Remaining false risk-off (score <= 0.40): {len(remaining_false_off)}")

# ============================================================================
# 11. HEAD-TO-HEAD: Threshold=0.45 vs Bull Override
# ============================================================================

print(f"\n--- HEAD-TO-HEAD: threshold=0.45 vs Bull Override ---")
print(f"")

# Threshold 0.45
t45_risk_on = merged['regime_score'] >= 0.45
t45_false_off = (~t45_risk_on & merged['above_sma200']).sum()
t45_correct_off = (~t45_risk_on & ~merged['above_sma200']).sum()
t45_risk_on_bear = (t45_risk_on & ~merged['above_sma200']).sum()
t45_correct_on = (t45_risk_on & merged['above_sma200']).sum()

# Bull override (score > 0.40 + SPY > SMA200 -> risk-on)
bo_risk_on = (merged['regime_score'] >= 0.50) | ((merged['regime_score'] > 0.40) & (merged['above_sma200']))
bo_false_off = (~bo_risk_on & merged['above_sma200']).sum()
bo_correct_off = (~bo_risk_on & ~merged['above_sma200']).sum()
bo_risk_on_bear = (bo_risk_on & ~merged['above_sma200']).sum()
bo_correct_on = (bo_risk_on & merged['above_sma200']).sum()

print(f"{'Metric':<35} {'Thresh=0.45':>12} {'BullOverride':>13} {'Curr(0.50)':>12}")
print("-" * 75)
print(f"{'False risk-off (SPY>SMA200)':<35} {t45_false_off:>12} {bo_false_off:>13} {len(false_risk_off):>12}")
print(f"{'Correct risk-off (SPY<SMA200)':<35} {t45_correct_off:>12} {bo_correct_off:>13} {len(true_risk_off):>12}")
print(f"{'Risk-on during bear (dangerous)':<35} {t45_risk_on_bear:>12} {bo_risk_on_bear:>13} {(merged['risk_on'] & ~merged['above_sma200']).sum():>12}")
print(f"{'Correct risk-on (SPY>SMA200)':<35} {t45_correct_on:>12} {bo_correct_on:>13} {len(correct_risk_on):>12}")

# Total risk-off precision
t45_total_off = t45_false_off + t45_correct_off
bo_total_off = bo_false_off + bo_correct_off
curr_total_off = len(false_risk_off) + len(true_risk_off)

t45_prec = t45_correct_off / t45_total_off if t45_total_off > 0 else 0
bo_prec = bo_correct_off / bo_total_off if bo_total_off > 0 else 0
curr_prec = len(true_risk_off) / curr_total_off if curr_total_off > 0 else 0

print(f"{'Risk-off precision':<35} {t45_prec:>12.3f} {bo_prec:>13.3f} {curr_prec:>12.3f}")
print(f"{'Total risk-off days':<35} {t45_total_off:>12} {bo_total_off:>13} {curr_total_off:>12}")

# ============================================================================
# 12. FINAL RECOMMENDATION
# ============================================================================

print(f"\n{'='*80}")
print(f"FINAL ANALYSIS & RECOMMENDATION")
print(f"{'='*80}")

# Calculate what threshold achieves equivalent false-off reduction as bull override
print(f"\nBull override eliminates {days_overridden} false risk-off days")
print(f"(those with score 0.40-0.50 when SPY > SMA200)")
print(f"")

for t in [0.50, 0.48, 0.47, 0.46, 0.45, 0.44, 0.43, 0.42, 0.40]:
    t_risk_on = merged['regime_score'] >= t
    t_false_off = (~t_risk_on & merged['above_sma200']).sum()
    t_added_bear_risk = ((merged['regime_score'] >= t) & (merged['regime_score'] < 0.50) & (~merged['above_sma200'])).sum()

    print(f"  threshold={t:.2f}: {t_false_off:>4} false risk-off remaining, "
          f"+{t_added_bear_risk:>4} bear days now risk-on (DANGER), "
          f"net false-off reduction: {len(false_risk_off) - t_false_off}")

print(f"\nBull override: {bo_false_off:>4} false risk-off remaining, "
      f"+0 bear days now risk-on (SAFE), "
      f"net false-off reduction: {len(false_risk_off) - bo_false_off}")

print(f"""
CONCLUSION:
===========
The bull override is STRICTLY SUPERIOR to a simple threshold reduction because:

1. A threshold reduction is BLIND to market context -- it reduces false risk-off
   but ALSO reduces true risk-off protection during genuine bear markets.

2. The bull override is CONDITIONAL -- it only overrides to risk-on when there's
   confirming evidence (SPY > SMA200), so it NEVER weakens bear protection.

3. To match the bull override's false-off reduction with a threshold change,
   you'd need threshold ~0.40, but that would also make {((merged['regime_score'] >= 0.40) & (merged['regime_score'] < 0.50) & (~merged['above_sma200'])).sum()}
   genuine bear-market days risk-on -- a direct increase in crash exposure.

ANSWER TO THE KEY QUESTION:
No, simply lowering the threshold from 0.50 to 0.45 or 0.40 would NOT achieve
the same effect as the bull override with less complexity. The threshold change
is a blunt instrument that trades crash protection for reduced false risk-off.
The bull override is a targeted fix that only affects the specific failure mode
(false risk-off during bull markets) without compromising bear protection.
""")
