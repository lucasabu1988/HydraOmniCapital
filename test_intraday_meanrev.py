"""
Test: Intraday Gap CONTINUATION with COMPASS Reserve Cash
========================================================
- If SPY opens DOWN vs previous close -> SHORT at Open, cover at Close (expect continuation down)
- If SPY opens UP vs previous close -> BUY at Open, sell at Close (expect continuation up)
- Uses only the reserve cash from COMPASS (not invested in positions)
- No leverage, no liquidating existing positions
- Proxy: Open->Close return (real would be 11:30->14:00)
"""
import pandas as pd
import numpy as np
import pickle
import os
import warnings
warnings.filterwarnings('ignore')

# Load SPY data
cache_file = 'data_cache/SPY_2000-01-01_2026-02-09.csv'
spy = pd.read_csv(cache_file, index_col=0, parse_dates=True)
print(f"SPY data: {len(spy)} days ({spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')})")

# Load COMPASS daily portfolio values to get reserve cash
compass_daily = pd.read_csv('backtests/v8_compass_daily.csv')
compass_daily['date'] = pd.to_datetime(compass_daily['date'])
compass_daily = compass_daily.set_index('date')
print(f"COMPASS daily data: {len(compass_daily)} days")

# ============================================================================
# STRATEGY: Intraday mean-reversion on SPY using reserve cash
# ============================================================================

COMMISSION_PER_TRADE = 1.0  # $1 per trade
SLIPPAGE_BPS = 5            # 5 bps round-trip slippage
INITIAL_CAPITAL = 100_000

print("\n" + "=" * 75)
print("INTRADAY GAP CONTINUATION TEST (REVERSED)")
print("Gap down -> Short Open, cover Close | Gap up -> Buy Open, sell Close")
print("Using COMPASS reserve cash only, no leverage")
print("=" * 75)

# Track results
trades = []
daily_pnl = []

for i in range(1, len(spy)):
    date = spy.index[i]
    prev_close = spy['Close'].iloc[i-1]
    today_open = spy['Open'].iloc[i]
    today_close = spy['Close'].iloc[i]

    if prev_close <= 0 or today_open <= 0:
        daily_pnl.append({'date': date, 'pnl': 0, 'direction': 'skip', 'cash_used': 0})
        continue

    # Gap = (Open - PrevClose) / PrevClose
    gap = (today_open - prev_close) / prev_close

    # Get reserve cash from COMPASS for this date
    if date in compass_daily.index:
        reserve_cash = compass_daily.loc[date, 'cash']
    else:
        # Find nearest prior date
        prior = compass_daily.index[compass_daily.index <= date]
        if len(prior) == 0:
            daily_pnl.append({'date': date, 'pnl': 0, 'direction': 'skip', 'cash_used': 0})
            continue
        reserve_cash = compass_daily.loc[prior[-1], 'cash']

    # Only use 90% of reserve cash (keep buffer)
    available = reserve_cash * 0.90

    if available < 500:
        daily_pnl.append({'date': date, 'pnl': 0, 'direction': 'skip', 'cash_used': 0})
        continue

    # Determine direction
    if abs(gap) < 0.0005:  # Gap too small (<0.05%), skip
        daily_pnl.append({'date': date, 'pnl': 0, 'direction': 'flat', 'cash_used': 0})
        continue

    if gap < 0:
        # Gap DOWN -> continuation = SHORT (expect further decline)
        direction = 'short'
        intraday_return = (today_open - today_close) / today_open
    else:
        # Gap UP -> continuation = LONG (expect further rise)
        direction = 'long'
        intraday_return = (today_close - today_open) / today_open

    # Calculate P&L
    shares = available / today_open
    gross_pnl = shares * today_open * intraday_return
    slippage = available * SLIPPAGE_BPS / 10000
    net_pnl = gross_pnl - COMMISSION_PER_TRADE * 2 - slippage  # 2 trades (open + close)

    trades.append({
        'date': date,
        'direction': direction,
        'gap': gap,
        'intraday_return': intraday_return,
        'cash_used': available,
        'gross_pnl': gross_pnl,
        'net_pnl': net_pnl,
    })
    daily_pnl.append({'date': date, 'pnl': net_pnl, 'direction': direction, 'cash_used': available})

# ============================================================================
# RESULTS
# ============================================================================

trades_df = pd.DataFrame(trades)
pnl_df = pd.DataFrame(daily_pnl)

total_pnl = trades_df['net_pnl'].sum()
num_trades = len(trades_df)
wins = (trades_df['net_pnl'] > 0).sum()
losses = (trades_df['net_pnl'] <= 0).sum()
win_rate = wins / num_trades if num_trades > 0 else 0
avg_win = trades_df.loc[trades_df['net_pnl'] > 0, 'net_pnl'].mean() if wins > 0 else 0
avg_loss = trades_df.loc[trades_df['net_pnl'] <= 0, 'net_pnl'].mean() if losses > 0 else 0
avg_cash_used = trades_df['cash_used'].mean()

# Long vs Short breakdown
longs = trades_df[trades_df['direction'] == 'long']
shorts = trades_df[trades_df['direction'] == 'short']

print(f"\n--- Overall ---")
print(f"Total trades:          {num_trades:>10,}")
print(f"Total net P&L:         ${total_pnl:>12,.2f}")
print(f"Win rate:              {win_rate:>10.1%}")
print(f"Avg winner:            ${avg_win:>12,.2f}")
print(f"Avg loser:             ${avg_loss:>12,.2f}")
print(f"Avg cash used/trade:   ${avg_cash_used:>12,.2f}")
print(f"P&L per trade:         ${total_pnl/num_trades:>12,.2f}")

print(f"\n--- Long (gap up -> buy) ---")
print(f"Trades:                {len(longs):>10,}")
print(f"Win rate:              {(longs['net_pnl']>0).mean():>10.1%}")
print(f"Total P&L:             ${longs['net_pnl'].sum():>12,.2f}")

print(f"\n--- Short (gap down -> sell) ---")
print(f"Trades:                {len(shorts):>10,}")
print(f"Win rate:              {(shorts['net_pnl']>0).mean():>10.1%}")
print(f"Total P&L:             ${shorts['net_pnl'].sum():>12,.2f}")

# By year
print(f"\n--- Annual Breakdown ---")
trades_df['year'] = trades_df['date'].dt.year
annual = trades_df.groupby('year').agg(
    trades=('net_pnl', 'count'),
    total_pnl=('net_pnl', 'sum'),
    win_rate=('net_pnl', lambda x: (x > 0).mean()),
    avg_cash=('cash_used', 'mean'),
).round(2)
print(f"{'Year':<6} {'Trades':>7} {'P&L':>12} {'WinRate':>8} {'AvgCash':>10}")
print("-" * 45)
for year, row in annual.iterrows():
    print(f"{year:<6} {int(row['trades']):>7} ${row['total_pnl']:>10,.0f} "
          f"{row['win_rate']:>7.1%} ${row['avg_cash']:>9,.0f}")

# Combined with COMPASS
print(f"\n--- Impact on COMPASS ---")
compass_final = compass_daily['value'].iloc[-1]
combined_final = compass_final + total_pnl
years = len(spy) / 252
compass_cagr = (compass_final / INITIAL_CAPITAL) ** (1/years) - 1
combined_cagr = (combined_final / INITIAL_CAPITAL) ** (1/years) - 1

print(f"COMPASS final:         ${compass_final:>12,.0f}  ({compass_cagr:.2%} CAGR)")
print(f"Intraday P&L:          ${total_pnl:>12,.0f}")
print(f"Combined final:        ${combined_final:>12,.0f}  ({combined_cagr:.2%} CAGR)")
print(f"CAGR delta:            {combined_cagr - compass_cagr:>+11.2%}")
