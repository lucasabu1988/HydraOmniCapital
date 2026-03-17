"""TypedDict response models for COMPASS API endpoints.

Used for test-time structural validation — not enforced at runtime.
"""

from typing import Dict, List, Optional
from typing_extensions import TypedDict


class StateResponse(TypedDict, total=False):
    status: str
    positions: Dict
    cash: float
    portfolio_value: float
    regime_score: Optional[float]
    trading_day_counter: int
    server_time: str
    engine: Dict
    portfolio: Dict
    position_details: List
    prices: Dict
    prev_closes: Dict
    universe: List[str]
    universe_year: Optional[int]
    config: Dict
    chassis: Dict
    preclose: Dict
    hydra: Dict
    implementation_shortfall: Dict
    state_recovery: Optional[str]
    message: str
    error: str


STATE_RESPONSE_REQUIRED_KEYS = {
    'status', 'positions', 'cash', 'portfolio_value',
    'trading_day_counter', 'server_time',
}


class CycleLogEntry(TypedDict, total=False):
    cycle_number: int
    start_date: Optional[str]
    end_date: Optional[str]
    cycle_return_pct: Optional[float]
    status: str
    hydra_return: float
    spy_return: float
    alpha: float
    portfolio_start: float
    portfolio_end: float
    spy_start: float
    spy_end: float
    positions_current: List[str]


CYCLE_LOG_ENTRY_REQUIRED_KEYS = {
    'cycle_number', 'start_date', 'end_date', 'cycle_return_pct',
}


class FanChart(TypedDict, total=False):
    days: List[int]
    p5: List[float]
    p10: List[float]
    p25: List[float]
    p50: List[float]
    p75: List[float]
    p90: List[float]
    p95: List[float]


FAN_CHART_REQUIRED_KEYS = {'days', 'p5', 'p10', 'p25', 'p50', 'p75', 'p90', 'p95'}


class MonteCarloResponse(TypedDict, total=False):
    fan_chart: FanChart
    summary: Dict
    seed: int
    source: str
    historical_stats: Dict
    error: str


MONTECARLO_RESPONSE_REQUIRED_KEYS = {
    'fan_chart', 'summary', 'seed', 'source',
}


class RiskResponse(TypedDict, total=False):
    computed_at: str
    portfolio_value: float
    cash: float
    num_positions: int
    lookback_days: int
    concentration_risk: float
    sector_concentration: float
    correlation_risk: float
    var_95: float
    var_95_pct: float
    max_position_pct: float
    beta: float
    risk_score: float
    risk_label: str
    error: str


RISK_RESPONSE_REQUIRED_KEYS = {
    'risk_score', 'risk_label', 'concentration_risk', 'var_95', 'beta',
}


class EngineHealth(TypedDict, total=False):
    running: bool
    uptime_minutes: Optional[float]
    cycles_completed: int
    engine_iterations: int
    last_cycle_at: Optional[str]
    ml_errors: Dict


class DataFeedHealth(TypedDict, total=False):
    last_price_update: Optional[str]
    price_age_seconds: Optional[float]
    consecutive_failures: int
    cache_size: int


class PortfolioHealth(TypedDict, total=False):
    value: float
    num_positions: int
    cash: float
    drawdown_pct: Optional[float]


class HealthResponse(TypedDict, total=False):
    status: str
    timestamp: str
    engine_running: bool
    price_freshness: Optional[float]
    engine: EngineHealth
    data_feed: DataFeedHealth
    portfolio: PortfolioHealth
    state: Dict
    git_sync: Dict


HEALTH_RESPONSE_REQUIRED_KEYS = {
    'status', 'engine_running', 'price_freshness',
}
