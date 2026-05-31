"""Phase 5 - Layer 1 Structural Validation Utilities

Reusable helpers for:
- Walk-forward window generation
- Purged cross-validation splits
- Regime-stratified performance analysis
"""

from dataclasses import dataclass
from typing import List
import pandas as pd
import numpy as np


@dataclass
class ValidationWindow:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    embargo_days: int = 5


def generate_walk_forward_windows(
    start_date: str,
    end_date: str,
    train_years: int = 10,
    test_years: int = 2,
    step_months: int = 12,
    embargo_days: int = 5,
) -> List[ValidationWindow]:
    """Generate rolling walk-forward windows with embargo."""
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    windows = []
    current = start

    while True:
        train_end = current + pd.DateOffset(years=train_years)
        test_end = train_end + pd.DateOffset(years=test_years)

        if test_end > end:
            break

        windows.append(ValidationWindow(
            train_start=current,
            train_end=train_end - pd.Timedelta(days=1),
            test_start=train_end,
            test_end=min(test_end, end),
            embargo_days=embargo_days,
        ))
        current += pd.DateOffset(months=step_months)

    return windows


def purged_train_test_split(
    all_dates: pd.DatetimeIndex,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    embargo_days: int = 5,
) -> tuple:
    """Return train and test date ranges with purging."""
    embargo_start = test_start - pd.Timedelta(days=embargo_days)
    embargo_end = test_end + pd.Timedelta(days=embargo_days)

    train_mask = (all_dates < embargo_start) | (all_dates > embargo_end)
    test_mask = (all_dates >= test_start) & (all_dates <= test_end)

    return all_dates[train_mask], all_dates[test_mask]


def regime_stratified_metrics(
    daily_df: pd.DataFrame,
    regime_column: str = 'regime_score',
    bull_threshold: float = 0.5,
) -> dict:
    """Split performance by broad regime."""
    if daily_df.empty or regime_column not in daily_df.columns:
        return {}

    daily_df = daily_df.copy()
    daily_df['regime_label'] = np.where(daily_df[regime_column] >= bull_threshold, 'bullish', 'bearish')

    results = {}
    for label, group in daily_df.groupby('regime_label'):
        if len(group) < 20:
            continue
        equity = group['portfolio_value']
        ret = equity.pct_change().dropna()
        years = max((equity.index[-1] - equity.index[0]).days / 365.25, 0.01)
        cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1
        vol = ret.std() * (252 ** 0.5)
        sharpe = (ret.mean() * 252) / vol if vol > 0 else 0.0
        results[label] = {
            'cagr': round(cagr * 100, 2),
            'sharpe': round(sharpe, 3),
            'n_days': len(group),
        }
    return results


if __name__ == "__main__":
    print("Layer 1 utilities loaded successfully")
    wins = generate_walk_forward_windows("2000-01-01", "2026-01-01", train_years=8, test_years=2)
    print(f"Generated {len(wins)} walk-forward windows")
