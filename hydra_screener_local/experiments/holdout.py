"""TASK-432 - the holdout, formal and immutable: research / validation / live.

Lucas, 2026-09-11: research = 2010-01-01..2023-12-31, validation = 2024-01-01..2026-09-07,
live = 2026-09-08 onwards (the v9 book's first execution). 2010 and not 2004 because the free
Russell membership record starts 2010-06-28; nothing before it is point-in-time on the traded
universe. The audit of 2026-09-06 already found that TEST 2016-2026 had been used once to pick T20
and had stopped being untouched - this file is what stops that happening silently again.

The declaration lives in `holdout.json`; its sha256 is pinned here. Any change to the dates is a
new declaration with a new date and a new hash, in a commit that says so. An experiment declares the
partition it is entitled to and calls `stamp()` on its payload: the evaluated window is compared
with the declared partition and **every excursion becomes a `HOLDOUT BREACH: ...` line, in the
payload and on stdout** - a mark, not a warning that scrolls by. A pre-registered, frozen experiment
may legitimately span research and validation (TASK-431 did); it says so by declaring
`"research+validation"`, and the stamp records that it was read.

    from holdout import load_holdout, partition_of, stamp
    payload = stamp(payload, first="2010-06-28", last="2026-08-26", declared="research+validation")
"""
from __future__ import annotations

import hashlib
import json
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HOLDOUT_PATH = os.path.join(HERE, "holdout.json")
#: sha256 of holdout.json with CRLF folded to LF (so Windows and Linux checkouts agree).
PINNED_HOLDOUT_SHA256 = "fc38929b64e81ad835d7a2652551d29ed1bf4d1a7a67d1ba4088e4dec7a9fc3d"
ORDER = ("research", "validation", "live")
BREACH = "HOLDOUT BREACH"


def sha256_lf(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()


def load_holdout(path: str = HOLDOUT_PATH, *, verify: bool = True) -> dict:
    """The declaration, verified against the pinned hash. Fails closed."""
    if not os.path.exists(path):
        raise SystemExit(f"holdout declaration missing: {path}")
    digest = sha256_lf(path)
    if verify and digest != PINNED_HOLDOUT_SHA256:
        raise SystemExit(
            f"holdout.json hash {digest[:16]}... != pinned {PINNED_HOLDOUT_SHA256[:16]}...: "
            "the partitions moved. A new declaration needs a new date, a new pin and a commit that says why."
        )
    with open(path, "r", encoding="utf-8") as fh:
        h = json.load(fh)
    h["sha256"] = digest
    return h


def _bounds(h: dict, name: str) -> tuple[pd.Timestamp, pd.Timestamp | None]:
    p = h["partitions"][name]
    start = pd.Timestamp(p["start"])
    end = pd.Timestamp(p["end"]) if p.get("end") else None
    return start, end


def partition_of(date, h: dict | None = None) -> str | None:
    """Which partition a date falls in; None before research starts."""
    h = h or load_holdout()
    d = pd.Timestamp(date).normalize()
    for name in ORDER:
        start, end = _bounds(h, name)
        if d >= start and (end is None or d <= end):
            return name
    return None


def _window(first, last) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The closed window [first, last], normalised. An inverted pair is refused, not repaired.

    `first > last` is a caller bug, and a silent one: every overlap test below is written for
    `first <= last`, so an inverted pair touches no partition and the run comes back with an
    empty span and no breach - the one stamp a human reads as clean. Swapping the dates would
    be worse than raising, because the inversion usually means the wrong window was measured
    and nobody can say which dates the numbers came from. This module fails closed everywhere
    else (`load_holdout` on a moved declaration, `_declared_set` on an unknown name); it fails
    closed here too.
    """
    a, b = pd.Timestamp(first).normalize(), pd.Timestamp(last).normalize()
    if a > b:
        raise ValueError(
            f"inverted window: first {a.date()} is after last {b.date()}. Which dates were "
            "evaluated is unknown, so no honest holdout mark can be written - pass them in order."
        )
    return a, b


def partitions_spanned(first, last, h: dict | None = None) -> list[str]:
    """Partitions touched by the closed window [first, last], in order."""
    h = h or load_holdout()
    a, b = _window(first, last)
    out = []
    for name in ORDER:
        start, end = _bounds(h, name)
        hi = end if end is not None else pd.Timestamp.max
        if a <= hi and b >= start:
            out.append(name)
    return out


def _declared_set(declared: str) -> set[str]:
    parts = {p.strip() for p in str(declared).replace(",", "+").split("+") if p.strip()}
    bad = parts - set(ORDER)
    if bad:
        raise ValueError(f"unknown partition(s) {sorted(bad)}; declare from {ORDER}")
    return parts


def breaches(first, last, declared: str, h: dict | None = None) -> list[str]:
    """`HOLDOUT BREACH: ...` lines for every partition the window touches beyond the declared ones.

    Empty list = the experiment stayed where it said it would. Reading a window that starts before
    research is not a breach of the holdout (there is nothing to protect there) but is named too,
    because the traded-universe record does not exist before 2010-06-28.
    """
    h = h or load_holdout()
    a, b = _window(first, last)
    want = _declared_set(declared)
    lines = []
    for name in partitions_spanned(a, b, h):
        if name not in want:
            start, end = _bounds(h, name)
            lines.append(f"{BREACH}: window {a.date()}..{b.date()} "
                         f"reads '{name}' ({start.date()}..{end.date() if end is not None else 'open'}) "
                         f"but declared '{declared}'")
    r_start, _ = _bounds(h, "research")
    if a < r_start:
        lines.append(f"{BREACH}: window starts {a.date()}, before research "
                     f"{r_start.date()} - not point-in-time on the traded universe (no Russell record)")
    return lines


def stamp(payload: dict, *, first, last, declared: str, h: dict | None = None,
          echo: bool = True) -> dict:
    """Attach the holdout block to an experiment payload and print every breach line.

    The block is data: declared partition, partitions actually spanned, the declaration's hash and
    the breach lines verbatim. `echo` prints the same lines to stdout so a human reading the run sees
    them where the numbers are, not in a log nobody opens.
    """
    h = h or load_holdout()
    a, b = _window(first, last)
    lines = breaches(a, b, declared, h)
    block = dict(
        declared=declared,
        spanned=partitions_spanned(a, b, h),
        window=dict(first=str(a.date()), last=str(b.date())),
        holdout_sha256=h["sha256"],
        holdout_declared_on=h.get("declared_on"),
        breaches=lines,
        breached=bool(lines),
    )
    payload = dict(payload)
    payload["holdout"] = block
    if echo:
        print(f"[holdout] declared={declared} spanned={'+'.join(block['spanned']) or 'none'} "
              f"sha={h['sha256'][:12]}", flush=True)
        for ln in lines:
            print(ln, flush=True)
    return payload
