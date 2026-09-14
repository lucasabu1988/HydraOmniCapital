"""TASK-434 - participation ceiling: ADV20, footprints, P95, max AUM. CAPACITY_NOT_CERTIFIED.

Pre-registered in `.comms/prereg-task-434-2026-09-14.md` (sha256 on the board) BEFORE any number
existed. Every rule below is a line of that document; the tests pin each one with a mutation.

What this module measures is a PARTICIPATION CEILING, not capacity: the largest book size at which
the 95th percentile of `|net order dollars| / ADV20` stays at or under 3 %. It says nothing about
market impact, so everything it publishes carries `LABEL` beside the number. The impact model gets
its own pre-registration, written before its distribution is seen.

The units, frozen:

  * The unit of participation is the EXECUTION FOOTPRINT: fills aggregated by
    (settle, sleeve, ticker) with signed netting across tranches (buy +, sell -). Gross (sum of
    absolute micro-fills) is a sensitivity column, never the headline.
  * ADV20 is EX-ANTE: the lab's one definition, `(close * volume).rolling(20).mean()`
    (`build_adv_panel.build_adv` = `redesign_lab.py` `P.ADV_USD`), read at the market bar
    IMMEDIATELY BEFORE the settle bar on the panel's own index. No previous bar, or a NaN there
    (window not full, zero volume) -> participation UNKNOWN. Never shortened, never filled.
  * P95 is one explicit order statistic: the observation at rank ceil(0.95 * N), 1-based, over the
    sorted sample. No interpolation. Unknown participations enter the CONSERVATIVE sample as +inf,
    so the conservative P95 is finite iff strictly fewer than N - ceil(0.95 N) + 1 footprints are
    unknown. The DESCRIPTIVE P95 is over known footprints only and is always printed with both
    coverage ratios (by footprint count and by notional).
  * The ceiling uses the conservative P95. It is NOT MEASURABLE when the unknown share exceeds
    5 % by count or by notional, or when no capital on the grid passes; the descriptive figures are
    still printed under that label, never as a ceiling.
  * One drive at capital 1.0, three rescalings: the engine is linear in capital when
    `whole_shares=False` (fractional units, proportional costs), a property `test_capacity_scale.py`
    demonstrates rather than assumes (F5). Production is fractional too (`portfolio_v9.py:546`).

The fill sidecar (`FillTap`) is an OBSERVER on the same seam `cost_stress._LedgerTap` already wraps
(`engine_backtest.E.settle`): it copies what `settle` returns and hands it back untouched. No engine
file changes, so the capacity drive is the accredited drive - F1 checks that with `book_sha256`.
"""
from __future__ import annotations

import json
import math
import os
import sys
from typing import Iterable

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import engine_backtest as EB  # noqa: E402
from build_adv_panel import build_adv  # noqa: E402

LABEL = "CAPACITY_NOT_CERTIFIED"
THRESHOLDS_PCT = (1.0, 3.0, 5.0)          # normal / warn / do-not-trade, as the board fixes them
CEILING_PCT = 3.0                          # the P95 bound the ceiling is read at
CAPITALS_USD = (100_000.0, 500_000.0, 1_000_000.0)
UNKNOWN_SHARE_MAX = 0.05                   # by count OR by notional; above it: NOT MEASURABLE
ADV_WINDOW = 20
FILLED = "filled"
SIDE_SIGN = {"buy": 1.0, "sell": -1.0}


def aum_grid(lo: float = 10_000.0, hi: float = 100_000_000.0, ratio: float = 1.25) -> list:
    """Geometric capital grid, 10 k .. 100 M by x1.25, inclusive of the first point >= hi."""
    out, c = [], float(lo)
    while c < hi * (1 - 1e-12):
        out.append(c)
        c *= ratio
    out.append(c)
    return out


# ----------------------------------------------------------------------------------------------
# the sidecar
# ----------------------------------------------------------------------------------------------
FILL_FIELDS = ("exec_date", "sleeve", "tranche", "ticker", "side", "dollars", "cost", "price",
               "units")


class FillTap:
    """Retains every FILLED record `settle` returns, by name. Observer, never participant.

    Same seam as `cost_stress._LedgerTap`, which aggregates the same records per sleeve; nesting
    the two is fine (each wraps whatever `settle` is at entry and restores it on exit). The
    records are COPIES of the engine's dicts: the tap cannot edit what the engine keeps.
    """

    def __init__(self):
        self.fills: list = []
        self._orig = None

    def __enter__(self):
        self._orig = EB.E.settle

        def wrapped(state, exec_date, *a, **kw):
            fills = self._orig(state, exec_date, *a, **kw)
            for f in fills or []:
                if str(f.get("status")) == FILLED:
                    self.fills.append({k: f.get(k) for k in FILL_FIELDS} | {"exec_date": str(exec_date)})
            return fills
        EB.E.settle = wrapped
        return self

    def __exit__(self, *exc):
        if self._orig is not None:
            EB.E.settle = self._orig
        return False

    def frame(self) -> pd.DataFrame:
        return fills_frame(self.fills)


def fills_frame(fills: Iterable[dict]) -> pd.DataFrame:
    df = pd.DataFrame(list(fills), columns=list(FILL_FIELDS))
    if df.empty:
        return df
    df["exec_date"] = pd.to_datetime(df["exec_date"])
    df["dollars"] = pd.to_numeric(df["dollars"], errors="coerce").astype(float)
    df["cost"] = pd.to_numeric(df["cost"], errors="coerce").astype(float)
    return df


# ----------------------------------------------------------------------------------------------
# footprints
# ----------------------------------------------------------------------------------------------
def footprints(fills: pd.DataFrame) -> pd.DataFrame:
    """(settle, sleeve, ticker) -> net_dollars (signed), gross_dollars, n_fills.

    Signed netting across tranches: a buy and a sell of the same name in the same settle are one
    order for `|net_dollars|`. A side other than buy/sell is not a footprint (transfers never reach
    `settle`'s fill list as filled; `park`/`hold_no_price` are `noted`, filtered upstream).
    """
    cols = ["settle", "sleeve", "ticker", "net_dollars", "gross_dollars", "n_fills"]
    if fills is None or fills.empty:
        return pd.DataFrame(columns=cols)
    f = fills[fills["side"].isin(SIDE_SIGN)].copy()
    f["signed"] = f["dollars"].abs() * f["side"].map(SIDE_SIGN)
    f["gross"] = f["dollars"].abs()
    g = f.groupby([f["exec_date"].rename("settle"), "sleeve", "ticker"], sort=True)
    out = g.agg(net_dollars=("signed", "sum"), gross_dollars=("gross", "sum"),
                n_fills=("signed", "size")).reset_index()
    return out[cols]


# ----------------------------------------------------------------------------------------------
# ADV, ex-ante
# ----------------------------------------------------------------------------------------------
def adv_panel(close: pd.DataFrame, volume: pd.DataFrame, window: int = ADV_WINDOW) -> pd.DataFrame:
    """The lab's one definition, via the TASK-406 builder (zero volume -> NaN, never 0.0 ADV)."""
    return build_adv(close, volume, window=window)


def adv_prev_bar(adv: pd.DataFrame, ticker: str, settle) -> float:
    """ADV at the market bar immediately BEFORE `settle` on `adv`'s own index, else NaN.

    `settle` must be a bar of the index (the engine settles on panel bars). The previous bar is
    positional - a Monday reads Friday - never `settle - 1 calendar day`. First bar, unknown
    ticker, or NaN at that bar (window not full, halted volume) -> NaN = UNKNOWN.
    """
    if ticker not in adv.columns:
        return float("nan")
    idx = adv.index
    pos = idx.get_indexer([pd.Timestamp(settle)])[0]
    if pos <= 0:
        return float("nan")
    v = adv.iat[pos - 1, adv.columns.get_loc(ticker)]
    return float(np.float64(v)) if pd.notna(v) else float("nan")


def attach_adv(fp: pd.DataFrame, adv: pd.DataFrame) -> pd.DataFrame:
    """Footprints + `adv_usd` (ex-ante) + `known` flag. Unknown is a state, not a zero."""
    out = fp.copy()
    out["adv_usd"] = [adv_prev_bar(adv, t, s) for t, s in zip(out["ticker"], out["settle"])]
    out["known"] = out["adv_usd"].notna() & (out["adv_usd"] > 0)
    return out


# ----------------------------------------------------------------------------------------------
# participation, P95, coverage, breaches
# ----------------------------------------------------------------------------------------------
def participation_pct(fp_adv: pd.DataFrame, capital: float) -> pd.Series:
    """|net_dollars| * capital / adv_usd, in percent; NaN where unknown.

    `net_dollars` are in units of the drive's capital (1.0), so `capital` rescales them to USD -
    licensed by the F5 property. For a real sheet (already in USD) pass capital=1.0.
    """
    part = fp_adv["net_dollars"].abs() * float(capital) / fp_adv["adv_usd"] * 100.0
    return part.where(fp_adv["known"], np.nan)


def p95_rank(values, n_unknown: int = 0) -> float:
    """The explicit order statistic at rank ceil(0.95 * N), 1-based, over known ∪ {+inf} x unknown.

    No interpolation anywhere. With N = len(values) + n_unknown and k = ceil(0.95 N): the result is
    +inf iff n_unknown >= N - k + 1, i.e. iff the unknowns reach into the top 5 % of the sorted
    sample. For N = 20 one unknown (5 %) leaves it finite, two do not; for N = 100 five do, six
    do not. Empty sample -> NaN (nothing to say), never 0.
    """
    known = np.asarray([v for v in np.asarray(values, dtype=float) if np.isfinite(v)], dtype=float)
    n = int(len(known) + int(n_unknown))
    if n == 0:
        return float("nan")
    k = int(math.ceil(0.95 * n))
    if k > len(known):
        return float("inf")
    return float(np.sort(known)[k - 1])


def coverage(fp_adv: pd.DataFrame) -> dict:
    n = int(len(fp_adv))
    notional = float(fp_adv["net_dollars"].abs().sum()) if n else 0.0
    k = fp_adv["known"] if n else pd.Series(dtype=bool)
    n_known = int(k.sum()) if n else 0
    notional_known = float(fp_adv.loc[k, "net_dollars"].abs().sum()) if n else 0.0
    return dict(
        footprints_total=n, footprints_known=n_known,
        footprints_covered_share=(n_known / n) if n else float("nan"),
        notional_total=notional, notional_known=notional_known,
        notional_covered_share=(notional_known / notional) if notional > 0 else float("nan"),
        unknown_share_by_count=((n - n_known) / n) if n else float("nan"),
        unknown_share_by_notional=((notional - notional_known) / notional) if notional > 0 else float("nan"),
    )


def breaches(part: pd.Series, thresholds=THRESHOLDS_PCT) -> dict:
    """Share of KNOWN footprints above each threshold, plus the unknown count beside them."""
    known = part.dropna()
    n = int(len(known))
    out = {f"gt_{t:g}pct": (float((known > t).mean()) if n else float("nan")) for t in thresholds}
    out["n_known"] = n
    out["n_unknown"] = int(part.isna().sum())
    return out


def two_p95(part: pd.Series) -> dict:
    known = part.dropna().to_numpy()
    n_unk = int(part.isna().sum())
    return dict(p95_descriptive=p95_rank(known, 0), p95_conservative=p95_rank(known, n_unk),
                n_known=int(len(known)), n_unknown=n_unk)


# ----------------------------------------------------------------------------------------------
# the ceiling
# ----------------------------------------------------------------------------------------------
def measurable(cov: dict) -> tuple[bool, list]:
    """The fail-closed gate: unknown share <= 5 % by count AND by notional."""
    why = []
    n, k = int(cov["footprints_total"]), int(cov["footprints_known"])
    if n <= 0:
        why.append("no footprints")
        return False, why
    # integers for the count: 5 of 100 is exactly 5 %, and a double must not decide that
    if (n - k) * 100 > int(round(UNKNOWN_SHARE_MAX * 100)) * n:
        why.append(f"unknown ADV on {cov['unknown_share_by_count']:.1%} of footprints (> 5 %)")
    if cov["unknown_share_by_notional"] > UNKNOWN_SHARE_MAX + 1e-12:
        why.append(f"unknown ADV on {cov['unknown_share_by_notional']:.1%} of notional (> 5 %)")
    return (not why), why


def aum_ceiling(fp_adv: pd.DataFrame, grid=None, bound_pct: float = CEILING_PCT) -> dict:
    """Largest C on the grid with conservative P95(participation at C) <= bound, bracketed.

    The curve is published so the scan can be audited; it is monotone in C by construction
    (participation is linear in C, unknowns are +inf at every C). `measurable` is the §3 gate; when
    it is False the descriptive scan is still returned under `NOT MEASURABLE`, never as a ceiling.
    """
    grid = list(grid or aum_grid())
    cov = coverage(fp_adv)
    ok, why = measurable(cov)
    curve = []
    for c in grid:
        part = participation_pct(fp_adv, c)
        q = two_p95(part)
        curve.append(dict(capital=float(c), p95_conservative=q["p95_conservative"],
                          p95_descriptive=q["p95_descriptive"]))
    passing = [r["capital"] for r in curve if r["p95_conservative"] <= bound_pct]
    failing = [r["capital"] for r in curve if not (r["p95_conservative"] <= bound_pct)]
    largest_passing = max(passing) if passing else None
    smallest_failing = min([f for f in failing if largest_passing is None or f > largest_passing],
                           default=None)
    if largest_passing is None:
        why = why + ["no capital on the grid passes the conservative bound"]
        ok = False
    return dict(
        label=LABEL,
        bound_pct=float(bound_pct),
        measurable=bool(ok),
        status="MEASURABLE" if ok else "NOT MEASURABLE",
        why_not_measurable=why,
        ceiling_usd=(float(largest_passing) if ok and largest_passing is not None else None),
        bracket=dict(largest_passing=largest_passing, smallest_failing=smallest_failing),
        curve=curve,
        coverage=cov,
    )


def scenario_table(fp_adv: pd.DataFrame, capitals=CAPITALS_USD) -> list:
    """Per capital level, per sleeve and total: breaches, both P95s, coverage. Label on every row."""
    rows = []
    groups = [("total", fp_adv)] + [(s, g) for s, g in fp_adv.groupby("sleeve", sort=True)]
    for c in capitals:
        for name, g in groups:
            part = participation_pct(g, c)
            q = two_p95(part)
            rows.append(dict(label=LABEL, capital=float(c), sleeve=name, **breaches(part),
                             p95_descriptive=q["p95_descriptive"],
                             p95_conservative=q["p95_conservative"], coverage=coverage(g)))
    return rows


# ----------------------------------------------------------------------------------------------
# F1 - the capacity drive IS the accredited drive
# ----------------------------------------------------------------------------------------------
def check_f1(reference: dict, book: pd.Series, measured: dict, *, rel: float = 1e-12) -> dict:
    """The sidecar drive reproduces the accredited book, or TASK-434 stops.

    `reference` = dict(book_sha256, calendar_sha256, n_marks, by_step, cost_bp_effective_by_sleeve)
    read from the accredited run (`20260914-cae2c54599aa`). `book_sha256` is provenance's seal on
    values AND index (`hash_pandas_object`), `calendar_sha256` the dated grid - never pickle bytes.
    The ledger comparison is per settle and sleeve on filled and cost dollars, plus the effective
    bp; `rel` is floating-point slack for identical arithmetic, not a tolerance for a different path.
    """
    import provenance as PV  # local: keeps capacity importable where the lab is not
    problems = []
    got_book = PV.book_sha256(book)
    got_cal = PV.calendar_sha256(book.index)
    if got_book != reference["book_sha256"]:
        problems.append(f"book_sha256 {got_book[:12]} != accredited {reference['book_sha256'][:12]}")
    if got_cal != reference["calendar_sha256"]:
        problems.append(f"calendar_sha256 {got_cal[:12]} != accredited {reference['calendar_sha256'][:12]}")
    if int(len(book)) != int(reference["n_marks"]):
        problems.append(f"{len(book)} marks != {reference['n_marks']}")
    led = (measured or {}).get("ledger") or {}
    mine, theirs = led.get("by_step") or {}, reference.get("by_step") or {}
    if set(mine) != set(theirs):
        problems.append(f"settle dates differ: {len(mine)} driven vs {len(theirs)} accredited")
    worst = 0.0
    for d in sorted(set(mine) & set(theirs)):
        for sleeve in sorted(set(mine[d]) | set(theirs[d])):
            a, b = mine[d].get(sleeve) or {}, theirs[d].get(sleeve) or {}
            for k in ("filled_dollars", "cost_dollars"):
                x, y = float(a.get(k, 0.0)), float(b.get(k, 0.0))
                worst = max(worst, abs(x - y))
                if not math.isclose(x, y, rel_tol=rel, abs_tol=0.0):
                    problems.append(f"{d} {sleeve} {k}: driven {x!r} vs accredited {y!r}")
    bp_mine = led.get("cost_bp_effective_by_sleeve") or {}
    bp_ref = reference.get("cost_bp_effective_by_sleeve") or {}
    for sleeve in sorted(set(bp_mine) | set(bp_ref)):
        x, y = float(bp_mine.get(sleeve, float("nan"))), float(bp_ref.get(sleeve, float("nan")))
        if not math.isclose(x, y, rel_tol=1e-9, abs_tol=0.0):
            problems.append(f"effective bp {sleeve}: driven {x} vs accredited {y}")
    return dict(passed=(not problems), problems=problems[:20], n_problems=len(problems),
                book_sha256=got_book, calendar_sha256=got_cal, n_marks=int(len(book)),
                max_abs_ledger_diff=worst, reference_book_sha256=reference["book_sha256"])


# ----------------------------------------------------------------------------------------------
# the real sheet
# ----------------------------------------------------------------------------------------------
def sheet_footprints(path: str, when: str = "planned") -> pd.DataFrame:
    """A weekly instruction sheet's orders as footprints in USD, dated at `planned` or `exec_date`.

    One sheet is one point: it goes in the table, it never gets a percentile of its own.
    """
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    orders = d.get("orders") or []
    date = d.get("exec_date") if when == "exec_date" else None
    rows = []
    for o in orders:
        if o.get("side") not in SIDE_SIGN:
            continue
        rows.append(dict(exec_date=str(date or o.get("planned") or d.get("date")),
                         sleeve=o.get("sleeve"), tranche=o.get("tranche"), ticker=o.get("ticker"),
                         side=o.get("side"), dollars=o.get("dollars"), cost=None, price=None,
                         units=None))
    return footprints(fills_frame(rows))


def payload(fp_adv: pd.DataFrame, *, grid=None, capitals=CAPITALS_USD, extra: dict | None = None) -> dict:
    """Everything this task publishes, `LABEL` at the top and on every row."""
    out = dict(label=LABEL, note=("participation ceiling under the pre-registered rule; NOT market "
                                  "impact, NOT certified capacity"),
               table=scenario_table(fp_adv, capitals), ceiling=aum_ceiling(fp_adv, grid))
    if extra:
        out.update(extra)
    return out
