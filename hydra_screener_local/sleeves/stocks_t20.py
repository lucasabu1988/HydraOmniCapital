"""T20 stock-sleeve adapter (TASK-366). Delegates to `core.portfolio_engine.stock_targets`."""
from __future__ import annotations

import pandas as pd

from config import V9
from core.portfolio_engine import stock_targets
from sleeves.base import MarketSlice


class StocksT20:
    name = "stocks"

    def __init__(self, cost_bp: float | None = None):
        self.cost_bp = float(V9["stock_cost_bp"] if cost_bp is None else cost_bp)

    def targets(self, market: MarketSlice, held: set, cfg: dict) -> pd.Series:
        return stock_targets(market.ranking, set(held or ()), market.stock_prices, cfg)
