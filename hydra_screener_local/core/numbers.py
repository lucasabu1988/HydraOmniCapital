"""Central numeric validators for the live book (audit phase 2).

Every monetary amount, price, unit count, weight and fee that reaches the ledger,
the engine or an instruction sheet goes through here. Two rules:

1. A value is either valid or it is an error. `value or 0.0` turns NaN into a
   silent zero and has already produced a NaN cash balance (repro R-102) and a
   -inf one (R-105); it is banned on the execution path.
2. Missing data fails closed. `require_*` raises; the `is_*` predicates are for
   callers that build a structured error instead.
"""
from __future__ import annotations

import math

__all__ = [
    "InvalidNumber",
    "is_finite",
    "is_finite_money",
    "is_finite_price",
    "is_valid_units",
    "is_valid_weight",
    "as_finite",
    "require_finite_money",
    "require_finite_price",
    "require_valid_units",
    "require_valid_weight",
    "weights_sum_to_one",
    "WEIGHT_SUM_TOL",
]

WEIGHT_SUM_TOL = 1e-9


class InvalidNumber(ValueError):
    """A value that must be finite (and in range) is not."""


def _coerce(value) -> float | None:
    """float(value) or None. Never raises, never returns NaN/inf."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def is_finite(value) -> bool:
    """True for a real, finite number. False for None, NaN, +/-inf, bool, str junk."""
    return _coerce(value) is not None


def is_finite_money(value) -> bool:
    """A dollar amount: finite, any sign (cash can be short, P&L can be negative)."""
    return _coerce(value) is not None


def is_finite_price(value) -> bool:
    """An executable price: finite and strictly positive."""
    v = _coerce(value)
    return v is not None and v > 0.0


def is_valid_units(value, *, allow_zero: bool = False) -> bool:
    """A share/unit count: finite and non-negative. Side carries the direction, never the sign."""
    v = _coerce(value)
    if v is None or v < 0.0:
        return False
    return True if allow_zero else v > 0.0


def is_valid_weight(value) -> bool:
    """A portfolio weight: finite, in [0, 1]. Shorts are not part of v9."""
    v = _coerce(value)
    return v is not None and 0.0 <= v <= 1.0


def as_finite(value, default=None):
    """`value` as a finite float, else `default`. For display and reports only.

    Do not use this to repair an execution input: use `require_*` there so a bad
    value stops the run instead of becoming a plausible-looking number.
    """
    v = _coerce(value)
    return default if v is None else v


def require_finite_money(value, what: str = "amount") -> float:
    v = _coerce(value)
    if v is None:
        raise InvalidNumber(f"{what} is not a finite number: {value!r}")
    return v


def require_finite_price(value, what: str = "price") -> float:
    v = _coerce(value)
    if v is None:
        raise InvalidNumber(f"{what} is not a finite number: {value!r}")
    if v <= 0.0:
        raise InvalidNumber(f"{what} must be > 0, got {v!r}")
    return v


def require_valid_units(value, what: str = "units", *, allow_zero: bool = False) -> float:
    v = _coerce(value)
    if v is None:
        raise InvalidNumber(f"{what} is not a finite number: {value!r}")
    if v < 0.0:
        raise InvalidNumber(f"{what} must be >= 0, got {v!r}")
    if v == 0.0 and not allow_zero:
        raise InvalidNumber(f"{what} must be > 0, got {v!r}")
    return v


def require_valid_weight(value, what: str = "weight") -> float:
    v = _coerce(value)
    if v is None:
        raise InvalidNumber(f"{what} is not a finite number: {value!r}")
    if not (0.0 <= v <= 1.0):
        raise InvalidNumber(f"{what} must be in [0, 1], got {v!r}")
    return v


def weights_sum_to_one(weights, *, tol: float = WEIGHT_SUM_TOL) -> bool:
    """Every weight valid and the total 1.0 within `tol` (documented tolerance, phase 8.3)."""
    values = list(weights.values()) if hasattr(weights, "values") else list(weights)
    if not values:
        return False
    total = 0.0
    for w in values:
        v = _coerce(w)
        if v is None or v < 0.0 or v > 1.0:
            return False
        total += v
    return abs(total - 1.0) <= tol
