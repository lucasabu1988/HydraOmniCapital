"""Methodology — metrics computation and waterfall corrections.

All functions are pure: they take BacktestResult objects (or DataFrames)
and return new metrics or new results. No I/O, no side effects.
"""
from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd

from hydra_backtest.engine import BacktestResult


def compute_metrics(
    daily_values: pd.DataFrame,
    risk_free_rate_annual: float = 0.0,
) -> Dict[str, float]:
    """Compute standard performance metrics from a daily equity curve.

    `daily_values` must have columns ('date', 'portfolio_value').
    `risk_free_rate_annual` is in decimal (0.035 = 3.5%).
    """
    if len(daily_values) < 2:
        return {
            'cagr': 0.0, 'sharpe': 0.0, 'sortino': 0.0, 'calmar': 0.0,
            'max_drawdown': 0.0, 'volatility': 0.0, 'final_value': 0.0,
        }

    values = daily_values['portfolio_value'].astype(float).values
    dates = pd.to_datetime(daily_values['date'])
    start_val = float(values[0])
    final_val = float(values[-1])

    # CAGR
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.25
    if years <= 0 or start_val <= 0:
        cagr = 0.0
    else:
        cagr = (final_val / start_val) ** (1 / years) - 1

    # Daily returns
    returns = pd.Series(values).pct_change().dropna().values
    if len(returns) < 2:
        return {
            'cagr': float(cagr), 'sharpe': 0.0, 'sortino': 0.0, 'calmar': 0.0,
            'max_drawdown': 0.0, 'volatility': 0.0, 'final_value': final_val,
        }

    vol_ann = float(np.std(returns, ddof=1) * np.sqrt(252))

    daily_rf = risk_free_rate_annual / 252
    excess = returns - daily_rf
    excess_std = float(np.std(excess, ddof=1))
    sharpe = (
        float(np.mean(excess) * 252 / (excess_std * np.sqrt(252)))
        if excess_std > 0 else 0.0
    )

    downside = excess[excess < 0]
    if len(downside) > 1:
        downside_std = float(np.std(downside, ddof=1))
        sortino = (
            float(np.mean(excess) * 252 / (downside_std * np.sqrt(252)))
            if downside_std > 0 else 0.0
        )
    else:
        sortino = 0.0

    # Max drawdown
    peaks = np.maximum.accumulate(values)
    dd_series = (values - peaks) / peaks
    max_dd = float(dd_series.min())

    calmar = float(cagr / abs(max_dd)) if max_dd < 0 else 0.0

    return {
        'cagr': float(cagr),
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'max_drawdown': max_dd,
        'volatility': vol_ann,
        'final_value': final_val,
    }


# -----------------------------------------------------------------------------
# Waterfall report
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class WaterfallTier:
    """One tier of the methodology waterfall (e.g. baseline, +T-bill, +next-open)."""
    name: str
    description: str
    cagr: float
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown: float
    volatility: float
    final_value: float
    delta_cagr_bps: float = 0.0
    delta_sharpe: float = 0.0
    delta_maxdd_bps: float = 0.0


@dataclass(frozen=True)
class WaterfallReport:
    """Full waterfall across all tiers + the two end-point backtest results."""
    tiers: List[WaterfallTier]
    baseline_result: BacktestResult
    net_honest_result: BacktestResult


def apply_slippage_postprocess(
    result: BacktestResult,
    slippage_bps: float,
    half_spread_bps: float,
) -> BacktestResult:
    """Apply per-trade slippage + half-spread to an existing BacktestResult.

    Works as post-process because costs are a small fraction that does not
    alter signal/stop decisions. Entry and exit prices are each penalized
    by (slippage + half_spread) bps, and the equity curve is rebuilt by
    propagating the extra cost forward from each trade's exit date.
    """
    if result.trades.empty:
        return result

    total_bps = (slippage_bps + half_spread_bps) / 10000.0
    trades = result.trades.copy()

    adjusted_entry = trades['entry_price'] * (1 + total_bps)
    adjusted_exit = trades['exit_price'] * (1 - total_bps)
    trades['entry_price'] = adjusted_entry
    trades['exit_price'] = adjusted_exit
    trades['pnl'] = (adjusted_exit - adjusted_entry) * trades['shares']
    # Guard against entry_price == 0 (shouldn't happen in practice)
    trades['return'] = trades['pnl'] / (adjusted_entry * trades['shares']).replace(0, np.nan)
    trades['return'] = trades['return'].fillna(0.0)

    # Rebuild equity curve by subtracting the extra cost starting at each exit_date.
    daily = result.daily_values.copy()
    daily_dates = pd.to_datetime(daily['date'])

    for _, trade in trades.iterrows():
        notional = abs(trade['shares'] * (trade['entry_price'] + trade['exit_price']) / 2.0)
        extra_cost = notional * 2 * total_bps  # round trip
        mask = daily_dates >= pd.to_datetime(trade['exit_date'])
        daily.loc[mask, 'portfolio_value'] -= extra_cost

    return BacktestResult(
        config=result.config,
        daily_values=daily,
        trades=trades,
        decisions=result.decisions,
        exit_events=result.exit_events,
        universe_size=result.universe_size,
        started_at=result.started_at,
        finished_at=result.finished_at,
        git_sha=result.git_sha,
        data_inputs_hash=result.data_inputs_hash,
    )


def _tier_from_result(
    name: str,
    description: str,
    result: BacktestResult,
    rf: float = 0.0,
) -> WaterfallTier:
    m = compute_metrics(result.daily_values, risk_free_rate_annual=rf)
    return WaterfallTier(
        name=name,
        description=description,
        cagr=m['cagr'],
        sharpe=m['sharpe'],
        sortino=m['sortino'],
        calmar=m['calmar'],
        max_drawdown=m['max_drawdown'],
        volatility=m['volatility'],
        final_value=m['final_value'],
    )


def _with_deltas(tiers: List[WaterfallTier]) -> List[WaterfallTier]:
    """Return a new list of tiers with delta_* fields populated vs. previous tier."""
    if not tiers:
        return tiers
    out = [tiers[0]]
    for i in range(1, len(tiers)):
        prev = out[i - 1]
        curr = tiers[i]
        out.append(WaterfallTier(
            name=curr.name,
            description=curr.description,
            cagr=curr.cagr,
            sharpe=curr.sharpe,
            sortino=curr.sortino,
            calmar=curr.calmar,
            max_drawdown=curr.max_drawdown,
            volatility=curr.volatility,
            final_value=curr.final_value,
            delta_cagr_bps=(curr.cagr - prev.cagr) * 10000.0,
            delta_sharpe=(curr.sharpe - prev.sharpe),
            delta_maxdd_bps=(curr.max_drawdown - prev.max_drawdown) * 10000.0,
        ))
    return out


def build_waterfall(
    tier_0: BacktestResult,
    tier_1: BacktestResult,
    tier_2: BacktestResult,
    t_bill_rf: float,
    slippage_bps: float,
    half_spread_bps: float,
) -> WaterfallReport:
    """Build a full WaterfallReport from 3 backtest runs + post-processing.

    Tiers:
      - tier_0: baseline (Aaa cash, same_close execution)
      - tier_1: + T-bill cash yield (re-run)
      - tier_2: + next_open execution (re-run)
      - tier_3 / real_costs: + slippage + half-spread (post-process of tier_2)
      - net_honest: alias for real_costs
    """
    tier_3_result = apply_slippage_postprocess(tier_2, slippage_bps, half_spread_bps)

    tiers_raw = [
        _tier_from_result('baseline',
                          'Live methodology (Aaa cash, same-close exec)',
                          tier_0, rf=0.0),
        _tier_from_result('t_bill', '+ T-bill 3M cash yield', tier_1, rf=t_bill_rf),
        _tier_from_result('next_open', '+ next-open execution', tier_2, rf=t_bill_rf),
        _tier_from_result('real_costs', '+ slippage and half-spread',
                          tier_3_result, rf=t_bill_rf),
    ]
    # net_honest is an alias for real_costs (same numbers, different name for
    # reporting clarity).
    real_costs_tier = tiers_raw[-1]
    tiers_raw.append(WaterfallTier(
        name='net_honest',
        description='NET HONEST — all corrections applied',
        cagr=real_costs_tier.cagr,
        sharpe=real_costs_tier.sharpe,
        sortino=real_costs_tier.sortino,
        calmar=real_costs_tier.calmar,
        max_drawdown=real_costs_tier.max_drawdown,
        volatility=real_costs_tier.volatility,
        final_value=real_costs_tier.final_value,
    ))
    tiers_with_deltas = _with_deltas(tiers_raw)

    return WaterfallReport(
        tiers=tiers_with_deltas,
        baseline_result=tier_0,
        net_honest_result=tier_3_result,
    )
