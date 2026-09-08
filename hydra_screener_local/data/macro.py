"""Macro observability: the Buffett indicator, fetched and snapshotted. Phase 1 of two.

Lucas asked (2026-09-08) whether the Buffett indicator - total US equity market value over GDP -
could become a selection criterion. It cannot: it is ONE number per day for the whole universe, so
in the cross-section it multiplies every ticker by the same constant and the ranking does not move.
That is the same arithmetic that makes the Meta-Layer unable to tilt the ranking (SPEC 4.4,
Spearman 1.000). A scalar like this can only change HOW MUCH is bought - exposure, `dynamic_count`,
the sleeve split - never WHAT.

So this module is phase 1, agreed with Lucas: **record it, never let it touch the book.** Nothing
imports it yet; wiring it into the run log and the instruction sheet touches the live path and
waits for the verified settle (TASK-414). Phase 2 - turning it into a rule - is pre-registered as
H-008 in `.comms/hypotheses.md` with a power check that has to pass first, and on this panel it is
expected to fail: since 2005 the indicator has traded essentially two episodes (cheap 2008-2012,
expensive 2013-2026), and two episodes do not estimate a mean difference.

## Why snapshots

GDP is quarterly, published with about a month's lag, and **revised for years**. Building the
indicator from today's GDP vintage and applying it to 2008 is look-ahead of exactly the kind that
already cost this project a rewrite on index membership. ALFRED serves real vintages, but only
through its API (a key) - the key-free `fredgraph.csv` endpoint 404s on `vintage_date`, verified
2026-09-08. So:

  * `provenance="revised"` - the whole history as it reads TODAY. Fine for a chart, NEVER a
    point-in-time input. `pit_series()` refuses to return it.
  * `provenance="snapshot"` - what we saw on the day we fetched it, appended to
    `data_cache/macro_snapshots.json`. These ARE vintages, ours, and the series starts at zero
    length today and grows one entry per run. That is the whole point of doing phase 1 now.

## Series

    NCBEILQ027S  Z.1 L.223, corporate equities liability of nonfinancial corporate business,
                 $ millions, quarterly from 1945. The standard numerator of the "classic"
                 Buffett indicator.
    GDP          nominal GDP, $ billions, quarterly, seasonally adjusted annual rate.

    indicator = (NCBEILQ027S / 1000) / GDP        # both in $ billions

Measured 2026-09-08: latest common quarter 2026-01-01 -> **2.181**, against a 1947-2026 median of
0.72 and an all-time high of 2.287 (2025 Q4). The Wilshire-5000 numerator some builds use is not
available key-free (`WILL5000IND`/`WILL5000PR` both 404), so this file commits to the Z.1
definition and says so rather than silently switching numerators between runs.

Network here follows the rest of `data/`: wrapped, retried, and it never raises into a caller.
"""
from __future__ import annotations

import csv
import json
import logging
import os
from io import StringIO

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_CACHE_DIR = os.path.join(PROJECT_ROOT, "data_cache")
SNAPSHOT_PATH = os.path.join(DATA_CACHE_DIR, "macro_snapshots.json")

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
# Measured 2026-09-08: FRED serves this endpoint instantly to any plain User-Agent and HANGS
# (read timeout, three attempts, both series) on the browser-like `Mozilla/5.0` that
# `data.universe._get_headers()` sends. So this module carries its own header instead of reusing
# that one - the failure mode was a silent timeout, not a 4xx, which is exactly the kind of thing
# that would have looked like "FRED is down" forever.
FRED_HEADERS = {"User-Agent": "hydra-screener/1.0 (+FRED macro observability)"}
EQUITIES_SERIES = "NCBEILQ027S"      # $ millions
GDP_SERIES = "GDP"                   # $ billions
SNAPSHOT_VERSION = 1

DEFINITION = (
    "buffett = (NCBEILQ027S / 1000) / GDP, both $bn, quarterly; Z.1 L.223 equities of "
    "nonfinancial corporate business over nominal GDP"
)


def _fetch_csv(series_id: str, timeout: int = 20) -> dict | None:
    """{date: value} from FRED's key-free CSV endpoint, or None. Never raises."""
    try:
        from data.universe import _get_with_retry
    except Exception:                                    # pragma: no cover - import shape only
        logger.warning("data.universe unavailable; cannot fetch %s", series_id)
        return None
    resp = _get_with_retry(FRED_CSV.format(series_id=series_id), timeout=timeout,
                           headers=FRED_HEADERS)
    if resp is None:
        return None
    try:
        rows = list(csv.reader(StringIO(resp.text)))
    except Exception as e:
        logger.warning("FRED CSV for %s did not parse: %s", series_id, e)
        return None
    out = {}
    for row in rows[1:]:
        if len(row) < 2 or row[1] in (".", ""):
            continue
        try:
            out[row[0]] = float(row[1])
        except ValueError:
            continue
    if not out:
        logger.warning("FRED CSV for %s had no usable observations", series_id)
        return None
    return out


def buffett_from_series(equities_musd: dict, gdp_busd: dict) -> dict:
    """{quarter: ratio} on the quarters both series cover. Pure; no network, no clock."""
    quarters = sorted(set(equities_musd) & set(gdp_busd))
    out = {}
    for q in quarters:
        gdp = gdp_busd[q]
        if not gdp:
            continue
        out[q] = (equities_musd[q] / 1000.0) / gdp
    return out


def fetch_buffett(timeout: int = 20) -> dict | None:
    """The indicator as it reads TODAY: `provenance="revised"`. None if either fetch fails."""
    equities = _fetch_csv(EQUITIES_SERIES, timeout=timeout)
    gdp = _fetch_csv(GDP_SERIES, timeout=timeout)
    if not equities or not gdp:
        return None
    series = buffett_from_series(equities, gdp)
    if not series:
        logger.warning("the two FRED series share no quarter; nothing to compute")
        return None
    last = max(series)
    return {
        "provenance": "revised",
        "definition": DEFINITION,
        "series": {EQUITIES_SERIES: EQUITIES_SERIES, GDP_SERIES: GDP_SERIES},
        "latest_obs_date": last,
        "latest_value": round(series[last], 4),
        "n_quarters": len(series),
        "first_obs_date": min(series),
        "history": {q: round(v, 6) for q, v in series.items()},
    }


# ----------------------------------------------------------------- the snapshot store
def load_snapshots(path: str = SNAPSHOT_PATH) -> list[dict]:
    """Our own vintages, oldest first. Missing or unreadable file -> empty list, never raises."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            blob = json.load(f)
    except Exception as e:
        logger.warning("macro snapshot store unreadable (%s); treating as empty", e)
        return []
    snaps = blob.get("snapshots") if isinstance(blob, dict) else blob
    if not isinstance(snaps, list):
        return []
    return sorted(snaps, key=lambda s: str(s.get("observed_at")))


def append_snapshot(reading: dict, observed_at: str, path: str = SNAPSHOT_PATH,
                    force: bool = False) -> dict:
    """Record what we saw today. One entry per `observed_at`; a re-run is a no-op.

    `observed_at` is passed in rather than read from a clock, so a caller (and a test) decides
    what date a vintage is stamped with. Returns {"written": bool, "reason": str, "snapshots": n}.
    """
    if not reading or reading.get("latest_value") is None:
        return {"written": False, "reason": "no reading to record", "snapshots": 0}
    snaps = load_snapshots(path)
    existing = next((s for s in snaps if str(s.get("observed_at")) == str(observed_at)), None)
    if existing and not force:
        same = abs(float(existing.get("value", 0.0)) - float(reading["latest_value"])) < 1e-9
        return {
            "written": False,
            "reason": ("already recorded today with the same value" if same else
                       "already recorded today with a DIFFERENT value; pass force to overwrite"),
            "snapshots": len(snaps),
        }
    entry = {
        "observed_at": str(observed_at),
        "provenance": "snapshot",
        "value": reading["latest_value"],
        "obs_date": reading["latest_obs_date"],
        "n_quarters": reading["n_quarters"],
        "definition": reading.get("definition", DEFINITION),
        "version": SNAPSHOT_VERSION,
    }
    snaps = [s for s in snaps if str(s.get("observed_at")) != str(observed_at)] + [entry]
    snaps.sort(key=lambda s: str(s["observed_at"]))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": SNAPSHOT_VERSION, "definition": DEFINITION, "snapshots": snaps},
                  f, indent=2)
    os.replace(tmp, path)
    return {"written": True, "reason": "recorded", "snapshots": len(snaps)}


def pit_series(path: str = SNAPSHOT_PATH) -> dict:
    """{observed_at: value} from OUR snapshots only.

    The revised history is deliberately not available through this function: a point-in-time
    caller must not be able to reach it by accident. It is in `fetch_buffett()["history"]`,
    labelled `revised`, for charts and for the record - not for a rule.
    """
    return {str(s["observed_at"]): float(s["value"]) for s in load_snapshots(path)
            if s.get("provenance") == "snapshot" and s.get("value") is not None}
