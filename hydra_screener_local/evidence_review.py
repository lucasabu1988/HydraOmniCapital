"""TASK-356 — quarterly / event-driven evidence review (spec 10.2).

Reads journal/*.json, writes `.comms/evidence-<period>.md`. Output only: tables
for the seven fixed questions, plus the three event triggers. No parameter
change, no recommendation beyond pointing at spec 10.3.

    python evidence_review.py --quarter 2026-Q4
    python evidence_review.py --since 2026-09-01
    python evidence_review.py --journal-dir path --out path.md
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import argparse
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
DEFAULT_JOURNAL = ROOT / "journal"
COMMS = REPO / ".comms"
RESIDUAL_TRIGGER = 0.5  # percent of book


def parse_quarter(q: str) -> tuple[str, str, str]:
    """'2026-Q4' -> (label, start, end exclusive)."""
    year, _, n = q.strip().upper().partition("-Q")
    n = int(n)
    starts = {1: f"{year}-01-01", 2: f"{year}-04-01", 3: f"{year}-07-01", 4: f"{year}-10-01"}
    ends = {1: f"{year}-04-01", 2: f"{year}-07-01", 3: f"{year}-10-01", 4: f"{int(year)+1}-01-01"}
    if n not in starts:
        raise ValueError(f"bad quarter {q}")
    return q.strip().upper(), starts[n], ends[n]


def load_journal(journal_dir: Path, since: str | None = None, until: str | None = None) -> list[dict]:
    recs = []
    for p in sorted(Path(journal_dir).glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        d = str(rec.get("date") or "")
        if since and d < since:
            continue
        if until and d >= until:
            continue
        recs.append(rec)
    recs.sort(key=lambda r: str(r.get("date") or ""))
    return recs


def _g(rec, *keys, default=None):
    cur = rec
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return default if cur is None else cur


def review(records: list[dict], period: str) -> dict:
    n = len(records)
    live_cums = [_g(r, "expectation", "live_cumulative") for r in records]
    live_cums = [x for x in live_cums if x is not None]
    last_cone = None
    last_pct = None
    for r in records:
        if _g(r, "expectation", "cone"):
            last_cone = r["expectation"]["cone"]
        if _g(r, "expectation", "step_return_percentile") is not None:
            last_pct = r["expectation"]["step_return_percentile"]
    if last_cone is None:
        from core.journal import cone_from_table, load_cone_table
        table = load_cone_table()
        h = max(1, n) if n else 1
        last_cone = cone_from_table(table, h) if table else None
    live_cum = live_cums[-1] if live_cums else None
    # drawdown of the live cumulative path (from capital=1)
    dd = None
    if live_cums:
        eq = [1.0 + x for x in live_cums]
        peak = eq[0]
        dd = 0.0
        for v in eq:
            peak = max(peak, v)
            dd = min(dd, v / peak - 1.0)

    slip_s, slip_e = [], []
    for r in records:
        rows = _g(r, "did", "slippage", "rows") or []
        for row in rows:
            (slip_s if row.get("sleeve") == "stocks" else slip_e).append(row.get("slippage_bp"))
    def _mean(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(xs) / len(xs), 2) if xs else None

    displaced = []
    for r in records:
        for d in _g(r, "seen", "sector_cap_displaced") or []:
            displaced.append(dict(date=r.get("date"), **d))
    sectors = {}
    for d in displaced:
        sectors[d.get("sector") or "?"] = sectors.get(d.get("sector") or "?", 0) + 1

    transfers = sum(_g(r, "did", "transfers") or 0 for r in records)
    interest = sum(_g(r, "did", "interest_dollars") or 0 for r in records)
    expos = [_g(r, "seen", "stock_exposure") for r in records]
    expos = [x for x in expos if x is not None]
    cash_drag = None if not expos else round(1.0 - sum(expos) / len(expos), 4)

    nf = sum(_g(r, "did", "not_filled") or 0 for r in records)
    hnp = sum(_g(r, "did", "hold_no_price") or 0 for r in records)
    wo = sum(_g(r, "did", "write_offs") or 0 for r in records)
    wo_d = sum(_g(r, "did", "write_off_dollars") or 0 for r in records)

    residuals = []
    for r in records:
        res = _g(r, "process", "reconcile_residual")
        if res is not None:
            tot = _g(r, "book", "total") or 0.0
            pct = (float(res) / tot * 100.0) if tot else None
            residuals.append(dict(date=r.get("date"), residual=float(res), pct=pct))

    degraded = [r.get("date") for r in records if _g(r, "seen", "degraded")]
    hard = [r.get("date") for r in records if _g(r, "process", "preflight", "hard")]
    coverage = [_g(r, "seen", "coverage") for r in records]
    coverage = [x for x in coverage if x is not None]

    triggers = []
    if last_cone and live_cum is not None:
        p5 = last_cone.get("p5")
        if p5 is not None and live_cum * 100 < float(p5):
            triggers.append(dict(
                kind="drawdown_beyond_p95",
                detail=f"live cum {live_cum*100:.2f}% below cone p5 {p5}%",
            ))
    if dd is not None and last_cone and last_cone.get("p5") is not None:
        # a live DD worse than the cone's 5th-percentile n-step return
        if dd * 100 < float(last_cone["p5"]):
            if not any(t["kind"] == "drawdown_beyond_p95" for t in triggers):
                triggers.append(dict(
                    kind="drawdown_beyond_p95",
                    detail=f"live maxDD {dd*100:.1f}% vs cone p5 {last_cone['p5']}%",
                ))
    if hard:
        triggers.append(dict(kind="preflight_hard_fail", detail=f"dates {hard}"))
    for row in residuals:
        if row["pct"] is not None and abs(row["pct"]) > RESIDUAL_TRIGGER:
            triggers.append(dict(
                kind="residual_gt_0.5pct",
                detail=f"{row['date']} residual {row['pct']:.3f}% of book",
            ))
            break

    return dict(
        period=period, n=n,
        dates=[r.get("date") for r in records],
        live_cum=live_cum, live_dd=dd, last_percentile=last_pct, cone=last_cone,
        slip_stocks=_mean(slip_s), slip_etf=_mean(slip_e),
        n_slip_stocks=len(slip_s), n_slip_etf=len(slip_e),
        n_displaced=len(displaced), sectors=sectors, displaced=displaced[:20],
        transfers=transfers, interest=interest, cash_drag=cash_drag,
        not_filled=nf, hold_no_price=hnp, write_offs=wo, write_off_dollars=wo_d,
        residuals=residuals,
        n_degraded=len(degraded), degraded=degraded,
        n_preflight_hard=len(hard), preflight_hard=hard,
        coverage_min=min(coverage) if coverage else None,
        coverage_mean=round(sum(coverage) / len(coverage), 4) if coverage else None,
        triggers=triggers,
    )


def render(rep: dict) -> str:
    cone = rep.get("cone") or {}
    lines = [
        f"# Evidence review — {rep['period']}",
        "",
        f"{rep['n']} journal record(s): {', '.join(d or '—' for d in (rep.get('dates') or [])[:12])}"
        + (" …" if len(rep.get("dates") or []) > 12 else ""),
        "",
        "Output only (spec 10.2). No parameter change. At most: evidence for a "
        "hypothesis (spec 10.3).",
        "",
        "## Triggers",
        "",
    ]
    if not rep["triggers"]:
        lines.append("None fired.")
    else:
        for t in rep["triggers"]:
            lines.append(f"- **{t['kind']}**: {t['detail']}")
    live = "—" if rep["live_cum"] is None else f"{100*rep['live_cum']:.2f}%"
    dd = "—" if rep["live_dd"] is None else f"{100*rep['live_dd']:.1f}%"
    lines += [
        "",
        "## 1. Live curve vs backtest cone",
        "",
        f"Live cumulative {live}  maxDD {dd}  last step percentile {rep['last_percentile']}",
        f"Cone n={cone.get('n_steps')}  5/50/95 = {cone.get('p5')}/{cone.get('p50')}/{cone.get('p95')} %",
        "",
        "## 2. Realised execution cost vs modelled 10/5 bp",
        "",
        "| sleeve | n fills | mean slippage bp | modelled |",
        "|---|---|---|---|",
        f"| stocks | {rep['n_slip_stocks']} | {rep['slip_stocks']} | 10 |",
        f"| etf | {rep['n_slip_etf']} | {rep['slip_etf']} | 5 |",
        "",
        "## 3. Sector cap binding",
        "",
        f"{rep['n_displaced']} name(s) displaced. By sector: {rep['sectors'] or '{}'}",
        "",
        "## 4. Reset transfers and vol-target cash drag vs interest",
        "",
        f"Transfers {rep['transfers']}  mean cash drag (1-expo) {rep['cash_drag']}  "
        f"interest accrued {rep['interest']}",
        "",
        "## 5. not_filled / hold_no_price / write-offs",
        "",
        f"not_filled {rep['not_filled']}  hold_no_price {rep['hold_no_price']}  "
        f"write-offs {rep['write_offs']} (${rep['write_off_dollars']})",
        "",
        "## 6. Reconciliation residual trend",
        "",
    ]
    if not rep["residuals"]:
        lines.append("No reconcile residual in the journal (351 not wired or not run).")
    else:
        lines.append("| date | residual $ | % of book |")
        lines.append("|---|---|---|")
        for row in rep["residuals"]:
            pct = "—" if row["pct"] is None else f"{row['pct']:.3f}"
            lines.append(f"| {row['date']} | {row['residual']:.2f} | {pct} |")
    lines += [
        "",
        "## 7. Data quality",
        "",
        f"DEGRADED runs {rep['n_degraded']} {rep['degraded'] or ''}",
        f"preflight HARD {rep['n_preflight_hard']} {rep['preflight_hard'] or ''}",
        f"coverage min {rep['coverage_min']} mean {rep['coverage_mean']}",
        "",
        "Evidence for a hypothesis (spec 10.3) only if a trigger fired or a table "
        "disagrees with the backtest in a way the journal can attribute.",
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Spec 10.2 evidence review from the journal")
    p.add_argument("--quarter", type=str, default=None, help="YYYY-QN")
    p.add_argument("--since", type=str, default=None)
    p.add_argument("--until", type=str, default=None)
    p.add_argument("--journal-dir", type=str, default=str(DEFAULT_JOURNAL))
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args(argv)
    since, until, label = args.since, args.until, None
    if args.quarter:
        label, since, until = parse_quarter(args.quarter)
    if not since and not args.quarter:
        since = "1970-01-01"
    label = label or (f"since-{since}" if since else str(date.today()))
    recs = load_journal(Path(args.journal_dir), since=since, until=until)
    rep = review(recs, label)
    text = render(rep)
    out = Path(args.out) if args.out else COMMS / f"evidence-{label}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"wrote {out}")
    for t in rep["triggers"]:
        print(f"TRIGGER {t['kind']}: {t['detail']}")
    if rep["triggers"]:
        try:
            from utils.notify import notify
            notify("ALERT", f"evidence {label}: {len(rep['triggers'])} trigger(s)",
                   "\n".join(f"{t['kind']}: {t['detail']}" for t in rep["triggers"]) + f"\nreport: {out}")
        except Exception as e:  # never fail the review on a notification
            print(f"[notify] skip: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
