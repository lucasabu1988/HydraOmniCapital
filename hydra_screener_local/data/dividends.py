"""TASK-349 — yfinance cash dividends by ex-date, cached.

`Ticker.dividends` is indexed by ex-date. Failures go into `report` and are not
raised (same policy as fetch_etf_closes). Cache: data_cache/dividends_cache.json.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import pandas as pd

logger = logging.getLogger(__name__)

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_MODULE_DIR)
DATA_CACHE_DIR = os.path.join(PROJECT_ROOT, "data_cache")
CACHE_FILE = os.path.join(DATA_CACHE_DIR, "dividends_cache.json")


def _load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("tickers"), dict):
                return data
        except Exception as e:
            logger.warning("dividend cache unreadable: %s", e)
    return {"updated": "", "tickers": {}}


def _save_cache(data: dict) -> None:
    os.makedirs(DATA_CACHE_DIR, exist_ok=True)
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, CACHE_FILE)


def _series_to_rows(ticker: str, s: pd.Series) -> list[dict]:
    out = []
    if s is None or getattr(s, "empty", True):
        return out
    for ts, val in s.dropna().items():
        try:
            dps = float(val)
        except (TypeError, ValueError):
            continue
        if dps <= 0:
            continue
        ex = str(pd.Timestamp(ts).date())
        out.append({"ticker": ticker, "ex_date": ex, "dps": dps})
    return out


def fetch_dividends(tickers: list[str] | None = None, *, report: dict | None = None) -> list[dict]:
    """Return [{ticker, ex_date, dps}, ...] for `tickers`. Cache-merged. Never raises."""
    if report is None:
        report = {}
    wanted = [str(t).strip() for t in (tickers or []) if t and str(t).strip() not in ("CASH", "TBILL")]
    report.update(requested=len(wanted), downloaded=0, failed_tickers=[], rows=0)
    cache = _load_cache()
    by_ticker: dict[str, list[dict]] = {
        t: list(rows) for t, rows in (cache.get("tickers") or {}).items()
    }
    failed = []
    downloaded = 0
    try:
        import yfinance as yf
    except Exception as e:
        logger.warning("yfinance missing for dividends: %s", e)
        failed = list(wanted)
        report.update(failed_tickers=failed, downloaded=0,
                      rows=sum(len(by_ticker.get(t, [])) for t in wanted))
        return [r for t in wanted for r in by_ticker.get(t, [])]
    for t in wanted:
        try:
            s = yf.Ticker(t).dividends
            rows = _series_to_rows(t, s)
            by_ticker[t] = rows
            downloaded += 1
        except Exception as e:
            logger.warning("dividend fetch failed %s: %s", t, e)
            failed.append(t)
    cache["tickers"] = by_ticker
    cache["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        _save_cache(cache)
    except Exception as e:
        logger.warning("dividend cache write failed: %s", e)
    rows = [r for t in wanted for r in by_ticker.get(t, [])]
    report.update(downloaded=downloaded, failed_tickers=failed, rows=len(rows))
    return rows
