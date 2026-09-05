"""
GICS sector lookup backed by a JSON cache (TASK-318, reworked in TASK-320).

Lookup order: cache -> config.SECTOR_BUCKETS -> "Other".

The cache only fills tickers it does not know yet. A listed company's sector changes
rarely enough that a refresh policy is not worth the ~0.4s/ticker it costs; to force a
rebuild, delete `data_cache/sector_cache.json`.

Resolution is done ONCE per run, upstream in screener.py, and the resulting map is handed
to the scoring code. `core/` must never call `refresh_sector_cache` — scoring does no
network I/O, so the backtest and the tests stay offline and deterministic.
"""
import json
import logging
import os
import time
from datetime import datetime

logger = logging.getLogger(__name__)

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_MODULE_DIR)
DATA_CACHE_DIR = os.path.join(PROJECT_ROOT, "data_cache")
CACHE_FILE = os.path.join(DATA_CACHE_DIR, "sector_cache.json")

UNKNOWN_SECTOR = "Other"

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
    """Cache -> buckets -> "Other". Reads only; never touches the network."""
    from config import SECTOR_BUCKETS
    sec = _load_cache().get("sectors", {}).get(ticker)
    if sec:
        return sec
    return SECTOR_BUCKETS.get(ticker, UNKNOWN_SECTOR)


def refresh_sector_cache(tickers, budget_seconds=None) -> dict:
    """Fetch the sectors we do not have yet, within a time budget. Never raises.

    yfinance only exposes `sector` through the per-ticker `.info` endpoint, so this costs
    roughly 0.4s per unknown name: ~3.7 min for the S&P 500 from cold, and the cache is
    what keeps it off the daily critical path. `budget_seconds` bounds a cold start;
    whatever is not fetched simply falls back to buckets/"Other" for this run and is
    picked up next time. Progress is saved as it goes, so an interrupted run is not lost.
    """
    data = _load_cache()
    sectors = dict(data.get("sectors") or {})
    need = [t for t in tickers if t and t not in sectors]
    if not need:
        return sectors

    try:
        import yfinance as yf
    except Exception as e:
        logger.warning("yfinance unavailable for sector fetch: %s - using cache/buckets", e)
        return sectors

    start = time.perf_counter()
    fetched = 0
    for i, t in enumerate(need):
        if budget_seconds is not None and time.perf_counter() - start > budget_seconds:
            logger.warning(
                "sector fetch hit its %ss budget after %d/%d tickers; the rest fall back "
                "to buckets/Other for this run", budget_seconds, i, len(need),
            )
            break
        try:
            info = yf.Ticker(t).info or {}
            name = info.get("sector") or info.get("industry")
            if name:
                sectors[t] = str(name)
                fetched += 1
        except Exception as e:
            logger.warning("sector fetch failed for %s: %s", t, e)
        if fetched and fetched % 100 == 0:
            _try_save(sectors)

    if fetched:
        _try_save(sectors)
    if fetched < len(need):
        logger.warning(
            "sector cache: resolved %d of %d unknown tickers; remainder fall back to "
            "buckets/Other", fetched, len(need),
        )
    return sectors


def _try_save(sectors):
    payload = {"updated": datetime.now().isoformat(), "sectors": sectors}
    try:
        _save_cache(payload)
    except Exception as e:
        logger.warning("sector cache write failed: %s", e)
        global _memory
        _memory = payload


def resolve_sectors(tickers, budget_seconds=None) -> dict:
    """The one entry point callers should use: {ticker: sector} for every ticker asked for.

    Refreshes what is missing (bounded by `budget_seconds`), then resolves everything
    through cache -> buckets -> "Other" so the caller gets a complete map and the scoring
    code never has to look anything up itself.
    """
    from config import SECTOR_BUCKETS
    tickers = [t for t in tickers if t]
    try:
        cached = refresh_sector_cache(tickers, budget_seconds=budget_seconds)
    except Exception as e:  # belt and braces: a sector map is never worth failing a run
        logger.warning("sector resolution failed, falling back to buckets: %s", e)
        cached = {}
    return {t: cached.get(t) or SECTOR_BUCKETS.get(t, UNKNOWN_SECTOR) for t in tickers}
