"""Replace presumed v9 fills with confirmed ones, and correct or cancel them (audit phase 1).

Does not rebalance. Uses Tranche cash/units math only. Does not import the engine.

Guarantees
----------
* **Validated at the door.** A row with negative units, a non-finite or non-positive
  price, a non-finite fee, or an unknown side never touches the state; it comes back
  `rejected` with the reasons (repros R-102..R-106).
* **Idempotent.** Re-sending the same broker line changes nothing (R-100).
* **Balanced corrections.** Correcting an already-confirmed fill reverses exactly the
  numbers that were booked and applies only the confirmed ones. Before phase 1 the
  reversal was skipped unless the event was still `filled`, so a correction *added* a
  second position (R-101: 10 shares corrected to 5 left 15 in the book).
* **Append-only audit trail.** A correction of a confirmed event marks that event
  `corrected` and appends the new one with `correction_of` pointing at it, so the
  ledger still explains the book and nothing is overwritten.

Two partial fills of one order share a natural key. The default reading of a second
line with the same key is *a correction*, because re-sending a file must not double a
position. To book a genuine second partial fill, give the row its own `event_id` or a
distinct `fill_seq`.
"""
from __future__ import annotations

from core.ledger import (
    CANCELLED,
    CONFIRMED,
    CONFIRMED_UNPLANNED,
    CORRECTED,
    EFFECTIVE_STATUSES,
    LEGACY_PRESUMED,
    PRESUMED,
    REJECTED,
    TRADE_SIDES,
    ensure_event_id,
    index_by_event_id,
    make_event_id,
    moves_book,
    natural_key,
    normalized_trade,
    validate_event,
)
from core.numbers import InvalidNumber, as_finite
from core.tranche_book import Tranche

OPEN_STATUSES = frozenset({LEGACY_PRESUMED, PRESUMED})


def fill_key(row: dict) -> tuple:
    """Kept for callers and CSVs that predate `event_id`."""
    return natural_key(row)


def _tranche(state: dict, sleeve: str, k: int) -> dict:
    return state["sleeves"][sleeve]["tranches"][k]


def _tranche_or_none(state: dict, sleeve: str, k: int) -> dict | None:
    try:
        trans = state["sleeves"][sleeve]["tranches"]
    except (KeyError, TypeError):
        return None
    if not isinstance(k, int) or k < 0 or k >= len(trans):
        return None
    return trans[k]


def _as_tranche(raw: dict) -> Tranche:
    return Tranche(
        cash=as_finite(raw.get("cash"), 0.0),
        units={t: as_finite(u, 0.0) for t, u in (raw.get("units") or {}).items()},
        last_px={t: as_finite(p, 0.0) for t, p in (raw.get("last_px") or {}).items()},
    )


def _dump_tranche(raw: dict, tr: Tranche) -> None:
    raw["cash"] = float(tr.cash)
    raw["units"] = {t: float(u) for t, u in tr.units.items() if u > 1e-12}
    raw["last_px"] = {t: float(p) for t, p in tr.last_px.items() if t in raw["units"]}


def _apply_side(tr: Tranche, side: str, ticker: str, units: float, price: float, fee: float,
                reverse: bool = False) -> None:
    """Apply or reverse a buy/sell on a Tranche. No rebalancing.

    Callers pass numbers that already went through `normalized_trade` (new events) or
    that were booked by a previous accepted event (reversals), so the arithmetic here
    can never see NaN.
    """
    u, p, f = float(units), float(price), float(fee)
    dollars = u * p
    if reverse:
        if side == "buy":
            tr.units[ticker] = tr.units.get(ticker, 0.0) - u
            tr.cash += dollars + f
        elif side == "sell":
            tr.units[ticker] = tr.units.get(ticker, 0.0) + u
            tr.cash -= dollars - f
    else:
        if side == "buy":
            tr.units[ticker] = tr.units.get(ticker, 0.0) + u
            tr.cash -= dollars + f
            if p > 0:
                tr.last_px[ticker] = p
        elif side == "sell":
            tr.units[ticker] = tr.units.get(ticker, 0.0) - u
            tr.cash += dollars - f
    if tr.units.get(ticker, 0.0) <= 1e-12:
        tr.units.pop(ticker, None)
        tr.last_px.pop(ticker, None)


def booked_numbers(event: dict) -> dict:
    """What this event actually put in the book, for an exact reversal.

    Read off the event as stored (never re-derived from a fresh price), which is what
    makes the reversal exact even for a legacy event with odd numbers.
    """
    return {
        "side": str(event.get("side") or ""),
        "ticker": str(event.get("ticker") or ""),
        "units": as_finite(event.get("units"), 0.0),
        "price": as_finite(event.get("price"), 0.0),
        "fee": as_finite(event.get("cost"), 0.0),
    }


def _reverse_event(state: dict, event: dict) -> dict | None:
    """Undo an effective trade's cash/units. Returns the tranche dict, or None."""
    if not moves_book(event.get("status")):
        return None
    booked = booked_numbers(event)
    if booked["side"] not in TRADE_SIDES or not booked["ticker"]:
        return None
    raw = _tranche_or_none(state, str(event.get("sleeve") or ""), _tranche_index(event))
    if raw is None:
        return None
    tr = _as_tranche(raw)
    _apply_side(tr, booked["side"], booked["ticker"], booked["units"], booked["price"],
                booked["fee"], reverse=True)
    _dump_tranche(raw, tr)
    return raw


def _tranche_index(row: dict) -> int:
    try:
        return int(row.get("tranche"))
    except (TypeError, ValueError):
        return -1


def _same_numbers(event: dict, trade: dict) -> bool:
    """The event already carries these confirmed numbers."""
    if str(event.get("status") or "") not in (CONFIRMED, CONFIRMED_UNPLANNED):
        return False
    for a, b in ((event.get("units"), trade["units"]),
                 (event.get("price"), trade["price"]),
                 (event.get("cost"), trade["fee"])):
        av = as_finite(a)
        if av is None or abs(av - float(b)) > 1e-9:
            return False
    return True


def _find_target(ledger: list[dict], by_id: dict[str, int], row: dict, trade: dict) -> int | None:
    """Ledger position this broker line refers to, or None for an unplanned fill.

    Explicit wins: `correction_of` and `event_id` address one event directly. Otherwise
    match the natural key, preferring a still-open (presumed) event over a confirmed one
    so the normal confirmation path is unchanged.
    """
    explicit = str(row.get("correction_of") or "")
    if explicit:
        return by_id.get(explicit)

    own = str(row.get("event_id") or "")
    if own:
        hit = by_id.get(own)
        if hit is not None:
            return hit
        return None                      # a new event with a caller-supplied id

    if row.get("fill_seq") is not None:
        want = make_event_id(row, seq=int(row["fill_seq"]))
        return by_id.get(want)

    key = natural_key(row)
    open_hit = None
    confirmed_hit = None
    for i, event in enumerate(ledger):
        if natural_key(event) != key:
            continue
        status = str(event.get("status") or "")
        if status in OPEN_STATUSES and open_hit is None:
            open_hit = i
        elif status in (CONFIRMED, CONFIRMED_UNPLANNED) and confirmed_hit is None:
            confirmed_hit = i
    return open_hit if open_hit is not None else confirmed_hit


def apply_confirmations(state: dict, rows: list[dict]) -> dict:
    """Book the broker's fills into `state`. Returns a report dict.

    `rows` carry exec_date, sleeve, tranche, ticker, side, units, price, fee, and
    optionally event_id / correction_of / fill_seq. Mutates `state` only for accepted
    rows; a rejected row leaves the state exactly as it was.
    """
    ledger = list(state.get("ledger") or [])
    state["ledger"] = ledger
    by_id = index_by_event_id(state)
    report: list[dict] = []
    warnings: list[str] = []
    rejected: list[dict] = []

    for row in rows:
        key = natural_key(row)
        rec = {"key": key, "matched": False, "changed": False}

        errors = validate_event(row)
        if errors:
            rec.update(status=REJECTED, errors=errors,
                       units=as_finite(row.get("units")), price=as_finite(row.get("price")),
                       fee=as_finite(row.get("fee") if row.get("fee") is not None else row.get("cost")),
                       dollars=None)
            report.append(rec)
            rejected.append({"key": key, "errors": errors})
            warnings.append(f"rejected {key}: {'; '.join(errors)}")
            continue

        try:
            trade = normalized_trade(row)
        except InvalidNumber as e:                      # pragma: no cover - validate_event covers it
            rec.update(status=REJECTED, errors=[str(e)], units=None, price=None, fee=None, dollars=None)
            report.append(rec)
            rejected.append({"key": key, "errors": [str(e)]})
            warnings.append(f"rejected {key}: {e}")
            continue

        rec.update(units=trade["units"], price=trade["price"], fee=trade["fee"],
                   dollars=trade["dollars"])

        sleeve = str(row.get("sleeve") or "")
        k = _tranche_index(row)
        raw = _tranche_or_none(state, sleeve, k)
        if raw is None:
            msg = f"no tranche {sleeve}[{k}]"
            rec.update(status=REJECTED, errors=[msg])
            report.append(rec)
            rejected.append({"key": key, "errors": [msg]})
            warnings.append(f"rejected {key}: {msg}")
            continue

        pos = _find_target(ledger, by_id, row, trade)
        rec["matched"] = pos is not None

        if pos is None:
            # No plan for this line: a fill Lucas made that the sheet did not ask for.
            warnings.append(f"unplanned fill {key}: recorded as confirmed_unplanned")
            tr = _as_tranche(raw)
            _apply_side(tr, trade["side"], str(row.get("ticker")), trade["units"],
                        trade["price"], trade["fee"], reverse=False)
            _dump_tranche(raw, tr)
            new = _new_event(row, trade, CONFIRMED_UNPLANNED, by_id)
            ledger.append(new)
            by_id[new["event_id"]] = len(ledger) - 1
            rec.update(changed=True, status=CONFIRMED_UNPLANNED, cash_after=raw["cash"],
                       event_id=new["event_id"])
            report.append(rec)
            continue

        event = ledger[pos]
        eid = ensure_event_id(event)
        by_id[eid] = pos

        if _same_numbers(event, trade):
            rec.update(status=event.get("status"), event_id=eid)
            report.append(rec)
            continue

        status = str(event.get("status") or "")
        old_units, old_price = event.get("units"), event.get("price")

        if status in OPEN_STATUSES:
            # Confirming a presumed fill: reverse the estimate, book the real numbers,
            # and keep the estimate in the event's own revision trail.
            _reverse_event(state, event)
            tr = _as_tranche(raw)
            _apply_side(tr, trade["side"], str(row.get("ticker")), trade["units"],
                        trade["price"], trade["fee"], reverse=False)
            _dump_tranche(raw, tr)
            event.setdefault("revisions", []).append({
                "status": status, "units": old_units, "price": old_price,
                "cost": event.get("cost"), "dollars": event.get("dollars"),
            })
            event.update(units=trade["units"], price=trade["price"], cost=trade["fee"],
                         dollars=trade["dollars"], status=CONFIRMED)
            rec.update(changed=True, old_units=old_units, old_price=old_price,
                       status=CONFIRMED, cash_after=raw["cash"], event_id=eid)
            report.append(rec)
            continue

        if status in (CONFIRMED, CONFIRMED_UNPLANNED):
            # A correction of numbers already confirmed. Reverse exactly what was
            # booked, retire the event, append the correction (R-101).
            _reverse_event(state, event)
            tr = _as_tranche(raw)
            _apply_side(tr, trade["side"], str(row.get("ticker")), trade["units"],
                        trade["price"], trade["fee"], reverse=False)
            _dump_tranche(raw, tr)
            event["status"] = CORRECTED
            event["corrected_by"] = None                # filled in below
            new = _new_event(row, trade, CONFIRMED, by_id, correction_of=eid)
            event["corrected_by"] = new["event_id"]
            ledger.append(new)
            by_id[new["event_id"]] = len(ledger) - 1
            rec.update(changed=True, old_units=old_units, old_price=old_price,
                       status=CONFIRMED, cash_after=raw["cash"],
                       event_id=new["event_id"], correction_of=eid)
            report.append(rec)
            continue

        # cancelled / corrected / not_filled / noted: nothing is booked, so there is
        # nothing to reverse. Record the confirmation as a fresh event.
        tr = _as_tranche(raw)
        _apply_side(tr, trade["side"], str(row.get("ticker")), trade["units"],
                    trade["price"], trade["fee"], reverse=False)
        _dump_tranche(raw, tr)
        new = _new_event(row, trade, CONFIRMED, by_id, correction_of=eid)
        ledger.append(new)
        by_id[new["event_id"]] = len(ledger) - 1
        rec.update(changed=True, status=CONFIRMED, cash_after=raw["cash"],
                   event_id=new["event_id"], correction_of=eid,
                   note=f"previous event was {status}")
        report.append(rec)

    return {"report": report, "warnings": warnings, "rejected": rejected, "state": state}


def _new_event(row: dict, trade: dict, status: str, by_id: dict, correction_of: str | None = None) -> dict:
    """A ledger event with a unique deterministic id."""
    event = {
        "exec_date": str(row.get("exec_date") or row.get("date") or ""),
        "sleeve": str(row.get("sleeve") or ""),
        "tranche": _tranche_index(row),
        "side": trade["side"],
        "ticker": str(row.get("ticker") or ""),
        "units": trade["units"],
        "price": trade["price"],
        "dollars": trade["dollars"],
        "cost": trade["fee"],
        "status": status,
    }
    if row.get("planned"):
        event["planned"] = str(row["planned"])
    if correction_of:
        event["correction_of"] = correction_of
    supplied = str(row.get("event_id") or "")
    if supplied and supplied not in by_id:
        event["event_id"] = supplied
    else:
        seq = 0
        while make_event_id(event, seq=seq) in by_id:
            seq += 1
        event["event_id"] = make_event_id(event, seq=seq)
        if seq:
            event["fill_seq"] = seq
    return event


def cancel_events(state: dict, event_ids: list[str], *, reason: str | None = None) -> dict:
    """Reverse and retire events by id. Cancelling twice is a no-op (phase 1.1/1.3)."""
    by_id = index_by_event_id(state)
    ledger = state.get("ledger") or []
    done, missing, already = [], [], []
    for eid in event_ids:
        pos = by_id.get(str(eid))
        if pos is None:
            missing.append(str(eid))
            continue
        event = ledger[pos]
        if str(event.get("status") or "") not in EFFECTIVE_STATUSES:
            already.append(str(eid))
            continue
        _reverse_event(state, event)
        event.setdefault("revisions", []).append({
            "status": event.get("status"), "units": event.get("units"),
            "price": event.get("price"), "cost": event.get("cost"),
            "dollars": event.get("dollars"),
        })
        event["status"] = CANCELLED
        if reason:
            event["cancel_reason"] = str(reason)
        done.append(str(eid))
    return {"cancelled": done, "missing": missing, "already_inert": already, "state": state}


def report_lines(result: dict) -> list[str]:
    lines = ["exec_date sleeve tranche side ticker  units  price  $  fee  status  matched"]
    for r in result.get("report") or []:
        k = r["key"]
        units = 0.0 if r.get("units") is None else r["units"]
        price = 0.0 if r.get("price") is None else r["price"]
        dollars = 0.0 if r.get("dollars") is None else r["dollars"]
        fee = 0.0 if r.get("fee") is None else r["fee"]
        lines.append(
            f"{k[0]} {k[1]} {k[2]} {k[4]} {k[3]}  {units:.4f}  {price:.4f}  "
            f"{dollars:.2f}  {fee:.4f}  {r.get('status')}  {r['matched']}"
        )
        for err in r.get("errors") or []:
            lines.append(f"    REJECTED {err}")
    for w in result.get("warnings") or []:
        lines.append(f"WARN {w}")
    return lines
