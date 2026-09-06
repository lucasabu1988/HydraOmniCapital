"""TASK-351 — broker vs state, read-only.

Lucas runs the book by hand. Compare a broker positions CSV (`ticker,units`)
and cash balances to `state/portfolio_v9.json`. Prints the diff; writes nothing;
exit 0 always.

    python reconcile.py positions.csv --cash-total 50000
    python reconcile.py positions.csv --cash-stocks 25000 --cash-etf 25000
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from core.ledger import moves_book

ROOT = Path(__file__).resolve().parent
DEFAULT_STATE = ROOT / "state" / "portfolio_v9.json"
QTY_TOL = 1e-6
CASH_TOL = 0.01


def _f(x, default=0.0) -> float:
    try:
        if x is None:
            return default
        v = float(x)
        return default if v != v else v
    except (TypeError, ValueError):
        return default


def units_from_state(state: dict) -> dict[str, float]:
    acc: dict[str, float] = {}
    for sleeve in (state.get("sleeves") or {}).values():
        for tr in sleeve.get("tranches") or []:
            for t, u in (tr.get("units") or {}).items():
                acc[str(t)] = acc.get(str(t), 0.0) + _f(u)
    return {t: u for t, u in acc.items() if abs(u) > QTY_TOL}


def last_px_from_state(state: dict) -> dict[str, float]:
    px: dict[str, float] = {}
    for sleeve in (state.get("sleeves") or {}).values():
        for tr in sleeve.get("tranches") or []:
            for t, p in (tr.get("last_px") or {}).items():
                if t not in px and p is not None:
                    px[str(t)] = _f(p)
    return px


def cash_from_state(state: dict) -> dict:
    by = {}
    total = 0.0
    for name, sleeve in (state.get("sleeves") or {}).items():
        c = sum(_f(tr.get("cash")) for tr in sleeve.get("tranches") or [])
        by[name] = c
        total += c
    return {"total": total, "by_sleeve": by}


def load_positions_csv(path: Path) -> dict[str, float]:
    df = pd.read_csv(path)
    cols = {c.lower().strip(): c for c in df.columns}
    tcol = cols.get("ticker") or cols.get("symbol") or list(df.columns)[0]
    ucol = cols.get("units") or cols.get("qty") or cols.get("quantity") or cols.get("shares")
    if ucol is None:
        if len(df.columns) < 2:
            raise ValueError("positions CSV needs ticker,units")
        ucol = df.columns[1]
    acc: dict[str, float] = {}
    for _, row in df.iterrows():
        t = str(row[tcol]).strip().upper()
        if not t or t.lower() == "nan":
            continue
        acc[t] = acc.get(t, 0.0) + _f(row[ucol])
    return {t: u for t, u in acc.items() if abs(u) > QTY_TOL}


def explanations(state: dict) -> dict:
    interest = sum(_f(x.get("dollars")) for x in (state.get("interest") or []))
    dividends = sum(_f(x.get("dollars")) for x in (state.get("dividends") or []))
    fees = sum(_f(f.get("cost")) for f in (state.get("ledger") or [])
               if moves_book(f.get("status")))
    pending = list(state.get("pending") or [])
    pending_buys = sum(_f(o.get("dollars")) for o in pending if o.get("side") == "buy")
    pending_sells = sum(_f(o.get("dollars")) for o in pending if o.get("side") == "sell")
    splits = list(state.get("splits") or [])
    return dict(
        interest_recorded=round(interest, 4),
        dividends_recorded=round(dividends, 4),
        splits_recorded=len(splits),
        splits_detail=[f"{s.get('date')} {s.get('ticker')} x{s.get('ratio')}" for s in splits[-5:]],
        fees_recorded=round(fees, 4),
        pending_buys=round(pending_buys, 4),
        pending_sells=round(pending_sells, 4),
        n_pending=len(pending),
        note=("Broker pays on pay-date; the book credits ex-date (TASK-349). "
              "That lag is a known residual, not an error."),
    )


def compare(state: dict, broker_units: dict[str, float],
            cash_total: float | None = None,
            cash_stocks: float | None = None,
            cash_etf: float | None = None) -> dict:
    book = units_from_state(state)
    px = last_px_from_state(state)
    state_cash = cash_from_state(state)
    expl = explanations(state)

    if cash_stocks is not None or cash_etf is not None:
        broker_cash = {
            "stocks": _f(cash_stocks),
            "etf": _f(cash_etf),
            "total": _f(cash_stocks) + _f(cash_etf),
        }
        cash_mode = "split"
    else:
        broker_cash = {"total": _f(cash_total), "stocks": None, "etf": None}
        cash_mode = "total"

    tickers = sorted(set(book) | set(broker_units))
    rows = []
    for t in tickers:
        s, b = book.get(t, 0.0), broker_units.get(t, 0.0)
        diff = b - s
        if t not in broker_units:
            kind = "missing"          # in state, not at broker
        elif t not in book:
            kind = "unknown"          # at broker, not in state
        elif abs(diff) > QTY_TOL:
            kind = "quantity-diff"
        else:
            kind = "match"
        last = px.get(t)
        rows.append(dict(
            ticker=t, state_units=round(s, 6), broker_units=round(b, 6),
            diff=round(diff, 6), kind=kind,
            last_px=last, state_value=None if last is None else round(s * last, 4),
            broker_value=None if last is None else round(b * last, 4),
        ))

    cash_delta = broker_cash["total"] - state_cash["total"]
    # Residual is the raw cash gap. Known items are listed so Lucas can
    # attribute it (pending not yet at the broker, 349 ex-date vs pay-date, etc.)
    # they are NOT subtracted automatically — we do not know which have settled.
    unexplained = cash_delta

    state_eq = state_cash["total"] + sum(r["state_value"] or 0.0 for r in rows)
    broker_eq = broker_cash["total"] + sum(
        r["broker_value"] if r["broker_value"] is not None else 0.0 for r in rows
    )
    return dict(
        positions=rows,
        n_missing=sum(1 for r in rows if r["kind"] == "missing"),
        n_unknown=sum(1 for r in rows if r["kind"] == "unknown"),
        n_diff=sum(1 for r in rows if r["kind"] == "quantity-diff"),
        n_match=sum(1 for r in rows if r["kind"] == "match"),
        cash_mode=cash_mode,
        state_cash=state_cash,
        broker_cash=broker_cash,
        cash_delta=round(cash_delta, 4),
        explanations=expl,
        residual=round(unexplained, 4),
        residual_pct=round(unexplained / state_eq * 100, 4) if state_eq else None,
        state_equity=round(state_eq, 4),
        broker_equity=round(broker_eq, 4),
        last_run_date=state.get("last_run_date"),
    )


def format_report(rep: dict) -> str:
    lines = ["[v9] reconcile (read-only, writes nothing)",
             f"last_run {rep.get('last_run_date') or '—'}"]
    lines += ["", "positions  (broker - state)",
              f"{'ticker':<8} {'kind':<14} {'state':>12} {'broker':>12} {'diff':>12} {'last_px':>10}"]
    for r in rep["positions"]:
        px = "" if r["last_px"] is None else f"{r['last_px']:.4f}"
        lines.append(f"{r['ticker']:<8} {r['kind']:<14} {r['state_units']:>12.4f} "
                     f"{r['broker_units']:>12.4f} {r['diff']:>12.4f} {px:>10}")
    if not rep["positions"]:
        lines.append("(no names on either side)")
    lines += [
        "",
        f"match {rep['n_match']}  missing(state-only) {rep['n_missing']}  "
        f"unknown(broker-only) {rep['n_unknown']}  quantity-diff {rep['n_diff']}",
        "",
        "cash",
        f"  state  {rep['state_cash']['total']:,.2f}  {rep['state_cash']['by_sleeve']}",
        f"  broker {rep['broker_cash']['total']:,.2f}  mode={rep['cash_mode']}",
        f"  delta  {rep['cash_delta']:,.2f}  (broker - state)",
        "",
        "known explanations (context; interest/dividends/fees already sit in state cash)",
        f"  interest recorded   {rep['explanations']['interest_recorded']:,.4f}",
        f"  dividends recorded  {rep['explanations']['dividends_recorded']:,.4f}",
        f"  fees recorded       {rep['explanations']['fees_recorded']:,.4f}",
        f"  splits recorded     {rep['explanations'].get('splits_recorded', 0)}"
        + (f"  ({', '.join(rep['explanations'].get('splits_detail') or [])})" if rep['explanations'].get('splits_recorded') else ""),
        f"  pending buys        {rep['explanations']['pending_buys']:,.4f}",
        f"  pending sells       {rep['explanations']['pending_sells']:,.4f}",
        f"  {rep['explanations']['note']}",
        "",
        f"unexplained residual  {rep['residual']:,.4f}"
        + (f"  ({rep['residual_pct']:.3f}% of state equity)" if rep["residual_pct"] is not None else ""),
        f"equity at state last_px  state {rep['state_equity']:,.2f}  broker {rep['broker_equity']:,.2f}",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Reconcile broker CSV vs v9 state (read-only)")
    p.add_argument("positions", help="CSV with ticker,units")
    p.add_argument("--state", default=str(DEFAULT_STATE))
    p.add_argument("--portfolio", default=None, help="Book from portfolios.toml (TASK-365)")
    p.add_argument("--cash-total", type=float, default=None)
    p.add_argument("--cash-stocks", type=float, default=None)
    p.add_argument("--cash-etf", type=float, default=None)
    args = p.parse_args(argv)
    # Audit phase 5.7: a reconciliation that could not be performed must exit
    # non-zero with an actionable message. Every path here used to `return 0`,
    # including the bare `except Exception`, so an unattended run read a broken
    # CSV as a clean reconciliation (repro R-507).
    if args.cash_total is None and args.cash_stocks is None and args.cash_etf is None:
        print("[v9] reconcile: pass --cash-total or --cash-stocks/--cash-etf "
              "(the broker cash balance is required to reconcile)")
        return 2
    st_path = Path(args.state)
    if args.portfolio:                                    # TASK-365: a named book brings its own state dir
        from core.portfolios import resolve
        st_path = resolve(args.portfolio, allow_disabled=True).state_dir / "portfolio_v9.json"
    if not st_path.exists():
        print(f"[v9] reconcile: state not found: {st_path} "
              f"(run portfolio_v9.py first, or pass --state)")
        return 2
    csv_path = Path(args.positions)
    if not csv_path.exists():
        print(f"[v9] reconcile: positions CSV not found: {csv_path}")
        return 2
    try:
        state = json.loads(st_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[v9] reconcile: cannot read the state at {st_path}: {e}")
        return 2
    try:
        broker = load_positions_csv(csv_path)
    except Exception as e:
        print(f"[v9] reconcile: cannot read {csv_path}: {e} "
              f"(the CSV needs a ticker column and a units/qty/shares column)")
        return 2
    if not broker:
        print(f"[v9] reconcile: {csv_path} parsed but held no positions — "
              f"check the column names and that the rows are not all zero")
        return 2
    try:
        rep = compare(state, broker, cash_total=args.cash_total,
                      cash_stocks=args.cash_stocks, cash_etf=args.cash_etf)
    except Exception as e:
        print(f"[v9] reconcile: comparison failed: {e}")
        return 2
    print(format_report(rep))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
