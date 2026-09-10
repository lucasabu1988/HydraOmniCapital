"""TASK-411 (a) — H-005 measured on the PIT panel: what it costs that the write-off clock
counts forward fills as prints.

`TrancheBook.age_stale` takes any finite price as a print: it clears the staleness counter and
rewrites `last_px`. In production `data.fetch` forward-fills gaps of up to
`FFILL_LIMIT_BARS` (3) bars, so a name that stopped printing can have its clock reset by a
fill and be carried past `max_stale_bars`. The lab panel never goes through `data.fetch` —
`experiments/backtest_variant_sweep.Panels.__init__` fills only `spy`, not `close` — so on the
panel `close.notna()` IS the observed mask, bit for bit what `attach_observed(prices,
prices.notna())` would store. That is what makes this half measurable today, without
`fix/astra-03`.

Two arms, identical rankings (both computed from the raw panel), differing only in the price
series the BOOK sees:

    observed   raw panel prices; a name that does not print is NaN and the clock runs
    filled     close.ffill(limit=3), production's own fill; a fill resets the clock

Measure only (rule 6). Changing the policy moves write-offs, historical P/L and cash, and that
is Lucas's call.

    python experiments/stale_policy_ab.py            # OOS PIT panel 2004-26
    python experiments/stale_policy_ab.py --in-sample
"""
from __future__ import annotations

import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import engine_backtest as EB  # noqa: E402
import metrics as M  # noqa: E402
import redesign_lab as L  # noqa: E402
import sleeve_lab as S  # noqa: E402
from config import V9  # noqa: E402
import core.portfolio_engine as E  # noqa: E402
from data.fetch import FFILL_LIMIT_BARS  # noqa: E402

START = EB.START
STEP = EB.STEP


# ----------------------------------------------------------------------- pure, cheap to test
def fill_like_production(close: pd.DataFrame) -> pd.DataFrame:
    """The panel as `data.fetch` would hand it over: gaps of at most FFILL_LIMIT_BARS filled,
    longer holes left NaN. Same call as `data/fetch.py:291`, so the two cannot drift."""
    return close.ffill(limit=FFILL_LIMIT_BARS)


def write_off_step(prices, max_stale_bars: int) -> int | None:
    """Replay `age_stale` for ONE held name over `prices` (one value per step, NaN = no print).

    Returns the index of the step at which the name is written off, or None if it survives the
    series. This is the accounting clock alone: no cash, no ranking, no engine.
    """
    stale = 0
    for i, p in enumerate(prices):
        if np.isfinite(p):
            stale = 0
            continue
        stale += 1
        if stale >= max_stale_bars:
            return i
    return None


def fill_carried_bars(raw, filled) -> int:
    """Bars of ageing a fill erases: the step is not observed (raw NaN) and the fill still hands
    the book a finite price, so `age_stale` clears the counter instead of advancing it.

    Counts every such bar, including the first missing one — that bar is exactly where the
    observed clock would have started. The stricter question, "how often did a fill wipe a
    counter that had already accumulated", is answered engine-side by `run_arm`, which reads
    the real `stale` map before and after each `plan()`.
    """
    return sum(1 for r, f in zip(raw, filled) if not np.isfinite(r) and np.isfinite(f))


# ----------------------------------------------------------------------------- the engine arm
def _held(state: dict) -> dict:
    """{(sleeve, tranche, ticker): stale_count} for every name the book holds right now."""
    out = {}
    for sleeve, s in state["sleeves"].items():
        for tr in s["tranches"]:
            k = int(tr["k"])
            for tk in tr["units"]:
                out[(sleeve, k, tk)] = int((tr.get("stale") or {}).get(tk, 0))
    return out


def run_arm(P, book_close: pd.DataFrame, *, label: str, capital: float = 1.0,
            progress_every: int = 50) -> dict:
    """Drive the production engine over the panel with `book_close` as the price series the
    book sees. Rankings always come from the raw panel, so the arms differ in one thing only.
    """
    cfg = dict(V9)
    idx = P.close.index
    st = E.new_state(float(capital), str(idx[START].date()), cfg)
    etf, irx = P.ETF, P.IRX
    c = dict(L.BASE)
    c.update(L.CONFIGS["T20"])
    recs, resets, carried = [], [], []
    prev_t = None
    n_steps = len(range(START, len(idx) - 6, STEP))

    for i, t in enumerate(range(START, len(idx) - 6, STEP)):
        today = str(idx[t].date())
        if st.get("pending") and prev_t is not None and prev_t + 1 < len(idx):
            e = prev_t + 1
            E.settle(st, str(idx[e].date()), book_close.iloc[e], etf.iloc[e], cfg)
        rk = EB._ranking(P, t, c)
        if rk is None:
            prev_t = t
            continue

        before = _held(st)
        st, _orders = E.plan(st, today, rk, book_close.iloc[: t + 1], etf.iloc[: t + 1], irx, cfg)
        after = _held(st)
        raw_row, fill_row = P.close.iloc[t], book_close.iloc[t]
        for key, stale_before in before.items():
            sleeve, k, tk = key
            if sleeve != "stocks" or key not in after:
                continue
            if np.isfinite(raw_row.get(tk, np.nan)) or not np.isfinite(fill_row.get(tk, np.nan)):
                continue
            # `last_px` just took a number nobody printed (question 1 of the TASK-402 note)
            carried.append(dict(date=today, tranche=k, ticker=tk, stale_before=stale_before))
            if stale_before > 0 and after[key] == 0:
                # ...and it wiped a counter that had already accumulated
                resets.append(dict(date=today, tranche=k, ticker=tk, stale_before=stale_before))

        prev_t = t
        s = E.summary_table(st, book_close.iloc[t], etf.iloc[t], cfg)
        recs.append((idx[t], s["total"]))
        if progress_every and (i + 1) % progress_every == 0:
            print(f"  {label} {i + 1}/{n_steps} {today} book={s['total']:.4f} "
                  f"wo={len(st.get('write_offs') or [])} resets={len(resets)}", flush=True)

    wo = list(st.get("write_offs") or [])
    ser = pd.Series({d: v for d, v in recs}, dtype=float).sort_index()
    return dict(
        label=label,
        book=ser,
        write_offs=[dict(date=w.get("date"), ticker=w.get("ticker"), sleeve=w.get("sleeve"),
                         proceeds=round(float(w.get("proceeds") or 0), 6)) for w in wo],
        write_off_dollars=round(float(sum(float(w.get("proceeds") or 0) for w in wo)), 6),
        resets=resets,
        carried_marks=carried,
    )


def bars_since_last_print(close: pd.DataFrame, ticker: str, date) -> int | None:
    """Bars between the last OBSERVED print of `ticker` and `date` (question 2 of the TASK-402
    note: how long a name is really carried, counting prints only, against the ten bars
    `max_stale_bars` claims)."""
    if ticker not in close.columns:
        return None
    col = close[ticker]
    upto = col.loc[: pd.Timestamp(date)]
    printed = upto.dropna()
    if printed.empty:
        return None
    return int(len(upto) - upto.index.get_loc(printed.index[-1]) - 1)


def compare(a: dict, b: dict, rf: pd.Series | None = None) -> dict:
    """`a` = observed (reference), `b` = filled (production-like). Positive `delay_bars` means
    the fill kept a name on the book longer than the observed clock would have."""
    sa = M.stats(a["book"].pct_change().dropna(), a["label"], STEP, rf=rf)
    sb = M.stats(b["book"].pct_change().dropna(), b["label"], STEP, rf=rf)

    first_a = {}
    for w in a["write_offs"]:
        first_a.setdefault((w["sleeve"], w["ticker"]), w["date"])
    first_b = {}
    for w in b["write_offs"]:
        first_b.setdefault((w["sleeve"], w["ticker"]), w["date"])

    delays, both = [], sorted(set(first_a) & set(first_b))
    for key in both:
        d = (pd.Timestamp(first_b[key]) - pd.Timestamp(first_a[key])).days
        delays.append(dict(sleeve=key[0], ticker=key[1], observed=first_a[key],
                           filled=first_b[key], calendar_days=int(d)))
    moved = sorted(set(first_a) ^ set(first_b))
    lagged = [d for d in delays if d["calendar_days"] != 0]

    return dict(
        observed=sa, filled=sb,
        ann_net_gap=round(float((sb.get("ann_net") or 0) - (sa.get("ann_net") or 0)), 4),
        maxdd_gap=round(float((sb.get("maxdd_net") or 0) - (sa.get("maxdd_net") or 0)), 4),
        write_offs=dict(observed=len(a["write_offs"]), filled=len(b["write_offs"])),
        write_off_dollars=dict(observed=a["write_off_dollars"], filled=b["write_off_dollars"],
                               displaced=round(b["write_off_dollars"] - a["write_off_dollars"], 6)),
        fill_resets=len(b["resets"]),
        reset_names=sorted({r["ticker"] for r in b["resets"]}),
        carried_marks=dict(n=len(b["carried_marks"]),
                           names=sorted({r["ticker"] for r in b["carried_marks"]})),
        delay_days=dict(
            n_compared=len(delays), n_lagged=len(lagged),
            median=float(np.median([d["calendar_days"] for d in lagged])) if lagged else 0.0,
            max=int(max((d["calendar_days"] for d in lagged), default=0)),
        ),
        only_in_one_arm=[dict(sleeve=k[0], ticker=k[1],
                              observed=first_a.get(k), filled=first_b.get(k)) for k in moved],
        lagged=lagged,
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description="TASK-411(a): stale-clock A/B on the lab panel")
    ap.add_argument("--in-sample", action="store_true",
                    help="in-sample panel _sweep_cache/ 2020-26. Default: OOS PIT 2004-26.")
    ap.add_argument("--json", default=None, help="write the full result to this path")
    args = ap.parse_args(argv)

    oos = not args.in_sample
    cache = os.path.join(HERE, "_sweep_cache_oos" if oos else "_sweep_cache", "close.pkl")
    if not os.path.exists(cache):
        print("SKIP:", cache, "missing")
        return 0

    print(f"loading {'OOS PIT' if oos else 'in-sample'} panel...", flush=True)
    P = L.load_panel(oos=oos)
    P.ETF = S.load_etfs(P.close.index)
    raw = P.close
    filled = fill_like_production(raw)
    n_filled = int((filled.notna() & raw.isna()).to_numpy().sum())
    print(f"  close {raw.shape}  {raw.index[0].date()} -> {raw.index[-1].date()}", flush=True)
    print(f"  cells the production fill would invent: {n_filled} "
          f"({100.0 * n_filled / raw.size:.3f}% of the panel)", flush=True)

    a = run_arm(P, raw, label="observed")
    b = run_arm(P, filled, label="filled")
    rf = M.step_risk_free(P.IRX, a["book"].index)
    out = compare(a, b, rf=rf)
    out["carried_before_write_off"] = {
        arm["label"]: [dict(ticker=w["ticker"], date=w["date"],
                            bars_since_print=bars_since_last_print(raw, w["ticker"], w["date"]))
                       for w in arm["write_offs"]]
        for arm in (a, b)
    }
    out["panel"] = dict(oos=oos, shape=list(raw.shape), filled_cells=n_filled,
                        ffill_limit_bars=FFILL_LIMIT_BARS,
                        max_stale_bars=V9["max_stale_bars"])

    print("\n" + json.dumps({k: v for k, v in out.items() if k not in ("lagged", "only_in_one_arm")},
                            indent=2, default=str))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, default=str)
        print("wrote", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
