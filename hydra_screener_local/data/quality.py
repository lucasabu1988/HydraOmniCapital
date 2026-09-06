"""Price provenance: observed vs filled vs stale vs absent (audit phase 2.6/2.7).

`data.fetch` forward-fills gaps of up to `FFILL_LIMIT_BARS` (3) bars so the scoring
path is not shredded by a missing print. That is right for analysis and wrong for
execution: downstream, a carried price is indistinguishable from a real one, and the
engine will happily put a buy at a three-day-old price on the sheet Lucas executes
by hand (repro R-209).

Four states, and only the first authorises an execution:

    observed   the provider printed a value for this ticker on this bar
    filled     the value on this bar was carried forward from an earlier bar
    stale      the last observed bar is older than the allowed age
    absent     no value at all on this bar and none to carry

`OBSERVED` is the only status `is_executable` accepts. Pure; no network.
"""
from __future__ import annotations

import pandas as pd

from core.numbers import is_finite_price

OBSERVED = "observed"
FILLED = "filled"
STALE = "stale"
ABSENT = "absent"

#: statuses a live order may be priced from
EXECUTABLE_STATUSES = frozenset({OBSERVED})


def is_executable(status) -> bool:
    """The single answer to "may an order be priced from this"."""
    return str(status or "") in EXECUTABLE_STATUSES


def observed_mask(raw: pd.DataFrame | None) -> pd.DataFrame:
    """True where the provider actually printed a finite, positive value.

    Call this on the frame *before* any forward fill.
    """
    if raw is None or getattr(raw, "empty", True):
        return pd.DataFrame()
    numeric = raw.apply(pd.to_numeric, errors="coerce")
    return numeric.notna() & (numeric > 0)


def last_observed_dates(raw: pd.DataFrame | None) -> dict[str, str]:
    """{ticker: last bar with a real print} from the pre-fill frame."""
    mask = observed_mask(raw)
    if mask.empty:
        return {}
    out: dict[str, str] = {}
    for col in mask.columns:
        hits = mask.index[mask[col].to_numpy()]
        if len(hits):
            out[str(col)] = str(pd.Timestamp(hits[-1]).date())
    return out


def classify(
    prices: pd.DataFrame | None,
    asof,
    *,
    last_observed: dict[str, str] | None = None,
    max_age_sessions: int = 0,
) -> dict[str, dict]:
    """Per-ticker provenance on the `asof` bar of a (possibly filled) frame.

    `last_observed` comes from the fetch report (see `data.fetch`); without it every
    finite price on the bar is reported as `filled`, because a filled frame carries
    no evidence of its own that a value was printed. Fail closed: unknown provenance
    is never `observed`.

    `max_age_sessions` is the explicit staleness budget in *rows of this frame*: 0
    means the print must be on the asof bar itself.
    """
    if prices is None or getattr(prices, "empty", True) or len(prices) == 0:
        return {}
    idx = pd.DatetimeIndex(prices.index).normalize()
    target = pd.Timestamp(asof).normalize()
    hits = idx[idx == target]
    if not len(hits):
        return {str(c): {"status": ABSENT, "price": None, "last_observed": None, "age_sessions": None}
                for c in prices.columns}
    row = prices.loc[prices.index[idx == target][-1]]
    observed = dict(last_observed or {})
    positions = {str(pd.Timestamp(d).date()): i for i, d in enumerate(idx)}
    target_pos = positions.get(str(target.date()))

    out: dict[str, dict] = {}
    for col in prices.columns:
        name = str(col)
        price = pd.to_numeric(row.get(col), errors="coerce")
        price = None if pd.isna(price) else float(price)
        seen = observed.get(name)
        age = None
        if seen is not None and target_pos is not None:
            seen_pos = positions.get(str(seen))
            age = None if seen_pos is None else int(target_pos - seen_pos)

        if price is None or not is_finite_price(price):
            status = ABSENT
        elif seen is None:
            # no provenance for this name: cannot claim it was printed today
            status = FILLED
        elif age == 0:
            status = OBSERVED
        elif age is not None and age <= int(max_age_sessions):
            status = FILLED
        else:
            status = STALE
        out[name] = {"status": status, "price": price, "last_observed": seen, "age_sessions": age}
    return out


def executable_prices(classification: dict[str, dict]) -> dict[str, float]:
    """{ticker: price} for the names an order may be priced from, and nothing else."""
    return {t: rec["price"] for t, rec in classification.items()
            if is_executable(rec.get("status")) and is_finite_price(rec.get("price"))}


def summarize(classification: dict[str, dict]) -> dict:
    """Counts per status plus the offending names, for a preflight row."""
    buckets: dict[str, list[str]] = {OBSERVED: [], FILLED: [], STALE: [], ABSENT: []}
    for name, rec in classification.items():
        buckets.setdefault(str(rec.get("status")), []).append(name)
    return {
        "counts": {k: len(v) for k, v in buckets.items()},
        "names": {k: sorted(v) for k, v in buckets.items()},
        "total": len(classification),
    }


def invalid_prices(prices: pd.DataFrame | None, asof=None) -> dict[str, float]:
    """{ticker: value} for cells on the bar that are present but not a valid price.

    A finite, non-positive close is impossible for an equity or an ETF; before phase 2
    a negative ETF close sailed through preflight because `pd.notna(-3.0)` is True
    (repro R-206).
    """
    if prices is None or getattr(prices, "empty", True) or len(prices) == 0:
        return {}
    if asof is None:
        row = prices.iloc[-1]
    else:
        idx = pd.DatetimeIndex(prices.index).normalize()
        target = pd.Timestamp(asof).normalize()
        hits = prices.index[idx == target]
        row = prices.loc[hits[-1]] if len(hits) else prices.iloc[-1]
    out: dict[str, float] = {}
    for col in prices.columns:
        v = pd.to_numeric(row.get(col), errors="coerce")
        if pd.isna(v):
            continue                       # absent is a different finding
        if not is_finite_price(float(v)):
            out[str(col)] = float(v)
    return out
