#!/usr/bin/env python
"""
Phase 5 Validation Harness Runner - Meta-Layer v1 A/B Testing

This is the main driver for heavier validation work.
It runs clean A/B backtests (Meta-Layer ON vs OFF) using the
integrated hydra_backtest.hydra harness and collects metrics
for the official validation_report.md.
"""

import argparse
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any

import pandas as pd

# Robust import for the hydra_backtest harness
import sys
from pathlib import Path

# When running this script from research/meta_layer_v1/, add the project root
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from hydra_backtest import (
        load_catalyst_assets,
        load_efa_series,
        load_pit_universe,
        load_price_history,
        load_sector_map,
        load_spy_data,
        load_vix_series,
        load_yield_series,
    )
    from hydra_backtest.hydra import run_hydra_backtest
    HARNESS_AVAILABLE = True
except ImportError as e:
    HARNESS_AVAILABLE = False
    print(f"WARNING: hydra_backtest package not importable: {e}")
    print("Make sure you are running from the project root or have the package in PYTHONPATH.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def compute_metrics(daily: pd.DataFrame, initial_capital: float = 100_000.0) -> Dict[str, float]:
    """Compute standard performance metrics from daily equity curve."""
    if daily.empty or 'portfolio_value' not in daily.columns:
        return {"error": "empty_or_invalid"}

    equity = daily['portfolio_value'].astype(float)
    returns = equity.pct_change().dropna()

    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 0.01)
    cagr = (equity.iloc[-1] / initial_capital) ** (1 / years) - 1
    total_return = equity.iloc[-1] / initial_capital - 1

    peak = equity.cummax()
    dd = (equity - peak) / peak
    max_dd = dd.min()

    calmar = cagr / abs(max_dd) if max_dd < 0 else float('inf')

    vol = returns.std() * (252 ** 0.5)
    sharpe = (returns.mean() * 252) / vol if vol > 0 else 0.0

    return {
        "cagr": round(cagr * 100, 2),
        "total_return_pct": round(total_return * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "calmar": round(calmar, 3),
        "sharpe": round(sharpe, 3),
        "ann_vol_pct": round(vol * 100, 2),
        "n_days": len(equity),
    }


def run_ab_backtest(
    config: Dict[str, Any],
    start: str,
    end: str,
    out_dir: Path,
    use_real_data: bool = True,
) -> Dict[str, Any]:
    """Run A/B (meta off vs on) and return structured results."""
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Loading data for {start} to {end}...")

    # Load data (same as the official hydra harness)
    pit_universe = load_pit_universe()
    price_data = load_price_history()
    spy_data = load_spy_data()
    vix_data = load_vix_series()
    catalyst_assets = load_catalyst_assets()
    efa_data = load_efa_series()
    cash_yield = load_yield_series()
    sector_map = load_sector_map()

    results = {
        "meta_off": {},
        "meta_on": {},
        "period": {"start": start, "end": end},
        "timestamp": datetime.now().isoformat(),
    }

    if not HARNESS_AVAILABLE:
        logger.error("Cannot run real backtests — harness not importable. Exiting.")
        return results

    for use_meta, label in [(False, "meta_off"), (True, "meta_on")]:
        logger.info(f"Running {label} (use_meta_layer={use_meta}) ...")

        result = run_hydra_backtest(
            config=config,
            price_data=price_data,
            pit_universe=pit_universe,
            spy_data=spy_data,
            vix_data=vix_data,
            catalyst_assets=catalyst_assets,
            efa_data=efa_data,
            cash_yield_daily=cash_yield,
            sector_map=sector_map,
            start_date=pd.Timestamp(start),
            end_date=pd.Timestamp(end),
            execution_mode="same_close",
            use_meta_layer=use_meta,
        )

        daily = result.daily_values
        metrics = compute_metrics(daily)

        # Save outputs
        daily_path = out_dir / f"{label}_daily.csv"
        daily.to_csv(daily_path, index=False)

        trades_path = out_dir / f"{label}_trades.csv"
        if not result.trades.empty:
            result.trades.to_csv(trades_path, index=False)

        results[label] = {
            "metrics": metrics,
            "daily_file": str(daily_path),
            "trades_file": str(trades_path) if not result.trades.empty else None,
            "meta_columns_present": any("meta_" in c for c in daily.columns),
        }

        logger.info(f"{label} complete: CAGR={metrics.get('cagr')}%, MaxDD={metrics.get('max_drawdown_pct')}%")

    # Write summary
    summary_path = out_dir / "ab_validation_summary.json"
    summary_path.write_text(json.dumps(results, indent=2, default=str))
    logger.info(f"A/B summary written to {summary_path}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Phase 5 Meta-Layer A/B Validation Runner")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--output-dir", default="research/meta_layer_v1/runs/dev", help="Where to write outputs")
    parser.add_argument("--full-validation", action="store_true", help="Mark this as part of the full 4-layer protocol run")
    parser.add_argument("--data-dir", default="data_cache", help="Directory containing the required .pkl/.csv data files")
    args = parser.parse_args()

    out_dir = Path(args.output_dir) / f"{args.start}_to_{args.end}".replace("-", "")
    out_dir.mkdir(parents=True, exist_ok=True)

    data_dir = Path(args.data_dir)

    # Production-like config
    config = {
        "INITIAL_CAPITAL": 100_000,
        "BASE_COMPASS_ALLOC": 0.425,
        "BASE_RATTLE_ALLOC": 0.425,
        "BASE_CATALYST_ALLOC": 0.15,
        "MOMENTUM_LOOKBACK": 90,
        "MOMENTUM_SKIP": 5,
        "NUM_POSITIONS": 5,
        "NUM_POSITIONS_RISK_OFF": 2,
        "HOLD_DAYS": 5,
        "HOLD_DAYS_MAX": 10,
        "RENEWAL_PROFIT_MIN": 0.04,
        "POSITION_STOP_LOSS": -0.08,
        "TRAILING_ACTIVATION": 0.05,
        "TRAILING_STOP_PCT": 0.03,
        "STOP_DAILY_VOL_MULT": 2.5,
        "BULL_OVERRIDE_THRESHOLD": 0.03,
        "MAX_PER_SECTOR": 3,
        "DD_SCALE_TIER1": -0.10,
        "DD_SCALE_TIER2": -0.20,
        "DD_SCALE_TIER3": -0.35,
        "LEV_FULL": 1.0,
        "LEV_MID": 0.60,
        "LEV_FLOOR": 0.30,
        "CRASH_VEL_5D": -0.06,
        "CRASH_VEL_10D": -0.10,
        "CRASH_LEVERAGE": 0.15,
        "CRASH_COOLDOWN": 10,
        "QUALITY_VOL_MAX": 0.60,
        "QUALITY_VOL_LOOKBACK": 63,
        "TARGET_VOL": 0.15,
        "LEVERAGE_MAX": 1.0,
        "VOL_LOOKBACK": 20,
        "TOP_N": 40,
        "MIN_AGE_DAYS": 63,
        "COMMISSION_PER_SHARE": 0.001,
        "EFA_MIN_BUY": 1000.0,
        "EFA_DEPLOYMENT_CAP": 0.90,
    }

    logger.info(f"Starting Phase 5 A/B validation run: {args.start} → {args.end}")
    if args.full_validation:
        logger.info("Marked as FULL validation protocol run")

    # Build full paths for the loaders
    data_paths = {
        "pit_universe": str(data_dir / "sp500_constituents_history.pkl"),
        "price_history": str(data_dir / "sp500_universe_prices.pkl"),
        # Add other expected files here as needed by the loaders
    }

    results = run_ab_backtest(config, args.start, args.end, out_dir, data_paths=data_paths)

    off = results["meta_off"]["metrics"]
    on = results["meta_on"]["metrics"]
    print("\n=== A/B Quick Comparison ===")
    print(f"Meta OFF:  CAGR {off.get('cagr')}% | MaxDD {off.get('max_drawdown_pct')}% | Calmar {off.get('calmar')}")
    print(f"Meta ON :  CAGR {on.get('cagr')}% | MaxDD {on.get('max_drawdown_pct')}% | Calmar {on.get('calmar')}")
    print(f"Results saved to: {out_dir}")


if __name__ == "__main__":
    main()
