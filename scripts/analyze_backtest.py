import pandas as pd
import numpy as np

def analyze_backtest(csv_path, spy_csv_path):
    df = pd.read_csv(csv_path, parse_dates=['date'])
    df['year'] = df['date'].dt.year
    df['month'] = df['date'].dt.month
    
    # Ensure value column exists
    val_col = 'portfolio_value' if 'portfolio_value' in df.columns else 'value'
    
    # 1. Annual Returns
    annual_returns = []
    for year, group in df.groupby('year'):
        start_val = group[val_col].iloc[0]
        end_val = group[val_col].iloc[-1]
        ret = (end_val / start_val) - 1
        annual_returns.append({'year': year, 'return': ret})
    
    annual_df = pd.DataFrame(annual_returns)
    best_3 = annual_df.nlargest(3, 'return')
    worst_3 = annual_df.nsmallest(3, 'return')
    
    # 2. Drawdowns
    df['peak'] = df[val_col].cummax()
    df['drawdown'] = (df[val_col] - df['peak']) / df['peak']
    
    # Find drawdown periods
    drawdowns = []
    in_drawdown = False
    start_idx = 0
    peak_val = 0
    
    for i in range(len(df)):
        if df['drawdown'].iloc[i] < 0:
            if not in_drawdown:
                in_drawdown = True
                start_idx = i
                peak_val = df['peak'].iloc[i]
        else:
            if in_drawdown:
                in_drawdown = False
                end_idx = i
                duration = end_idx - start_idx
                min_dd = df['drawdown'].iloc[start_idx:end_idx].min()
                drawdowns.append({
                    'start_date': df['date'].iloc[start_idx],
                    'end_date': df['date'].iloc[end_idx],
                    'duration': duration,
                    'depth': min_dd
                })
                
    drawdowns_df = pd.DataFrame(drawdowns)
    longest_5 = drawdowns_df.nlargest(5, 'duration')
    
    # 3. Rolling 1-year returns
    # Assuming ~252 trading days per year
    df['return_1y'] = df[val_col].pct_change(252)
    positive_windows = (df['return_1y'] > 0).mean()
    
    # 4. Seasonality
    df['monthly_return'] = df[val_col].pct_change(21) # Approx monthly
    seasonality = df.groupby('month')['monthly_return'].mean()
    strongest_month = seasonality.idxmax()
    weakest_month = seasonality.idxmin()

    # 5. Consecutive losing weeks (5-day periods)
    df['return_5d'] = df[val_col].pct_change(5)
    df['is_losing_week'] = df['return_5d'] < 0
    
    max_consecutive = 0
    current_consecutive = 0
    for is_loss in df['is_losing_week']:
        if is_loss:
            current_consecutive += 1
            max_consecutive = max(max_consecutive, current_consecutive)
        else:
            current_consecutive = 0
            
    # 6. Comparison with SPY (simplified)
    # Load SPY data
    spy_df = pd.read_csv(spy_csv_path, parse_dates=['date'])
    spy_df['peak'] = spy_df['close'].cummax()
    spy_df['drawdown'] = (spy_df['close'] - spy_df['peak']) / spy_df['peak']
    
    # Define crisis periods
    periods = {
        '2008 Crisis': ('2008-01-01', '2009-03-09'),
        'COVID Crash': ('2020-02-19', '2020-03-23'),
        '2022 Bear': ('2022-01-03', '2022-10-12')
    }
    
    comparison = {}
    for name, (start, end) in periods.items():
        hydra_dd = df[(df['date'] >= start) & (df['date'] <= end)]['drawdown'].min()
        spy_dd = spy_df[(spy_df['date'] >= start) & (spy_df['date'] <= end)]['drawdown'].min()
        comparison[name] = {'HYDRA': hydra_dd, 'SPY': spy_dd}

    print("--- Analysis Results ---")
    print(f"Best 3 Years:\n{best_3}")
    print(f"Worst 3 Years:\n{worst_3}")
    print(f"Longest 5 Drawdowns:\n{longest_5}")
    print(f"Rolling 1-Year Positive %: {positive_windows:.2%}")
    print(f"Strongest Month: {strongest_month}, Weakest Month: {weakest_month}")
    print(f"Max Consecutive Losing Weeks: {max_consecutive}")
    print(f"Crisis Comparison:\n{comparison}")

if __name__ == "__main__":
    analyze_backtest('backtests/hydra_clean_daily.csv', 'backtests/spy_benchmark.csv')
