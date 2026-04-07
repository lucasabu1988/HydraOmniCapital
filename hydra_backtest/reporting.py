"""Reporting — output writers for CSVs, JSON, and stdout summary."""
import json
import os

from hydra_backtest.engine import BacktestResult
from hydra_backtest.methodology import WaterfallReport


def _ensure_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def write_daily_csv(result: BacktestResult, path: str) -> None:
    """Write the daily equity curve as CSV.

    Columns: date, portfolio_value, cash, n_positions, leverage, drawdown,
             regime_score, crash_active, max_positions
    """
    _ensure_dir(path)
    result.daily_values.to_csv(path, index=False)


def write_trades_csv(result: BacktestResult, path: str) -> None:
    """Write all trades as CSV."""
    _ensure_dir(path)
    result.trades.to_csv(path, index=False)


def write_waterfall_json(report: WaterfallReport, path: str) -> None:
    """Write the waterfall report as JSON.

    Schema:
        {
            "tiers": [
                {"name", "description", "cagr", "sharpe", "sortino",
                 "calmar", "max_drawdown", "volatility", "final_value",
                 "delta_cagr_bps", "delta_sharpe", "delta_maxdd_bps"},
                ...
            ],
            "metadata": {"git_sha", "data_inputs_hash",
                         "started_at", "finished_at"}
        }
    """
    _ensure_dir(path)
    baseline = report.baseline_result
    data = {
        'tiers': [
            {
                'name': t.name,
                'description': t.description,
                'cagr': t.cagr,
                'sharpe': t.sharpe,
                'sortino': t.sortino,
                'calmar': t.calmar,
                'max_drawdown': t.max_drawdown,
                'volatility': t.volatility,
                'final_value': t.final_value,
                'delta_cagr_bps': t.delta_cagr_bps,
                'delta_sharpe': t.delta_sharpe,
                'delta_maxdd_bps': t.delta_maxdd_bps,
            }
            for t in report.tiers
        ],
        'metadata': {
            'git_sha': baseline.git_sha,
            'data_inputs_hash': baseline.data_inputs_hash,
            'started_at': baseline.started_at.isoformat(),
            'finished_at': baseline.finished_at.isoformat(),
        },
    }
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def format_summary_table(report: WaterfallReport) -> str:
    """Render the waterfall as a fixed-width ASCII table for stdout."""
    lines = []
    lines.append('=' * 90)
    lines.append(
        f"{'Tier':<14} {'CAGR':>8} {'Sharpe':>8} "
        f"{'MaxDD':>10} {'Sortino':>9} {'Final':>18}"
    )
    lines.append('-' * 90)
    for t in report.tiers:
        cagr_pct = t.cagr * 100
        mdd_pct = t.max_drawdown * 100
        line = (
            f"{t.name:<14} {cagr_pct:>7.2f}% {t.sharpe:>8.3f} "
            f"{mdd_pct:>9.2f}% {t.sortino:>9.3f} ${t.final_value:>16,.0f}"
        )
        lines.append(line)
        if t.delta_cagr_bps != 0:
            lines.append(
                f"{'':<14}  Δ vs prev: {t.delta_cagr_bps:+.1f} bp CAGR, "
                f"{t.delta_sharpe:+.3f} Sharpe, {t.delta_maxdd_bps:+.0f} bp MaxDD"
            )
    lines.append('=' * 90)
    return '\n'.join(lines)
