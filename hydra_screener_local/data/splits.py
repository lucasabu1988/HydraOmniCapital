"""TASK-363 — yfinance stock splits by effective date, cached (same policy as data/dividends.py).

`fetch_splits(tickers)` -> [{ticker, date, ratio}, ...]; ratio 2.0 = 2-for-1, 0.1 = 1-for-10 reverse.
One download per ticker per UTC day (`updated_by_ticker`), cache fallback on failure, never raises.
Cache: data_cache/splits_cache.json.
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
CACHE_FILE = os.path.join(DATA_CACHE_DIR, "splits_cache.json")


def _load_cache() -> dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning("splits cache unreadable: %s", e)
        return {}


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
            ratio = float(val)
        except (TypeError, ValueError):
            continue
        if ratio <= 0 or ratio == 1.0:
            continue
        out.append({"ticker": ticker, "date": str(pd.Timestamp(ts).date()), "ratio": ratio})
    return out


def fetch_splits(tickers: list[str] | None = None, *, report: dict | None = None) -> list[dict]:
    """Return [{ticker, date, ratio}, ...] for `tickers`. Cache-merged. Never raises."""
    if report is None:
        report = {}
    wanted = [str(t).strip() for t in (tickers or []) if t and str(t).strip() not in ("CASH", "TBILL")]
    report.update(requested=len(wanted), downloaded=0, failed_tickers=[], rows=0, skipped_fresh=[])
    cache = _load_cache()
    by_ticker: dict[str, list[dict]] = {t: list(rows) for t, rows in (cache.get("tickers") or {}).items()}
    updated_by = dict(cache.get("updated_by_ticker") or {})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    failed, skipped, downloaded = [], [], 0
    try:
        import yfinance as yf
    except Exception as e:
        logger.warning("yfinance missing for splits: %s", e)
        report.update(failed_tickers=list(wanted), rows=sum(len(by_ticker.get(t, [])) for t in wanted))
        return [r for t in wanted for r in by_ticker.get(t, [])]
    for t in wanted:
        stamp = str(updated_by.get(t) or "")[:10]
        if stamp == today and t in by_ticker:
            skipped.append(t)
            continue
        try:
            rows = _series_to_rows(t, yf.Ticker(t).splits)
            by_ticker[t] = rows
            updated_by[t] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            downloaded += 1
        except Exception as e:
            logger.warning("split fetch failed %s: %s", t, e)
            failed.append(t)
    cache["tickers"] = by_ticker
    cache["updated_by_ticker"] = updated_by
    cache["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        _save_cache(cache)
    except Exception as e:
        logger.warning("splits cache write failed: %s", e)
    rows = [r for t in wanted for r in by_ticker.get(t, [])]
    report.update(downloaded=downloaded, failed_tickers=failed, skipped_fresh=skipped, rows=len(rows))
    return rows
