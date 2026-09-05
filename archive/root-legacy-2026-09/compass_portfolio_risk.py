import math
from datetime import datetime

import numpy as np
import pandas as pd


RISK_LOOKBACK_DAYS = 30
VAR_Z_95 = 1.645


def _coerce_price(value, default=0.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return value


def _extract_close_series(df):
    if df is None or len(df) == 0:
        return None
    if 'Adj Close' in df.columns:
        series = df['Adj Close']
    elif 'Close' in df.columns:
        series = df['Close']
    else:
        return None
    series = pd.to_numeric(series, errors='coerce').dropna()
    if len(series) < 2:
        return None
    return series


def _label_for_score(score):
    if score < 30:
        return 'LOW'
    if score < 60:
        return 'MODERATE'
    if score < 80:
        return 'HIGH'
    return 'EXTREME'


def compute_portfolio_risk(state, prices, hist_data):
    positions = dict(state.get('positions') or {})
    position_meta = dict(state.get('position_meta') or {})
    cash = _coerce_price(state.get('cash'), 0.0)
    prices = dict(prices or {})
    hist_data = dict(hist_data or {})

    position_values = {}
    sector_weights = {}
    total_positions_value = 0.0

    for symbol, pos_data in positions.items():
        if not isinstance(pos_data, dict):
            continue
        shares = _coerce_price(pos_data.get('shares'), 0.0)
        entry_price = _coerce_price(position_meta.get(symbol, {}).get('entry_price') or pos_data.get('avg_cost'), 0.0)
        price = _coerce_price(prices.get(symbol), entry_price)
        market_value = max(0.0, shares * price)
        if market_value <= 0:
            continue

        position_values[symbol] = market_value
        total_positions_value += market_value

    portfolio_value = _coerce_price(
        state.get('portfolio_value'),
        cash + total_positions_value,
    )
    if total_positions_value > 0:
        portfolio_value = max(portfolio_value, cash + total_positions_value)
    if portfolio_value <= 0:
        portfolio_value = cash + total_positions_value
    if portfolio_value <= 0:
        portfolio_value = 1.0

    if not position_values:
        return {
            'computed_at': datetime.now().isoformat(),
            'portfolio_value': round(portfolio_value, 2),
            'cash': round(cash, 2),
            'num_positions': 0,
            'lookback_days': RISK_LOOKBACK_DAYS,
            'concentration_risk': 0.0,
            'sector_concentration': 0.0,
            'correlation_risk': 0.0,
            'var_95': 0.0,
            'var_95_pct': 0.0,
            'max_position_pct': 0.0,
            'beta': 0.0,
            'risk_score': 0.0,
            'risk_label': 'LOW',
        }

    weights = {}
    for symbol, market_value in position_values.items():
        weight = market_value / portfolio_value
        weights[symbol] = weight
        sector = (position_meta.get(symbol) or {}).get('sector', 'Unknown')
        sector_weights[sector] = sector_weights.get(sector, 0.0) + weight

    concentration_risk = sum(weight ** 2 for weight in weights.values())
    sector_concentration = max(sector_weights.values(), default=0.0) * 100.0
    max_position_pct = max(weights.values(), default=0.0) * 100.0

    returns_map = {}
    for symbol in position_values:
        close_series = _extract_close_series(hist_data.get(symbol))
        if close_series is None:
            continue
        returns = close_series.pct_change().dropna()
        if len(returns) >= 5:
            returns_map[symbol] = returns.tail(RISK_LOOKBACK_DAYS)

    correlation_risk = 0.0
    portfolio_returns = None
    if len(returns_map) >= 2:
        returns_frame = pd.DataFrame(returns_map).dropna(how='any')
        if len(returns_frame) >= 2:
            corr_matrix = returns_frame.corr()
            mask = np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)
            off_diag = corr_matrix.where(mask).stack()
            if len(off_diag) > 0:
                correlation_risk = float(off_diag.mean())
            weight_vector = np.array(
                [weights.get(symbol, 0.0) for symbol in returns_frame.columns],
                dtype=float,
            )
            portfolio_returns = returns_frame.mul(weight_vector, axis=1).sum(axis=1)
    elif len(returns_map) == 1:
        only_symbol = next(iter(returns_map))
        portfolio_returns = returns_map[only_symbol] * weights.get(only_symbol, 0.0)

    portfolio_vol = 0.0
    if portfolio_returns is not None and len(portfolio_returns) >= 2:
        portfolio_vol = float(portfolio_returns.std(ddof=0))

    var_horizon_scale = math.sqrt(RISK_LOOKBACK_DAYS)
    var_95_pct = portfolio_vol * VAR_Z_95 * var_horizon_scale * 100.0
    var_95 = portfolio_value * portfolio_vol * VAR_Z_95 * var_horizon_scale

    beta = 0.0
    spy_returns = None
    spy_close_series = _extract_close_series(hist_data.get('SPY'))
    if spy_close_series is not None:
        spy_returns = spy_close_series.pct_change().dropna().tail(RISK_LOOKBACK_DAYS)
    if portfolio_returns is not None and spy_returns is not None:
        joined = pd.concat(
            [portfolio_returns.rename('portfolio'), spy_returns.rename('spy')],
            axis=1,
        ).dropna()
        if len(joined) >= 2:
            spy_var = float(joined['spy'].var(ddof=0))
            if spy_var > 0:
                beta = float(joined['portfolio'].cov(joined['spy'], ddof=0) / spy_var)

    concentration_component = min(100.0, concentration_risk * 100.0)
    sector_component = min(100.0, sector_concentration)
    correlation_component = min(100.0, max(0.0, correlation_risk) * 100.0)
    var_component = min(100.0, var_95_pct)
    max_position_component = min(100.0, max_position_pct)
    beta_component = min(100.0, max(0.0, abs(beta) - 1.0) * 50.0)

    risk_score = (
        concentration_component * 0.22
        + sector_component * 0.18
        + correlation_component * 0.16
        + var_component * 0.22
        + max_position_component * 0.12
        + beta_component * 0.10
    )
    if max_position_pct >= 80.0 or concentration_risk >= 0.5:
        concentration_floor = 65.0 + min(25.0, var_component * 0.25)
        risk_score = max(risk_score, concentration_floor)
    risk_score = max(0.0, min(100.0, risk_score))

    return {
        'computed_at': datetime.now().isoformat(),
        'portfolio_value': round(portfolio_value, 2),
        'cash': round(cash, 2),
        'num_positions': len(position_values),
        'lookback_days': RISK_LOOKBACK_DAYS,
        'concentration_risk': round(concentration_risk, 4),
        'sector_concentration': round(sector_concentration, 2),
        'correlation_risk': round(correlation_risk, 3),
        'var_95': round(var_95, 2),
        'var_95_pct': round(var_95_pct, 2),
        'max_position_pct': round(max_position_pct, 2),
        'beta': round(beta, 2),
        'risk_score': round(risk_score, 1),
        'risk_label': _label_for_score(risk_score),
    }
