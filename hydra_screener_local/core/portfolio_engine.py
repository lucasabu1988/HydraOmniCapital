"""
HYDRA v9 portfolio engine — 50/50 T20 (stocks) + ETF trend, four tranches per sleeve.

Pure: takes the screener ranking, price frames and the T-bill rate; returns a new state and the
orders to execute. No network, no files (portfolio_v9.py does I/O). Authorised by Lucas on
2026-09-06; design in .comms/claude-v9-production-design-2026-09-06.md.

Time convention (same as the executable simulator): the engine runs after the close of bar t with
data up to t. `plan()` decides what to do and emits orders priced at t's close as ESTIMATES; the
orders are executed at the close of t+1 (MOC). `settle()` books them at t+1 prices (dollar amounts
are kept, units are recomputed at the fill price). `mark()` values the book at any later close.

Rebalancing policy (executable version of the lab's 50/50 mix): on a renewal bar both sleeves
renew one tranche; the renewed pair of tranches (one per sleeve) is split 50/50 by value, so the sleeve
totals drift back to 50/50 one tranche per week. The cash moved between sleeves is recorded as a
transfer. Nothing else is rebalanced for free.
"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from config import MAX_PER_SECTOR, V9
from core.tranche_book import Tranche, TrancheBook

STATE_SCHEMA = 1
SLEEVES = ("stocks", "etf")      # the default registry; kept for callers that import it


# ----------------------------------------------------------------------------- sleeves (TASK-386)
def _sleeves(cfg: dict) -> dict:
    """name -> Sleeve from `cfg["sleeves"]` (default stocks + etf). Lazy import: the adapters import
    `stock_targets` / `etf_targets` from this module."""
    from sleeves.registry import build
    return build(cfg)


def _mix(cfg: dict, names: list) -> dict:
    """Target mix over the registry's names. `cfg["mix"]` (policy, per book via TASK-365) or equal
    weights; must cover every name and sum to 1. The state does not store it (schema 1 unchanged)."""
    mix = dict(cfg.get("mix") or {})
    if not mix:
        mix = {n: 1.0 / len(names) for n in names}
    missing = [n for n in names if n not in mix]
    if missing:
        raise ValueError(f"cfg['mix'] has no weight for sleeve(s) {missing}")
    total = float(sum(float(mix[n]) for n in names))
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"cfg['mix'] over {names} sums to {total}, not 1")
    return {n: float(mix[n]) for n in names}


def _price_rows(sleeves: dict, stock_row, etf_row) -> dict:
    """Which close row marks each sleeve (`Sleeve.mark_frame`: 'stocks' or 'etf')."""
    return {name: (stock_row if getattr(sl, "mark_frame", name) == "stocks" else etf_row)
            for name, sl in sleeves.items()}


# ----------------------------------------------------------------------------- state
def new_state(capital: float, anchor_date: str, cfg: dict = None) -> dict:
    cfg = cfg or V9
    k = cfg["tranches"]
    sleeves = _sleeves(cfg)
    mix = _mix(cfg, list(sleeves))
    return {
        "schema_version": STATE_SCHEMA,
        "algo_version": "v9",
        "anchor_date": anchor_date,
        "last_run_date": None,
        "last_renewal_date": None,
        "week_index": -1,
        "capital_reference": float(capital),
        # each sleeve starts with capital x mix / K per tranche (two sleeves at 50/50: capital / 8)
        "sleeves": {s: {"tranches": [{"k": i, "opened": None, "units": {}, "cash": float(capital) * mix[s] / k,
                                      "last_px": {}, "stale": {}} for i in range(k)]}
                    for s in sleeves},
        "pending": [],          # orders planned at last_run_date, to settle at the next close
        "ledger": [],           # every order ever settled
        "write_offs": [],
        "transfers": [],
        "interest": [],         # T-bill accrued on idle cash, one record per sleeve per plan() (spec 9.3)
    }


def _book(state: dict, sleeve: str, cost_bp: float, cfg: dict) -> TrancheBook:
    book = TrancheBook(cfg["tranches"], cost_bp, max_stale_bars=cfg["max_stale_bars"])
    for i, tr in enumerate(state["sleeves"][sleeve]["tranches"]):
        book.tranches[i] = Tranche(cash=float(tr["cash"]), units={k: float(v) for k, v in tr["units"].items()},
                                   stale={k: int(v) for k, v in (tr.get("stale") or {}).items()},
                                   last_px={k: float(v) for k, v in tr.get("last_px", {}).items()})
    return book


def _dump(state: dict, sleeve: str, book: TrancheBook) -> None:
    for i, tr in enumerate(book.tranches):
        st = state["sleeves"][sleeve]["tranches"][i]
        st["cash"] = float(tr.cash)
        st["units"] = {k: float(v) for k, v in tr.units.items() if v > 1e-12}
        st["last_px"] = {k: float(v) for k, v in tr.last_px.items() if k in st["units"]}
        # marks without a print, per held name: without this the counter restarted from zero at every
        # run and a delisted name was carried at its last price forever (TASK-350 review: 492
        # hold_no_price events on AET/ESRX/TWX and no write-off in 22 years)
        st["stale"] = {k: int(v) for k, v in tr.stale.items() if k in st["units"]}


# ----------------------------------------------------------------------------- calendar
def bars_between(index: pd.DatetimeIndex, start: str, end: str) -> int:
    """Trading bars strictly after `start` up to and including `end`, on the price calendar."""
    idx = pd.DatetimeIndex(index).normalize()
    a, b = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    return int(((idx > a) & (idx <= b)).sum())


def renewal_slot(state: dict, index: pd.DatetimeIndex, today: str, cfg: dict = None) -> Optional[Tuple[int, int]]:
    """(week_index, tranche k) if `today` is a renewal bar, else None. The anchor bar itself is week 0."""
    cfg = cfg or V9
    n = bars_between(index, state["anchor_date"], today)
    if pd.Timestamp(today).normalize() < pd.Timestamp(state["anchor_date"]).normalize():
        return None
    if n % cfg["step_bars"] != 0:
        return None
    week = n // cfg["step_bars"]
    if week <= state["week_index"]:
        return None                                  # already renewed this week (idempotent)
    return week, week % cfg["tranches"]


# ----------------------------------------------------------------------------- targets
def _is_vetoed(row) -> bool:
    r = row.get("reason", "") if hasattr(row, "get") else ""
    return isinstance(r, str) and r.startswith("Vetado")


def select_tranche_names(ranking: pd.DataFrame, n: int, held: set, buffer: float,
                         max_per_sector: int = MAX_PER_SECTOR) -> List[str]:
    """Names for the renewed stock tranche. Mirrors experiments/redesign_lab.select():
    vetoed names out; held names stay while they rank within buffer*n; vacancies filled walking
    down the ranking under the hard sector cap ("Other" exempt)."""
    df = ranking.sort_values("rank")
    if "reason" in df.columns:
        df = df[~df["reason"].fillna("").astype(str).str.startswith("Vetado")]
    order = df["ticker"].tolist()
    sectors = dict(zip(df["ticker"], df["sector"], strict=True)) if "sector" in df.columns else {}
    keep_zone = set(order[:int(round(buffer * n))]) if buffer > 1.0 else set()
    picked, counts = [], {}
    for name in order:
        if name in held and name in keep_zone:
            picked.append(name)
            s = sectors.get(name, "Other")
            counts[s] = counts.get(s, 0) + 1
    for name in order:
        if len(picked) >= n:
            break
        if name in picked:
            continue
        s = sectors.get(name, "Other")
        if s != "Other" and counts.get(s, 0) >= max_per_sector:
            continue
        picked.append(name)
        counts[s] = counts.get(s, 0) + 1
    return picked[:n]


def stock_targets(ranking: pd.DataFrame, held: set, prices: pd.DataFrame, cfg: dict = None) -> pd.Series:
    """Equal weights over the selected names, scaled by exposure = min(1, target_vol / basket vol63).
    Zero recommended (dynamic count 0 or every name vetoed) -> empty Series: the tranche goes to T-bill."""
    cfg = cfg or V9
    if ranking is None or len(ranking) == 0:
        return pd.Series(dtype=float)
    n = int(ranking["recommended_count"].iloc[0]) if "recommended_count" in ranking.columns else int(ranking["recommended"].sum())
    if n <= 0:
        return pd.Series(dtype=float)
    names = select_tranche_names(ranking, n, held, cfg["stock_buffer"])
    names = [x for x in names if x in prices.columns]
    if not names:
        return pd.Series(dtype=float)
    rets = prices[names].pct_change(fill_method=None).iloc[-63:]
    basket = rets.mean(axis=1)
    rv = float(basket.std(ddof=1)) * math.sqrt(252) if len(basket) > 2 else 0.0
    expo = min(1.0, cfg["stock_target_vol"] / rv) if rv > 0 else 1.0
    return pd.Series(expo / len(names), index=names)


def etf_targets(etf_closes: pd.DataFrame, tbill_daily: pd.Series, cfg: dict = None) -> pd.Series:
    from sleeves.etf_trend import target_weights
    cfg = cfg or V9
    return target_weights(etf_closes, tbill_daily, "invvol", cfg["etf_lookback_bars"], cfg["etf_vol_bars"])


# ----------------------------------------------------------------------------- plan / settle / mark
def mark(state: dict, stock_prices: pd.Series, etf_prices: pd.Series, cfg: dict = None) -> dict:
    """Value the book at the given closes (last_px carry for names that do not print). Ages
    staleness and records write-offs. Mutates state; returns a summary."""
    cfg = cfg or V9
    sleeves = _sleeves(cfg)
    rows = _price_rows(sleeves, stock_prices, etf_prices)
    out = {"sleeves": {}, "total": 0.0}
    for sleeve, sl in sleeves.items():
        px = rows[sleeve]
        book = _book(state, sleeve, sl.cost_bp, cfg)
        book.age_stale(px)
        for w in book.write_offs:
            state["write_offs"].append(dict(w, sleeve=sleeve, date=state.get("last_run_date")))
        v = book.value_with_stale(px)
        out["sleeves"][sleeve] = {"value": v, "cash": float(sum(t.cash for t in book.tranches)),
                                  "exposure": book.exposure(px), "distinct": book.distinct(),
                                  "tranches": [book.tranches[i].value(px) + sum(u * book.tranches[i].last_px.get(t, 0.0)
                                               for t, u in book.tranches[i].units.items() if not np.isfinite(px.get(t, np.nan)))
                                               for i in range(cfg["tranches"])]}
        out["total"] += v
        _dump(state, sleeve, book)
    return out


def accrue_interest(state: dict, index: pd.DatetimeIndex, today: str, tbill_rate) -> float:
    """Idle cash earns the 13-week T-bill (Lucas, 2026-09-05: the books model the money-market
    yield). Every tranche's cash compounds by rate/252 for each price-calendar bar strictly after
    `last_run_date` up to and including `today`, at the ^IRX print of that bar (`tbill_rate` as an
    annualised decimal Series; a scalar is a flat rate). Nothing accrues on the first run. The cash
    spent at t+1 settles earned one bar less than the book assumes (< 0.01 bp; accepted). Records
    one entry per sleeve in `state["interest"]`; returns the total dollars accrued."""
    last = state.get("last_run_date")
    if not last:
        return 0.0
    idx = pd.DatetimeIndex(index).normalize()
    bars = idx[(idx > pd.Timestamp(last).normalize()) & (idx <= pd.Timestamp(today).normalize())]
    if not len(bars):
        return 0.0
    if isinstance(tbill_rate, pd.Series):
        r = pd.to_numeric(tbill_rate, errors="coerce")
        r.index = pd.DatetimeIndex(r.index).normalize()
        daily = r.reindex(idx).ffill().reindex(bars).fillna(0.0).astype(float) / 252.0
    else:
        daily = pd.Series(float(tbill_rate) / 252.0, index=bars)
    factor = float((1.0 + daily).prod())
    total = 0.0
    state.setdefault("interest", [])
    for sleeve in list(state["sleeves"].keys()):
        earned = 0.0
        for tr in state["sleeves"][sleeve]["tranches"]:
            cash = float(tr["cash"])
            if cash > 0:                                       # a (transient) negative balance is not charged
                tr["cash"] = cash * factor
                earned += cash * (factor - 1.0)
        state["interest"].append(dict(date=today, since=last, sleeve=sleeve, bars=int(len(bars)),
                                      rate=float(daily.mean() * 252.0), dollars=earned))
        total += earned
    return total


def plan(state: dict, today: str, ranking: pd.DataFrame, stock_prices: pd.DataFrame,
         etf_prices: pd.DataFrame, tbill_rate: float, cfg: dict = None) -> Tuple[dict, List[dict]]:
    """Run after the close of `today`. Marks the book, decides whether a tranche renews and, if so,
    produces the orders (estimates at today's close) for execution at the next close.

    Returns (state, orders). Idempotent: a second call on the same date returns no new orders.
    TASK-386: the sleeves come from the registry (`cfg["sleeves"]`, default stocks + etf) and the
    bundle of renewed tranches is reset to `cfg["mix"]`; two sleeves at 50/50 is today's engine."""
    cfg = cfg or V9
    if state.get("last_run_date") == today:
        return state, []                                 # same day again: nothing new (idempotent)
    if state["pending"]:
        raise RuntimeError("pending orders from %s not settled; call settle() with the next close first"
                           % state["pending"][0]["planned"])
    sleeves = _sleeves(cfg)
    names = list(sleeves)
    mix = _mix(cfg, names)
    px_s, px_e = stock_prices.iloc[-1], etf_prices.iloc[-1]
    rows = _price_rows(sleeves, px_s, px_e)
    accrue_interest(state, stock_prices.index, today, tbill_rate)
    state["last_run_date"] = today
    summary = mark(state, px_s, px_e, cfg)
    slot = renewal_slot(state, stock_prices.index, today, cfg)
    if slot is None:
        return state, []
    week, k = slot
    # Bundle reset (spec 9.3, generalised): the renewed tranches of every sleeve form one bundle whose
    # value V is split by the target mix, so the transfer legs sum to zero for any N and the book is
    # conserved. Sizing a leg to 1/(N*K) of the whole book instead (the pre-2026-09-07 rule) created
    # or destroyed cash on paper whenever the bundle differed from 1/K of the book (TASK-347 review,
    # -0.9 pp/yr in-sample). Two sleeves at 50/50 reproduce the pair reset exactly.
    own_by_sleeve = {}
    for sleeve in names:
        px = rows[sleeve]
        tr = state["sleeves"][sleeve]["tranches"][k]
        own_by_sleeve[sleeve] = float(tr["cash"]) + sum(
            u * float(px.get(t, tr.get("last_px", {}).get(t, np.nan)) or 0.0) for t, u in tr["units"].items())
    bundle_value = sum(own_by_sleeve.values())
    tranche_target_by = {sleeve: mix[sleeve] * bundle_value for sleeve in names}

    # T-bill hurdle for the ETF sleeve: the trailing 252-bar accumulated T-bill return, as measured
    # in the lab (`tbill_rate` as an annualised decimal Series on the price calendar). A scalar is
    # accepted for hand cases and means a flat rate.
    if isinstance(tbill_rate, pd.Series):
        tb_daily = pd.to_numeric(tbill_rate, errors="coerce").reindex(etf_prices.index).ffill().fillna(0.0) / 252.0
    else:
        tb_daily = pd.Series(float(tbill_rate) / 252.0, index=etf_prices.index)
    from sleeves.base import MarketSlice
    market = MarketSlice(stock_prices=stock_prices, volumes=None, spy=None, etf_closes=etf_prices,
                         tbill=tb_daily, ranking=ranking)
    orders: List[dict] = []
    cost_by_sleeve = {}
    for sleeve, sl in sleeves.items():
        tr = state["sleeves"][sleeve]["tranches"][k]
        px = rows[sleeve]
        cost_by_sleeve[sleeve] = float(sl.cost_bp)
        targets = sl.targets(market, set(tr["units"]), cfg)
        tranche_target = tranche_target_by[sleeve]
        own = own_by_sleeve[sleeve]
        transfer = tranche_target - own                     # + receives cash from the bundle, - gives
        # sells: everything held that is not in the target, plus trims of kept names
        for t, u in tr["units"].items():
            p = float(px.get(t, np.nan))
            if not np.isfinite(p):
                orders.append(dict(sleeve=sleeve, tranche=k, ticker=t, side="hold_no_price", dollars=0.0, est_units=u, est_price=None,
                                   note="no print today; carried at last price, cannot be sold"))
                continue
            cur = u * p
            tgt = float(targets.get(t, 0.0)) * tranche_target
            if tgt < cur - 1e-9:
                # close=True: the name leaves the tranche, so settle() sells every unit rather than a
                # dollar amount (a dollar sell at t+1 prices left dust positions of 1e-10 units that
                # later surfaced as hold_no_price and write-offs; TASK-350 review)
                orders.append(dict(sleeve=sleeve, tranche=k, ticker=t, side="sell", dollars=cur - tgt, est_units=(cur - tgt) / p, est_price=p,
                                   close=bool(tgt <= 1e-12)))
        for t, w in targets.items():
            p = float(px.get(t, np.nan))
            if not np.isfinite(p):
                continue
            cur = float(tr["units"].get(t, 0.0)) * p
            tgt = float(w) * tranche_target
            if tgt > cur + 1e-9:
                orders.append(dict(sleeve=sleeve, tranche=k, ticker=t, side="buy", dollars=tgt - cur, est_units=(tgt - cur) / p, est_price=p))
        if abs(transfer) > 1e-9:
            orders.append(dict(sleeve=sleeve, tranche=k, ticker="CASH", side="transfer_in" if transfer > 0 else "transfer_out",
                               dollars=abs(transfer), est_units=None, est_price=None,
                               note="50/50 reset: renewed pair of tranches split equally by value" if len(names) == 2 and abs(mix[sleeve] - 0.5) < 1e-12
                               else "bundle reset: renewed tranches split by the target mix"))
        if not len(targets):
            orders.append(dict(sleeve=sleeve, tranche=k, ticker="TBILL", side="park", dollars=tranche_target, est_units=None, est_price=None,
                               note="no names selected: tranche stays in T-bill (no fallback)"))
    for o in orders:
        o.update(planned=today, week=week, cost_bp=cost_by_sleeve[o["sleeve"]])
    state["pending"] = orders
    state["week_index"] = week
    state["last_renewal_date"] = today
    for sleeve in names:
        state["sleeves"][sleeve]["tranches"][k]["opened"] = today
    return state, orders


def settle(state: dict, exec_date: str, stock_prices: pd.Series, etf_prices: pd.Series, cfg: dict = None) -> dict:
    """Book the pending orders at the execution-day closes: sells first, then the inter-sleeve cash
    transfers (ins before outs, so a paying sleeve can receive first), then buys (dollar amounts kept,
    units at the fill price, costs charged). Returns the list of fills (also appended to the ledger).
    Idempotent: nothing pending -> nothing done."""
    cfg = cfg or V9
    if not state["pending"]:
        return []
    fills = []
    sleeves = _sleeves(cfg)
    books = {name: _book(state, name, sl.cost_bp, cfg) for name, sl in sleeves.items()}
    px = _price_rows(sleeves, stock_prices, etf_prices)
    pend = state["pending"]
    for phase in ("sell", "transfer_in", "transfer_out", "buy"):
        for o in pend:
            if o["side"] != phase:
                continue
            tr = books[o["sleeve"]].tranches[o["tranche"]]
            bp = o["cost_bp"] / 10000.0
            if phase in ("transfer_in", "transfer_out"):
                sign = 1.0 if phase == "transfer_in" else -1.0
                tr.cash += sign * o["dollars"]
                state["transfers"].append(dict(date=exec_date, sleeve=o["sleeve"], tranche=o["tranche"], dollars=sign * o["dollars"]))
                continue
            p = float(px[o["sleeve"]].get(o["ticker"], np.nan))
            if not np.isfinite(p) or p <= 0:
                fills.append(dict(o, exec_date=exec_date, status="not_filled", reason="no price on execution day"))
                continue
            if phase == "sell":
                units = tr.units.get(o["ticker"], 0.0) if o.get("close") else min(o["dollars"] / p, tr.units.get(o["ticker"], 0.0))
                dollars = units * p
                tr.units[o["ticker"]] = tr.units.get(o["ticker"], 0.0) - units
                if tr.units[o["ticker"]] <= 1e-12:
                    tr.units.pop(o["ticker"], None)
                    tr.last_px.pop(o["ticker"], None)
                    tr.stale.pop(o["ticker"], None)
                cost = dollars * bp
                tr.cash += dollars - cost
            else:
                dollars = min(o["dollars"], max(tr.cash, 0.0) / (1 + bp))
                units = dollars / p
                cost = dollars * bp
                tr.units[o["ticker"]] = tr.units.get(o["ticker"], 0.0) + units
                tr.last_px[o["ticker"]] = p
                tr.cash -= dollars + cost
            fills.append(dict(o, exec_date=exec_date, status="filled", units=units, price=p, dollars=dollars, cost=cost))
    # park / hold_no_price are instructions too: they land in the ledger as "noted" so the audit
    # trail matches the sheet (review 341).
    for o in pend:
        if o["side"] in ("park", "hold_no_price"):
            fills.append(dict(o, exec_date=exec_date, status="noted"))
    for sleeve in sleeves:
        _dump(state, sleeve, books[sleeve])
    state["ledger"].extend(fills)
    state["pending"] = []
    return fills


def summary_table(state: dict, stock_prices: pd.Series, etf_prices: pd.Series, cfg: dict = None) -> dict:
    """Read-only valuation for the instruction sheet (no staleness ageing, no state mutation)."""
    cfg = cfg or V9
    out = {"sleeves": {}, "total": 0.0}
    sleeves = _sleeves(cfg)
    rows = _price_rows(sleeves, stock_prices, etf_prices)
    for sleeve, sl in sleeves.items():
        px = rows[sleeve]
        book = _book(state, sleeve, sl.cost_bp, cfg)
        v = book.value_with_stale(px)
        out["sleeves"][sleeve] = {"value": v, "cash": float(sum(t.cash for t in book.tranches)), "exposure": book.exposure(px),
                                  "distinct": book.distinct(), "names": sorted(set().union(*[book.held(i) for i in range(cfg["tranches"])]))}
        out["total"] += v
    for sleeve in SLEEVES:
        out["sleeves"][sleeve]["share"] = out["sleeves"][sleeve]["value"] / out["total"] if out["total"] > 0 else 0.0
    return out
