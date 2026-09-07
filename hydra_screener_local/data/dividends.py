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
                data.setdefault("updated_by_ticker", {})
                return data
        except Exception as e:
            logger.warning("dividend cache unreadable: %s", e)
    return {"updated": "", "tickers": {}, "updated_by_ticker": {}}


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
    report.update(requested=len(wanted), downloaded=0, failed_tickers=[], rows=0, no_dividends=[])
    cache = _load_cache()
    by_ticker: dict[str, list[dict]] = {
        t: list(rows) for t, rows in (cache.get("tickers") or {}).items()
    }
    updated_by = dict(cache.get("updated_by_ticker") or {})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    failed = []
    downloaded = 0
    skipped_fresh = []
    try:
        import yfinance as yf
    except Exception as e:
        logger.warning("yfinance missing for dividends: %s", e)
        failed = list(wanted)
        report.update(failed_tickers=failed, downloaded=0, skipped_fresh=[],
                      rows=sum(len(by_ticker.get(t, [])) for t in wanted))
        return [r for t in wanted for r in by_ticker.get(t, [])]
    for t in wanted:
        stamp = str(updated_by.get(t) or "")[:10]
        if stamp == today and t in by_ticker:
            skipped_fresh.append(t)
            continue
        try:
            s = yf.Ticker(t).dividends
            rows = _series_to_rows(t, s)
            by_ticker[t] = rows
            updated_by[t] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            downloaded += 1
        except Exception as e:
            logger.warning("dividend fetch failed %s: %s", t, e)
            failed.append(t)
    cache["tickers"] = by_ticker
    cache["updated_by_ticker"] = updated_by
    cache["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        _save_cache(cache)
    except Exception as e:
        logger.warning("dividend cache write failed: %s", e)
    rows = [r for t in wanted for r in by_ticker.get(t, [])]
    # TASK-385: an empty list means "fetched, none" only when the ticker carries a stamp; a failed
    # fetch leaves no stamp and must not be read as "no dividends"
    report.update(downloaded=downloaded, failed_tickers=failed, skipped_fresh=skipped_fresh, rows=len(rows),
                  no_dividends=[t for t in wanted if t in by_ticker and not by_ticker[t] and updated_by.get(t)])
    return rows


def coverage(tickers: list[str], *, max_age_days: int = 7) -> dict[str, list[str]]:
    """Cache status per ticker: fresh (stamped within max_age_days), stale (older stamp), missing (never
    fetched successfully). Read-only; the local adjustment must not trust a `missing` name."""
    cache = _load_cache()
    updated_by = dict(cache.get("updated_by_ticker") or {})
    have = cache.get("tickers") or {}
    now = datetime.now(timezone.utc)
    out = {"fresh": [], "stale": [], "missing": []}
    for t in [str(x) for x in tickers]:
        stamp = updated_by.get(t)
        if not stamp or t not in have:
            out["missing"].append(t)
            continue
        try:
            age = (now - datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))).days
        except Exception:
            out["stale"].append(t)
            continue
        (out["fresh"] if age <= max_age_days else out["stale"]).append(t)
    return out
