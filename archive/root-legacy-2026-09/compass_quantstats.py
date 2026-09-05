import logging
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
import quantstats as qs

logger = logging.getLogger(__name__)

_tearsheet_lock = threading.Lock()
_TEARSHEET_TTL = 3600

BACKTEST_CSV = Path(__file__).parent / "backtests" / "hydra_clean_daily.csv"
STATE_JSON = Path(__file__).parent / "state" / "compass_state_latest.json"
DEFAULT_TEARSHEET = Path(__file__).parent / "static" / "reports" / "tearsheet.html"


def load_returns(source="backtest"):
    if source == "backtest":
        return _load_backtest_returns()
    elif source == "live":
        return _load_live_returns()
    raise ValueError(f"Unknown source: {source}")


def _load_backtest_returns():
    df = pd.read_csv(BACKTEST_CSV, parse_dates=["date"], index_col="date")
    returns = df["value"].pct_change().dropna()
    returns.index.name = None
    return returns


def _load_live_returns():
    import json
    with open(STATE_JSON) as f:
        state = json.load(f)
    values = state.get("portfolio_values_history", [])
    if len(values) < 2:
        return pd.Series(dtype=float)
    values = values[:-1]
    returns = pd.Series(values).pct_change().dropna()
    end_date = pd.Timestamp(state.get("last_trading_date", pd.Timestamp.now().date()))
    end_date = end_date - pd.offsets.BDay(1)
    dates = pd.bdate_range(end=end_date, periods=len(returns))
    returns.index = dates
    return returns


def compute_metrics(returns, benchmark=None):
    metrics = {
        'sharpe': qs.stats.sharpe(returns),
        'sortino': qs.stats.sortino(returns),
        'max_drawdown': qs.stats.max_drawdown(returns),
        'calmar': qs.stats.calmar(returns),
        'cagr': qs.stats.cagr(returns),
        'volatility': qs.stats.volatility(returns),
        'var_95': qs.stats.var(returns),
        'cvar_95': qs.stats.cvar(returns),
        'win_rate': qs.stats.win_rate(returns),
        'profit_factor': qs.stats.profit_factor(returns),
        'best_day': qs.stats.best(returns),
        'worst_day': qs.stats.worst(returns),
        'avg_return': qs.stats.avg_return(returns),
        'avg_win': qs.stats.avg_win(returns),
        'avg_loss': qs.stats.avg_loss(returns),
        'payoff_ratio': qs.stats.payoff_ratio(returns),
        'skew': qs.stats.skew(returns),
        'kurtosis': qs.stats.kurtosis(returns),
    }
    for k, v in metrics.items():
        if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
            metrics[k] = None
    return metrics


def generate_tearsheet(returns, benchmark=None, output_path=None):
    if output_path is None:
        output_path = str(DEFAULT_TEARSHEET)
    output_path = str(output_path)

    path = Path(output_path)
    if path.exists():
        age = time.time() - path.stat().st_mtime
        if age < _TEARSHEET_TTL:
            return output_path

    acquired = _tearsheet_lock.acquire(blocking=False)
    if not acquired:
        return output_path

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if benchmark is not None:
            qs.reports.html(returns, benchmark, output=output_path)
        else:
            qs.reports.html(returns, output=output_path)
        logger.info(f"Tearsheet generated: {output_path}")
    finally:
        _tearsheet_lock.release()

    return output_path


def get_rolling_metrics(returns, window=63):
    rolling_sharpe = qs.stats.rolling_sharpe(returns, rolling_period=window)
    rolling_sortino = qs.stats.rolling_sortino(returns, rolling_period=window)
    rolling_vol = qs.stats.rolling_volatility(returns, rolling_period=window)

    df = pd.DataFrame({
        'rolling_sharpe': rolling_sharpe,
        'rolling_sortino': rolling_sortino,
        'rolling_vol': rolling_vol,
    }, index=returns.index)
    return df
