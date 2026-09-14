"""TASK-434 step 8 - the numbers, read ONLY after F1 passed for the panel.

    python experiments/capacity_report.py --run-id 20260914-<digest>

Reads `_lab_scratch/capacity/runs/<run_id>/`: the F1 records, the fill sidecars and the ADV panels
`capacity_drive.py` wrote, plus the live sheet. Refuses a panel whose `F1.json` does not say
`passed: true`. Writes `task434_capacity_<run_id>.json` beside the run dir and prints the table.

Every rule is `capacity.py`'s (pre-registered); this file only routes each footprint to the ADV
panel of its sleeve - stocks to the panel's own ADV, ETFs to the ETF cache's ADV - and assembles
the payload. `CAPACITY_NOT_CERTIFIED` is on the payload, on the ceiling and on every table row.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import capacity as C  # noqa: E402

CAP_ROOT = os.path.join(HERE, "_lab_scratch", "capacity", "runs")
LIVE_SHEET = os.path.join(ROOT, "state", "instructions_20260904.json")
PANELS = ("russell", "sp500")


def _rel(path: str) -> str:
    return os.path.relpath(path, ROOT).replace("\\", "/")


def load_f1(run_dir: str, panel: str) -> dict:
    path = os.path.join(run_dir, f"{panel}_base.F1.json")
    if not os.path.exists(path):
        raise SystemExit(f"{panel}: no F1 record at {_rel(path)} - capacity_drive.py has not run for it")
    with open(path, encoding="utf-8") as fh:
        f1 = json.load(fh)
    if not f1.get("passed"):
        raise SystemExit(f"{panel}: F1 did not pass ({f1.get('n_problems')} problems) - no number is read")
    return f1


def attach_adv_by_sleeve(fp: pd.DataFrame, panels: dict) -> pd.DataFrame:
    """Each footprint looks up the ADV panel of ITS sleeve; a sleeve without a panel is unknown.

    The lookup rule (`capacity.adv_prev_bar`: previous market bar, full window or NaN) is not
    restated here - only the routing is.
    """
    out = fp.copy()
    vals = []
    for sleeve, ticker, settle in zip(out["sleeve"], out["ticker"], out["settle"]):
        adv = panels.get(sleeve)
        vals.append(C.adv_prev_bar(adv, ticker, settle) if adv is not None else float("nan"))
    out["adv_usd"] = vals
    out["known"] = out["adv_usd"].notna() & (out["adv_usd"] > 0)
    return out


def panel_payload(run_dir: str, panel: str, adv_etf: pd.DataFrame | None) -> dict:
    f1 = load_f1(run_dir, panel)
    fills = pd.read_pickle(os.path.join(run_dir, f"{panel}_base.fills.pkl"))
    adv_stocks = pd.read_pickle(os.path.join(run_dir, f"adv_usd_{panel}.pkl"))
    fp = C.footprints(fills)
    fa = attach_adv_by_sleeve(fp, {"stocks": adv_stocks, "etf": adv_etf})
    gross = fa.copy()
    gross["net_dollars"] = gross["gross_dollars"]        # the sensitivity column: gross instead of net
    out = C.payload(fa, extra=dict(
        panel=panel, f1=dict(passed=f1["passed"], book_sha256=f1["book_sha256"], n_marks=f1["n_marks"]),
        footprints=dict(n=int(len(fa)), by_sleeve={s: int(n) for s, n in fa["sleeve"].value_counts().items()},
                        first=str(fa["settle"].min().date()) if len(fa) else None,
                        last=str(fa["settle"].max().date()) if len(fa) else None),
        gross_sensitivity=dict(ceiling=C.aum_ceiling(gross)["ceiling_usd"],
                               status=C.aum_ceiling(gross)["status"],
                               table=[r for r in C.scenario_table(gross) if r["sleeve"] == "total"]),
        etf_adv_available=adv_etf is not None,
    ))
    # the grid's top passing is a LOWER BOUND on the ceiling, not a measured ceiling
    ce = out["ceiling"]
    ce["grid_exhausted"] = bool(ce["measurable"] and ce["bracket"]["smallest_failing"] is None)
    ce["reading"] = (f">= {ce['ceiling_usd']:,.0f} USD (grid exhausted: every capital up to the top of the "
                     f"10k..100M grid passes; the ceiling is above it, not at it)" if ce["grid_exhausted"]
                     else (f"{ce['ceiling_usd']:,.0f} USD" if ce["ceiling_usd"] else ce["status"]))
    return out


def sheet_payload(adv_panels: dict, adv_etf: pd.DataFrame | None) -> dict:
    """The one real sheet, one point: participation per footprint at `planned - 1` and `exec - 1`."""
    if not os.path.exists(LIVE_SHEET):
        return dict(present=False)
    out = dict(present=True, path=_rel(LIVE_SHEET), label=C.LABEL, by_when={})
    for when in ("planned", "exec_date"):
        fp = C.sheet_footprints(LIVE_SHEET, when=when)
        rows = []
        for name, adv in adv_panels.items():
            fa = attach_adv_by_sleeve(fp, {"stocks": adv, "etf": adv_etf})
            part = C.participation_pct(fa, 1.0)           # already USD
            fa = fa.assign(participation_pct=part)
            rows.append(dict(adv_panel=name, coverage=C.coverage(fa), breaches=C.breaches(part),
                             p95=C.two_p95(part),
                             footprints=[dict(ticker=t, sleeve=s, usd=float(abs(d)),
                                              adv_usd=(None if pd.isna(a) else float(a)),
                                              participation_pct=(None if pd.isna(p) else float(p)))
                                         for t, s, d, a, p in zip(fa["ticker"], fa["sleeve"], fa["net_dollars"],
                                                                  fa["adv_usd"], fa["participation_pct"])]))
        out["by_when"][when] = rows
    return out


def print_table(payload: dict) -> None:
    for panel in PANELS:
        p = payload["panels"].get(panel)
        if not p:
            continue
        ce = p["ceiling"]
        print(f"\n== {panel}  {C.LABEL}  footprints {p['footprints']['n']} {p['footprints']['by_sleeve']} "
              f"{p['footprints']['first']}..{p['footprints']['last']}  etf_adv={'yes' if p['etf_adv_available'] else 'NO'}")
        cov = ce["coverage"]
        print(f"   coverage: {cov['footprints_known']}/{cov['footprints_total']} footprints "
              f"({cov['footprints_covered_share']:.1%}), notional {cov['notional_covered_share']:.1%}")
        print(f"   ceiling (P95 cons <= {ce['bound_pct']:g} %): {ce['status']}  {ce['reading']}  bracket {ce['bracket']}"
              + ("" if ce['ceiling_usd'] else f"  {ce['why_not_measurable']}"))
        print(f"   {'capital':>12s} {'sleeve':>7s} {'>1%':>7s} {'>3%':>7s} {'>5%':>7s} {'P95 desc':>9s} {'P95 cons':>9s} {'known':>6s} {'unk':>5s}")
        for r in p["table"]:
            print(f"   {r['capital']:>12,.0f} {r['sleeve']:>7s} {r['gt_1pct']:>7.1%} {r['gt_3pct']:>7.1%} {r['gt_5pct']:>7.1%} "
                  f"{r['p95_descriptive']:>9.3f} {r['p95_conservative']:>9.3f} {r['n_known']:>6d} {r['n_unknown']:>5d}")
        g = p["gross_sensitivity"]
        print(f"   gross sensitivity: ceiling {g['status']} {g['ceiling'] if g['ceiling'] is None else format(g['ceiling'], ',.0f')}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--etf-volume", default=None,
                    help="ETF volume pickle (default: experiments/_sweep_cache_etf/volume.pkl if present)")
    a = ap.parse_args(argv)
    run_dir = os.path.join(CAP_ROOT, a.run_id)
    if not os.path.isdir(run_dir):
        raise SystemExit(f"no run dir {_rel(run_dir)}")
    etf_cache = os.path.join(HERE, "_sweep_cache_etf")
    vol_p = a.etf_volume or os.path.join(etf_cache, "volume.pkl")
    adv_etf = None
    if os.path.exists(vol_p) and os.path.exists(os.path.join(etf_cache, "close.pkl")):
        adv_etf = C.adv_panel(pd.read_pickle(os.path.join(etf_cache, "close.pkl")), pd.read_pickle(vol_p))
    payload = dict(task="TASK-434", run_id=a.run_id, label=C.LABEL, prereg=".comms/prereg-task-434-2026-09-14.md",
                   etf_adv=dict(available=adv_etf is not None, volume_path=_rel(vol_p) if adv_etf is not None else None),
                   panels={}, live_sheet=None)
    adv_panels = {}
    for panel in PANELS:
        if os.path.exists(os.path.join(run_dir, f"{panel}_base.F1.json")):
            payload["panels"][panel] = panel_payload(run_dir, panel, adv_etf)
            adv_panels[panel] = pd.read_pickle(os.path.join(run_dir, f"adv_usd_{panel}.pkl"))
    payload["live_sheet"] = sheet_payload(adv_panels, adv_etf)
    out = os.path.join(HERE, "_lab_scratch", f"task434_capacity_{a.run_id}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    print_table(payload)
    print(f"\n[written] {_rel(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
