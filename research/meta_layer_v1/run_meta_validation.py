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

    # Robust year calculation - handle both DatetimeIndex and integer index
    try:
        if pd.api.types.is_datetime64_any_dtype(equity.index):
            years = max((equity.index[-1] - equity.index[0]).days / 365.25, 0.01)
        else:
            # Fallback for integer or other index types (e.g. day count)
            years = max(len(returns) / 252.0, 0.01)
    except Exception:
        years = max(len(returns) / 252.0, 0.01)

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
    data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run A/B (meta off vs on) and return structured results."""
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Loading data for {start} to {end}...")

    data_dir = data_dir or Path("data_cache")

    # Load using current project data layout (broad_pool pickle is the modern source)
    broad_pool_path = data_dir / "broad_pool_2000-01-01_2026-02-09.pkl"
    if broad_pool_path.exists():
        import pickle
        with open(broad_pool_path, 'rb') as f:
            price_data = pickle.load(f)
        logger.info(f"Loaded {len(price_data)} tickers from broad_pool pickle")
    else:
        price_data = load_price_history(str(data_dir / "sp500_universe_prices.pkl"))

    # Simplified PIT universe for longer validation runs (all tickers active in recent years)
    recent_tickers = list(price_data.keys())[:800]  # cap for performance
    pit_universe = {year: recent_tickers for year in range(2010, 2027)}

    spy_path = data_dir / "SPY_2000-01-01_2026-02-09.csv"
    spy_data = load_spy_data(str(spy_path)) if spy_path.exists() else load_spy_data(str(data_dir / "SPY_2000-01-01_2027-01-01.csv"))

    vix_path = data_dir / "vix_history.csv"
    vix_data = load_vix_series(str(vix_path)) if vix_path.exists() else pd.Series(dtype=float)

    cat_path = data_dir / "catalyst_assets.pkl"
    catalyst_assets = load_catalyst_assets(str(cat_path)) if cat_path.exists() else {}

    efa_path = data_dir / "efa_history.pkl"
    efa_data = load_efa_series(str(efa_path)) if efa_path.exists() else pd.DataFrame()

    yield_path = data_dir / "moody_aaa_yield.csv"
    cash_yield = load_yield_series(str(yield_path)) if yield_path.exists() else pd.Series(dtype=float)

    sector_path = data_dir / "sp500_sector_map.json"
    sector_map = load_sector_map(str(sector_path)) if sector_path.exists() else {}

    results = {
        "meta_off": {},
        "meta_on": {},
        "period": {"start": start, "end": end},
        "timestamp": datetime.now().isoformat(),
    }

    if not HARNESS_AVAILABLE:
        logger.error("Cannot run real backtests — harness not importable. Exiting.")
        return results

    # Comprehensive defaults for all known required keys in the HYDRA engine (prevents KeyError on long runs)
    defaults = {
        'BULL_OVERRIDE_MIN_SCORE': 0.40,
        'BULL_OVERRIDE_THRESHOLD': 0.03,
        'QUALITY_MAX_SINGLE_DAY': 0.50,
        'QUALITY_VOL_MAX': 0.60,
        'QUALITY_VOL_LOOKBACK': 63,
        'CRASH_VEL_5D': -0.06,
        'CRASH_VEL_10D': -0.10,
        'CRASH_LEVERAGE': 0.15,
        'CRASH_COOLDOWN': 10,
        'MARGIN_RATE': 0.06,
        'TARGET_VOL': 0.15,
        'VOL_LOOKBACK': 20,
        'LEV_FLOOR': 0.30,
        'LEVERAGE_MAX': 1.0,
        'MIN_AGE_DAYS': 63,
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
        'MAX_PER_SECTOR': 3,
        'DD_SCALE_TIER1': -0.10,
        'DD_SCALE_TIER2': -0.20,
        'DD_SCALE_TIER3': -0.35,
        'LEV_FULL': 1.0,
        'LEV_MID': 0.60,
        'COMMISSION_PER_SHARE': 0.001,
        'EFA_MIN_BUY': 1000.0,
        'EFA_DEPLOYMENT_CAP': 0.90,
        'MIN_MOMENTUM_STOCKS': 20,
        'MOMENTUM_RENEWAL_THRESHOLD': 0.85,
    }
    for k, v in defaults.items():
        config.setdefault(k, v)

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

    # Try to load the full project default config (best for long runs)
    try:
        from hydra_backtest.hydra.__main__ import _CONFIG as PROJECT_CONFIG
        config = dict(PROJECT_CONFIG)
        logger.info("Loaded complete project default config")
    except Exception:
        logger.warning("Could not import project _CONFIG, using fallback (may miss keys)")
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

        # Missing keys from previous runs
        "BULL_OVERRIDE_MIN_SCORE": 0.40,
        "MARGIN_RATE": 0.06,
        "COMMISSION_PER_SHARE": 0.001,
        "TARGET_VOL": 0.15,
        "VOL_LOOKBACK": 20,
        "LEV_FLOOR": 0.30,
        "LEVERAGE_MAX": 1.0,
    }

    logger.info(f"Starting Phase 5 A/B validation run: {args.start} to {args.end}")
    if args.full_validation:
        logger.info("Marked as FULL validation protocol run")

    results = run_ab_backtest(config, args.start, args.end, out_dir, data_dir=data_dir)

    off = results["meta_off"]["metrics"]
    on = results["meta_on"]["metrics"]
    print("\n=== A/B Quick Comparison ===")
    print(f"Meta OFF:  CAGR {off.get('cagr')}% | MaxDD {off.get('max_drawdown_pct')}% | Calmar {off.get('calmar')}")
    print(f"Meta ON :  CAGR {on.get('cagr')}% | MaxDD {on.get('max_drawdown_pct')}% | Calmar {on.get('calmar')}")
    print(f"Results saved to: {out_dir}")


if __name__ == "__main__":
    main()
