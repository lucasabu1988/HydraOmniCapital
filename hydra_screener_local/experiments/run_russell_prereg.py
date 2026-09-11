"""TASK-431 — frozen HYDRA v9 on the Russell PIT panel.

Runs `.comms/prereg-russell-pit-2026-09-08.md` as written. No threshold moves.
The engine is `engine_backtest.drive_engine` on `_sweep_cache_russell/`; Wikipedia
S&P membership is never installed. SPY is injected from the OOS cache (the Russell
cache has no spy.pkl). Membership overlay is `membership.pkl`.

    python experiments/run_russell_prereg.py           # the declared run
    python experiments/run_russell_prereg.py --dry-run # freeze + coverage table, no engine
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPO = os.path.dirname(ROOT)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import engine_backtest as EB  # noqa: E402
import metrics as M  # noqa: E402
import redesign_lab as L  # noqa: E402
import sleeve_lab as S  # noqa: E402
from config import (  # noqa: E402
    ALGO_VERSION,
    MAX_DIST_TO_HIGH_PCT,
    MAX_PER_SECTOR,
    MIN_REGIME_SCORE,
    PROXIMITY_HIGH_DAYS,
    SHORT_TERM_BOOST,
    SHORT_TERM_LOOKBACK,
    VOL_SURGE_THRESHOLD,
    V9,
)

PREREG_PATH = os.path.join(REPO, ".comms", "prereg-russell-pit-2026-09-08.md")
# Claude 2026-09-11, amendment included. If this file does not hash here, the run is void.
PINNED_PREREG_SHA256 = "3d5598d944ce887caf1abb6121daff3c46b3fdee1c7513027b99d6274fae890e"

RUSSELL_CACHE = os.path.join(HERE, "_sweep_cache_russell")
OOS_CACHE = os.path.join(HERE, "_sweep_cache_oos")
TRADING_CACHE = os.path.join(HERE, "_lab_scratch", "russell_prereg_cache")
SP_BOOK = os.path.join(HERE, "_lab_scratch", "engine_book_oos.pkl")
SCRATCH = os.path.join(HERE, "_lab_scratch", "task431.json")
STEP = 5
# EODHD keeps US holidays as rows where 1–7 of 6048 names print. Yahoo's OOS panel
# drops those days. A holiday NaN poisons rolling(20) volume for 20 bars and
# rolling(63) vol for 63 bars, so rank_day returns None on almost every step.
# Dropping them is calendar hygiene, not a threshold move.
MIN_PRINT_SHARE = 0.05

# Published S&P 500 PIT engine row (TASK-350 --oos). Universe comparison, not a re-run.
SP_OOS_PUBLISHED = dict(ann_net=7.03, ratio_net_vol=0.74, maxdd_net=-17.7, sharpe_excess=0.56)

FROZEN_FILE_HASHES = {
    "core/signals.py": "f9806b77bd61",
    # Amendment: 656ff8135814 -> 0f475602519b is typing/whitespace (5e4b4f6); body unchanged.
    "core/regime.py": "0f475602519b",
    "core/filters.py": "95c78d2591c6",
    "core/meta_layer.py": "5e81ff429455",
}

FROZEN_V9 = {
    "step_bars": 5,
    "hold_bars": 20,
    "tranches": 4,
    "stock_momentum_window": "mom12_7",
    "stock_buffer": 2.0,
    "stock_target_vol": 0.15,
    "stock_cost_bp": 10.0,
    "etf_lookback_bars": 252,
    "etf_vol_bars": 63,
    "etf_cost_bp": 5.0,
    "max_stale_bars": 10,
}
FROZEN_ETF_UNIVERSE = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "GLD", "DBC", "VNQ"]
FROZEN_MIX = {"stocks": 0.5, "etf": 0.5}
FROZEN_CONFIG = {
    "MAX_PER_SECTOR": 5,
    "MIN_REGIME_SCORE": 0.35,
    "SHORT_TERM_LOOKBACK": 10,
    "PROXIMITY_HIGH_DAYS": 20,
    "MAX_DIST_TO_HIGH_PCT": 3.0,
    "SHORT_TERM_BOOST": 0.35,
    "VOL_SURGE_THRESHOLD": 1.50,
    "ALGO_VERSION": "v9",
}

SURVIVE_D = -0.10
FAIL_D = -0.25
MAXDD_WORSE_PP = 5.0
MIN_CYCLES = 200  # ~4y of 5-bar steps; fewer means the calendar is still poisoned


def sha256_file(path: str, *, lf: bool = False) -> str:
    """sha256 of file bytes. `lf=True` folds CRLF to LF so Windows autocrlf matches the git blob."""
    with open(path, "rb") as fh:
        data = fh.read()
    if lf:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def sha256_12(path: str) -> str:
    return sha256_file(path)[:12]


def verify_freeze() -> dict:
    """Fail closed if the prereg file or the frozen surface has moved."""
    if not os.path.exists(PREREG_PATH):
        raise SystemExit(f"prereg missing: {PREREG_PATH}")
    prereg = sha256_file(PREREG_PATH, lf=True)
    if prereg != PINNED_PREREG_SHA256:
        raise SystemExit(
            f"prereg hash mismatch: got {prereg}, pinned {PINNED_PREREG_SHA256}. "
            "The run is void; rewrite the pre-registration with a new date."
        )
    problems = []
    hashes = {}
    for rel, expect in FROZEN_FILE_HASHES.items():
        got = sha256_12(os.path.join(ROOT, rel))
        hashes[rel] = got
        if got != expect:
            problems.append(f"{rel}: {got} != {expect}")
    for key, expect in FROZEN_V9.items():
        got = V9.get(key)
        if got != expect:
            problems.append(f"V9[{key!r}]: {got!r} != {expect!r}")
    if list(V9.get("etf_universe") or []) != FROZEN_ETF_UNIVERSE:
        problems.append(f"V9 etf_universe {V9.get('etf_universe')!r} != {FROZEN_ETF_UNIVERSE}")
    mix = V9.get("mix") or {}
    if dict(mix) != FROZEN_MIX:
        problems.append(f"V9 mix {mix!r} != {FROZEN_MIX}")
    live = {
        "MAX_PER_SECTOR": MAX_PER_SECTOR,
        "MIN_REGIME_SCORE": MIN_REGIME_SCORE,
        "SHORT_TERM_LOOKBACK": SHORT_TERM_LOOKBACK,
        "PROXIMITY_HIGH_DAYS": PROXIMITY_HIGH_DAYS,
        "MAX_DIST_TO_HIGH_PCT": MAX_DIST_TO_HIGH_PCT,
        "SHORT_TERM_BOOST": SHORT_TERM_BOOST,
        "VOL_SURGE_THRESHOLD": VOL_SURGE_THRESHOLD,
        "ALGO_VERSION": ALGO_VERSION,
    }
    for key, expect in FROZEN_CONFIG.items():
        if live[key] != expect:
            problems.append(f"{key}: {live[key]!r} != {expect!r}")
    if problems:
        raise SystemExit("frozen surface moved:\n  " + "\n  ".join(problems))
    return dict(prereg_sha256=prereg, file_hashes=hashes, v9=dict(FROZEN_V9), config=dict(FROZEN_CONFIG))


def load_coverage(cache_dir: str) -> dict:
    path = os.path.join(cache_dir, "coverage.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def caveat_table(cov: dict) -> pd.DataFrame:
    """Own table, not a footnote. The four figures the amendment requires next to every number."""
    dropped = cov.get("spliced_dropped") or []
    return pd.DataFrame([
        dict(item="cell_coverage", value=cov.get("cell_coverage"),
             note="priced member-cells / full membership record"),
        dict(item="ghost_names", value=cov.get("ghost_names"),
             note="still members >1y after last print"),
        dict(item="ghost_member_cells", value=cov.get("ghost_member_cells"),
             note="empty member-cells after last print + 1y"),
        dict(item="spliced_dropped", value=",".join(dropped) if dropped else None,
             note="ticker-reuse columns excluded from the panel"),
        dict(item="honest_window", value=cov.get("honest_window"),
             note="free record starts June 2010"),
        dict(item="names", value=cov.get("names"),
             note=f"requested {cov.get('names_requested')}"),
        dict(item="holiday_rows_dropped", value=cov.get("holiday_rows_dropped"),
             note=f"EODHD US-holiday rows, print share < {MIN_PRINT_SHARE:.0%}"),
    ])


def trading_day_mask(close: pd.DataFrame, min_print_share: float = MIN_PRINT_SHARE) -> pd.Series:
    """True on dates where enough names printed. Holidays are ~1/6048."""
    share = close.notna().mean(axis=1)
    return share >= float(min_print_share)


def materialize_trading_cache(src: str, dest: str, oos_cache: str) -> dict:
    """Copy the Russell panel with holiday rows removed so rolling windows match Yahoo."""
    close = pd.read_pickle(os.path.join(src, "close.pkl"))
    keep = trading_day_mask(close)
    dropped = int((~keep).sum())
    dates = [str(pd.Timestamp(d).date()) for d in close.index[~keep]]
    os.makedirs(dest, exist_ok=True)
    for name in ("close", "close_raw", "volume", "open"):
        path = os.path.join(src, f"{name}.pkl")
        if not os.path.exists(path):
            continue
        pd.read_pickle(path).loc[keep].to_pickle(os.path.join(dest, f"{name}.pkl"))
    mem_path = os.path.join(src, "membership.pkl")
    if os.path.exists(mem_path):
        mem = pd.read_pickle(mem_path)
        mem.reindex(index=close.index[keep]).to_pickle(os.path.join(dest, "membership.pkl"))
    ensure_spy(src, oos_cache)
    spy = pd.read_pickle(os.path.join(src, "spy.pkl"))
    spy.reindex(close.index[keep]).to_pickle(os.path.join(dest, "spy.pkl"))
    cov_src = os.path.join(src, "coverage.json")
    cov = json.load(open(cov_src, encoding="utf-8")) if os.path.exists(cov_src) else {}
    cov["holiday_rows_dropped"] = dropped
    cov["holiday_dates"] = dates
    with open(os.path.join(dest, "coverage.json"), "w", encoding="utf-8") as fh:
        json.dump(cov, fh, indent=2)
    print(f"dropped {dropped} EODHD holiday rows (print share < {MIN_PRINT_SHARE:.0%}); "
          f"trading cache {close.loc[keep].shape}", flush=True)
    return cov


def ensure_spy(russell_cache: str, oos_cache: str) -> str:
    dest = os.path.join(russell_cache, "spy.pkl")
    if os.path.exists(dest):
        return dest
    src = os.path.join(oos_cache, "spy.pkl")
    if not os.path.exists(src):
        raise SystemExit(f"need SPY at {src} to inject into the Russell cache")
    shutil.copy2(src, dest)
    print(f"injected spy.pkl from OOS cache -> {dest}", flush=True)
    return dest


def attach_russell_membership(P, membership) -> callable:
    """AND the Russell membership frame into eligibility. Never a Wikipedia PIT payload.

    `membership` is a boolean DataFrame or a pickle path. Returns a restorer for
    `redesign_lab.eligibility_mask`.
    """
    if isinstance(membership, str):
        membership = pd.read_pickle(membership)
    m = membership.reindex(index=P.close.index, columns=P.close.columns)
    m = m.where(m.notna(), False).astype(bool)
    P.MEMBERSHIP = m
    P.pit_payload = None
    orig = L.eligibility_mask

    def wrapped(P_, t, c):
        elig = orig(P_, t, c)
        row = P_.MEMBERSHIP.iloc[t].reindex(elig.index)
        return (elig & row.fillna(False)).astype(bool)

    L.eligibility_mask = wrapped

    def restore():
        L.eligibility_mask = orig

    return restore


def start_bar(P) -> int:
    """First bar the engine may plan: max(280, first membership date on this calendar)."""
    has = P.MEMBERSHIP.any(axis=1)
    if not bool(has.any()):
        raise SystemExit("Russell membership is empty on the close calendar")
    first = int(np.argmax(has.to_numpy()))
    return max(int(EB.START), first)


def align_book_to_marks(book: pd.Series, marks: pd.DatetimeIndex) -> pd.Series:
    """S&P marks sit on the Yahoo 5-bar grid; Russell marks sit on EODHD's.

    Forward-fill the S&P wealth path onto the Russell mark calendar so the pair is
    the same dates, not the same phase.
    """
    sp = pd.Series(book).copy()
    sp.index = pd.DatetimeIndex(sp.index)
    marks = pd.DatetimeIndex(marks)
    union = sp.index.union(marks).sort_values()
    return sp.reindex(union).ffill().reindex(marks).dropna()


def memmel_se(e1: pd.Series, e2: pd.Series) -> dict:
    """Memmel (2003) SE of the difference of two per-period Sharpes, annualised."""
    common = e1.index.intersection(e2.index)
    a = e1.loc[common].astype(float)
    b = e2.loc[common].astype(float)
    n = int(len(common))
    if n < 3:
        return dict(n=n, d_sharpe=float("nan"), se=float("nan"), rho=float("nan"))
    py = M.periods_per_year(STEP)
    s1 = float(a.mean() / a.std(ddof=1)) if a.std(ddof=1) else 0.0
    s2 = float(b.mean() / b.std(ddof=1)) if b.std(ddof=1) else 0.0
    rho = float(a.corr(b)) if a.std(ddof=1) and b.std(ddof=1) else 0.0
    var = (1.0 / n) * (2.0 - 2.0 * rho + 0.5 * (s1 ** 2 + s2 ** 2) - rho * s1 * s2)
    se_step = float(np.sqrt(max(var, 0.0)))
    return dict(
        n=n,
        d_sharpe=round((s1 - s2) * np.sqrt(py), 4),
        se=round(se_step * np.sqrt(py), 4),
        rho=round(rho, 4),
    )


def cost_from_ledger(counts: dict, cost_dollars: float, book: pd.Series) -> dict:
    """Implied annual cost as a fraction of ann_net. Engine net already includes these costs."""
    n = max(int(len(book)) - 1, 1)
    years = n * STEP / 252.0
    mean_book = float(book.mean()) if len(book) else 1.0
    ann_cost_pct = (float(cost_dollars) / mean_book / years * 100.0) if years and mean_book else 0.0
    turnover = float(counts.get("turnover") or 0.0)
    blended_bp = 0.5 * float(V9["stock_cost_bp"]) + 0.5 * float(V9["etf_cost_bp"])
    # turnover is mean(traded/book)*100 per step; traded is buy+sell dollars.
    step_cost = (turnover / 100.0) * (blended_bp / 10000.0)
    ann_from_turnover = step_cost * (252.0 / STEP) * 100.0
    return dict(
        cost_dollars=round(float(cost_dollars), 6),
        ann_cost_pct_of_mean_book=round(ann_cost_pct, 3),
        ann_cost_pct_from_turnover=round(ann_from_turnover, 3),
        blended_bp=blended_bp,
        turnover_pct_per_step=turnover,
    )


def verdict(*, d_sharpe: float, dd_worse_pp: float, cost_frac: float | None) -> str:
    """The rule written before looking. Point estimate vs the two fences; SE is reported beside it."""
    fail_sharpe = d_sharpe <= FAIL_D
    fail_cost = bool(cost_frac is not None and cost_frac > 0.5)
    if fail_sharpe or fail_cost:
        return "FAIL"
    if d_sharpe >= SURVIVE_D and dd_worse_pp <= MAXDD_WORSE_PP:
        return "SURVIVE"
    return "INCONCLUSIVE"


def _patch_settle_cost(accum: dict) -> callable:
    orig = EB.E.settle

    def wrapped(*a, **k):
        fills = orig(*a, **k)
        for f in fills:
            if f.get("status") == "filled":
                accum["dollars"] += float(f.get("cost") or 0.0)
                accum["n"] += 1
        return fills

    EB.E.settle = wrapped

    def restore():
        EB.E.settle = orig

    return restore


def _stats_row(book: pd.Series, irx: pd.Series, label: str) -> dict:
    rf = M.step_risk_free(irx, book.index)
    return M.stats(book.pct_change().dropna(), label, STEP, rf=rf)


def run(cache_dir: str) -> dict:
    freeze = verify_freeze()
    print("freeze OK  prereg", freeze["prereg_sha256"], flush=True)
    for rel, h in freeze["file_hashes"].items():
        print(f"  {rel} {h}", flush=True)

    cov = materialize_trading_cache(cache_dir, TRADING_CACHE, OOS_CACHE)
    print("\n--- panel caveats (table, not a footnote) ---", flush=True)
    print(caveat_table(cov).to_string(index=False), flush=True)

    print("\nloading Russell panel (FLAT5 over ~6000 names; this can take a while)...", flush=True)
    P = L.load_panel(oos=False, cache_dir=TRADING_CACHE)
    restore_mem = attach_russell_membership(P, os.path.join(TRADING_CACHE, "membership.pkl"))
    P.ETF = S.load_etfs(P.close.index)
    start = start_bar(P)
    print(f"  close {P.close.shape} {P.close.index[0].date()} -> {P.close.index[-1].date()}", flush=True)
    print(f"  START {start} {P.close.index[start].date()} (warmup {EB.START}, membership first)",
          flush=True)
    print(f"  membership True-share {float(P.MEMBERSHIP.mean().mean()):.3f}  "
          f"pit_payload={P.pit_payload!r}", flush=True)

    cost_acc = dict(dollars=0.0, n=0)
    restore_settle = _patch_settle_cost(cost_acc)
    old_start = EB.START
    try:
        EB.START = start
        print("engine (pair reset, trailing hurdle, interest; frozen V9)...", flush=True)
        eng, counts = EB.drive_engine(P, progress_every=25)
    finally:
        EB.START = old_start
        restore_settle()
        restore_mem()

    print("  engine series", len(eng),
          str(eng.index[0].date()) if len(eng) else None, "->",
          str(eng.index[-1].date()) if len(eng) else None, flush=True)

    rus = _stats_row(eng, P.IRX, "engine Russell PIT")
    cost = cost_from_ledger(counts, cost_acc["dollars"], eng)
    ann_net = float(rus.get("ann_net") or 0.0)
    ann_cost = float(cost["ann_cost_pct_of_mean_book"])
    cost_frac = (ann_cost / ann_net) if ann_net > 0 else None

    sp_pub = dict(config="S&P 500 PIT engine --oos (published)", **SP_OOS_PUBLISHED)
    pair = None
    sp_overlap = None
    d_sharpe = float("nan")
    dd_worse = float("nan")
    if os.path.exists(SP_BOOK) and len(eng):
        sp_book = pd.read_pickle(SP_BOOK)
        sp_aligned = align_book_to_marks(sp_book, pd.DatetimeIndex(eng.index))
        common = eng.index.intersection(sp_aligned.index)
        if len(common) >= 20:
            rus_c = eng.loc[common]
            sp_c = sp_aligned.loc[common]
            rus_on = _stats_row(rus_c, P.IRX, "Russell on overlap")
            sp_overlap = _stats_row(sp_c, P.IRX, "S&P 500 on overlap")
            r_ex = rus_c.pct_change().dropna()
            s_ex = sp_c.pct_change().dropna()
            rf = M.step_risk_free(P.IRX, rus_c.index)
            # excess = net - rf, on common return dates
            r_net = r_ex.reindex(rf.index).dropna()
            s_net = s_ex.reindex(rf.index).dropna()
            both = r_net.index.intersection(s_net.index)
            pair = memmel_se(r_net.loc[both] - rf.loc[both], s_net.loc[both] - rf.loc[both])
            d_sharpe = float(pair["d_sharpe"])
            dd_r = float(rus_on.get("maxdd_net") or 0.0)
            dd_s = float(sp_overlap.get("maxdd_net") or 0.0)
            dd_worse = dd_s - dd_r  # more negative Russell => positive worse-pp
            pair["dd_russell"] = dd_r
            pair["dd_sp"] = dd_s
            pair["dd_worse_pp"] = round(dd_worse, 2)
            pair["n_marks"] = int(len(common))
            pair["first"] = str(pd.Timestamp(common[0]).date())
            pair["last"] = str(pd.Timestamp(common[-1]).date())

    decision = verdict(
        d_sharpe=d_sharpe if np.isfinite(d_sharpe) else FAIL_D - 1,  # missing pair is not survive
        dd_worse_pp=dd_worse if np.isfinite(dd_worse) else MAXDD_WORSE_PP + 1,
        cost_frac=cost_frac,
    )
    n_cycles = int(rus.get("cycles") or 0)
    if n_cycles < MIN_CYCLES or not np.isfinite(d_sharpe):
        decision = "INCONCLUSIVE"
        print(f"NOTE: engine cycles {n_cycles} < {MIN_CYCLES} or pair missing: "
              "not a prereg verdict (calendar still poisoned or overlay bug).", flush=True)

    rows = [sp_pub, rus]
    if sp_overlap is not None:
        rows.append(sp_overlap)

    print("\n--- universe comparison ---", flush=True)
    print(pd.DataFrame(rows).to_string(index=False), flush=True)
    if pair:
        print("\n--- paired delta (Russell − S&P, same dates, S&P wealth ffilled onto Russell marks) ---",
              flush=True)
        print(pd.DataFrame([pair]).to_string(index=False), flush=True)
        print(f"  d_sharpe {pair['d_sharpe']}  SE {pair['se']}  "
              f"survive>={SURVIVE_D}  fail<={FAIL_D}", flush=True)
        print(f"  maxDD Russell {pair['dd_russell']}  S&P {pair['dd_sp']}  "
              f"worse_pp {pair['dd_worse_pp']}  fence {MAXDD_WORSE_PP}", flush=True)
    print("\n--- costs ---", flush=True)
    print(pd.DataFrame([cost]).to_string(index=False), flush=True)
    print(f"  cost / ann_net = {cost_frac if cost_frac is not None else 'n/a'}  "
          f"(fail if > 0.5)", flush=True)

    print("\n--- plumbing ---", flush=True)
    print("  not_filled", counts.get("not_filled"), "hold_no_price", counts.get("hold_no_price"),
          "write-offs", counts.get("write_offs"), "turnover", counts.get("turnover"), flush=True)

    print(f"\nVERDICT  {decision}", flush=True)
    if decision == "FAIL":
        print("prereg failed: do not retune. Open H-0xx and stop.", flush=True)
    elif decision == "SURVIVE":
        print("v9 is measured on its own universe.", flush=True)
    else:
        print("inconclusive: declare it and touch nothing.", flush=True)

    payload = dict(
        task="TASK-431",
        prereg=os.path.relpath(PREREG_PATH, REPO).replace("\\", "/"),
        prereg_sha256=freeze["prereg_sha256"],
        freeze=freeze,
        coverage=cov,
        caveats=caveat_table(cov).to_dict(orient="records"),
        rows=rows,
        pair=pair,
        cost=cost,
        cost_frac_of_ann_net=cost_frac,
        verdict=decision,
        counts={k: v for k, v in counts.items()
                if k not in ("write_off_names", "hold_no_price_names", "not_filled_names",
                             "interest_by_year", "replayed")},
        engine_first=str(eng.index[0].date()) if len(eng) else None,
        engine_last=str(eng.index[-1].date()) if len(eng) else None,
        start_bar=start,
        start_date=str(P.close.index[start].date()),
        note="frozen v9 on Russell PIT; no threshold moved",
    )
    os.makedirs(os.path.dirname(SCRATCH), exist_ok=True)
    with open(SCRATCH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    pd.to_pickle(eng, os.path.join(HERE, "_lab_scratch", "engine_book_russell.pkl"))
    print("wrote", SCRATCH, flush=True)
    return payload


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="TASK-431: frozen v9 on Russell PIT")
    ap.add_argument("--cache", default=RUSSELL_CACHE, help="Russell panel cache directory")
    ap.add_argument("--dry-run", action="store_true",
                    help="verify the freeze and print the caveat table; do not drive the engine")
    args = ap.parse_args(argv)

    freeze = verify_freeze()
    print("freeze OK  prereg", freeze["prereg_sha256"], flush=True)
    cov = load_coverage(args.cache)
    if cov:
        print("\n--- panel caveats (table, not a footnote) ---", flush=True)
        print(caveat_table(cov).to_string(index=False), flush=True)
    else:
        print("SKIP coverage.json missing at", args.cache, flush=True)
    if args.dry_run:
        print("dry-run: engine not started", flush=True)
        return 0
    if not os.path.exists(os.path.join(args.cache, "close.pkl")):
        print("SKIP:", os.path.join(args.cache, "close.pkl"), "missing", flush=True)
        return 0
    if not os.path.exists(os.path.join(args.cache, "membership.pkl")):
        print("SKIP: membership.pkl missing", flush=True)
        return 0
    run(args.cache)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
