"""Quick test: Hold 5d vs 6d"""
import importlib
import omnicapital_vortex_v3_sweep as v3
importlib.reload(v3)

price_data = v3.download_broad_pool()
spy_data = v3.download_spy()
annual_universe = v3.compute_annual_top40(price_data)
regime = v3.compute_regime(spy_data)

all_dates = set()
for df in price_data.values():
    all_dates.update(df.index)
all_dates = sorted(list(all_dates))
first_date = all_dates[0]

print("\n" + "=" * 70)
print("HOLD PERIOD TEST: 5d vs 6d")
print("=" * 70)
print(f"{'Hold':<6} {'CAGR':>8} {'Sharpe':>8} {'MaxDD':>8} {'Final':>14} {'Trades':>7}")
print("-" * 55)

for hold in [4, 5, 6, 7, 8]:
    params = {
        'momentum_lookback': 90,
        'momentum_skip': 5,
        'hold_days': hold,
        'num_positions': 5,
        'target_vol': 0.15,
    }
    r = v3.run_parametric_backtest(
        price_data, annual_universe, spy_data, regime, all_dates, first_date, params
    )
    print(f"{hold}d{' *' if hold==5 else '  ':<4} {r['cagr']:>7.2%} {r['sharpe']:>8.3f} "
          f"{r['max_dd']:>7.1%} ${r['final']:>12,.0f} {r['trades']:>7}")

print("\n  * = COMPASS v8.2 baseline")
