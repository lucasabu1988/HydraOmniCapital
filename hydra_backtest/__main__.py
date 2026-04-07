"""CLI entrypoint: python -m hydra_backtest

Reads PIT data from data_cache/, runs 3 backtests (baseline, +T-bill,
+next-open), post-processes for the slippage tier, writes CSV + JSON
outputs, and prints a waterfall summary to stdout.
"""
import argparse
import os
import sys

import pandas as pd

from hydra_backtest import (
    build_waterfall,
    format_summary_table,
    load_pit_universe,
    load_price_history,
    load_sector_map,
    load_spy_data,
    load_yield_series,
    run_backtest,
    run_smoke_tests,
    validate_config,
    write_daily_csv,
    write_trades_csv,
    write_waterfall_json,
)


# Canonical COMPASS config — matches omnicapital_live.CONFIG (see spec §4.2).
_CONFIG = {
    'MOMENTUM_LOOKBACK': 90, 'MOMENTUM_SKIP': 5, 'MIN_MOMENTUM_STOCKS': 20,
    'NUM_POSITIONS': 5, 'NUM_POSITIONS_RISK_OFF': 2, 'HOLD_DAYS': 5,
    'HOLD_DAYS_MAX': 10, 'RENEWAL_PROFIT_MIN': 0.04,
    'MOMENTUM_RENEWAL_THRESHOLD': 0.85,
    'POSITION_STOP_LOSS': -0.08, 'TRAILING_ACTIVATION': 0.05,
    'TRAILING_STOP_PCT': 0.03,
    'STOP_DAILY_VOL_MULT': 2.5, 'STOP_FLOOR': -0.06, 'STOP_CEILING': -0.15,
    'TRAILING_VOL_BASELINE': 0.25,
    'BULL_OVERRIDE_THRESHOLD': 0.03, 'BULL_OVERRIDE_MIN_SCORE': 0.40,
    'MAX_PER_SECTOR': 3,
    'DD_SCALE_TIER1': -0.10, 'DD_SCALE_TIER2': -0.20, 'DD_SCALE_TIER3': -0.35,
    'LEV_FULL': 1.0, 'LEV_MID': 0.60, 'LEV_FLOOR': 0.30,
    'CRASH_VEL_5D': -0.06, 'CRASH_VEL_10D': -0.10,
    'CRASH_LEVERAGE': 0.15, 'CRASH_COOLDOWN': 10,
    'QUALITY_VOL_MAX': 0.60, 'QUALITY_VOL_LOOKBACK': 63,
    'QUALITY_MAX_SINGLE_DAY': 0.50,
    'TARGET_VOL': 0.15, 'LEVERAGE_MAX': 1.0, 'VOL_LOOKBACK': 20,
    'TOP_N': 40, 'MIN_AGE_DAYS': 63,
    'INITIAL_CAPITAL': 100_000, 'MARGIN_RATE': 0.06,
    'COMMISSION_PER_SHARE': 0.0035,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog='python -m hydra_backtest',
        description='Reproducible COMPASS standalone backtest with waterfall reporting.',
    )
    parser.add_argument('--start', type=str, default='2000-01-01',
                        help='Backtest start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, default='2026-03-05',
                        help='Backtest end date (YYYY-MM-DD)')
    parser.add_argument('--out-dir', type=str, default='backtests',
                        help='Output directory for CSVs and JSON')
    parser.add_argument('--constituents', type=str,
                        default='data_cache/sp500_constituents_history.pkl')
    parser.add_argument('--prices', type=str,
                        default='data_cache/sp500_universe_prices.pkl')
    parser.add_argument('--sectors', type=str,
                        default='data_cache/sp500_sector_map.json')
    parser.add_argument('--spy', type=str,
                        default='data_cache/SPY_2000-01-01_2027-01-01.csv')
    parser.add_argument('--aaa', type=str,
                        default='data_cache/moody_aaa_yield.csv')
    parser.add_argument('--tbill', type=str,
                        default='data_cache/tbill_3m.csv')
    parser.add_argument('--aaa-date-col', type=str, default='DATE')
    parser.add_argument('--aaa-value-col', type=str, default='DAAA')
    parser.add_argument('--tbill-date-col', type=str, default='DATE')
    parser.add_argument('--tbill-value-col', type=str, default='DGS3MO')
    parser.add_argument('--slippage-bps', type=float, default=2.0)
    parser.add_argument('--half-spread-bps', type=float, default=0.5)
    parser.add_argument('--t-bill-rf', type=float, default=0.03)
    args = parser.parse_args(argv)

    validate_config(_CONFIG)

    print("Loading data...", flush=True)
    pit = load_pit_universe(args.constituents)
    prices = load_price_history(args.prices)
    sectors = load_sector_map(args.sectors)
    spy = load_spy_data(args.spy)
    aaa_yield = load_yield_series(
        args.aaa, date_col=args.aaa_date_col, value_col=args.aaa_value_col,
    )
    tbill_yield = load_yield_series(
        args.tbill, date_col=args.tbill_date_col, value_col=args.tbill_value_col,
    )
    print(
        f"  PIT universe: {sum(len(v) for v in pit.values()) // max(len(pit), 1)} tickers/year avg, "
        f"{len(prices)} total tickers",
        flush=True,
    )

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)

    def _make_progress_cb(tier_name):
        def _cb(info):
            print(
                f"  [{tier_name}] {info['year']}: {info['progress_pct']:5.1f}% | "
                f"portfolio ${info['portfolio_value']:>12,.0f} | "
                f"{info['n_positions']} positions",
                flush=True,
            )
        return _cb

    print("\nTier 0: baseline (Aaa cash, same-close exec)", flush=True)
    tier_0 = run_backtest(
        config=_CONFIG, price_data=prices, pit_universe=pit, spy_data=spy,
        cash_yield_daily=aaa_yield, sector_map=sectors,
        start_date=start, end_date=end, execution_mode='same_close',
        progress_callback=_make_progress_cb('tier0'),
    )
    run_smoke_tests(tier_0)  # BLOCKING — Layer A
    print("  tier 0 smoke tests: PASSED", flush=True)

    print("\nTier 1: + T-bill cash yield", flush=True)
    tier_1 = run_backtest(
        config=_CONFIG, price_data=prices, pit_universe=pit, spy_data=spy,
        cash_yield_daily=tbill_yield, sector_map=sectors,
        start_date=start, end_date=end, execution_mode='same_close',
        progress_callback=_make_progress_cb('tier1'),
    )
    run_smoke_tests(tier_1)
    print("  tier 1 smoke tests: PASSED", flush=True)

    print("\nTier 2: + next-open execution", flush=True)
    tier_2 = run_backtest(
        config=_CONFIG, price_data=prices, pit_universe=pit, spy_data=spy,
        cash_yield_daily=tbill_yield, sector_map=sectors,
        start_date=start, end_date=end, execution_mode='next_open',
        progress_callback=_make_progress_cb('tier2'),
    )
    run_smoke_tests(tier_2)
    print("  tier 2 smoke tests: PASSED", flush=True)

    print("\nBuilding waterfall...", flush=True)
    report = build_waterfall(
        tier_0=tier_0, tier_1=tier_1, tier_2=tier_2,
        t_bill_rf=args.t_bill_rf,
        slippage_bps=args.slippage_bps,
        half_spread_bps=args.half_spread_bps,
    )

    os.makedirs(args.out_dir, exist_ok=True)
    write_daily_csv(tier_0, os.path.join(args.out_dir, 'hydra_v2_daily.csv'))
    write_trades_csv(tier_0, os.path.join(args.out_dir, 'hydra_v2_trades.csv'))
    write_waterfall_json(report, os.path.join(args.out_dir, 'hydra_v2_waterfall.json'))

    print('\n' + format_summary_table(report), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
