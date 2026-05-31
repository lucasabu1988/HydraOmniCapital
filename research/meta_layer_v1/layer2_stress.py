"""Phase 5 - Layer 2 Robustness / Stress Period Utilities (Scaffolding)

Provides helpers for running and analyzing performance over major
historical stress windows (2008, 2020, 2022, etc.).
"""

from dataclasses import dataclass
from typing import List, Dict
import pandas as pd


STRESS_PERIODS = [
    ("2008_GFC", "2007-10-01", "2009-03-31"),
    ("2020_COVID", "2020-02-01", "2020-05-31"),
    ("2022_Bear", "2022-01-01", "2022-12-31"),
]


@dataclass
class StressPeriodResult:
    name: str
    start: str
    end: str
    cagr: float
    max_dd: float
    calmar: float


def analyze_stress_periods(
    daily_df: pd.DataFrame,
    periods: List[tuple] = None,
) -> List[StressPeriodResult]:
    """Compute performance restricted to each stress window."""
    if periods is None:
        periods = STRESS_PERIODS

    results = []
    for name, start, end in periods:
        mask = (daily_df.index >= start) & (daily_df.index <= end)
        sub = daily_df.loc[mask]
        if len(sub) < 30:
            continue

        equity = sub['portfolio_value']
        ret = equity.pct_change().dropna()
        years = max((equity.index[-1] - equity.index[0]).days / 365.25, 0.01)
        cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1
        peak = equity.cummax()
        dd = (equity - peak) / peak
        max_dd = dd.min()
        calmar = cagr / abs(max_dd) if max_dd < 0 else float('inf')

        results.append(StressPeriodResult(
            name=name,
            start=start,
            end=end,
            cagr=round(cagr * 100, 2),
            max_dd=round(max_dd * 100, 2),
            calmar=round(calmar, 3),
        ))
    return results


if __name__ == "__main__":
    print("Layer 2 stress utilities loaded. Defined periods:", len(STRESS_PERIODS))
