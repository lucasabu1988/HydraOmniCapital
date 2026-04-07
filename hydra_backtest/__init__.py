"""hydra_backtest — reproducible COMPASS standalone backtest.

See docs/superpowers/specs/2026-04-06-hydra-reproducible-backtest-design.md
for the design and docs/superpowers/plans/2026-04-06-hydra-reproducible-backtest.md
for the implementation plan.
"""
from hydra_backtest.data import (
    compute_data_fingerprint,
    load_pit_universe,
    load_price_history,
    load_sector_map,
    load_spy_data,
    load_vix_series,
    load_yield_series,
    validate_config,
)
from hydra_backtest.engine import (
    BacktestResult,
    BacktestState,
    run_backtest,
)
from hydra_backtest.errors import (
    HydraBacktestError,
    HydraBacktestLookaheadError,
    HydraBacktestValidationError,
    HydraDataError,
)
from hydra_backtest.methodology import (
    WaterfallReport,
    WaterfallTier,
    build_waterfall,
    compute_metrics,
)
from hydra_backtest.reporting import (
    format_summary_table,
    write_daily_csv,
    write_trades_csv,
    write_waterfall_json,
)
from hydra_backtest.validation import run_smoke_tests

__all__ = [
    # errors
    'HydraBacktestError', 'HydraDataError',
    'HydraBacktestValidationError', 'HydraBacktestLookaheadError',
    # data
    'validate_config', 'load_pit_universe', 'load_sector_map',
    'load_price_history', 'load_spy_data', 'load_vix_series',
    'load_yield_series', 'compute_data_fingerprint',
    # engine
    'BacktestState', 'BacktestResult', 'run_backtest',
    # methodology
    'WaterfallTier', 'WaterfallReport', 'build_waterfall', 'compute_metrics',
    # validation
    'run_smoke_tests',
    # reporting
    'write_daily_csv', 'write_trades_csv', 'write_waterfall_json',
    'format_summary_table',
]
