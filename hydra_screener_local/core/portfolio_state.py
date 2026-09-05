"""
TASK-329 — current holdings as implied by history/*.json.

Production emits a fresh recommended list every run and does not keep a
portfolio object. Redesign candidates that hold names across cycles need
to know what is already held. This module only *reads*. Nothing in scoring
imports it.

`current_positions(history_dir, as_of)` looks at the most recent run with
date <= as_of and returns the recommended names. For each name, `entry_bar`
is `data_last_bar` of the earliest run in the trailing consecutive streak
(v1 files with no data_last_bar fall back to the run date). `bars_held` is
the count of weekdays from that entry bar to `as_of` (no price index here).
"""
from __future__ import annotations

import json
import os

import pandas as pd


def _run_date(name: str) -> str:
    return name.replace(".json", "")


def _parse_day(s):
    if not s:
        return None
    try:
        return pd.Timestamp(s).normalize()
    except (ValueError, TypeError):
        return None


def _load(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _recommended(run: dict) -> list[str]:
    out = []
    for c in run.get("top_candidates") or []:
        if c.get("recommended") and c.get("ticker"):
            out.append(str(c["ticker"]))
    return out


def _entry_bar(run: dict, run_date: str) -> str:
    bar = run.get("data_last_bar")
    if bar:
        return str(bar)
    return run_date


def _bars_held(entry_bar: str, as_of: str) -> int:
    a = _parse_day(entry_bar)
    b = _parse_day(as_of)
    if a is None or b is None or b < a:
        return 0
    return int(len(pd.bdate_range(a, b, inclusive="left")))


def _runs_through(history_dir: str, as_of: str) -> list[tuple[str, str, dict]]:
    """(run_date, path, payload) with run_date <= as_of, oldest first."""
    if not history_dir or not os.path.isdir(history_dir):
        return []
    as_ts = _parse_day(as_of)
    rows = []
    for fn in os.listdir(history_dir):
        if not fn.endswith(".json"):
            continue
        d = _run_date(fn)
        ts = _parse_day(d)
        if ts is None or (as_ts is not None and ts > as_ts):
            continue
        path = os.path.join(history_dir, fn)
        try:
            payload = _load(path)
        except (OSError, json.JSONDecodeError):
            continue
        rows.append((d, path, payload))
    rows.sort(key=lambda r: r[0])
    return rows


def current_positions(history_dir: str, as_of: str) -> list[dict]:
    """Holdings implied by the latest history file on or before `as_of`."""
    rows = _runs_through(history_dir, as_of)
    if not rows:
        return []
    latest_date, _, latest = rows[-1]
    names = _recommended(latest)
    if not names:
        return []

    # Walk backward while each name stays recommended to find the streak start.
    first_run = {n: (latest_date, latest) for n in names}
    still = set(names)
    for run_date, _, payload in reversed(rows[:-1]):
        rec = set(_recommended(payload))
        drop = [n for n in still if n not in rec]
        for n in drop:
            still.discard(n)
        if not still:
            break
        for n in list(still):
            first_run[n] = (run_date, payload)

    out = []
    for n in names:
        run_date, payload = first_run[n]
        entry = _entry_bar(payload, run_date)
        out.append({
            "ticker": n,
            "run_date": latest_date,
            "entry_bar": entry,
            "bars_held": _bars_held(entry, as_of),
            "schema_version": payload.get("schema_version", 1),
        })
    return out
