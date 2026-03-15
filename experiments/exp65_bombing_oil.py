"""
EXP65 -- US Bombing -> Oil Override Backtest
-------------------------------------------
Rule: When the US bombs a country, sell entire HYDRA portfolio and
buy crude oil (USO ETF / CL=F proxy) for 2 months, then return to HYDRA.

Uses hydra_clean_daily.csv as the base HYDRA equity curve and overlays
the bombing-to-oil switch on top.
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import timedelta
import os
import json

# ============================================================================
# US BOMBING / MILITARY STRIKE EVENTS (2000-2026)
# Major US military operations with clear start dates
# ============================================================================
BOMBING_EVENTS = [
    # Afghanistan -- Operation Enduring Freedom
    {"date": "2001-10-07", "target": "Afghanistan", "operation": "Operation Enduring Freedom"},
    # Iraq -- Shock and Awe
    {"date": "2003-03-20", "target": "Iraq", "operation": "Shock and Awe / Iraq War"},
    # Pakistan -- Drone campaign escalation
    {"date": "2008-01-29", "target": "Pakistan", "operation": "Drone strikes escalation"},
    # Libya -- Operation Odyssey Dawn
    {"date": "2011-03-19", "target": "Libya", "operation": "Operation Odyssey Dawn"},
    # ISIS -- Operation Inherent Resolve (Syria/Iraq)
    {"date": "2014-09-23", "target": "Syria/Iraq", "operation": "Operation Inherent Resolve vs ISIS"},
    # Syria -- Shayrat missile strike (chemical weapons response)
    {"date": "2017-04-07", "target": "Syria", "operation": "Shayrat missile strike"},
    # Syria -- Combined strikes (chemical weapons)
    {"date": "2018-04-14", "target": "Syria", "operation": "Combined missile strikes"},
    # Iraq -- Soleimani assassination / Baghdad strike
    {"date": "2020-01-03", "target": "Iraq", "operation": "Soleimani strike, Baghdad"},
    # Syria -- Biden airstrike on Iran-backed militias
    {"date": "2021-02-25", "target": "Syria", "operation": "Airstrike on Iran-backed militias"},
    # Afghanistan -- Kabul drone strike (ISIS-K)
    {"date": "2021-08-29", "target": "Afghanistan", "operation": "Kabul drone strike (ISIS-K)"},
    # Syria/Iraq -- Strikes on Houthi/Iran-backed groups
    {"date": "2024-01-12", "target": "Yemen", "operation": "Strikes on Houthi targets"},
    # Yemen -- Continued Houthi strikes
    {"date": "2024-02-03", "target": "Yemen/Iraq/Syria", "operation": "Multi-target strikes"},
]

OIL_HOLD_DAYS = 42  # ~2 months of trading days


def get_oil_prices():
    """Download crude oil futures (CL=F) daily prices 2000-2026."""
    print("Downloading crude oil (CL=F) prices...")
    oil = yf.download("CL=F", start="1999-12-01", end="2026-03-15", progress=False)
    if isinstance(oil.columns, pd.MultiIndex):
        oil.columns = oil.columns.get_level_values(0)
    oil = oil[['Close']].dropna()
    oil.columns = ['close']
    oil.index = pd.to_datetime(oil.index).tz_localize(None)
    print(f"  Oil data: {oil.index[0].date()} to {oil.index[-1].date()} ({len(oil)} days)")
    return oil


def run_backtest():
    """Run the bombing->oil overlay on HYDRA base equity curve."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bt_dir = os.path.join(base_dir, 'backtests')

    # Load HYDRA base curve
    hydra = pd.read_csv(os.path.join(bt_dir, 'hydra_clean_daily.csv'), parse_dates=['date'])
    hydra.set_index('date', inplace=True)
    hydra.index = pd.to_datetime(hydra.index).tz_localize(None)
    print(f"HYDRA base: {hydra.index[0].date()} to {hydra.index[-1].date()}")
    print(f"  Start: ${hydra['value'].iloc[0]:,.2f}  End: ${hydra['value'].iloc[-1]:,.2f}")

    # Calculate HYDRA daily returns
    hydra['return'] = hydra['value'].pct_change().fillna(0)

    # Load oil prices
    oil = get_oil_prices()
    oil['return'] = oil['close'].pct_change().fillna(0)

    # Build bombing override periods
    bombing_dates = [pd.Timestamp(e['date']) for e in BOMBING_EVENTS]

    # For each date in HYDRA, determine if we're in "oil mode"
    in_oil_mode = pd.Series(False, index=hydra.index)
    active_event = pd.Series("", index=hydra.index)

    for event in BOMBING_EVENTS:
        start = pd.Timestamp(event['date'])
        # Find the next trading day on or after the bombing date
        valid_starts = hydra.index[hydra.index >= start]
        if len(valid_starts) == 0:
            continue
        actual_start = valid_starts[0]

        # Hold oil for OIL_HOLD_DAYS trading days
        start_idx = hydra.index.get_loc(actual_start)
        end_idx = min(start_idx + OIL_HOLD_DAYS, len(hydra.index) - 1)

        oil_period = hydra.index[start_idx:end_idx + 1]
        in_oil_mode[oil_period] = True
        active_event[oil_period] = f"{event['target']} ({event['operation']})"

    # Build the combined equity curve
    combined_value = [hydra['value'].iloc[0]]
    daily_source = []  # Track which strategy was active each day

    for i in range(1, len(hydra)):
        date = hydra.index[i]
        prev_value = combined_value[-1]

        if in_oil_mode.iloc[i]:
            # Use oil return for this day
            if date in oil.index:
                day_return = oil.loc[date, 'return']
            else:
                day_return = 0  # No oil data for this day, flat
            daily_source.append('OIL')
        else:
            # Use HYDRA return
            day_return = hydra['return'].iloc[i]
            daily_source.append('HYDRA')

        combined_value.append(prev_value * (1 + day_return))

    daily_source.insert(0, 'HYDRA')  # First day

    # Build results DataFrame
    results = pd.DataFrame({
        'date': hydra.index,
        'hydra_value': hydra['value'].values,
        'combined_value': combined_value,
        'source': daily_source,
        'in_oil': in_oil_mode.values,
        'event': active_event.values,
    })

    # Calculate metrics
    hydra_final = hydra['value'].iloc[-1]
    hydra_start = hydra['value'].iloc[0]
    combined_final = combined_value[-1]

    n_years = (hydra.index[-1] - hydra.index[0]).days / 365.25
    hydra_cagr = (hydra_final / hydra_start) ** (1 / n_years) - 1
    combined_cagr = (combined_final / hydra_start) ** (1 / n_years) - 1

    # Drawdown calculations
    hydra_peak = hydra['value'].cummax()
    hydra_dd = ((hydra['value'] - hydra_peak) / hydra_peak).min()

    combined_series = pd.Series(combined_value, index=hydra.index)
    combined_peak = combined_series.cummax()
    combined_dd = ((combined_series - combined_peak) / combined_peak).min()

    # Sharpe
    hydra_daily_ret = hydra['value'].pct_change().dropna()
    combined_daily_ret = combined_series.pct_change().dropna()
    hydra_sharpe = hydra_daily_ret.mean() / hydra_daily_ret.std() * np.sqrt(252)
    combined_sharpe = combined_daily_ret.mean() / combined_daily_ret.std() * np.sqrt(252)

    # Oil mode stats
    oil_days = in_oil_mode.sum()
    total_days = len(hydra)
    n_events_in_range = sum(1 for e in BOMBING_EVENTS
                           if pd.Timestamp(e['date']) >= hydra.index[0]
                           and pd.Timestamp(e['date']) <= hydra.index[-1])

    # Per-event P&L
    event_results = []
    for event in BOMBING_EVENTS:
        start = pd.Timestamp(event['date'])
        valid_starts = hydra.index[hydra.index >= start]
        if len(valid_starts) == 0:
            continue
        actual_start = valid_starts[0]
        start_idx = hydra.index.get_loc(actual_start)
        end_idx = min(start_idx + OIL_HOLD_DAYS, len(hydra.index) - 1)

        # Oil return during this period
        period_dates = hydra.index[start_idx:end_idx + 1]
        oil_returns = []
        for d in period_dates:
            if d in oil.index:
                oil_returns.append(oil.loc[d, 'return'])
        oil_total = np.prod([1 + r for r in oil_returns]) - 1 if oil_returns else 0

        # HYDRA return during same period (what we gave up)
        hydra_period_return = hydra['value'].iloc[end_idx] / hydra['value'].iloc[start_idx] - 1

        event_results.append({
            'date': event['date'],
            'target': event['target'],
            'operation': event['operation'],
            'oil_return': round(oil_total * 100, 2),
            'hydra_return': round(hydra_period_return * 100, 2),
            'delta': round((oil_total - hydra_period_return) * 100, 2),
        })

    # Print results
    print("\n" + "=" * 70)
    print("EXP65 -- US BOMBING -> OIL OVERRIDE BACKTEST")
    print("=" * 70)
    print(f"\nPeriod: {hydra.index[0].date()} to {hydra.index[-1].date()} ({n_years:.1f} years)")
    print(f"Bombing events in range: {n_events_in_range}")
    print(f"Days in oil mode: {oil_days} / {total_days} ({oil_days/total_days*100:.1f}%)")
    print(f"\n{'Metric':<25} {'HYDRA Base':>15} {'HYDRA + Oil':>15} {'Delta':>10}")
    print("-" * 70)
    print(f"{'Final Value':<25} ${hydra_final:>14,.0f} ${combined_final:>14,.0f} ${combined_final - hydra_final:>9,.0f}")
    print(f"{'CAGR':<25} {hydra_cagr*100:>14.2f}% {combined_cagr*100:>14.2f}% {(combined_cagr-hydra_cagr)*100:>9.2f}%")
    print(f"{'Sharpe':<25} {hydra_sharpe:>15.3f} {combined_sharpe:>15.3f} {combined_sharpe-hydra_sharpe:>10.3f}")
    print(f"{'Max Drawdown':<25} {hydra_dd*100:>14.2f}% {combined_dd*100:>14.2f}% {(combined_dd-hydra_dd)*100:>9.2f}%")
    print(f"{'Total Return':<25} {(hydra_final/hydra_start-1)*100:>13.1f}% {(combined_final/hydra_start-1)*100:>14.1f}%")

    print(f"\n{'Event-by-Event Analysis':}")
    print(f"{'Date':<12} {'Target':<15} {'Oil Return':>12} {'HYDRA Return':>14} {'Delta':>10}")
    print("-" * 70)
    for er in event_results:
        print(f"{er['date']:<12} {er['target']:<15} {er['oil_return']:>11.2f}% {er['hydra_return']:>13.2f}% {er['delta']:>9.2f}%")

    wins = sum(1 for er in event_results if er['delta'] > 0)
    print(f"\nOil wins: {wins}/{len(event_results)} ({wins/len(event_results)*100:.0f}%)")

    # Save results
    out_csv = os.path.join(bt_dir, 'exp65_bombing_oil_daily.csv')
    results[['date', 'hydra_value', 'combined_value', 'source', 'event']].to_csv(out_csv, index=False)
    print(f"\nSaved: {out_csv}")

    # Save summary
    summary = {
        'experiment': 'EXP65 -- US Bombing -> Oil Override',
        'period': f"{hydra.index[0].date()} to {hydra.index[-1].date()}",
        'n_years': round(n_years, 1),
        'n_events': n_events_in_range,
        'oil_hold_days': OIL_HOLD_DAYS,
        'hydra': {
            'final_value': round(hydra_final, 2),
            'cagr': round(hydra_cagr * 100, 2),
            'sharpe': round(hydra_sharpe, 3),
            'max_drawdown': round(hydra_dd * 100, 2),
        },
        'combined': {
            'final_value': round(combined_final, 2),
            'cagr': round(combined_cagr * 100, 2),
            'sharpe': round(combined_sharpe, 3),
            'max_drawdown': round(combined_dd * 100, 2),
        },
        'events': event_results,
    }
    summary_path = os.path.join(bt_dir, 'exp65_bombing_oil_summary.json')
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"Saved: {summary_path}")

    return results, summary


if __name__ == '__main__':
    run_backtest()
