"""
Shared data loading utilities for Regime OS research and validation.

This module centralizes PIT-friendly loading of SPY, VIX, and breadth proxy data
from the existing project infrastructure (data_cache_parquet + research caches).

Intended to be shared between:
- Phase 0 research (regime_feature_research.py)
- Task 1.4+ validation harness (regime_validation_harness.py)
- Future Phase 5 integrated validation work

All functions are pure (no global mutation) and fail-safe where practical.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

import pandas as pd

# ---------------------------------------------------------------------
# Constants (centralized)
# ---------------------------------------------------------------------
PARQUET_CACHE_DIR = Path("data_cache_parquet")
VIX_CACHE_FILE = Path("research/regime_features/vix_cache.parquet")

# Stable 30-ticker large-cap proxy for breadth (same as Phase 0 research)
BREADTH_PROXY_TICKERS = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "AVGO", "JPM", "V",
    "XOM", "UNH", "MA", "PG", "JNJ", "HD", "CVX", "ABBV", "COST", "PEP",
    "ADBE", "CRM", "NFLX", "DIS", "INTC", "AMD", "QCOM", "TXN", "HON", "IBM",
]

MIN_HISTORY_BREADTH = 300  # minimum history (in trading days) for a ticker to be used in breadth


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize parquet DataFrames (handle MultiIndex columns, dates, Close/Volume)."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    if "Close" not in df.columns and "close" in [c.lower() for c in df.columns]:
        df["Close"] = df[[c for c in df.columns if c.lower() == "close"][0]]
    if "Volume" not in df.columns and "volume" in [c.lower() for c in df.columns]:
        df["Volume"] = df[[c for c in df.columns if c.lower() == "volume"][0]]
    return df


def load_spy_full() -> pd.DataFrame:
    """Load full SPY history from parquet (Close + Volume only)."""
    p = PARQUET_CACHE_DIR / "SPY.parquet"
    if not p.exists():
        raise FileNotFoundError(f"SPY.parquet missing – run refresh first. Path: {p}")
    df = pd.read_parquet(p)
    df = _normalize_df(df)
    if len(df) < 500:
        raise ValueError("SPY history too short for regime validation")
    return df[["Close", "Volume"]].dropna()


def load_vix_from_cache() -> pd.Series:
    """Load cached VIX series (with fallback name handling)."""
    if not VIX_CACHE_FILE.exists():
        raise FileNotFoundError(f"VIX cache missing: {VIX_CACHE_FILE}")
    vix = pd.read_parquet(VIX_CACHE_FILE)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = [c[0] for c in vix.columns]
    vix.index = pd.to_datetime(vix.index)
    vix = vix.sort_index()
    col = "vix" if "vix" in vix.columns else vix.columns[0]
    s = vix[col].dropna()
    s.name = "vix"
    return s


def load_breadth_closes(min_history: int = MIN_HISTORY_BREADTH) -> Dict[str, pd.Series]:
    """Load Close series for the stable breadth proxy tickers from parquet."""
    closes: Dict[str, pd.Series] = {}
    for t in BREADTH_PROXY_TICKERS:
        p = PARQUET_CACHE_DIR / f"{t}.parquet"
        if not p.exists():
            continue
        try:
            df = pd.read_parquet(p)
            df = _normalize_df(df)
            if len(df) >= min_history and "Close" in df.columns:
                closes[t] = df["Close"].dropna()
        except Exception:
            continue
    return closes


def load_all_data() -> Tuple[pd.DataFrame, pd.Series, Dict[str, pd.Series]]:
    """Convenience loader returning (spy, vix, breadth_closes)."""
    spy = load_spy_full()
    vix = load_vix_from_cache()
    breadth = load_breadth_closes()
    return spy, vix, breadth
