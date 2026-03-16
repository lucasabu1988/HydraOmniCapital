"""Drawdown analysis for HYDRA backtest results."""
import argparse
import pandas as pd
import sys


def find_drawdowns(equity):
    """Identify all drawdown periods from an equity series.

    Returns a DataFrame with one row per drawdown containing start date,
    trough date, recovery date, depth, duration (trading days to trough),
    and recovery time (trading days from trough back to previous peak).
    """
    peak = equity.cummax()
    dd = (equity - peak) / peak

    records = []
    in_dd = False
    start = None
    trough_val = 0.0
    trough_date = None
    peak_val = None

    for dt, val in dd.items():
        if val < 0 and not in_dd:
            in_dd = True
            start = dt
            trough_val = val
            trough_date = dt
            peak_val = float(peak.loc[dt])
        elif val < 0 and in_dd:
            if val < trough_val:
                trough_val = val
                trough_date = dt
        elif val >= 0 and in_dd:
            in_dd = False
            records.append({
                'start_date': start,
                'trough_date': trough_date,
                'recovery_date': dt,
                'depth_pct': round(trough_val * 100, 2),
                'peak_value': round(peak_val, 2),
                'trough_value': round(peak_val * (1 + trough_val), 2),
            })

    # Handle ongoing drawdown at end of series
    if in_dd:
        records.append({
            'start_date': start,
            'trough_date': trough_date,
            'recovery_date': None,
            'depth_pct': round(trough_val * 100, 2),
            'peak_value': round(peak_val, 2),
            'trough_value': round(peak_val * (1 + trough_val), 2),
        })

    df = pd.DataFrame(records)
    if df.empty:
        return df

    # Compute durations in trading days
    dates = equity.index
    date_pos = {d: i for i, d in enumerate(dates)}
    durations = []
    recoveries = []
    for _, row in df.iterrows():
        s = date_pos.get(row['start_date'], 0)
        t = date_pos.get(row['trough_date'], s)
        durations.append(t - s)
        if row['recovery_date'] is not None:
            r = date_pos.get(row['recovery_date'], t)
            recoveries.append(r - t)
        else:
            recoveries.append(None)

    df['duration_days'] = durations
    df['recovery_days'] = recoveries
    return df


def underwater_curve(equity):
    """Return the underwater equity curve (pct below previous peak)."""
    peak = equity.cummax()
    return ((equity - peak) / peak * 100).round(4)


def main():
    parser = argparse.ArgumentParser(description='Analyze drawdowns')
    parser.add_argument('csv_path', nargs='?',
                        default='backtests/v84_compass_daily.csv')
    parser.add_argument('--value-col', default=None,
                        help='Column name for portfolio value')
    args = parser.parse_args()

    df = pd.read_csv(args.csv_path, parse_dates=['date'])
    df = df.sort_values('date').reset_index(drop=True)

    # Auto-detect value column
    val_col = args.value_col
    if val_col is None:
        for candidate in ('value', 'portfolio_value', 'close'):
            if candidate in df.columns:
                val_col = candidate
                break
    if val_col is None or val_col not in df.columns:
        print(f"ERROR: no value column found in {list(df.columns)}", file=sys.stderr)
        sys.exit(1)

    equity = df.set_index('date')[val_col]

    # 1. Find all drawdowns
    dds = find_drawdowns(equity)
    if dds.empty:
        print("No drawdowns found.")
        return

    # 2. Top 5 by depth
    top5 = dds.nsmallest(5, 'depth_pct').reset_index(drop=True)

    # 3. Max drawdown
    worst = top5.iloc[0]

    # 4. Underwater curve
    uw = underwater_curve(equity)
    uw_df = uw.reset_index()
    uw_df.columns = ['date', 'underwater_pct']

    # 5. Output CSV — top 5 drawdowns
    top5.to_csv('backtests/drawdown_analysis.csv', index=False)

    # 6. Print summary
    print(f"Backtest: {args.csv_path}  ({len(equity)} trading days)")
    print(f"Period: {equity.index[0].date()} to {equity.index[-1].date()}")
    print()
    print(f"Max Drawdown: {worst['depth_pct']:.2f}%")
    print(f"  Start:    {worst['start_date'].date()}")
    print(f"  Trough:   {worst['trough_date'].date()}")
    if worst['recovery_date'] is not None:
        print(f"  Recovery: {worst['recovery_date'].date()}")
    else:
        print(f"  Recovery: (ongoing)")
    print(f"  Duration: {worst['duration_days']} days to trough")
    if worst['recovery_days'] is not None:
        print(f"  Recovery: {worst['recovery_days']} days from trough")
    print()
    print("Top 5 Drawdowns:")
    print("-" * 80)
    for i, row in top5.iterrows():
        rec = (f"{int(row['recovery_days'])}d"
               if row['recovery_days'] is not None else "ongoing")
        print(f"  #{i+1}  {row['depth_pct']:>7.2f}%  "
              f"{row['start_date'].date()} -> {row['trough_date'].date()}  "
              f"duration={row['duration_days']}d  recovery={rec}")

    print()
    print(f"Output: backtests/drawdown_analysis.csv ({len(top5)} rows)")


if __name__ == '__main__':
    main()
