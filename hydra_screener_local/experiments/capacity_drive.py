"""TASK-434 steps 5-7: ADV panels (sha256), ONE drive per panel with the fill sidecar, F1 in full.

    python experiments/capacity_drive.py                # both panels, stops at the first F1 failure
    python experiments/capacity_drive.py --panel russell

Pre-registration: `.comms/prereg-task-434-2026-09-14.md` (sha256 on the board). This script produces
EVIDENCE, not numbers: it writes the sidecar, the book, its manifest and the F1 record under
`_lab_scratch/capacity/runs/<run_id>/`. Reading participation, P95 or a ceiling is `capacity_report.py`,
which refuses to run unless the F1 record here says `passed: true` for the panel.

The drive is `cost_stress.drive(panel, 10, 5)` - the exact call `accredit_433.produce` made for the
accredited `<panel>/base` books - wrapped in `capacity.FillTap`, an observer on `settle`. F1 then
requires `book_sha256` and `calendar_sha256` equal to the accredited book's, the same 814 settles
with the same per-sleeve filled and cost dollars, and the same effective bp. If F1 fails nothing
else is written and the exit code is non-zero: the sidecar changed the path, and the task is a
bug, not capacity.

Nothing under `accredited/` is written, re-sealed or read for anything but the reference.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # cp1252 consoles never take a run down

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import accredit_433 as A  # noqa: E402
import capacity as C  # noqa: E402
import cost_stress as CS  # noqa: E402
import provenance as PV  # noqa: E402
import run_russell_prereg as R  # noqa: E402
import sleeve_lab as S  # noqa: E402

ACCREDITED_433 = "20260914-cae2c54599aa"
CAP_ROOT = os.path.join(HERE, "_lab_scratch", "capacity", "runs")
BASE_BP = (10.0, 5.0)                     # the base scenario; the sidecar drive IS russell/base
LIVE_SHEET = os.path.join(ROOT, "state", "instructions_20260904.json")
PANEL_CACHE = {"russell": R.TRADING_CACHE, "sp500": R.OOS_CACHE, "etf": S.ETF_CACHE}
#: The ETF sleeve's ADV is evidence like the stock panels': built once, written into the run dir
#: with its sha256 and its inputs' sha256 (review of #97: the report used to rebuild it from the
#: mutable cache files at read time, and the audit re-read the same mutable files).
ADV_PANELS = ("russell", "sp500", "etf")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_dir(run_id: str) -> str:
    return os.path.join(CAP_ROOT, run_id)


# ----------------------------------------------------------------------------------------------
def accredited_reference(panel: str) -> dict:
    """What F1 compares against, read from the accredited run and nothing else."""
    A.use_run(ACCREDITED_433)
    path = A.acc_path(panel, "base")
    man = PV.read_manifest(path)
    assert man, f"no manifest at {PV.manifest_path(path)}"
    book = pd.read_pickle(path)
    with open(A.engine_path(panel, "base"), encoding="utf-8") as fh:
        eng = json.load(fh)
    led = eng.get("ledger") or {}
    ref = dict(book_sha256=man["result"]["sha256"], calendar_sha256=PV.calendar_sha256(book.index),
               n_marks=int(len(book)), by_step=led.get("by_step") or {},
               cost_bp_effective_by_sleeve=led.get("cost_bp_effective_by_sleeve") or {},
               source=dict(run_id=ACCREDITED_433, book=PV._rel(path)))
    assert PV.book_sha256(book) == ref["book_sha256"], "the accredited book no longer matches its own seal"
    return ref


def build_adv(panel: str, out_dir: str) -> dict:
    """The lab's one definition on the panel's own caches; written into the run dir, sha recorded."""
    cache = PANEL_CACHE[panel]
    close = pd.read_pickle(os.path.join(cache, "close.pkl"))
    volume = pd.read_pickle(os.path.join(cache, "volume.pkl"))
    adv = C.adv_panel(close, volume)
    path = os.path.join(out_dir, f"adv_usd_{panel}.pkl")
    adv.to_pickle(path)
    live = []
    if os.path.exists(LIVE_SHEET):
        with open(LIVE_SHEET, encoding="utf-8") as fh:
            live = sorted({o["ticker"] for o in (json.load(fh).get("orders") or [])})
    covered_live = [t for t in live if t in adv.columns and adv[t].notna().any()]
    return dict(panel=panel, path=PV._rel(path), sha256=sha256_file(path), window=C.ADV_WINDOW,
                shape=list(adv.shape), first=str(adv.index.min().date()), last=str(adv.index.max().date()),
                nonnull_share=float(adv.notna().to_numpy().mean()),
                inputs=dict(close=dict(path=PV._rel(os.path.join(cache, "close.pkl")),
                                       sha256=sha256_file(os.path.join(cache, "close.pkl"))),
                            volume=dict(path=PV._rel(os.path.join(cache, "volume.pkl")),
                                        sha256=sha256_file(os.path.join(cache, "volume.pkl")))),
                live_sheet_tickers=len(live), live_sheet_covered=len(covered_live),
                live_sheet_uncovered=sorted(set(live) - set(covered_live)))


def drive_panel(panel: str, run_id: str, *, progress_every: int = 100) -> dict:
    """ONE drive with the sidecar on; F1 in full before anything but the F1 record is written."""
    out_dir = run_dir(run_id)
    os.makedirs(out_dir, exist_ok=True)
    ref = accredited_reference(panel)        # leaves accredit_433 pointed at the ACCREDITED run:
    # the S&P drive lands on the accredited russell/base grid (`russell_start_date`, `anchor_calendar`
    # read that book), which is exactly the grid F1 then requires. 434's outputs live under
    # capacity/runs/, never under accredited/runs/, so `A.use_run(run_id)` would point at nothing.
    s_bp, e_bp = BASE_BP
    start_date = A.russell_start_date() if panel == "sp500" else None
    t0 = time.time()
    print(f"[{panel}/base] capacity drive, sidecar on, stock {s_bp} bp / etf {e_bp} bp ...", flush=True)
    with C.FillTap() as tap:
        book, measured = CS.drive(panel, s_bp, e_bp, start_date=start_date, progress_every=progress_every)
    secs = time.time() - t0
    f1 = C.check_f1(ref, book, measured)
    f1.update(panel=panel, run_id=run_id, seconds=round(secs, 1), reference=ref["source"],
              utc=pd.Timestamp.utcnow().isoformat())
    with open(os.path.join(out_dir, f"{panel}_base.F1.json"), "w", encoding="utf-8") as fh:
        json.dump(f1, fh, indent=2, default=str)
    if not f1["passed"]:
        print(f"[{panel}/base] F1 FAILED - {f1['n_problems']} problem(s); nothing else written:", flush=True)
        for p in f1["problems"]:
            print("   ", p, flush=True)
        raise SystemExit(2)
    print(f"[{panel}/base] F1 PASSED: book {f1['book_sha256'][:12]} calendar {f1['calendar_sha256'][:12]} "
          f"{f1['n_marks']} marks, max |ledger diff| {f1['max_abs_ledger_diff']:.3e}, {secs:.0f}s", flush=True)

    book_path = os.path.join(out_dir, f"{panel}_base.pkl")
    pd.to_pickle(book, book_path)
    req = A.effective_request(panel, "base")
    for key in ("universe", "sectors"):
        if measured.get(key):
            req[key] = {**(req.get(key) or {}), **measured[key]}
    if measured.get("start_bar") is not None:
        req["config"]["start_bar"] = int(measured["start_bar"])
    man = PV.write_manifest(book, book_path, req, engine=measured)
    with open(os.path.join(out_dir, f"{panel}_base.engine.json"), "w", encoding="utf-8") as fh:
        json.dump(measured, fh, indent=2, default=str)
    fills = tap.frame()
    fills_path = os.path.join(out_dir, f"{panel}_base.fills.pkl")
    fills.to_pickle(fills_path)
    side = dict(path=PV._rel(fills_path), sha256=sha256_file(fills_path), n_fills=int(len(fills)),
                n_settles=int(fills["exec_date"].nunique()) if len(fills) else 0,
                filled_dollars_total=float(fills["dollars"].sum()) if len(fills) else 0.0,
                by_sleeve={s: float(g["dollars"].sum()) for s, g in fills.groupby("sleeve")} if len(fills) else {})
    # the sidecar is the ledger, disaggregated: its per-sleeve sums are the tap's
    led = (measured.get("ledger") or {}).get("by_sleeve") or {}
    for s, tot in side["by_sleeve"].items():
        theirs = float((led.get(s) or {}).get("filled_dollars", float("nan")))
        assert abs(tot - theirs) <= 1e-9 * max(1.0, abs(theirs)), (s, tot, theirs)
    print(f"[{panel}/base] sidecar {side['n_fills']} fills over {side['n_settles']} settles, "
          f"sha {side['sha256'][:12]}; book sealed {man['result']['sha256'][:12]}", flush=True)
    return dict(panel=panel, f1=f1, book=PV._rel(book_path), manifest=PV._rel(PV.manifest_path(book_path)),
                sidecar=side, seconds=round(secs, 1))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--panel", choices=["russell", "sp500", "both"], default="both")
    ap.add_argument("--run-id", default=None, help="default: accredit_433.mint_run_id() - a property of the repo")
    ap.add_argument("--progress-every", type=int, default=100)
    a = ap.parse_args(argv)
    run_id = a.run_id or A.mint_run_id()
    out_dir = run_dir(run_id)
    os.makedirs(out_dir, exist_ok=True)
    panels = ["russell", "sp500"] if a.panel == "both" else [a.panel]
    summary_path = os.path.join(out_dir, "capacity_drive.json")
    if os.path.exists(summary_path):
        # a second invocation (one panel at a time) ADDS to the run's record; it never restarts it
        with open(summary_path, encoding="utf-8") as fh:
            summary = json.load(fh)
        assert summary.get("run_id") == run_id, (summary.get("run_id"), run_id)
        summary.setdefault("code_by_invocation", []).append(PV.code_identity())
    else:
        summary = dict(task="TASK-434", run_id=run_id, run_dir=PV._rel(out_dir), label=C.LABEL,
                       prereg=".comms/prereg-task-434-2026-09-14.md",
                       accredited_reference=ACCREDITED_433, code=PV.code_identity(), adv={}, drives={})
    for adv_panel in ADV_PANELS:
        if adv_panel in summary["adv"] and os.path.exists(os.path.join(out_dir, f"adv_usd_{adv_panel}.pkl")):
            continue
        summary["adv"][adv_panel] = build_adv(adv_panel, out_dir)
        rec = summary["adv"][adv_panel]
        print(f"[{adv_panel}] adv_usd sha {rec['sha256'][:12]} shape {rec['shape']} nonnull {rec['nonnull_share']:.1%}; "
              f"live sheet covered {rec['live_sheet_covered']}/{rec['live_sheet_tickers']}", flush=True)
    for panel in panels:
        if panel in summary["drives"] and os.path.exists(os.path.join(out_dir, f"{panel}_base.F1.json")):
            print(f"[{panel}] already driven in this run (F1 record present) - left alone", flush=True)
            continue
    for panel in panels:
        if panel in summary["drives"] and os.path.exists(os.path.join(out_dir, f"{panel}_base.F1.json")):
            continue
        summary["drives"][panel] = drive_panel(panel, run_id, progress_every=a.progress_every)
        with open(summary_path, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, default=str)
    print(f"[done] {PV._rel(summary_path)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
