"""HYDRA v9 local live dashboard.

Read-only over state/portfolio_v9.json. Never mutates the state, never places orders,
never sends webhooks. The only file written is append-only state/equity_curve.csv.

Cost-basis rule (average cost, per sleeve/tranche/ticker):
  filled buy  : qty += u;  cost_total += u * price;  avg = cost_total / qty
  filled sell : realised += (price - avg) * u;  qty -= u;  cost_total = avg * qty
  write-off   : realised += proceeds - cost_total;  qty = 0
  Fees (`cost` on fills) are tracked separately and are NOT in avg.
  not_filled / noted / transfers do not move units.

Usage:
    python dashboard_v9.py
    python dashboard_v9.py --port 8765 --refresh 300
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

DEFAULT_STATE_DIR = ROOT / "state"
DEFAULT_PORT = 8765
DEFAULT_REFRESH = 300
CURVE_FIELDS = ("timestamp", "total", "stocks", "etf", "cash", "spy_close")
HTML_PATH = ROOT / "dashboard" / "index.html"


# --------------------------------------------------------------------------- cost basis / snapshot (pure)


def _f(x, default=0.0) -> float:
    try:
        if x is None:
            return default
        v = float(x)
        if v != v:  # NaN
            return default
        return v
    except (TypeError, ValueError):
        return default


def _lots_from_ledger(state: dict) -> dict:
    """(sleeve, tranche, ticker) -> {qty, cost_total, realised, fees} after walking fills + write-offs."""
    lots = {}

    def slot(sleeve, tranche, ticker):
        key = (sleeve, int(tranche), str(ticker))
        if key not in lots:
            lots[key] = {"qty": 0.0, "cost_total": 0.0, "realised": 0.0, "fees": 0.0}
        return lots[key]

    for fill in state.get("ledger") or []:
        if fill.get("status") != "filled":
            continue
        side = fill.get("side")
        if side not in ("buy", "sell"):
            continue
        ticker = fill.get("ticker")
        if not ticker or ticker in ("CASH", "TBILL"):
            continue
        lot = slot(fill.get("sleeve"), fill.get("tranche", 0), ticker)
        u = _f(fill.get("units"))
        px = _f(fill.get("price"))
        lot["fees"] += _f(fill.get("cost"))
        if u <= 0 or px <= 0:
            continue
        if side == "buy":
            lot["qty"] += u
            lot["cost_total"] += u * px
        else:
            sold = min(u, lot["qty"])
            avg = lot["cost_total"] / lot["qty"] if lot["qty"] else 0.0
            lot["realised"] += (px - avg) * sold
            lot["qty"] -= sold
            lot["cost_total"] = avg * lot["qty"]

    for wo in state.get("write_offs") or []:
        ticker = wo.get("ticker")
        if not ticker:
            continue
        lot = slot(wo.get("sleeve"), wo.get("tranche", 0), ticker)
        lot["realised"] += _f(wo.get("proceeds")) - lot["cost_total"]
        lot["qty"] = 0.0
        lot["cost_total"] = 0.0
    return lots


def summarize_interest(state: dict | None) -> dict:
    """Read-only rollup of `state["interest"]`. Missing key -> zeros (old states)."""
    rows = list((state or {}).get("interest") or [])
    cumulative = 0.0
    by_sleeve: dict[str, float] = {}
    for r in rows:
        d = _f(r.get("dollars"))
        cumulative += d
        sl = str(r.get("sleeve") or "?")
        by_sleeve[sl] = by_sleeve.get(sl, 0.0) + d
    last_date = rows[-1].get("date") if rows else None
    since = [r for r in rows if last_date is not None and r.get("date") == last_date]
    since_from = since[0].get("since") if since else None          # the previous run the accrual covers
    since_total = sum(_f(r.get("dollars")) for r in since)
    since_by: dict[str, float] = {}
    for r in since:
        sl = str(r.get("sleeve") or "?")
        since_by[sl] = since_by.get(sl, 0.0) + _f(r.get("dollars"))
    return {
        "records": rows,
        "cumulative": cumulative,
        "by_sleeve": by_sleeve,
        "since_last_run": since_total,
        "since_from": since_from,
        "since_last_by_sleeve": since_by,
        "last_date": last_date,
    }


def _quote_price(quotes: dict, ticker: str, fallback: float | None) -> tuple[float | None, bool]:
    """Return (price, stale). quotes[t] may be a float or {price, stale}."""
    q = (quotes or {}).get(ticker)
    if isinstance(q, dict):
        p = q.get("price")
        if p is not None:
            return _f(p), bool(q.get("stale", False))
    elif q is not None:
        return _f(q), False
    if fallback is not None:
        return _f(fallback), True
    return None, True


def exec_date_for(planned, state_dir: Path | None = None):
    """Execution day of an order planned at the close of `planned`: the sheet's `exec_date`
    (state/instructions_<planned>.json) when it exists, else the next business day."""
    if not planned:
        return None
    if state_dir is not None:
        sheet = Path(state_dir) / f"instructions_{str(planned).replace('-', '')}.json"
        if sheet.exists():
            try:
                with sheet.open("r", encoding="utf-8") as f:
                    ex = json.load(f).get("exec_date")
                if ex:
                    return str(ex)
            except (OSError, ValueError):
                pass
    import pandas as pd
    return str((pd.Timestamp(planned) + pd.offsets.BDay(1)).date())


def ny_day(ts) -> str:
    """Calendar day in America/New_York of an ISO timestamp (the marks are stored in UTC, and a
    US evening sits past UTC midnight: the day P/L must not reset at 20:00 ET)."""
    import pandas as pd
    try:
        t = pd.Timestamp(str(ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        return str(t.tz_convert("America/New_York").date())
    except (TypeError, ValueError):
        return str(ts)[:10]


def build_snapshot(state: dict, quotes: dict, spy=None, state_dir: Path | None = None) -> dict:
    """Pure. `quotes` maps ticker -> float or {price, stale}. `spy` is the same for SPY."""
    if not state:
        return {"ok": False, "error": "no state"}
    lots = _lots_from_ledger(state)
    capital = _f(state.get("capital_reference"))
    if isinstance(spy, dict):
        spy_q, spy_stale = spy.get("price"), bool(spy.get("stale", False))
        if spy_q is not None:
            spy_q = _f(spy_q)
    elif spy is not None:
        spy_q, spy_stale = _f(spy), False
    else:
        spy_q, spy_stale = _quote_price(quotes, "SPY", None)

    positions = []
    sleeves_out = {}
    fees_total = 0.0
    realised_total = 0.0
    invested = 0.0
    cash_total = 0.0
    distinct = set()

    for sleeve, payload in (state.get("sleeves") or {}).items():
        s_value = 0.0
        s_cash = 0.0
        s_invested = 0.0
        s_names = set()
        tranches = []
        for tr in payload.get("tranches") or []:
            k = int(tr.get("k", 0))
            cash = _f(tr.get("cash"))
            s_cash += cash
            cash_total += cash
            last_px = tr.get("last_px") or {}
            t_pos = []
            t_invested = 0.0
            for ticker, units in (tr.get("units") or {}).items():
                u = _f(units)
                if u <= 1e-12:
                    continue
                px, stale = _quote_price(quotes, ticker, last_px.get(ticker))
                if px is None:
                    px, stale = _f(last_px.get(ticker)), True
                mv = u * px
                lot = lots.get((sleeve, k, ticker), {"qty": u, "cost_total": 0.0, "realised": 0.0, "fees": 0.0})
                avg = lot["cost_total"] / lot["qty"] if lot["qty"] else (lot["cost_total"] / u if u else 0.0)
                if lot["qty"] <= 0 and u > 0:
                    avg = 0.0
                unreal = (px - avg) * u if avg else 0.0
                pos = {
                    "sleeve": sleeve, "tranche": k, "ticker": ticker, "units": u,
                    "avg_cost": avg, "last": px, "stale": stale, "market_value": mv,
                    "unrealised": unreal, "realised": lot["realised"], "fees": lot["fees"],
                }
                t_pos.append(pos)
                positions.append(pos)
                t_invested += mv
                s_invested += mv
                invested += mv
                s_names.add(ticker)
                distinct.add(ticker)
            s_value += cash + t_invested
            tranches.append({"k": k, "opened": tr.get("opened"), "cash": cash,
                             "invested": t_invested, "value": cash + t_invested, "positions": t_pos})
        sleeves_out[sleeve] = {
            "value": s_value, "cash": s_cash, "invested": s_invested,
            "exposure": s_invested / s_value if s_value else 0.0,
            "distinct": len(s_names), "names": sorted(s_names),
            "share": 0.0, "target_share": 0.5, "tranches": tranches,
        }

    realised_total = sum(lot["realised"] for lot in lots.values())
    fees_total = sum(lot["fees"] for lot in lots.values())

    total = cash_total + invested
    for sleeve, sl in sleeves_out.items():
        sl["share"] = sl["value"] / total if total else 0.0
        sl["share_gap"] = sl["share"] - sl["target_share"]

    pending = []
    for o in state.get("pending") or []:
        pending.append({
            "planned": o.get("planned"),
            "exec_date": o.get("exec_date") or exec_date_for(o.get("planned"), state_dir),
            "sleeve": o.get("sleeve"), "tranche": o.get("tranche"),
            "side": o.get("side"), "ticker": o.get("ticker"),
            "dollars": _f(o.get("dollars")), "est_units": o.get("est_units"),
            "est_price": o.get("est_price"), "status": "pending",
            "note": o.get("note"),
        })

    trade_log = []
    for fill in state.get("ledger") or []:
        trade_log.append({
            "date": fill.get("exec_date") or fill.get("planned"),
            "sleeve": fill.get("sleeve"), "tranche": fill.get("tranche"),
            "side": fill.get("side"), "ticker": fill.get("ticker"),
            "units": fill.get("units"), "price": fill.get("price"),
            "dollars": fill.get("dollars"), "cost": fill.get("cost"),
            "status": fill.get("status") or "filled",
        })
    ix = summarize_interest(state)
    for r in ix["records"]:
        trade_log.append({
            "date": r.get("date"),
            "sleeve": r.get("sleeve"),
            "tranche": None,
            "side": "interest",
            "ticker": "TBILL",
            "units": r.get("bars"),
            "price": r.get("rate"),
            "dollars": r.get("dollars"),
            "cost": None,
            "status": "noted",
            "bars": r.get("bars"),
            "rate": r.get("rate"),
            "since": r.get("since"),
        })

    since_usd = total - capital if capital else 0.0
    since_pct = since_usd / capital if capital else 0.0
    unreal_open = sum(p["unrealised"] for p in positions)

    return {
        "ok": True,
        "banner": "fills presumidos — simulación de ejecución al cierre; no es un extracto del bróker",
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "anchor_date": state.get("anchor_date"),
        "last_run_date": state.get("last_run_date"),
        "last_renewal_date": state.get("last_renewal_date"),
        "week_index": state.get("week_index"),
        "capital_reference": capital,
        "total": total,
        "cash": cash_total,
        "invested": invested,
        "exposure": invested / total if total else 0.0,
        "distinct": len(distinct),
        "unrealised": unreal_open,
        "realised": realised_total,
        "fees": fees_total,
        "interest": ix["cumulative"],
        "interest_by_sleeve": ix["by_sleeve"],
        "interest_since_last_run": ix["since_last_run"],
        "pnl_total": unreal_open + realised_total - fees_total + ix["cumulative"],
        "since_inception_usd": since_usd,
        "since_inception_pct": since_pct,
        "spy": {"price": spy_q, "stale": spy_stale},
        "sleeves": sleeves_out,
        "positions": positions,
        "pending": pending,
        "transfers": list(state.get("transfers") or []),
        "write_offs": list(state.get("write_offs") or []),
        "trade_log": trade_log,
        "day_pnl_usd": None,  # filled by caller once the curve is known
        "day_pnl_pct": None,
        "vs_spy_pct": None,
        "curve": [],
    }


# --------------------------------------------------------------------------- quotes / curve / I/O


def load_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def fetch_quotes(tickers: list[str], fallback: dict) -> dict:
    """Intraday last via yfinance. Missing names fall back to `fallback` and are marked stale."""
    out = {}
    for t in tickers:
        if t in (fallback or {}) and fallback[t] is not None:
            out[t] = {"price": _f(fallback[t]), "stale": True}
        else:
            out[t] = {"price": None, "stale": True}
    wanted = [t for t in tickers if t]
    if not wanted:
        return out
    try:
        import yfinance as yf
        data = yf.download(wanted, period="1d", progress=False, threads=True, auto_adjust=True)
        if data is None or data.empty:
            return out
        close = data["Close"] if "Close" in getattr(data, "columns", []) or (
            hasattr(data.columns, "get_level_values") and "Close" in data.columns.get_level_values(0)
        ) else data
        if hasattr(close, "columns") and getattr(close.columns, "nlevels", 1) > 1:
            close = data["Close"]
        if isinstance(close, type(data)) and hasattr(close, "iloc"):
            if close.ndim == 1:
                t = wanted[0]
                val = close.dropna()
                if len(val):
                    out[t] = {"price": float(val.iloc[-1]), "stale": False}
            else:
                for t in wanted:
                    if t not in close.columns:
                        continue
                    val = close[t].dropna()
                    if len(val):
                        out[t] = {"price": float(val.iloc[-1]), "stale": False}
    except Exception:
        pass
    for t, fb in (fallback or {}).items():
        if t not in out or out[t].get("price") is None:
            out[t] = {"price": _f(fb), "stale": True}
    return out


def held_fallback_px(state: dict) -> dict:
    fb = {}
    for payload in (state.get("sleeves") or {}).values():
        for tr in payload.get("tranches") or []:
            for t, p in (tr.get("last_px") or {}).items():
                fb[t] = _f(p)
    return fb


def read_curve(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def append_curve(path: Path, row: dict) -> bool:
    """Append one mark. Idempotent: same timestamp already present -> no write. Returns True if written."""
    ts = str(row["timestamp"])
    existing = read_curve(path)
    if any(r.get("timestamp") == ts for r in existing):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(CURVE_FIELDS))
        if new_file:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in CURVE_FIELDS})
    return True


def annotate_performance(snap: dict, curve: list[dict]) -> dict:
    total = _f(snap.get("total"))
    if curve:
        prev = curve[-1]
        # day P&L vs the last mark on a previous New York date, else vs previous mark
        today = ny_day(snap.get("as_of") or "")
        day_base = None
        for r in reversed(curve):
            if ny_day(r.get("timestamp", "")) != today:
                day_base = _f(r.get("total"))
                break
        if day_base is None and len(curve) >= 1:
            # intra-day: vs first mark today if any, else last
            first_today = next((r for r in curve if ny_day(r.get("timestamp", "")) == today), None)
            day_base = _f((first_today or prev).get("total"))
        snap["day_pnl_usd"] = total - day_base
        snap["day_pnl_pct"] = (total - day_base) / day_base if day_base else 0.0
        first_spy = _f(curve[0].get("spy_close"), default=None) if curve[0].get("spy_close") not in ("", None) else None
        spy_now = (snap.get("spy") or {}).get("price")
        if first_spy and spy_now:
            snap["vs_spy_pct"] = spy_now / first_spy - 1.0
            snap["since_inception_vs_spy"] = snap["since_inception_pct"] - snap["vs_spy_pct"]
    snap["curve"] = [
        {"timestamp": r.get("timestamp"), "total": _f(r.get("total")),
         "stocks": _f(r.get("stocks")), "etf": _f(r.get("etf")),
         "cash": _f(r.get("cash")), "spy_close": _f(r.get("spy_close"))}
        for r in curve
    ]
    return snap


_QUOTE_CACHE = {"t": 0.0, "quotes": {}}
_QUOTE_TTL = DEFAULT_REFRESH


def cached_quotes(tickers: list[str], fallback: dict) -> tuple[dict, bool]:
    """Return (quotes, refreshed). `refreshed` is True only when yfinance (or fallback) was fetched."""
    now = time.time()
    if _QUOTE_CACHE["quotes"] and (now - _QUOTE_CACHE["t"]) < _QUOTE_TTL:
        return _QUOTE_CACHE["quotes"], False
    q = fetch_quotes(tickers, fallback)
    _QUOTE_CACHE["t"] = now
    _QUOTE_CACHE["quotes"] = q
    return q, True


def live_snapshot(state_dir: Path) -> dict:
    state_path = Path(state_dir) / "portfolio_v9.json"
    state = load_state(state_path)
    if not state:
        return {"ok": False, "error": f"missing {state_path}", "banner": "sin estado v9 — corre portfolio_v9.py primero"}
    fallback = held_fallback_px(state)
    tickers = sorted(set(fallback) | {"SPY"})
    quotes, refreshed = cached_quotes(tickers, fallback)
    spy = quotes.get("SPY")
    snap = build_snapshot(state, quotes, spy, state_dir=Path(state_dir))
    curve_path = Path(state_dir) / "equity_curve.csv"
    curve = read_curve(curve_path)
    should_append = refreshed or not curve
    if not should_append and curve:
        last_ts = str(curve[-1].get("timestamp") or "")
        try:
            last = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - last).total_seconds()
            should_append = age >= _QUOTE_TTL
        except (TypeError, ValueError):
            should_append = True
    if should_append:
        mark = {
            "timestamp": snap["as_of"],
            "total": f"{snap['total']:.6f}",
            "stocks": f"{(snap['sleeves'].get('stocks') or {}).get('value', 0):.6f}",
            "etf": f"{(snap['sleeves'].get('etf') or {}).get('value', 0):.6f}",
            "cash": f"{snap['cash']:.6f}",
            "spy_close": "" if not (spy and spy.get("price") is not None) else f"{spy['price']:.6f}",
        }
        append_curve(curve_path, mark)
        curve = read_curve(curve_path)
    return annotate_performance(snap, curve)


# --------------------------------------------------------------------------- HTTP


def _handler(state_dir: Path, html: bytes):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            sys.stderr.write("[dashboard] " + fmt % args + "\n")

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._send(200, html, "text/html; charset=utf-8")
                return
            if path == "/api/snapshot":
                try:
                    snap = live_snapshot(state_dir)
                except Exception as e:
                    snap = {"ok": False, "error": str(e)}
                body = json.dumps(snap, default=str).encode("utf-8")
                self._send(200, body, "application/json; charset=utf-8")
                return
            self._send(404, b"not found", "text/plain")

    return Handler


def serve(state_dir: Path, host: str = "127.0.0.1", port: int = DEFAULT_PORT, refresh: int = DEFAULT_REFRESH):
    global _QUOTE_TTL
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("dashboard binds localhost only")
    _QUOTE_TTL = max(5, int(refresh))
    html_file = HTML_PATH
    if not html_file.exists():
        raise SystemExit(f"missing {html_file}")
    poll_ms = min(max(int(refresh), 5), 300) * 1000
    html = html_file.read_text(encoding="utf-8").replace("/*REFRESH_MS*/ 5000", str(poll_ms)).encode("utf-8")
    httpd = ThreadingHTTPServer((host, port), _handler(state_dir, html))
    url = f"http://{host}:{port}/"
    print(f"HYDRA v9 dashboard  {url}")
    print(f"  state dir : {state_dir}")
    print(f"  refresh   : {refresh}s (page polls /api/snapshot)")
    print("  bind      : 127.0.0.1 only — no cloud, no orders, state is read-only")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
        httpd.shutdown()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="HYDRA v9 local live dashboard (read-only)")
    p.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--refresh", type=int, default=DEFAULT_REFRESH)
    args = p.parse_args(argv)
    serve(Path(args.state_dir), host=args.host, port=args.port, refresh=args.refresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
