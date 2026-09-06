"""TASK-367 — where does the book's return come from? Pure over the v9 state (+ optional marks).

Cumulative since the anchor, per sleeve and for the book:

    value_now - initial_cash = trading + fees + interest + dividends + transfers + residual

  trading    = market value now + sell proceeds + write-off proceeds - buy dollars   (per sleeve;
               the stock sleeve's trading is "selection", the ETF sleeve's is "etf")
  fees       = -(sum of fill costs)
  interest   = T-bill accrued on idle cash (state["interest"])
  dividends  = cash dividends credited (state["dividends"])
  transfers  = signed reset legs (state["transfers"]); they net to zero over the book — asserted
  residual   = what the identity does not explain. Zero on a replay-clean state; non-zero means
               fills confirmed with different units/prices than the book assumed, or a state edit.

Weekly deltas are differences of two cumulative blocks (`diff`), which the journal stores
each run. No I/O here; marks default to each tranche's `last_px`.
"""
from __future__ import annotations

from core.costbasis import FILLED_STATUSES, _f, lots_from_ledger

SLEEVE_LABEL = {"stocks": "selection", "etf": "etf"}
TOL = 1e-9


def _mark(marks: dict | None, sleeve: str, ticker: str, fallback) -> float | None:
    if marks:
        m = marks.get(sleeve) if isinstance(marks.get(sleeve), dict) else marks
        v = m.get(ticker) if isinstance(m, dict) else None
        if v is not None:
            return _f(v)
    return None if fallback is None else _f(fallback)


def positions(state: dict, marks: dict | None = None) -> list[dict]:
    """Per sleeve/tranche/ticker: units, avg cost, mark, market value, unrealised, realised, fees."""
    lots = lots_from_ledger(state, statuses=FILLED_STATUSES)
    out = []
    for sleeve, payload in (state.get("sleeves") or {}).items():
        for tr in payload.get("tranches") or []:
            k = int(tr.get("k", 0))
            last_px = tr.get("last_px") or {}
            for ticker, units in (tr.get("units") or {}).items():
                u = _f(units)
                if u <= 1e-12:
                    continue
                px = _mark(marks, sleeve, ticker, last_px.get(ticker))
                lot = lots.get((sleeve, k, ticker), {"qty": 0.0, "cost_total": 0.0, "realised": 0.0, "fees": 0.0})
                avg = lot["cost_total"] / lot["qty"] if lot["qty"] > 0 else 0.0
                mv = u * px if px is not None else 0.0
                out.append(dict(
                    sleeve=sleeve, tranche=k, ticker=ticker, units=u, avg_cost=avg, mark=px,
                    market_value=mv, unrealised=(px - avg) * u if (px is not None and avg) else 0.0,
                    realised=lot["realised"], fees=lot["fees"],
                ))
    # closed lots (realised only, no units left) still carry realised P/L and fees
    open_keys = {(p["sleeve"], p["tranche"], p["ticker"]) for p in out}
    for (sleeve, k, ticker), lot in lots.items():
        if (sleeve, k, ticker) in open_keys:
            continue
        if abs(lot["realised"]) > TOL or abs(lot["fees"]) > TOL:
            out.append(dict(sleeve=sleeve, tranche=k, ticker=ticker, units=0.0, avg_cost=0.0, mark=None,
                            market_value=0.0, unrealised=0.0, realised=lot["realised"], fees=lot["fees"]))
    return out


def _initial_cash_by_sleeve(state: dict) -> dict:
    capital = _f(state.get("capital_reference"))
    sleeves = list((state.get("sleeves") or {}).keys()) or ["stocks", "etf"]
    mix = state.get("mix") or {}
    if not mix:
        mix = {s: 1.0 / len(sleeves) for s in sleeves}
    return {s: capital * _f(mix.get(s), 1.0 / len(sleeves)) for s in sleeves}


def attribution(state: dict, marks: dict | None = None) -> dict:
    """Cumulative decomposition since the anchor. See the module docstring for the identity."""
    state = state or {}
    initial = _initial_cash_by_sleeve(state)
    per = {s: dict(initial=v, cash=0.0, market_value=0.0, buys=0.0, sells=0.0, fees=0.0, write_offs=0.0,
                   interest=0.0, dividends=0.0, transfers=0.0, n_fills=0, n_write_offs=0)
           for s, v in initial.items()}

    def sl(name):
        if name not in per:
            per[name] = dict(initial=0.0, cash=0.0, market_value=0.0, buys=0.0, sells=0.0, fees=0.0,
                             write_offs=0.0, interest=0.0, dividends=0.0, transfers=0.0, n_fills=0, n_write_offs=0)
        return per[name]

    for sleeve, payload in (state.get("sleeves") or {}).items():
        d = sl(sleeve)
        for tr in payload.get("tranches") or []:
            d["cash"] += _f(tr.get("cash"))
            last_px = tr.get("last_px") or {}
            for ticker, units in (tr.get("units") or {}).items():
                u = _f(units)
                if u <= 1e-12:
                    continue
                px = _mark(marks, sleeve, ticker, last_px.get(ticker))
                d["market_value"] += u * (px or 0.0)

    for f in state.get("ledger") or []:
        if f.get("status") not in FILLED_STATUSES or f.get("side") not in ("buy", "sell"):
            continue
        d = sl(str(f.get("sleeve")))
        dollars = _f(f.get("dollars"))
        if dollars == 0.0:
            dollars = _f(f.get("units")) * _f(f.get("price"))
        if f.get("side") == "buy":
            d["buys"] += dollars
        else:
            d["sells"] += dollars
        d["fees"] += _f(f.get("cost"))
        d["n_fills"] += 1
    for w in state.get("write_offs") or []:
        d = sl(str(w.get("sleeve")))
        d["write_offs"] += _f(w.get("proceeds"))
        d["n_write_offs"] += 1
    for r in state.get("interest") or []:
        sl(str(r.get("sleeve")))["interest"] += _f(r.get("dollars"))
    for r in state.get("dividends") or []:
        sl(str(r.get("sleeve")))["dividends"] += _f(r.get("dollars"))
    for r in state.get("transfers") or []:
        sl(str(r.get("sleeve")))["transfers"] += _f(r.get("dollars"))

    sleeves_out = {}
    book = dict(initial=0.0, value=0.0, change=0.0, selection=0.0, etf=0.0, trading_other=0.0,
                fees=0.0, interest=0.0, dividends=0.0, transfers=0.0, residual=0.0)
    for s, d in per.items():
        value = d["cash"] + d["market_value"]
        trading = d["market_value"] + d["sells"] + d["write_offs"] - d["buys"]
        fees = -d["fees"]
        explained = trading + fees + d["interest"] + d["dividends"] + d["transfers"]
        change = value - d["initial"]
        residual = change - explained
        sleeves_out[s] = dict(
            initial=d["initial"], value=value, change=change, trading=trading, fees=fees,
            interest=d["interest"], dividends=d["dividends"], transfers=d["transfers"], residual=residual,
            cash=d["cash"], market_value=d["market_value"], n_fills=d["n_fills"], n_write_offs=d["n_write_offs"],
            label=SLEEVE_LABEL.get(s, s),
        )
        book["initial"] += d["initial"]
        book["value"] += value
        book["change"] += change
        key = SLEEVE_LABEL.get(s)
        if key in ("selection", "etf"):
            book[key] += trading
        else:
            book["trading_other"] += trading
        book["fees"] += fees
        book["interest"] += d["interest"]
        book["dividends"] += d["dividends"]
        book["transfers"] += d["transfers"]
        book["residual"] += residual
    components = book["selection"] + book["etf"] + book["trading_other"] + book["fees"] + book["interest"] \
        + book["dividends"] + book["transfers"] + book["residual"]
    book["identity_gap"] = book["change"] - components          # 0 by construction; kept as a self-check
    book["transfers_net_zero"] = abs(book["transfers"]) <= 1e-6
    book["change_pct"] = (book["change"] / book["initial"]) if book["initial"] else None
    return dict(book=book, sleeves=sleeves_out, positions=positions(state, marks),
                anchor_date=state.get("anchor_date"), as_of=state.get("last_run_date"))


def diff(prev: dict | None, cur: dict) -> dict | None:
    """Weekly delta: cur.book - prev.book for the additive components. None without a previous block."""
    if not prev or not isinstance(prev.get("book"), dict):
        return None
    keys = ("value", "change", "selection", "etf", "trading_other", "fees", "interest", "dividends", "transfers", "residual")
    pb, cb = prev["book"], cur["book"]
    return {k: _f(cb.get(k)) - _f(pb.get(k)) for k in keys}


def render_markdown(block: dict, weekly: dict | None = None) -> str:
    b = block["book"]
    lines = [f"# Attribution since {block.get('anchor_date')} (as of {block.get('as_of')})", "",
             f"Book {b['value']:,.2f} vs initial {b['initial']:,.2f}: change **{b['change']:,.2f}**"
             + (f" ({b['change_pct'] * 100:.2f} %)" if b.get("change_pct") is not None else ""), "",
             "| component | cumulative $ |" + (" week $ |" if weekly else ""), "|---|---:|" + ("---:|" if weekly else "")]
    for k, label in (("selection", "stock selection"), ("etf", "ETF sleeve"), ("trading_other", "other sleeves"),
                     ("fees", "fees"), ("interest", "interest"), ("dividends", "dividends"),
                     ("transfers", "reset transfers (net)"), ("residual", "residual / fill rounding")):
        row = f"| {label} | {b.get(k, 0.0):,.2f} |"
        if weekly:
            row += f" {weekly.get(k, 0.0):,.2f} |"
        lines.append(row)
    lines += ["", f"identity gap {b['identity_gap']:.2e}; transfers net to zero: {b['transfers_net_zero']}", "",
              "| sleeve | value | change | trading | fees | interest | dividends | transfers | residual |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for s, d in block["sleeves"].items():
        lines.append(f"| {s} | {d['value']:,.2f} | {d['change']:,.2f} | {d['trading']:,.2f} | {d['fees']:,.2f} | "
                     f"{d['interest']:,.2f} | {d['dividends']:,.2f} | {d['transfers']:,.2f} | {d['residual']:,.2f} |")
    return "\n".join(lines) + "\n"
