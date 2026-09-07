"""TASK-377 — local total-return adjustment of a close series (prototype, no production caller).

Convention (CRSP / Yahoo): the adjusted close of every bar strictly BEFORE an ex-date d is
multiplied by ``1 - dps_d / raw_close[last bar before d]``; the ex-date bar itself and later bars
are untouched by that dividend. Factors compound backwards from the last bar, so the latest bar
always equals the raw close. Splits are applied the same way with factor ``1 / ratio`` and are
only needed when the raw series is NOT already split-adjusted (Yahoo's ``Close`` and its
``dividends`` series are split-adjusted, so pass ``splits=None`` for Yahoo data).

Pure pandas; no network. ``adjust`` never raises on odd inputs: a dividend before the first bar,
on a bar with no previous print, or larger than the previous close is skipped and reported.
"""
from __future__ import annotations

import pandas as pd


def _norm_index(s: pd.Series) -> pd.Series:
    out = pd.to_numeric(s, errors="coerce").astype(float).copy()
    out.index = pd.DatetimeIndex(pd.to_datetime(out.index)).normalize()
    if getattr(out.index, "tz", None) is not None:
        out.index = out.index.tz_convert("UTC").tz_localize(None)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def _events(series: pd.Series | dict | None) -> list[tuple[pd.Timestamp, float]]:
    if series is None:
        return []
    if isinstance(series, dict):
        series = pd.Series(series, dtype=float)
    if len(series) == 0:
        return []
    s = _norm_index(series).dropna()
    return [(pd.Timestamp(d), float(v)) for d, v in s.items() if v != 0.0]


def adjust(
    raw_close: pd.Series,
    dividends: pd.Series | dict | None = None,
    splits: pd.Series | dict | None = None,
    *,
    report: dict | None = None,
) -> pd.Series:
    """Total-return adjusted close from a raw close series.

    ``dividends``: ex_date -> dividend per share (cash). ``splits``: date -> ratio (2.0 for a 2:1
    split, 0.1 for a 1:10 reverse split); apply only to raw series that are not split-adjusted.
    ``report`` (optional dict) receives ``skipped`` = [(kind, date, value, reason), ...] and
    ``applied`` = number of factors used.
    """
    if report is None:
        report = {}
    report.setdefault("skipped", [])
    report["applied"] = 0
    if raw_close is None or len(raw_close) == 0:
        return pd.Series(dtype=float)
    raw = _norm_index(raw_close)
    idx = raw.index
    factors = pd.Series(1.0, index=idx)

    for ex_date, dps in _events(dividends):
        prev = idx[idx < ex_date]
        if len(prev) == 0:
            report["skipped"].append(("dividend", str(ex_date.date()), dps, "no bar before ex-date"))
            continue
        p = raw.loc[prev[-1]]
        if not (p > 0) or pd.isna(p):
            report["skipped"].append(("dividend", str(ex_date.date()), dps, "no previous close"))
            continue
        f = 1.0 - dps / p
        if not (f > 0):
            report["skipped"].append(("dividend", str(ex_date.date()), dps, "dps >= previous close"))
            continue
        factors.loc[prev[-1]] *= f
        report["applied"] += 1

    for date, ratio in _events(splits):
        if not (ratio > 0):
            report["skipped"].append(("split", str(date.date()), ratio, "ratio <= 0"))
            continue
        prev = idx[idx < date]
        if len(prev) == 0:
            report["skipped"].append(("split", str(date.date()), ratio, "no bar before split"))
            continue
        factors.loc[prev[-1]] *= 1.0 / ratio
        report["applied"] += 1

    # a factor recorded at bar u applies to every bar <= u: reverse cumulative product
    cum = factors.iloc[::-1].cumprod().iloc[::-1]
    return (raw * cum).rename(getattr(raw_close, "name", None))


def contemporaneous_close(
    adjusted: pd.Series,
    dividends: pd.Series | dict | None = None,
    splits: pd.Series | dict | None = None,
    *,
    report: dict | None = None,
) -> pd.Series:
    """Exact inverse of `adjust`: every bar back in the currency it actually printed in.

    Audit ASTRA-05b. A total-return series is the right input for a *ratio* (momentum, returns):
    scaling the whole history by a constant leaves ratios alone. It is the wrong input for an
    ABSOLUTE currency threshold (price >= 5 USD, close x volume >= 5M USD), because a dividend
    paid in the future lowers every earlier adjusted bar: a stock that printed 6 USD in 2005 and
    later paid 2 USD of dividends shows up as 4 USD and fails a 5 USD floor it passed at the
    time. That is look-ahead in the eligibility mask.

    Given the same event series `adjust` was called with, this returns the as-printed closes, so
    eligibility is invariant to anything that happens after the bar. Without the events there is
    nothing to invert - the caller needs a raw close panel instead (`report['recovered']` is 0).
    """
    if report is None:
        report = {}
    report.setdefault("skipped", [])
    report["recovered"] = 0
    if adjusted is None or len(adjusted) == 0:
        return pd.Series(dtype=float)
    adj = _norm_index(adjusted)
    idx = adj.index
    div_at, split_at = {}, {}
    for ex_date, dps in _events(dividends):
        prev = idx[idx < ex_date]
        if len(prev) == 0:
            report["skipped"].append(("dividend", str(ex_date.date()), dps, "no bar before ex-date"))
            continue
        div_at[prev[-1]] = div_at.get(prev[-1], 0.0) + dps
    for date, ratio in _events(splits):
        prev = idx[idx < date]
        if not (ratio > 0):
            report["skipped"].append(("split", str(date.date()), ratio, "ratio <= 0"))
            continue
        if len(prev) == 0:
            report["skipped"].append(("split", str(date.date()), ratio, "no bar before split"))
            continue
        split_at[prev[-1]] = split_at.get(prev[-1], 1.0) * ratio

    out = pd.Series(index=idx, dtype=float)
    s = 1.0                                   # product of the factors of the bars already seen
    for bar in idx[::-1]:
        dps = float(div_at.get(bar, 0.0))
        ratio = float(split_at.get(bar, 1.0))
        a = float(adj.loc[bar]) if pd.notna(adj.loc[bar]) else float("nan")
        # adjust(): adj_u = (raw_u - dps) * s / ratio  ->  raw_u = adj_u * ratio / s + dps
        raw = a * ratio / s + dps
        if dps and not (raw > dps):            # adjust() skipped this dividend; so must the inverse
            report["skipped"].append(("dividend", str(pd.Timestamp(bar).date()), dps, "dps >= previous close"))
            dps, raw = 0.0, a * ratio / s
        out.loc[bar] = raw
        if pd.notna(raw) and raw > 0:
            f = (1.0 - dps / raw) / ratio
            if f > 0:
                s *= f
                if dps or ratio != 1.0:
                    report["recovered"] += 1
    return out.rename(getattr(adjusted, "name", None))


def dividends_from_rows(rows: list[dict], ticker: str) -> pd.Series:
    """`data.dividends.fetch_dividends` rows ({ticker, ex_date, dps}) -> Series ex_date -> dps."""
    pairs = {}
    for r in rows or []:
        if str(r.get("ticker")) != str(ticker):
            continue
        try:
            d = pd.Timestamp(r.get("ex_date")).normalize()
            v = float(r.get("dps") or 0.0)
        except Exception:
            continue
        if v:
            pairs[d] = pairs.get(d, 0.0) + v
    return pd.Series(pairs, dtype=float).sort_index()


def compare(adjusted: pd.Series, reference: pd.Series) -> dict:
    """Relative differences of two adjusted series on their common bars."""
    a = _norm_index(adjusted)
    b = _norm_index(reference)
    common = a.index.intersection(b.index)
    if len(common) == 0:
        return {"n": 0, "max_rel": None, "median_rel": None, "first_bad": None}
    a = a.loc[common]
    b = b.loc[common]
    rel = ((a - b).abs() / b.abs().where(b.abs() > 0)).dropna()
    if rel.empty:
        return {"n": int(len(common)), "max_rel": None, "median_rel": None, "first_bad": None}
    bad = rel[rel > 1e-6]
    return {
        "n": int(len(common)),
        "max_rel": float(rel.max()),
        "median_rel": float(rel.median()),
        "first_bad": str(bad.index[0].date()) if len(bad) else None,
        "n_bad": int(len(bad)),
    }
