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
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import V9, MAX_PER_SECTOR
from core.numbers import is_finite_money, is_finite_price, is_valid_units
from core.tranche_book import TrancheBook, Tranche

STATE_SCHEMA = 1
#: the sleeves a *new* v9 state is created with. Never iterate this over an existing
#: state — use `sleeve_names(state)`, so a state with a different registry is not
#: silently truncated to these two (audit phase 8.4/8.6).
DEFAULT_SLEEVES = ("stocks", "etf")
SLEEVES = DEFAULT_SLEEVES          # kept for callers that predate phase 8


def sleeve_names(state: dict | None = None, cfg: dict | None = None) -> list[str]:
    """The sleeves this state actually has, in a stable order.

    Phase 8.4: omitting a sleeve from a loop hides the capital sitting in it. Every
    valuation, settlement and summary walk asks this instead of a module constant.
    """
    if state:
        names = list((state.get("sleeves") or {}).keys())
        if names:
            return names
    if state and (state.get("mix") or {}):
        return list(state["mix"].keys())
    cfg = cfg or V9
    return list(cfg.get("sleeves") or DEFAULT_SLEEVES)


def sleeve_cost_bp(sleeve: str, cfg: dict) -> float:
    """Cost in basis points for a sleeve, from cfg. Unknown sleeve -> the stock cost."""
    per = cfg.get("sleeve_cost_bp") or {}
    if sleeve in per:
        return float(per[sleeve])
    key = f"{sleeve}_cost_bp"
    if key in cfg:
        return float(cfg[key])
    return float(cfg.get("stock_cost_bp", 0.0))


def effective_config(state: dict | None, cfg: dict | None = None) -> dict:
    """The configuration a run must use.

    Phase 8.2: a replay uses the configuration persisted *with that run*, not
    whatever the current process happens to have imported. Passing `cfg` explicitly
    still wins, because that is how the lab drives a sweep.
    """
    if cfg is not None:
        return cfg
    stored = (state or {}).get("config")
    if isinstance(stored, dict) and stored:
        return stored
    return V9


def config_hash(cfg: dict) -> str:
    import hashlib
    import json
    blob = json.dumps(cfg, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def sleeve_registry(state: dict | None = None, cfg: dict | None = None) -> dict:
    """{sleeve: {cost_bp, weight}} — what the state says its sleeves are."""
    cfg = effective_config(state, cfg)
    names = sleeve_names(state, cfg)
    mix = (state or {}).get("mix") or cfg.get("mix") or {}
    if not mix:
        mix = {n: 1.0 / len(names) for n in names} if names else {}
    return {n: {"cost_bp": sleeve_cost_bp(n, cfg), "weight": float(mix.get(n, 0.0))}
            for n in names}


def validate_mix(mix: dict, names: list[str], *, tol: float = None) -> list[str]:
    """Errors in a sleeve mix. Empty list = usable (audit phase 8.3).

    Weights must be finite, in [0, 1], sum to 1 within `MIX_SUM_TOL`, and name every
    sleeve exactly once — a sleeve missing from the mix is capital nobody accounts
    for (phase 8.4).
    """
    from core.numbers import is_finite_money, weights_sum_to_one
    tol = MIX_SUM_TOL if tol is None else tol
    errors: list[str] = []
    if not isinstance(mix, dict) or not mix:
        return [f"mix must be a non-empty mapping, got {mix!r}"]
    for name, w in mix.items():
        if not is_finite_money(w):
            errors.append(f"mix[{name!r}]={w!r} is not finite")
        elif float(w) < 0.0:
            errors.append(f"mix[{name!r}]={w!r} is negative")
        elif float(w) > 1.0:
            errors.append(f"mix[{name!r}]={w!r} is above 1")
    if not errors and not weights_sum_to_one(mix, tol=tol):
        errors.append(f"mix sums to {sum(float(w) for w in mix.values())!r}, not 1 within {tol:g}")
    missing = sorted(set(names) - set(mix))
    if missing:
        errors.append(f"sleeve(s) absent from mix: {missing}")
    extra = sorted(set(mix) - set(names))
    if extra:
        errors.append(f"mix names no such sleeve: {extra}")
    return errors


#: documented tolerance for "the weights sum to one" (phase 8.3)
MIX_SUM_TOL = 1e-9


class DataError(RuntimeError):
    """Data the engine needs to size an order is missing or impossible.

    Raised rather than worked around: an order priced off a non-finite or
    non-positive close is an order Lucas would execute by hand (audit phase 2.3).
    """


def _price_for_order(px, ticker: str) -> tuple[float | None, str | None]:
    """(price, rejection reason). A price is usable only if finite and > 0.

    Before phase 2 only `np.isfinite` was checked, so a close of 0.0 raised
    ZeroDivisionError inside plan() (repro R-201) and a negative close produced a
    buy order for real dollars at negative est_units (repro R-202: $575.86 at
    -46.07 shares, est_price -12.50).
    """
    raw = px.get(ticker, np.nan)
    try:
        p = float(raw)
    except (TypeError, ValueError):
        return None, f"price is not a number: {raw!r}"
    if not np.isfinite(p):
        return None, "no print on the planning close"
    if p <= 0.0:
        return None, f"close is not a valid price: {p!r}"
    return p, None


def _reject(state: dict, today: str, sleeve: str, k: int, ticker: str, intent: str, reason: str) -> dict:
    """Record a structured refusal on the state and return it (phase 2.3/1.11)."""
    rec = {
        "date": str(today), "sleeve": str(sleeve), "tranche": int(k), "ticker": str(ticker),
        "intent": str(intent), "reason": str(reason), "code": "price_not_executable",
    }
    state.setdefault("data_errors", []).append(rec)
    return rec


def validate_orders(orders: list) -> list[str]:
    """Errors in a planned order list. Empty list = every order is executable.

    Acceptance criterion 3: no order may carry a NaN, infinite, zero-invalid or
    negative price, unit count or dollar amount.
    """
    errors: list[str] = []
    for i, o in enumerate(orders):
        where = f"order[{i}] {o.get('sleeve')}[{o.get('tranche')}] {o.get('side')} {o.get('ticker')}"
        dollars = o.get("dollars")
        if not is_finite_money(dollars):
            errors.append(f"{where}: dollars is not finite ({dollars!r})")
        elif float(dollars) < 0.0:
            errors.append(f"{where}: dollars is negative ({dollars!r})")
        px = o.get("est_price")
        if px is not None and not is_finite_price(px):
            errors.append(f"{where}: est_price is not a valid price ({px!r})")
        units = o.get("est_units")
        if units is not None and not is_valid_units(units, allow_zero=True):
            errors.append(f"{where}: est_units is not a valid unit count ({units!r})")
    return errors


# ----------------------------------------------------------------------------- state
def new_state(capital: float, anchor_date: str, cfg: dict = None) -> dict:
    """A fresh v9 state, carrying the configuration it was created with.

    Phase 8.1: the state persists its schema version, the effective configuration and
    its hash, the sleeve mix, the sleeve registry and its hash, the price calendar the
    runs have seen, and the last mark date. A replay reads those instead of importing
    whatever config the process has now (phase 8.2).
    """
    cfg = cfg or V9
    k = cfg["tranches"]
    names = list(cfg.get("sleeves") or DEFAULT_SLEEVES)
    mix = dict(cfg.get("mix") or {}) or {n: 1.0 / len(names) for n in names}
    problems = validate_mix(mix, names)
    if problems:
        raise ValueError("cannot create a state with an invalid mix: " + "; ".join(problems))
    registry = {n: {"cost_bp": sleeve_cost_bp(n, cfg), "weight": float(mix[n])} for n in names}
    state = {
        "schema_version": STATE_SCHEMA,
        "algo_version": "v9",
        "anchor_date": anchor_date,
        "last_run_date": None,
        "last_renewal_date": None,
        "last_mark_date": None,
        "week_index": -1,
        "capital_reference": float(capital),
        "mix": mix,
        "config": dict(cfg),
        "config_sha256": config_hash(cfg),
        "sleeve_registry": registry,
        "registry_sha256": config_hash(registry),
        "calendar": [],         # every price-calendar session the runs have seen (phase 8.8)
        "sleeves": {n: {"tranches": [{"k": i, "opened": None, "units": {}, "cash": float(capital) * mix[n] / k,
                                      "last_px": {}, "stale": {}} for i in range(k)]}
                    for n in names},
        "pending": [],          # orders planned at last_run_date, to settle at the next close
        "ledger": [],           # every order ever settled
        "write_offs": [],
        "transfers": [],
        "interest": [],         # T-bill accrued on idle cash, one record per sleeve per plan() (spec 9.3)
    }
    return state


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
    """Trading bars strictly after `start` up to and including `end`, on `index`."""
    idx = pd.DatetimeIndex(index).normalize()
    a, b = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    return int(((idx > a) & (idx <= b)).sum())


def record_calendar(state: dict, index) -> list[str]:
    """Add `index`'s sessions to the state's persisted calendar. Append-only, sorted.

    Phase 8.8: the renewal schedule must not depend on how many bars the last
    download returned. Probed on the base commit with a 700-bar calendar and a
    2-year fetch window: `bars_between` gave 699 on the full index and 500 on the
    trimmed one, so the renewal week was 139 versus 100 and a renewal fired on one
    and not the other. The union of every session the runs have seen is the state's
    own calendar, and it only grows.
    """
    if index is None or len(index) == 0:
        return list(state.get("calendar") or [])
    seen = set(state.get("calendar") or [])
    for d in pd.DatetimeIndex(index).normalize():
        seen.add(str(pd.Timestamp(d).date()))
    out = sorted(seen)
    state["calendar"] = out
    return out


def effective_calendar(state: dict | None, index=None) -> pd.DatetimeIndex:
    """The calendar to count renewals on: the persisted sessions union `index`."""
    dates = set((state or {}).get("calendar") or [])
    if index is not None and len(index):
        for d in pd.DatetimeIndex(index).normalize():
            dates.add(str(pd.Timestamp(d).date()))
    if not dates:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(sorted(dates))


def calendar_covers_anchor(state: dict, index=None) -> bool:
    """Can the renewal count be trusted? False when the calendar starts after the anchor."""
    cal = effective_calendar(state, index)
    if not len(cal):
        return False
    anchor = pd.Timestamp(state["anchor_date"]).normalize()
    return bool(cal[0] <= anchor)


def renewal_slot(state: dict, index: pd.DatetimeIndex, today: str, cfg: dict = None) -> Optional[Tuple[int, int]]:
    """(week_index, tranche k) if `today` is a renewal bar, else None.

    Counted on `effective_calendar` — the persisted sessions union the index handed in
    — so a shorter download cannot move the schedule (phase 8.8). The anchor bar
    itself is week 0.
    """
    cfg = effective_config(state, cfg)
    if pd.Timestamp(today).normalize() < pd.Timestamp(state["anchor_date"]).normalize():
        return None
    cal = effective_calendar(state, index)
    if not len(cal):
        cal = pd.DatetimeIndex(index).normalize() if index is not None else pd.DatetimeIndex([])
    n = bars_between(cal, state["anchor_date"], today)
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
    sectors = dict(zip(df["ticker"], df["sector"])) if "sector" in df.columns else {}
    keep_zone = set(order[:int(round(buffer * n))]) if buffer > 1.0 else set()
    picked, counts = [], {}
    for name in order:
        if name in held and name in keep_zone:
            picked.append(name); s = sectors.get(name, "Other"); counts[s] = counts.get(s, 0) + 1
    for name in order:
        if len(picked) >= n:
            break
        if name in picked:
            continue
        s = sectors.get(name, "Other")
        if s != "Other" and counts.get(s, 0) >= max_per_sector:
            continue
        picked.append(name); counts[s] = counts.get(s, 0) + 1
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
    cfg = effective_config(state, cfg)
    out = {"sleeves": {}, "total": 0.0}
    prices_for = {"stocks": stock_prices, "etf": etf_prices}
    for sleeve in sleeve_names(state, cfg):
        px = prices_for.get(sleeve, stock_prices)
        bp = sleeve_cost_bp(sleeve, cfg)
        book = _book(state, sleeve, bp, cfg)
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
    state["last_mark_date"] = state.get("last_run_date")
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
    for sleeve in sleeve_names(state):
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

    Returns (state, orders). Idempotent: a second call on the same date returns no new orders."""
    cfg = effective_config(state, cfg)
    if state.get("last_run_date") == today:
        return state, []                                 # same day again: nothing new (idempotent)
    if state["pending"]:
        raise RuntimeError("pending orders from %s not settled; call settle() with the next close first"
                           % state["pending"][0]["planned"])
    px_s, px_e = stock_prices.iloc[-1], etf_prices.iloc[-1]
    # every session this run saw joins the state's own calendar, so the renewal
    # schedule stops depending on how many bars the download returned (phase 8.8)
    record_calendar(state, stock_prices.index)
    accrue_interest(state, stock_prices.index, today, tbill_rate)
    state["last_run_date"] = today
    summary = mark(state, px_s, px_e, cfg)
    slot = renewal_slot(state, stock_prices.index, today, cfg)
    if slot is None:
        return state, []
    week, k = slot
    # 50/50 reset (spec 9.3): the renewed PAIR of tranches (stocks k, etf k) is split equally by value,
    # so the two transfer legs are equal and opposite and the book is conserved. Sizing each leg to
    # 1/8 of the whole book instead (the pre-2026-09-07 rule) created or destroyed cash on paper
    # whenever the pair's value differed from 1/4 of the book (found by the end-to-end engine
    # backtest, TASK-347 review: -0.9 pp/yr in-sample).
    own_by_sleeve = {}
    for sleeve, px in (("stocks", px_s), ("etf", px_e)):
        tr = state["sleeves"][sleeve]["tranches"][k]
        value = float(tr["cash"])
        for t, u in tr["units"].items():
            mark_px = px.get(t, tr.get("last_px", {}).get(t, np.nan))
            try:
                mark_px = float(mark_px)
            except (TypeError, ValueError):
                mark_px = np.nan
            if not np.isfinite(mark_px) or mark_px <= 0.0:
                # no print and no carried mark: the name contributes nothing to the
                # renewal split and is reported. The sells loop below emits
                # hold_no_price for it, so it is visible on the sheet too.
                _reject(state, today, sleeve, k, t, "mark", "no print and no last_px to carry")
                continue
            value += float(u) * mark_px
        if not is_finite_money(value):
            raise DataError(f"{sleeve}[{k}] tranche value is not finite; refusing to plan")
        own_by_sleeve[sleeve] = value
    tranche_target = sum(own_by_sleeve.values()) / 2.0
    if not is_finite_money(tranche_target):
        raise DataError("renewal target is not finite; refusing to plan")

    # T-bill hurdle for the ETF sleeve: the trailing 252-bar accumulated T-bill return, as measured
    # in the lab (`tbill_rate` as an annualised decimal Series on the price calendar). A scalar is
    # accepted for hand cases and means a flat rate.
    if isinstance(tbill_rate, pd.Series):
        tb_daily = pd.to_numeric(tbill_rate, errors="coerce").reindex(etf_prices.index).ffill().fillna(0.0) / 252.0
    else:
        tb_daily = pd.Series(float(tbill_rate) / 252.0, index=etf_prices.index)
    orders: List[dict] = []
    for sleeve, targets, px, bp in (
        ("stocks", stock_targets(ranking, set(state["sleeves"]["stocks"]["tranches"][k]["units"]), stock_prices, cfg), px_s, cfg["stock_cost_bp"]),
        ("etf", etf_targets(etf_prices, tb_daily, cfg), px_e, cfg["etf_cost_bp"]),
    ):
        tr = state["sleeves"][sleeve]["tranches"][k]
        own = own_by_sleeve[sleeve]
        transfer = tranche_target - own                     # + receives cash from the other sleeve, - gives
        # sells: everything held that is not in the target, plus trims of kept names
        for t, u in tr["units"].items():
            p, reason = _price_for_order(px, t)
            if p is None:
                _reject(state, today, sleeve, k, t, "sell", reason)
                orders.append(dict(sleeve=sleeve, tranche=k, ticker=t, side="hold_no_price", dollars=0.0, est_units=u, est_price=None,
                                   note=f"cannot be sold: {reason}"))
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
            p, reason = _price_for_order(px, t)
            if p is None:
                # no order at all: a buy priced off a bad close is a hand-executed
                # order at a wrong price (phase 2.3). The refusal is structured.
                _reject(state, today, sleeve, k, t, "buy", reason)
                continue
            cur = float(tr["units"].get(t, 0.0)) * p
            tgt = float(w) * tranche_target
            if tgt > cur + 1e-9:
                orders.append(dict(sleeve=sleeve, tranche=k, ticker=t, side="buy", dollars=tgt - cur, est_units=(tgt - cur) / p, est_price=p))
        if abs(transfer) > 1e-9:
            orders.append(dict(sleeve=sleeve, tranche=k, ticker="CASH", side="transfer_in" if transfer > 0 else "transfer_out",
                               dollars=abs(transfer), est_units=None, est_price=None,
                               note="50/50 reset: renewed pair of tranches split equally by value"))
        if not len(targets):
            orders.append(dict(sleeve=sleeve, tranche=k, ticker="TBILL", side="park", dollars=tranche_target, est_units=None, est_price=None,
                               note="no names selected: tranche stays in T-bill (no fallback)"))
    for o in orders:
        o.update(planned=today, week=week, cost_bp=cfg["stock_cost_bp"] if o["sleeve"] == "stocks" else cfg["etf_cost_bp"])
    problems = validate_orders(orders)
    if problems:
        # Fail closed: nothing becomes pending and no sheet is written (audit rule 10).
        raise DataError("refusing to plan; unexecutable order(s): " + "; ".join(problems))
    state["pending"] = orders
    state["week_index"] = week
    state["last_renewal_date"] = today
    for sleeve in sleeve_names(state, cfg):
        state["sleeves"][sleeve]["tranches"][k]["opened"] = today
    return state, orders


def settle(state: dict, exec_date: str, stock_prices: pd.Series, etf_prices: pd.Series, cfg: dict = None) -> list[dict]:
    """Book the pending orders at the execution-day closes: sells first, then the inter-sleeve cash
    transfer, then buys (dollar amounts kept, units at the fill price, costs charged). Returns the
    list of fills (also appended to the ledger). Idempotent: nothing pending -> nothing done."""
    cfg = cfg or V9
    if not state["pending"]:
        return []
    fills = []
    books = {"stocks": _book(state, "stocks", cfg["stock_cost_bp"], cfg), "etf": _book(state, "etf", cfg["etf_cost_bp"], cfg)}
    px = {"stocks": stock_prices, "etf": etf_prices}
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
                    tr.units.pop(o["ticker"], None); tr.last_px.pop(o["ticker"], None); tr.stale.pop(o["ticker"], None)
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
    for sleeve in sleeve_names(state, cfg):
        if sleeve in books:
            _dump(state, sleeve, books[sleeve])
    state["ledger"].extend(fills)
    state["pending"] = []
    return fills


def summary_table(state: dict, stock_prices: pd.Series, etf_prices: pd.Series, cfg: dict = None) -> dict:
    """Read-only valuation for the instruction sheet (no staleness ageing, no state mutation)."""
    cfg = effective_config(state, cfg)
    out = {"sleeves": {}, "total": 0.0}
    prices_for = {"stocks": stock_prices, "etf": etf_prices}
    for sleeve in sleeve_names(state, cfg):
        px = prices_for.get(sleeve, stock_prices)
        book = _book(state, sleeve, sleeve_cost_bp(sleeve, cfg), cfg)
        v = book.value_with_stale(px)
        out["sleeves"][sleeve] = {"value": v, "cash": float(sum(t.cash for t in book.tranches)), "exposure": book.exposure(px),
                                  "distinct": book.distinct(), "names": sorted(set().union(*[book.held(i) for i in range(cfg["tranches"])]))}
        out["total"] += v
    for sleeve in sleeve_names(state, cfg):
        out["sleeves"][sleeve]["share"] = out["sleeves"][sleeve]["value"] / out["total"] if out["total"] > 0 else 0.0
    return out
