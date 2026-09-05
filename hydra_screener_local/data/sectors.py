"""
GICS-style sector lookup with a daily JSON cache (TASK-318).

Stale cache beats no data. Fetch failures never crash a run.
Lookup order: cache -> config.SECTOR_BUCKETS -> "Other".
"""
import json
import logging
import os
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_MODULE_DIR)
DATA_CACHE_DIR = os.path.join(PROJECT_ROOT, "data_cache")
CACHE_FILE = os.path.join(DATA_CACHE_DIR, "sector_cache.json")
CACHE_DAYS = 7

_memory = None  # {"updated": iso, "sectors": {ticker: sector}}


def _empty():
    return {"updated": "", "sectors": {}}


def _load_cache():
    global _memory
    if _memory is not None:
        return _memory
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("sectors"), dict):
                _memory = data
                return _memory
        except Exception as e:
            logger.warning("sector cache unreadable: %s", e)
    _memory = _empty()
    return _memory


def _save_cache(data):
    global _memory
    os.makedirs(DATA_CACHE_DIR, exist_ok=True)
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, CACHE_FILE)
    _memory = data


def lookup_sector(ticker: str) -> str:
    from config import SECTOR_BUCKETS
    sec = _load_cache().get("sectors", {}).get(ticker)
    if sec:
        return sec
    return SECTOR_BUCKETS.get(ticker, "Other")


def _cache_is_fresh(data) -> bool:
    raw = data.get("updated") or ""
    if not raw:
        return False
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError:
        return False
    return datetime.now() - ts < timedelta(days=CACHE_DAYS)


def refresh_sector_cache(tickers, force: bool = False) -> dict:
    """Fill missing tickers via yfinance. Never raises. Returns the sector map used."""
    from config import SECTOR_BUCKETS

    data = _load_cache()
    sectors = dict(data.get("sectors") or {})
    need = []
    for t in tickers:
        if not t:
            continue
        # Synthetic names from unit tests (T000, T001, ...) — never hit the network.
        if len(t) <= 4 and t[0] == "T" and t[1:].isdigit():
            continue
        if t not in sectors:
            need.append(t)
        elif force:
            need.append(t)

    if need:
        try:
            import yfinance as yf
        except Exception as e:
            logger.warning("yfinance unavailable for sector fetch: %s — using cache/buckets", e)
            need = []

    fetched = 0
    for t in need:
        try:
            info = yf.Ticker(t).info or {}
            name = info.get("sector") or info.get("industry")
            if name:
                sectors[t] = str(name)
                fetched += 1
        except Exception as e:
            logger.warning("sector fetch failed for %s: %s", t, e)

    if fetched or not data.get("updated"):
        payload = {"updated": datetime.now().isoformat(), "sectors": sectors}
        try:
            _save_cache(payload)
        except Exception as e:
            logger.warning("sector cache write failed: %s", e)
            payload = {"updated": data.get("updated", ""), "sectors": sectors}
            global _memory
            _memory = payload
    else:
        payload = data

    if need and fetched < len(need):
        logger.warning(
            "sector cache: fetched %d/%d missing tickers; remainder fall back to buckets/Other",
            fetched, len(need),
        )
    return payload.get("sectors") or {}
