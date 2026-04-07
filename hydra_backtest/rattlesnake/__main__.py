"""CLI entrypoint: python -m hydra_backtest.rattlesnake

Reads PIT data from data_cache/, runs 3 Rattlesnake backtest tiers
(baseline + T-bill + next-open), post-processes for slippage tier,
writes CSV + JSON outputs, and prints a waterfall summary.
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
    load_spy_data,
    load_vix_series,
    load_yield_series,
    write_daily_csv,
    write_trades_csv,
    write_waterfall_json,
)
from hydra_backtest.rattlesnake import (
    run_rattlesnake_backtest,
    run_rattlesnake_smoke_tests,
)


# Rattlesnake config — subset of COMPASS keys (no leverage, no DD scaling).
_CONFIG = {
    'INITIAL_CAPITAL': 100_000,
    'COMMISSION_PER_SHARE': 0.0035,
    'NUM_POSITIONS': 5,
    'NUM_POSITIONS_RISK_OFF': 2,
    'MIN_AGE_DAYS': 220,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog='python -m hydra_backtest.rattlesnake',
        description='Reproducible Rattlesnake mean-reversion standalone backtest.',
    )
    parser.add_argument('--start', type=str, default='2000-01-01',
                        help='Backtest start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, default='2026-03-05',
                        help='Backtest end date (YYYY-MM-DD)')
    parser.add_argument('--out-dir', type=str, default='backtests/rattlesnake_v1',
                        help='Output directory for CSVs and JSON')
    parser.add_argument('--constituents', type=str,
                        default='data_cache/sp500_constituents_history.pkl')
    parser.add_argument('--prices', type=str,
                        default='data_cache/sp500_universe_prices.pkl')
    parser.add_argument('--spy', type=str,
                        default='data_cache/SPY_2000-01-01_2027-01-01.csv')
    parser.add_argument('--vix', type=str,
                        default='data_cache/vix_history.csv')
    parser.add_argument('--aaa', type=str,
                        default='data_cache/moody_aaa_yield.csv')
    parser.add_argument('--tbill', type=str,
                        default='data_cache/tbill_3m_fred.csv')
    parser.add_argument('--aaa-date-col', type=str, default='DATE')
    parser.add_argument('--aaa-value-col', type=str, default='DAAA')
    parser.add_argument('--tbill-date-col', type=str, default='DATE')
    parser.add_argument('--tbill-value-col', type=str, default='DGS3MO')
    parser.add_argument('--slippage-bps', type=float, default=2.0)
    parser.add_argument('--half-spread-bps', type=float, default=0.5)
    parser.add_argument('--t-bill-rf', type=float, default=0.03)
    args = parser.parse_args(argv)

    print("Loading data...", flush=True)
    pit = load_pit_universe(args.constituents)
    prices = load_price_history(args.prices)
    spy = load_spy_data(args.spy)
    vix = load_vix_series(args.vix)
    aaa_yield = load_yield_series(
        args.aaa, date_col=args.aaa_date_col, value_col=args.aaa_value_col,
    )
    tbill_yield = load_yield_series(
        args.tbill, date_col=args.tbill_date_col, value_col=args.tbill_value_col,
    )
    print(
        f"  PIT universe: {sum(len(v) for v in pit.values()) // max(len(pit), 1)} tickers/year avg, "
        f"{len(prices)} total tickers, VIX {len(vix)} bars",
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
    tier_0 = run_rattlesnake_backtest(
        config=_CONFIG, price_data=prices, pit_universe=pit, spy_data=spy,
        vix_data=vix, cash_yield_daily=aaa_yield,
        start_date=start, end_date=end, execution_mode='same_close',
        progress_callback=_make_progress_cb('tier0'),
    )
    run_rattlesnake_smoke_tests(tier_0)
    print("  tier 0 smoke tests: PASSED", flush=True)

    print("\nTier 1: + T-bill cash yield", flush=True)
    tier_1 = run_rattlesnake_backtest(
        config=_CONFIG, price_data=prices, pit_universe=pit, spy_data=spy,
        vix_data=vix, cash_yield_daily=tbill_yield,
        start_date=start, end_date=end, execution_mode='same_close',
        progress_callback=_make_progress_cb('tier1'),
    )
    run_rattlesnake_smoke_tests(tier_1)
    print("  tier 1 smoke tests: PASSED", flush=True)

    print("\nTier 2: + next-open execution", flush=True)
    tier_2 = run_rattlesnake_backtest(
        config=_CONFIG, price_data=prices, pit_universe=pit, spy_data=spy,
        vix_data=vix, cash_yield_daily=tbill_yield,
        start_date=start, end_date=end, execution_mode='next_open',
        progress_callback=_make_progress_cb('tier2'),
    )
    run_rattlesnake_smoke_tests(tier_2)
    print("  tier 2 smoke tests: PASSED", flush=True)

    print("\nBuilding waterfall...", flush=True)
    report = build_waterfall(
        tier_0=tier_0, tier_1=tier_1, tier_2=tier_2,
        t_bill_rf=args.t_bill_rf,
        slippage_bps=args.slippage_bps,
        half_spread_bps=args.half_spread_bps,
    )

    os.makedirs(args.out_dir, exist_ok=True)
    write_daily_csv(tier_0, os.path.join(args.out_dir, 'rattlesnake_v2_daily.csv'))
    write_trades_csv(tier_0, os.path.join(args.out_dir, 'rattlesnake_v2_trades.csv'))
    write_waterfall_json(report, os.path.join(args.out_dir, 'rattlesnake_v2_waterfall.json'))

    print('\n' + format_summary_table(report), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
