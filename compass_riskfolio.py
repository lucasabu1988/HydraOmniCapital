import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    import riskfolio as rp
    _riskfolio_available = True
except ImportError:
    _riskfolio_available = False
    logger.warning("riskfolio-lib not installed, only inv_vol method available")


def optimize_weights(symbols, hist_data=None, lookback=20, method="cascade"):
    available = [s for s in symbols if hist_data and s in hist_data]
    if not available and hist_data is not None:
        available = symbols
    if not available:
        available = symbols

    if hist_data is None:
        hist_data = _fetch_data(available, lookback=max(lookback, 63))

    available = [s for s in available if s in hist_data and len(hist_data[s]) >= lookback]
    if not available:
        raise ValueError("No symbols with sufficient historical data")

    if len(available) == 1:
        return {"weights": {available[0]: 1.0}, "method_used": "single", "metrics": {}}

    returns_df = _build_returns_df(available, hist_data, lookback=max(lookback, 63))

    n = len(available)
    if n < 3:
        w_min, w_max = 0.05, 0.95
    else:
        w_min, w_max = 0.05, 0.40

    if method == "cascade":
        return _cascade(available, returns_df, hist_data, lookback, w_min, w_max)
    elif method == "min_cvar":
        weights = _try_min_cvar(returns_df, w_min, w_max)
        return {"weights": dict(zip(available, weights)), "method_used": "min_cvar", "metrics": {}}
    elif method == "risk_parity":
        weights = _try_risk_parity(returns_df, w_min, w_max)
        return {"weights": dict(zip(available, weights)), "method_used": "risk_parity", "metrics": {}}
    elif method == "inv_vol":
        weights = _compute_inv_vol(available, hist_data, lookback)
        return {"weights": weights, "method_used": "inv_vol", "metrics": {}}
    else:
        raise ValueError(f"Unknown method: {method}")


def _cascade(available, returns_df, hist_data, lookback, w_min, w_max):
    if _riskfolio_available:
        try:
            weights = _try_min_cvar(returns_df, w_min, w_max)
            logger.info("Riskfolio: Min-CVaR optimization succeeded")
            return {"weights": dict(zip(available, weights)), "method_used": "min_cvar", "metrics": {}}
        except Exception as e:
            logger.info(f"Min-CVaR failed ({e}), trying Risk Parity")

        try:
            weights = _try_risk_parity(returns_df, w_min, w_max)
            logger.info("Riskfolio: Risk Parity optimization succeeded")
            return {"weights": dict(zip(available, weights)), "method_used": "risk_parity", "metrics": {}}
        except Exception as e:
            logger.info(f"Risk Parity failed ({e}), falling back to inv-vol")

    weights = _compute_inv_vol(available, hist_data, lookback)
    return {"weights": weights, "method_used": "inv_vol", "metrics": {}}


def _try_min_cvar(returns_df, w_min, w_max):
    port = rp.Portfolio(returns=returns_df)
    port.assets_stats(method_mu="hist", method_cov="hist")
    port.upperlng = w_max
    port.lowerlng = w_min
    w = port.optimization(
        model="Classic",
        rm="CVaR",
        obj="MinRisk",
        hist=True,
        rf=0,
        l=0,
    )
    if w is None or w.empty:
        raise RuntimeError("CVaR optimizer returned empty weights")
    return w.values.flatten()


def _try_risk_parity(returns_df, w_min, w_max):
    port = rp.Portfolio(returns=returns_df)
    port.assets_stats(method_mu="hist", method_cov="hist")
    port.upperlng = w_max
    port.lowerlng = w_min
    w = port.rp_optimization(
        model="Classic",
        rm="MV",
        hist=True,
        rf=0,
        b=None,
    )
    if w is None or w.empty:
        raise RuntimeError("Risk Parity optimizer returned empty weights")
    return w.values.flatten()


def _compute_inv_vol(symbols, hist_data, lookback):
    vols = {}
    for sym in symbols:
        if sym not in hist_data:
            continue
        df = hist_data[sym]
        close = df["Close"].iloc[-lookback:] if len(df) >= lookback else df["Close"]
        returns = close.pct_change().dropna()
        vol = returns.std() * np.sqrt(252)
        if vol > 0:
            vols[sym] = vol

    if not vols:
        return {s: 1.0 / len(symbols) for s in symbols}

    raw = {s: 1.0 / v for s, v in vols.items()}
    total = sum(raw.values())
    return {s: w / total for s, w in raw.items()}


def _build_returns_df(symbols, hist_data, lookback=63):
    frames = {}
    for sym in symbols:
        if sym in hist_data:
            close = hist_data[sym]["Close"].iloc[-lookback:]
            frames[sym] = close.pct_change().dropna()

    df = pd.DataFrame(frames).dropna()
    if df.empty:
        raise ValueError("No overlapping return data for optimization")
    return df


def _fetch_data(symbols, lookback=63):
    import yfinance as yf
    hist = {}
    for sym in symbols:
        try:
            data = yf.download(sym, period=f"{lookback + 30}d", progress=False)
            if not data.empty:
                hist[sym] = data
        except Exception as e:
            logger.warning(f"Failed to fetch {sym}: {e}")
    return hist


def compute_correlation_matrix(symbols, hist_data=None, lookback=63):
    if hist_data is None:
        hist_data = _fetch_data(symbols, lookback=lookback + 30)
    returns_df = _build_returns_df(symbols, hist_data, lookback)
    return returns_df.corr()


def compute_risk_contribution(symbols, weights, hist_data=None, lookback=63):
    if hist_data is None:
        hist_data = _fetch_data(symbols, lookback)

    available = [s for s in symbols if s in hist_data and s in weights]
    returns_df = _build_returns_df(available, hist_data, lookback)
    cov = returns_df.cov().values
    w = np.array([weights[s] for s in available])

    marginal = cov @ w
    port_vol = np.sqrt(w @ cov @ w)
    rc = w * marginal / port_vol if port_vol > 0 else w
    rc_normalized = rc / rc.sum() if rc.sum() > 0 else rc

    result = {}
    for i, sym in enumerate(available):
        result[sym] = {
            "weight": weights[sym],
            "risk_contribution": float(rc_normalized[i]),
            "marginal_risk": float(marginal[i]),
        }
    return result
