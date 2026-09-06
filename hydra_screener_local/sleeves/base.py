"""Sleeve protocol (TASK-366). Engine untouched; this is the seam, not a new signal."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd


@dataclass
class MarketSlice:
    """One day's inputs, shared across sleeves. A sleeve reads what it needs and ignores the rest.

    `tbill` is the daily rate (annualised ^IRX / 252), indexed like `etf_closes` — the same
    series `core.portfolio_engine.etf_targets` already receives.
    """
    stock_prices: pd.DataFrame
    volumes: pd.DataFrame
    spy: pd.Series
    etf_closes: pd.DataFrame
    tbill: pd.Series
    ranking: pd.DataFrame


class Sleeve(Protocol):
    name: str
    cost_bp: float

    def targets(self, market: MarketSlice, held: set, cfg: dict) -> pd.Series:
        """Target weights of the sleeve's renewed-tranche capital. Sum <= 1; remainder is T-bill."""
        ...
