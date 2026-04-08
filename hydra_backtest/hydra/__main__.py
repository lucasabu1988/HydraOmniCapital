"""CLI entrypoint: python -m hydra_backtest.hydra

Loads all four pillar inputs, runs 3 HYDRA backtest tiers
(baseline + T-bill + next-open), post-processes for slippage tier,
writes CSV + JSON outputs (including Layer B comparison report),
and prints a waterfall summary.
"""
import argparse
import json
import os
import sys

import pandas as pd

from hydra_backtest import (
    build_waterfall,
    format_summary_table,
    load_catalyst_assets,
    load_efa_series,
    load_pit_universe,
    load_price_history,
    load_sector_map,
    load_spy_data,
    load_vix_series,
    load_yield_series,
    write_daily_csv,
    write_trades_csv,
    write_waterfall_json,
)
from hydra_backtest.hydra import (
    compute_layer_b_report,
    run_hydra_backtest,
    run_hydra_smoke_tests,
)


_CONFIG = {
    # COMPASS (matches hydra_backtest/tests/conftest.py minimal_config)
    'MOMENTUM_LOOKBACK': 90,
    'MOMENTUM_SKIP': 5,
    'MIN_MOMENTUM_STOCKS': 20,
    'NUM_POSITIONS': 5,
    'NUM_POSITIONS_RISK_OFF': 2,
    'HOLD_DAYS': 5,
    'HOLD_DAYS_MAX': 10,
    'RENEWAL_PROFIT_MIN': 0.04,
    'MOMENTUM_RENEWAL_THRESHOLD': 0.85,
    'POSITION_STOP_LOSS': -0.08,
    'TRAILING_ACTIVATION': 0.05,
    'TRAILING_STOP_PCT': 0.03,
    'STOP_DAILY_VOL_MULT': 2.5,
    'STOP_FLOOR': -0.06,
    'STOP_CEILING': -0.15,
    'TRAILING_VOL_BASELINE': 0.25,
    'BULL_OVERRIDE_THRESHOLD': 0.03,
    'BULL_OVERRIDE_MIN_SCORE': 0.40,
    'MAX_PER_SECTOR': 3,
    'DD_SCALE_TIER1': -0.10,
    'DD_SCALE_TIER2': -0.20,
    'DD_SCALE_TIER3': -0.35,
    'LEV_FULL': 1.0,
    'LEV_MID': 0.60,
    'LEV_FLOOR': 0.30,
    'CRASH_VEL_5D': -0.06,
    'CRASH_VEL_10D': -0.10,
    'CRASH_LEVERAGE': 0.15,
    'CRASH_COOLDOWN': 10,
    'QUALITY_VOL_MAX': 0.60,
    'QUALITY_VOL_LOOKBACK': 63,
    'QUALITY_MAX_SINGLE_DAY': 0.50,
    'TARGET_VOL': 0.15,
    'LEVERAGE_MAX': 1.0,
    'VOL_LOOKBACK': 20,
    'TOP_N': 40,
    'MIN_AGE_DAYS': 63,
    'INITIAL_CAPITAL': 100_000,
    'MARGIN_RATE': 0.06,
    'COMMISSION_PER_SHARE': 0.001,
    # HYDRA-specific
    'BASE_COMPASS_ALLOC': 0.425,
    'BASE_RATTLE_ALLOC': 0.425,
    'BASE_CATALYST_ALLOC': 0.15,
    'MAX_COMPASS_ALLOC': 0.75,
    'EFA_LIQUIDATION_CASH_THRESHOLD_PCT': 0.20,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog='python -m hydra_backtest.hydra',
        description='Reproducible full HYDRA standalone backtest.',
    )
    parser.add_argument('--start', type=str, default='2000-01-01')
    parser.add_argument('--end', type=str, default='2026-03-05')
    parser.add_argument('--out-dir', type=str, default='backtests/hydra_v1')
    parser.add_argument('--constituents', type=str,
                        default='data_cache/sp500_constituents_history.pkl')
    parser.add_argument('--prices', type=str,
                        default='data_cache/sp500_universe_prices.pkl')
    parser.add_argument('--sectors', type=str,
                        default='data_cache/sp500_sector_map.json')
    parser.add_argument('--spy', type=str,
                        default='data_cache/SPY_2000-01-01_2027-01-01.csv')
    parser.add_argument('--vix', type=str,
                        default='data_cache/vix_history.csv')
    parser.add_argument('--catalyst-assets', type=str,
                        default='data_cache/catalyst_assets.pkl')
    parser.add_argument('--efa', type=str,
                        default='data_cache/efa_history.pkl')
    parser.add_argument('--aaa', type=str,
                        default='data_cache/moody_aaa_yield.csv')
    parser.add_argument('--tbill', type=str,
                        default='data_cache/tbill_3m_fred.csv')
    parser.add_argument('--aaa-date-col', type=str, default='observation_date')
    parser.add_argument('--aaa-value-col', type=str, default='yield_pct')
    parser.add_argument('--tbill-date-col', type=str, default='DATE')
    parser.add_argument('--tbill-value-col', type=str, default='DGS3MO')
    parser.add_argument('--slippage-bps', type=float, default=2.0)
    parser.add_argument('--half-spread-bps', type=float, default=0.5)
    parser.add_argument('--t-bill-rf', type=float, default=0.03)
    args = parser.parse_args(argv)

    print("Loading data...", flush=True)
    pit = load_pit_universe(args.constituents)
    prices = load_price_history(args.prices)
    sector_map = load_sector_map(args.sectors)
    spy = load_spy_data(args.spy)
    vix = load_vix_series(args.vix)
    catalyst_assets = load_catalyst_assets(args.catalyst_assets)
    efa = load_efa_series(args.efa)
    aaa = load_yield_series(args.aaa, date_col=args.aaa_date_col,
                            value_col=args.aaa_value_col)
    tbill = load_yield_series(args.tbill, date_col=args.tbill_date_col,
                              value_col=args.tbill_value_col)
    print(
        f"  PIT: {len(pit)} years, prices: {len(prices)} tickers, "
        f"catalyst: {len(catalyst_assets)} ETFs, EFA: {len(efa)} rows",
        flush=True,
    )

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)

    def _make_progress_cb(tier_name):
        def _cb(info):
            print(
                f"  [{tier_name}] {info['year']}: "
                f"{info['progress_pct']:5.1f}% | "
                f"PV ${info['portfolio_value']:>12,.0f} | "
                f"{info['n_positions']} pos | "
                f"recycled {info.get('recycled_pct', 0) * 100:.0f}%",
                flush=True,
            )
        return _cb

    print("\nTier 0: baseline (Aaa, same-close)", flush=True)
    tier_0 = run_hydra_backtest(
        config=_CONFIG, price_data=prices, pit_universe=pit, spy_data=spy,
        vix_data=vix, catalyst_assets=catalyst_assets, efa_data=efa,
        cash_yield_daily=aaa, sector_map=sector_map,
        start_date=start, end_date=end, execution_mode='same_close',
        progress_callback=_make_progress_cb('tier0'),
    )
    run_hydra_smoke_tests(tier_0)
    print("  tier 0 smoke tests: PASSED", flush=True)

    print("\nTier 1: + T-bill cash yield", flush=True)
    tier_1 = run_hydra_backtest(
        config=_CONFIG, price_data=prices, pit_universe=pit, spy_data=spy,
        vix_data=vix, catalyst_assets=catalyst_assets, efa_data=efa,
        cash_yield_daily=tbill, sector_map=sector_map,
        start_date=start, end_date=end, execution_mode='same_close',
        progress_callback=_make_progress_cb('tier1'),
    )
    run_hydra_smoke_tests(tier_1)
    print("  tier 1 smoke tests: PASSED", flush=True)

    print("\nTier 2: + next-open execution", flush=True)
    tier_2 = run_hydra_backtest(
        config=_CONFIG, price_data=prices, pit_universe=pit, spy_data=spy,
        vix_data=vix, catalyst_assets=catalyst_assets, efa_data=efa,
        cash_yield_daily=tbill, sector_map=sector_map,
        start_date=start, end_date=end, execution_mode='next_open',
        progress_callback=_make_progress_cb('tier2'),
    )
    run_hydra_smoke_tests(tier_2)
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

    # Layer B comparison (informational, non-blocking)
    layer_b = compute_layer_b_report(tier_0.daily_values)
    with open(os.path.join(args.out_dir, 'layer_b_report.json'), 'w') as f:
        json.dump(layer_b, f, indent=2, default=str)
    verdict = layer_b.get('verdict', layer_b.get('status'))
    print(f"\n  Layer B vs hydra_clean_daily.csv: {verdict}", flush=True)
    if layer_b.get('status') == 'COMPLETE':
        print(
            f"    Spearman: {layer_b['spearman']:.4f} | "
            f"Pearson: {layer_b['pearson']:.4f} | "
            f"MAE: ${layer_b['mae']:,.0f} | "
            f"max_err: ${layer_b['max_err']:,.0f}",
            flush=True,
        )

    print('\n' + format_summary_table(report), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
