"""TASK-438 step 4 - the numbers: the impact overlay on the TASK-434 sidecars, read against 433's rungs.

    python experiments/impact_report.py --run-id 20260914-cc34d9465892

Refuses to run unless the sidecars' bytes are the ones `capacity_drive.json` recorded (G1) and the
F1 records say `passed: true`. Reads the close panels the 433 books recorded (checked by sha against
the 433 manifests' data blocks), builds sigma, joins each fill to its footprint's ADV and its
sleeve's sigma at t-1, and publishes `task438_impact_<run_id>.json` with `IMPACT_MODELLED_NOT_MEASURED`
on top. The 433 table is read for the drag cross-check only; the measured deltas stay authoritative.
"""
from __future__ import annotations

import argparse
import hashlib
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
import impact as I  # noqa: E402
import provenance as PV  # noqa: E402
import run_russell_prereg as R  # noqa: E402
import sleeve_lab as S  # noqa: E402

CAP_ROOT = os.path.join(HERE, "_lab_scratch", "capacity", "runs")
ACCREDITED_433 = "20260914-cae2c54599aa"
ACC_433 = os.path.join(HERE, "_lab_scratch", "accredited", "runs", ACCREDITED_433)
TABLE_433 = os.path.join(HERE, "_lab_scratch", f"task433_accredited_{ACCREDITED_433}.json")
CLOSE_BY_PANEL = {"russell": os.path.join(R.TRADING_CACHE, "close.pkl"),
                  "sp500": os.path.join(R.OOS_CACHE, "close.pkl")}
ETF_CLOSE = os.path.join(S.ETF_CACHE, "close.pkl")
SETTLES_PER_YEAR = 814 / 16.163          # the accredited window: 814 settles, 2010-06-28 .. 2026-08-26
PANELS = ("russell", "sp500")


def _rel(path: str) -> str:
    return os.path.relpath(path, ROOT).replace("\\", "/")


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def gate(run_dir: str, summary: dict, panel: str) -> dict:
    """G1: sidecar bytes are the recorded ones and F1 passed, or no number is read."""
    with open(os.path.join(run_dir, f"{panel}_base.F1.json"), encoding="utf-8") as fh:
        f1 = json.load(fh)
    if not f1.get("passed"):
        raise SystemExit(f"{panel}: F1 did not pass in run {summary['run_id']} - no number is read")
    side = summary["drives"][panel]["sidecar"]
    path = os.path.join(ROOT, side["path"])
    got = _sha(path)
    if got != side["sha256"]:
        raise SystemExit(f"{panel}: sidecar on disk {got[:12]} != recorded {side['sha256'][:12]} (G1)")
    return dict(sidecar_sha256=got, f1_book_sha256=f1["book_sha256"], n_marks=f1["n_marks"])


def close_panel(panel: str) -> tuple[pd.DataFrame, dict]:
    """The close panel the 433 books recorded as `data:price_close`, checked by sha."""
    path = CLOSE_BY_PANEL[panel]
    got = _sha(path)
    man = PV.read_manifest(os.path.join(ACC_433, f"{panel}_base.pkl"))
    rec = ((man or {}).get("data") or {}).get("price_close") or {}
    if rec.get("sha256") and rec["sha256"] != got:
        raise SystemExit(f"{panel}: close.pkl {got[:12]} is not the 433-recorded data block {rec['sha256'][:12]}")
    return pd.read_pickle(path), dict(path=_rel(path), sha256=got, matches_433_data_block=bool(rec.get("sha256") == got))


def turnover_per_year(run_dir: str, panel: str) -> dict:
    with open(os.path.join(run_dir, f"{panel}_base.engine.json"), encoding="utf-8") as fh:
        led = json.load(fh)["ledger"]
    per_settle = led["turnover_filled_pct_by_sleeve"]           # percent of NAV per settle, one-way
    return {s: float(v) / 100.0 * SETTLES_PER_YEAR for s, v in per_settle.items()}


def rung_deltas_433() -> dict:
    """433's measured delta ann_net per rung and panel - the authoritative yardstick."""
    if not os.path.exists(TABLE_433):
        return {}
    with open(TABLE_433, encoding="utf-8") as fh:
        rows = json.load(fh)["rows_accredited"]
    ann = {(r["panel"], r["scenario"]): float(r["ann_net"]) for r in rows}
    out = {}
    for panel in PANELS:
        base = ann.get((panel, "base"))
        out[panel] = {rung: (base - ann[(panel, rung)]) for rung in I.RUNGS_BP if (panel, rung) in ann and base is not None}
    return out


def build(run_id: str) -> dict:
    run_dir = os.path.join(CAP_ROOT, run_id)
    with open(os.path.join(run_dir, "capacity_drive.json"), encoding="utf-8") as fh:
        summary = json.load(fh)
    etf_rec = summary["adv"]["etf"]
    adv_etf = pd.read_pickle(os.path.join(ROOT, etf_rec["path"]))
    assert _sha(os.path.join(ROOT, etf_rec["path"])) == etf_rec["sha256"], "adv_usd_etf.pkl moved"
    etf_close = pd.read_pickle(ETF_CLOSE)
    etf_close_sha = _sha(ETF_CLOSE)
    assert etf_close_sha == etf_rec["inputs"]["close"]["sha256"], "ETF close.pkl is not the 434-recorded input"
    sigma_etf = I.sigma_panel(etf_close)
    sigma_etf_21 = I.sigma_panel(etf_close, I.SIGMA_WINDOW_SENSITIVITY)
    deltas = rung_deltas_433()

    out = dict(task="TASK-438", label=I.LABEL, prereg=".comms/prereg-task-438-impact-2026-09-14.md",
               run_434=run_id, run_433=ACCREDITED_433, settles_per_year=SETTLES_PER_YEAR,
               inputs=dict(etf_close=dict(path=_rel(ETF_CLOSE), sha256=etf_close_sha),
                           adv_etf=dict(path=etf_rec["path"], sha256=etf_rec["sha256"])),
               panels={})
    for panel in PANELS:
        g = gate(run_dir, summary, panel)
        fills = pd.read_pickle(os.path.join(run_dir, f"{panel}_base.fills.pkl"))
        adv_rec = summary["adv"][panel]
        adv = pd.read_pickle(os.path.join(ROOT, adv_rec["path"]))
        assert _sha(os.path.join(ROOT, adv_rec["path"])) == adv_rec["sha256"], f"{panel}: adv panel moved"
        close, close_rec = close_panel(panel)
        sigma = I.sigma_panel(close)
        f = I.fills_with_footprints(fills, {"stocks": adv, "etf": adv_etf}, {"stocks": sigma, "etf": sigma_etf})
        f21 = I.fills_with_footprints(fills, {"stocks": adv, "etf": adv_etf},
                                      {"stocks": I.sigma_panel(close, I.SIGMA_WINDOW_SENSITIVITY), "etf": sigma_etf_21})
        to = turnover_per_year(run_dir, panel)
        pay = I.payload(f, extra=dict(
            panel=panel, gate=g, close_panel=close_rec, adv_panel=dict(path=adv_rec["path"], sha256=adv_rec["sha256"]),
            turnover_one_way_per_year=to,
            sigma_window_sensitivity=dict(window=I.SIGMA_WINDOW_SENSITIVITY,
                                          fixed=[dict(capital=float(c), **I.effective_bp(f21, c, I.K_HEADLINE))
                                                 for c in I.FIXED_CAPITALS]),
            drag_cross_check=[
                dict(rung=rung, sleeve="stocks",
                     capital_reaching_rung=x["stocks"]["capital_reaching_rung"],
                     impact_target_bp=x["stocks"]["target_impact_bp"],
                     drag_pp_per_year_at_target=I.drag_pp_per_year(x["stocks"]["target_impact_bp"], to.get("stocks", float("nan"))),
                     measured_433_delta_ann_net_pp=deltas.get(panel, {}).get(rung))
                for rung, x in I.crossings(I.curve(f, C.aum_grid(), I.K_HEADLINE)).items()],
        ))
        out["panels"][panel] = pay
    return out


def print_report(p: dict) -> None:
    for panel, pay in p["panels"].items():
        cov = pay["coverage"]
        print(f"\n== {panel}  {I.LABEL}  fills {cov['n_fills']} known {cov['n_known']} "
              f"({1 - cov['unknown_share_by_notional']:.1%} of notional)  close.pkl==433 data block: {pay['close_panel']['matches_433_data_block']}")
        print(f"   {'capital':>14s} {'k':>4s} {'total bp':>9s} {'stocks bp':>10s} {'etf bp':>8s} {'measurable':>10s}")
        for r in pay["fixed"]:
            print(f"   {r['capital']:>14,.0f} {r['k']:>4.1f} {r['total']['eff_bp_side']:>9.3f} {r['stocks']['eff_bp_side']:>10.3f} "
                  f"{r['etf']['eff_bp_side']:>8.3f} {str(r['total']['measurable']):>10s}")
        for k, x in pay["crossings"].items():
            row = "  ".join(f"{rung}: {('%.3g' % v['stocks']['capital_reaching_rung']) if v['stocks']['capital_reaching_rung'] else ('>=100M' if v['stocks']['grid_exhausted'] else 'n/a')}"
                            for rung, v in x.items())
            print(f"   k={k}: stocks reach  {row}")
        print("   drag cross-check (stocks, k=1):")
        for d in pay["drag_cross_check"]:
            m = d["measured_433_delta_ann_net_pp"]
            print(f"     {d['rung']:16s} +{d['impact_target_bp']:.0f} bp -> arithmetic drag {d['drag_pp_per_year_at_target']:.2f} pp/yr; "
                  f"433 measured delta ann_net {m if m is None else round(m, 3)} pp; capital reaching it "
                  f"{('%.3g' % d['capital_reaching_rung']) if d['capital_reaching_rung'] else '>= grid top'}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-id", required=True)
    a = ap.parse_args(argv)
    p = build(a.run_id)
    out = os.path.join(HERE, "_lab_scratch", f"task438_impact_{a.run_id}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(p, fh, indent=2, default=str)
    print_report(p)
    print(f"\n[written] {_rel(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
