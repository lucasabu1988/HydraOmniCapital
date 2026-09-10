"""The canonical ledger event model (audit phase 1). Pure; does not import the engine.

One projection, one set of rules. Before this module the dashboard counted only
`filled` (so a confirmed fill vanished from cost basis and P&L, repro R-108), the
journal counted `filled` and `confirmed` but not `confirmed_unplanned`, and
`state_check` / `reconcile` / `core.dividends` each carried their own literal set.
Everything now asks `moves_book()`.

Trade lifecycle
---------------
    presumed   the engine booked it at the t+1 close from an estimate; the broker
               has not confirmed it. Legacy states wrote this as "filled".
    confirmed  the broker's own numbers, as entered through confirm_fills.py.
    corrected  superseded by a later event whose `correction_of` points at it.
               Inert: the correction event carries the numbers now.
    cancelled  never executed; the booked effect has been reversed.
    rejected   refused at the door (bad units/price/fee/side). Never booked, so
               it never reaches the ledger; it is reported back to the caller.

`moves_book(status)` is the single answer to "does this event change cash and
units". An unknown status is inert and reported, never assumed effective.
"""
from __future__ import annotations

import hashlib

from core.numbers import (
    InvalidNumber,
    is_finite_money,
    is_finite_price,
    is_valid_units,
    require_finite_money,
    require_finite_price,
    require_valid_units,
)

# ------------------------------------------------------------------ lifecycle
PRESUMED = "presumed"
CONFIRMED = "confirmed"
CONFIRMED_UNPLANNED = "confirmed_unplanned"
CORRECTED = "corrected"
CANCELLED = "cancelled"
REJECTED = "rejected"

# Written by core.portfolio_engine before this module existed. `filled` is a
# presumed fill; both stay readable forever so live states never need a rewrite.
LEGACY_PRESUMED = "filled"
LEGACY_NOT_FILLED = "not_filled"
LEGACY_NOTED = "noted"

#: statuses whose cash/units effect is in the book
EFFECTIVE_STATUSES = frozenset({LEGACY_PRESUMED, PRESUMED, CONFIRMED, CONFIRMED_UNPLANNED})
#: booked but the broker has not confirmed the numbers
PRESUMED_STATUSES = frozenset({LEGACY_PRESUMED, PRESUMED})
#: the broker's own numbers
CONFIRMED_STATUSES = frozenset({CONFIRMED, CONFIRMED_UNPLANNED})
#: statuses that are recorded but move nothing
INERT_STATUSES = frozenset({LEGACY_NOT_FILLED, LEGACY_NOTED, CORRECTED, CANCELLED, REJECTED})
KNOWN_STATUSES = EFFECTIVE_STATUSES | INERT_STATUSES

TRADE_SIDES = frozenset({"buy", "sell"})
#: sides the engine records as instructions rather than trades
NOTE_SIDES = frozenset({"park", "hold_no_price"})
TRANSFER_SIDES = frozenset({"transfer_in", "transfer_out"})
KNOWN_SIDES = TRADE_SIDES | NOTE_SIDES | TRANSFER_SIDES

CASH_TICKERS = frozenset({"CASH", "TBILL"})
UNITS_EPS = 1e-12


def moves_book(status) -> bool:
    """The one definition of "this event's cash and units are in the book"."""
    return str(status or "") in EFFECTIVE_STATUSES


def is_known_status(status) -> bool:
    return str(status or "") in KNOWN_STATUSES


def is_trade(event) -> bool:
    """An effective buy/sell of a real ticker — what a lots/cost-basis walk consumes."""
    if not moves_book(event.get("status")):
        return False
    if str(event.get("side") or "") not in TRADE_SIDES:
        return False
    ticker = str(event.get("ticker") or "")
    return bool(ticker) and ticker not in CASH_TICKERS


def effective_trades(state: dict | None) -> list[dict]:
    """Every ledger event that moves units of a real ticker, in ledger order."""
    return [e for e in ((state or {}).get("ledger") or []) if is_trade(e)]


# ------------------------------------------------------------------ identity
def natural_key(row: dict) -> tuple:
    """(exec_date, sleeve, tranche, ticker, side) — how a broker line matches a plan."""
    return (
        str(row.get("exec_date") or row.get("date") or ""),
        str(row.get("sleeve") or ""),
        _int(row.get("tranche")),
        str(row.get("ticker") or ""),
        str(row.get("side") or ""),
    )


def make_event_id(row: dict, *, seq: int = 0) -> str:
    """Deterministic id for an event. Same natural key + same `seq` -> same id.

    Idempotency depends on this being a pure function of the event's identity, so
    replaying the same broker file cannot mint a second id for the same fill.
    """
    key = natural_key(row)
    payload = "|".join([*(str(p) for p in key), str(row.get("planned") or ""), str(int(seq))])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def ensure_event_id(event: dict, *, seq: int = 0) -> str:
    """Return the event's id, minting and storing a deterministic one if absent.

    Live states written before phase 1 have no `event_id`; this backfills them
    without changing a single number.
    """
    have = str(event.get("event_id") or "")
    if have:
        return have
    new = make_event_id(event, seq=seq)
    event["event_id"] = new
    return new


def index_by_event_id(state: dict) -> dict[str, int]:
    """event_id -> ledger position, backfilling ids for pre-phase-1 events.

    `seq` disambiguates events that share a natural key (two partial fills of one
    order), so every ledger row ends up with its own id.
    """
    ledger = state.get("ledger") or []
    seen: dict[tuple, int] = {}
    out: dict[str, int] = {}
    for i, event in enumerate(ledger):
        key = natural_key(event)
        seq = seen.get(key, 0)
        seen[key] = seq + 1
        eid = str(event.get("event_id") or "")
        if not eid:
            eid = ensure_event_id(event, seq=seq)
        out[eid] = i
    return out


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------ validation
def validate_event(row: dict, *, require_price: bool = True) -> list[str]:
    """Errors that must stop this row from reaching the book. Empty list = accept.

    Phase 1.5: negative units, non-finite prices, prices <= 0, non-finite dollars,
    non-finite fees, unknown side or status.
    """
    errors: list[str] = []
    side = str(row.get("side") or "")
    if side not in KNOWN_SIDES:
        errors.append(f"unknown side {side!r} (known: {', '.join(sorted(KNOWN_SIDES))})")

    status = row.get("status")
    if status is not None and not is_known_status(status):
        errors.append(f"unknown status {str(status)!r}")

    if side in TRADE_SIDES:
        units = row.get("units")
        if not is_valid_units(units):
            errors.append(f"units must be a finite number > 0, got {units!r}")

        price = row.get("price")
        if require_price or price is not None:
            if not is_finite_price(price):
                errors.append(f"price must be finite and > 0, got {price!r}")

        if row.get("dollars") is not None and not is_finite_money(row.get("dollars")):
            errors.append(f"dollars must be finite, got {row.get('dollars')!r}")

        fee = row.get("fee") if row.get("fee") is not None else row.get("cost")
        if fee is not None and not is_finite_money(fee):
            errors.append(f"fee must be finite, got {fee!r}")
        elif fee is not None and float(fee) < 0.0:
            errors.append(f"fee must be >= 0, got {fee!r}")

        if not str(row.get("ticker") or ""):
            errors.append("ticker is empty")

    return errors


def normalized_trade(row: dict) -> dict:
    """Validated numbers for a buy/sell. Raises InvalidNumber on anything unusable."""
    side = str(row.get("side") or "")
    if side not in TRADE_SIDES:
        raise InvalidNumber(f"not a trade side: {side!r}")
    units = require_valid_units(row.get("units"), "units")
    price = require_finite_price(row.get("price"), "price")
    raw_fee = row.get("fee") if row.get("fee") is not None else row.get("cost")
    fee = 0.0 if raw_fee is None else require_finite_money(raw_fee, "fee")
    if fee < 0.0:
        raise InvalidNumber(f"fee must be >= 0, got {fee!r}")
    dollars = require_finite_money(units * price, "dollars")
    return {"side": side, "units": units, "price": price, "fee": fee, "dollars": dollars}


# ------------------------------------------------------------------ invariants
class Violation:
    """One broken invariant. Truthy so `if violations:` reads naturally."""

    __slots__ = ("code", "message")

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message

    def __repr__(self) -> str:
        return f"Violation({self.code!r}, {self.message!r})"

    def __eq__(self, other) -> bool:
        return isinstance(other, Violation) and (self.code, self.message) == (other.code, other.message)


def check_invariants(state: dict) -> list[Violation]:
    """Phase 1.6. Cheap, pure, and safe to run before every write.

    - units per ticker are never negative
    - every cash balance is finite
    - every effective event's numbers are finite
    - every event_id is counted exactly once
    """
    out: list[Violation] = []

    for sleeve, block in (state.get("sleeves") or {}).items():
        for i, tr in enumerate((block or {}).get("tranches") or []):
            cash = tr.get("cash")
            if not is_finite_money(cash):
                out.append(Violation("cash_not_finite", f"{sleeve}[{i}] cash={cash!r}"))
            for ticker, units in (tr.get("units") or {}).items():
                if not is_finite_money(units):
                    out.append(Violation("units_not_finite", f"{sleeve}[{i}] {ticker} units={units!r}"))
                elif float(units) < -UNITS_EPS:
                    out.append(Violation("units_negative", f"{sleeve}[{i}] {ticker} units={units!r}"))
            for ticker, px in (tr.get("last_px") or {}).items():
                if not is_finite_price(px):
                    out.append(Violation("last_px_invalid", f"{sleeve}[{i}] {ticker} last_px={px!r}"))

    counts: dict[str, int] = {}
    for i, event in enumerate(state.get("ledger") or []):
        eid = str(event.get("event_id") or "")
        if eid:
            counts[eid] = counts.get(eid, 0) + 1
        status = event.get("status")
        if not is_known_status(status):
            out.append(Violation("status_unknown", f"ledger[{i}] status={str(status)!r}"))
        if not moves_book(status):
            continue
        side = str(event.get("side") or "")
        if side not in KNOWN_SIDES:
            out.append(Violation("side_unknown", f"ledger[{i}] side={side!r}"))
        if side not in TRADE_SIDES:
            continue
        if not is_valid_units(event.get("units"), allow_zero=True):
            out.append(Violation("event_units_invalid", f"ledger[{i}] units={event.get('units')!r}"))
        if not is_finite_price(event.get("price")):
            out.append(Violation("event_price_invalid", f"ledger[{i}] price={event.get('price')!r}"))
        if event.get("dollars") is not None and not is_finite_money(event.get("dollars")):
            out.append(Violation("event_dollars_invalid", f"ledger[{i}] dollars={event.get('dollars')!r}"))
        if event.get("cost") is not None and not is_finite_money(event.get("cost")):
            out.append(Violation("event_fee_invalid", f"ledger[{i}] cost={event.get('cost')!r}"))

    for eid, n in sorted(counts.items()):
        if n > 1:
            out.append(Violation("event_id_duplicated", f"event_id {eid} appears {n} times"))

    return out


def format_violations(violations: list[Violation]) -> str:
    if not violations:
        return "ledger invariants: clean (0 violations)"
    lines = [f"ledger invariants: {len(violations)} violation(s)"]
    for v in violations:
        lines.append(f"  {v.code:<22} {v.message}")
    return "\n".join(lines)
