#!/usr/bin/env python3
"""
COMBINED PORTFOLIO ANALYSIS
============================
COMPASS v8.2 (Momentum) + RATTLESNAKE v1.0 (Mean-Reversion)
Yin & Yang: Buy winners + Buy oversold losers

Tests multiple allocation ratios to find the optimal blend.
"""

import numpy as np
import pandas as pd
import warnings

warnings.filterwarnings('ignore')

INITIAL_CAPITAL = 100_000
RISK_FREE = 0.02


def load_compass():
    """Load COMPASS backtest equity curve."""
    df = pd.read_csv('backtests/v8_compass_daily.csv', parse_dates=['date'])
    df = df.set_index('date')[['value']].rename(columns={'value': 'compass'})
    return df


def load_rattlesnake():
    """Run RATTLESNAKE and capture equity curve, or load from saved."""
    import os
    cache = 'backtests/rattlesnake_daily.csv'
    if os.path.exists(cache):
        df = pd.read_csv(cache, parse_dates=['date'])
        return df.set_index('date')

    # Need to run the backtest
    print("  Running RATTLESNAKE backtest to get equity curve...")
    import rattlesnake_v1 as rs
    data = rs.download_data()
    port_df, trade_df, stats = rs.run_backtest(data)
    df = port_df.rename(columns={'value': 'rattlesnake'})
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date')

    # Save for future use
    os.makedirs('backtests', exist_ok=True)
    df.to_csv(cache)
    return df


def compute_metrics(equity_series, name="Strategy"):
    """Compute full metrics for an equity curve."""
    df = equity_series.to_frame('value') if isinstance(equity_series, pd.Series) else equity_series
    df = df.dropna()

    if len(df) < 100:
        return None

    # Returns
    daily_ret = df['value'].pct_change().dropna()
    total_days = len(daily_ret)
    years = total_days / 252

    final_val = df['value'].iloc[-1]
    initial_val = df['value'].iloc[0]
    cagr = (final_val / initial_val) ** (1 / years) - 1

    # Risk
    annual_vol = daily_ret.std() * np.sqrt(252)
    sharpe = (cagr - RISK_FREE) / annual_vol if annual_vol > 0 else 0

    downside = daily_ret[daily_ret < 0].std() * np.sqrt(252)
    sortino = (cagr - RISK_FREE) / downside if downside > 0 else 0

    # Drawdown
    cummax = df['value'].cummax()
    dd = (df['value'] / cummax) - 1
    max_dd = dd.min()
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    # Monthly
    monthly = df['value'].resample('ME').last()
    monthly_ret = monthly.pct_change().dropna()
    monthly_win = (monthly_ret > 0).mean()

    # Yearly
    yearly = df['value'].resample('YE').last()
    yearly_ret = yearly.pct_change().dropna()
    best_year = yearly_ret.max()
    worst_year = yearly_ret.min()
    positive_years = (yearly_ret > 0).mean()

    return {
        'name': name,
        'initial': initial_val,
        'final': final_val,
        'cagr': cagr,
        'annual_vol': annual_vol,
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'max_dd': max_dd,
        'monthly_win': monthly_win,
        'best_year': best_year,
        'worst_year': worst_year,
        'positive_years': positive_years,
        'years': years,
        'daily_returns': daily_ret,
        'yearly_returns': yearly_ret
    }


def print_comparison(metrics_list):
    """Print side-by-side comparison table."""
    # Header
    header = f"  {'METRIC':<22}"
    for m in metrics_list:
        header += f" {m['name']:>14}"
    print(header)
    print(f"  {'-' * (22 + 15 * len(metrics_list))}")

    rows = [
        ('$100K becomes', lambda m: f"${m['final']:>11,.0f}"),
        ('CAGR', lambda m: f"{m['cagr']:>13.2%}"),
        ('Annual Vol', lambda m: f"{m['annual_vol']:>13.2%}"),
        ('Sharpe', lambda m: f"{m['sharpe']:>14.2f}"),
        ('Sortino', lambda m: f"{m['sortino']:>14.2f}"),
        ('Calmar', lambda m: f"{m['calmar']:>14.2f}"),
        ('Max Drawdown', lambda m: f"{m['max_dd']:>13.2%}"),
        ('Monthly Win %', lambda m: f"{m['monthly_win']:>13.1%}"),
        ('Best Year', lambda m: f"{m['best_year']:>13.1%}"),
        ('Worst Year', lambda m: f"{m['worst_year']:>13.1%}"),
        ('Positive Years', lambda m: f"{m['positive_years']:>13.1%}"),
    ]

    for label, fmt in rows:
        row = f"  {label:<22}"
        for m in metrics_list:
            row += fmt(m)
        print(row)


def find_best(metrics_list):
    """Highlight the best strategy for each metric."""
    print(f"\n  WINNERS:")
    metrics_to_check = [
        ('Highest CAGR', 'cagr', True),
        ('Best Sharpe', 'sharpe', True),
        ('Best Sortino', 'sortino', True),
        ('Best Calmar', 'calmar', True),
        ('Lowest Max DD', 'max_dd', False),  # Less negative = better
        ('Lowest Vol', 'annual_vol', False),  # Lower = better for same return
        ('Best Monthly Win%', 'monthly_win', True),
    ]

    for label, key, higher_is_better in metrics_to_check:
        if higher_is_better:
            best = max(metrics_list, key=lambda m: m[key])
        else:
            # For max_dd (negative), "best" = closest to 0; for vol, lowest
            if key == 'max_dd':
                best = max(metrics_list, key=lambda m: m[key])  # least negative
            else:
                best = min(metrics_list, key=lambda m: m[key])

        val = best[key]
        if key in ('cagr', 'annual_vol', 'max_dd', 'monthly_win', 'best_year', 'worst_year', 'positive_years'):
            val_str = f"{val:.2%}"
        else:
            val_str = f"{val:.2f}"
        print(f"  {label:<22} -> {best['name']} ({val_str})")


def main():
    print("=" * 65)
    print("  COMBINED PORTFOLIO: COMPASS + RATTLESNAKE")
    print("  Momentum + Mean-Reversion = Yin & Yang")
    print("=" * 65)

    # Load data
    print("\n  Loading equity curves...")
    compass_df = load_compass()
    rattle_df = load_rattlesnake()

    print(f"  COMPASS:     {compass_df.index[0].strftime('%Y-%m-%d')} to {compass_df.index[-1].strftime('%Y-%m-%d')} ({len(compass_df)} days)")
    print(f"  RATTLESNAKE: {rattle_df.index[0].strftime('%Y-%m-%d')} to {rattle_df.index[-1].strftime('%Y-%m-%d')} ({len(rattle_df)} days)")

    # Align dates
    common = compass_df.index.intersection(rattle_df.index)
    print(f"  Common dates: {len(common)}")

    c = compass_df.loc[common, 'compass']
    r = rattle_df.loc[common, 'rattlesnake']

    # Normalize both to start at $100K
    c_norm = c / c.iloc[0] * INITIAL_CAPITAL
    r_norm = r / r.iloc[0] * INITIAL_CAPITAL

    # Daily returns for correlation
    c_ret = c_norm.pct_change().dropna()
    r_ret = r_norm.pct_change().dropna()

    corr = c_ret.corr(r_ret)

    print(f"\n  ========================================")
    print(f"  DAILY RETURN CORRELATION: {corr:.3f}")
    print(f"  ========================================")
    if abs(corr) < 0.2:
        print(f"  VERY LOW correlation -> excellent diversification!")
    elif abs(corr) < 0.4:
        print(f"  LOW correlation -> good diversification potential")
    elif abs(corr) < 0.6:
        print(f"  MODERATE correlation -> some benefit")
    else:
        print(f"  HIGH correlation -> limited diversification")

    # Rolling correlation (1-year windows)
    rolling_corr = c_ret.rolling(252).corr(r_ret).dropna()
    print(f"\n  Rolling 1Y Correlation:")
    print(f"    Min:    {rolling_corr.min():.3f}")
    print(f"    Max:    {rolling_corr.max():.3f}")
    print(f"    Mean:   {rolling_corr.mean():.3f}")
    print(f"    Median: {rolling_corr.median():.3f}")

    # ── TEST MULTIPLE ALLOCATIONS ──
    print(f"\n{'='*65}")
    print(f"  ALLOCATION SWEEP: COMPASS/RATTLESNAKE")
    print(f"{'='*65}")

    allocations = [
        (1.0, 0.0, "100% COMPASS"),
        (0.8, 0.2, "80/20"),
        (0.7, 0.3, "70/30"),
        (0.6, 0.4, "60/40"),
        (0.5, 0.5, "50/50"),
        (0.4, 0.6, "40/60"),
        (0.3, 0.7, "30/70"),
        (0.0, 1.0, "100% RATTLESNAKE"),
    ]

    all_metrics = []

    for w_c, w_r, label in allocations:
        # Build combined equity curve with daily rebalancing assumption
        # Simple: combined_return = w_c * compass_return + w_r * rattle_return
        combined_ret = w_c * c_ret + w_r * r_ret
        combined_equity = (1 + combined_ret).cumprod() * INITIAL_CAPITAL
        combined_equity = pd.DataFrame({'value': combined_equity})

        metrics = compute_metrics(combined_equity, label)
        if metrics:
            all_metrics.append(metrics)

    # Print sweep results
    print(f"\n  {'Alloc':<20} {'CAGR':>8} {'Sharpe':>8} {'Sortino':>9} {'MaxDD':>9} {'Calmar':>8} {'Vol':>8}")
    print(f"  {'-'*72}")

    best_sharpe = max(all_metrics, key=lambda m: m['sharpe'])
    best_calmar = max(all_metrics, key=lambda m: m['calmar'])
    best_sortino = max(all_metrics, key=lambda m: m['sortino'])

    for m in all_metrics:
        markers = []
        if m == best_sharpe:
            markers.append('*S')
        if m == best_calmar:
            markers.append('*C')
        if m == best_sortino:
            markers.append('*So')
        marker = ' '.join(markers)

        print(f"  {m['name']:<20} {m['cagr']:>7.2%} {m['sharpe']:>8.2f} {m['sortino']:>9.2f} {m['max_dd']:>8.2%} {m['calmar']:>8.2f} {m['annual_vol']:>7.2%}  {marker}")

    # ── DETAILED COMPARISON OF KEY PORTFOLIOS ──
    print(f"\n{'='*65}")
    print(f"  HEAD-TO-HEAD: Best Candidates")
    print(f"{'='*65}\n")

    key_metrics = [m for m in all_metrics if m['name'] in ('100% COMPASS', '70/30', '50/50', '100% RATTLESNAKE')]
    print_comparison(key_metrics)
    find_best(key_metrics)

    # ── YEARLY COMPARISON ──
    print(f"\n{'='*65}")
    print(f"  ANNUAL RETURNS BY STRATEGY")
    print(f"{'='*65}\n")

    # Get yearly returns for key strategies
    compass_metrics = [m for m in all_metrics if m['name'] == '100% COMPASS'][0]
    combo_metrics = best_sharpe  # Use best Sharpe combo
    rattle_metrics = [m for m in all_metrics if m['name'] == '100% RATTLESNAKE'][0]

    c_yearly = compass_metrics['yearly_returns']
    combo_yearly = combo_metrics['yearly_returns']
    r_yearly = rattle_metrics['yearly_returns']

    print(f"  {'Year':<6} {'COMPASS':>10} {'BEST COMBO':>12} {'RATTLESNAKE':>13} {'Combo wins?':>13}")
    print(f"  {'-'*56}")

    combo_wins = 0
    total_years = 0
    for yr_idx in c_yearly.index:
        yr = yr_idx.year
        cv = c_yearly.get(yr_idx, float('nan'))
        rv = r_yearly.get(yr_idx, float('nan'))
        bv = combo_yearly.get(yr_idx, float('nan'))

        if pd.isna(cv) or pd.isna(bv):
            continue

        total_years += 1
        # Does combo beat pure COMPASS?
        combo_better = bv > cv if not pd.isna(bv) else False
        if combo_better:
            combo_wins += 1
        marker = '<--' if combo_better else ''

        print(f"  {yr:<6} {cv:>9.1%} {bv:>11.1%} {rv:>12.1%}  {marker}")

    print(f"\n  Best combo ({combo_metrics['name']}) beats pure COMPASS in {combo_wins}/{total_years} years ({combo_wins/max(total_years,1)*100:.0f}%)")

    # ── FINAL VERDICT ──
    print(f"\n{'='*65}")
    print(f"  FINAL VERDICT")
    print(f"{'='*65}")
    print(f"")
    print(f"  Correlation (COMPASS vs RATTLESNAKE): {corr:.3f}")
    print(f"")
    print(f"  Best risk-adjusted portfolio: {best_sharpe['name']}")
    print(f"    Sharpe:  {best_sharpe['sharpe']:.2f}")
    print(f"    CAGR:    {best_sharpe['cagr']:.2%}")
    print(f"    Max DD:  {best_sharpe['max_dd']:.2%}")
    print(f"    Calmar:  {best_sharpe['calmar']:.2f}")
    print(f"")

    # Compare best combo vs pure COMPASS
    comp = [m for m in all_metrics if m['name'] == '100% COMPASS'][0]
    print(f"  vs Pure COMPASS:")
    sharpe_diff = best_sharpe['sharpe'] - comp['sharpe']
    dd_diff = best_sharpe['max_dd'] - comp['max_dd']
    cagr_diff = best_sharpe['cagr'] - comp['cagr']
    print(f"    Sharpe delta:  {sharpe_diff:+.2f} ({'better' if sharpe_diff > 0 else 'worse'})")
    print(f"    CAGR delta:    {cagr_diff:+.2%}")
    print(f"    MaxDD delta:   {dd_diff:+.2%} ({'less risk' if dd_diff > 0 else 'more risk'})")
    print(f"")
    print(f"{'='*65}")


if __name__ == '__main__':
    main()
