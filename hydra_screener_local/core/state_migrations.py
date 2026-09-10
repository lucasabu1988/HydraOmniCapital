"""State schema migrations (TASK-360).

The first migration only fills missing keys and leaves `schema_version` at 1.
A bump is Claude's call. Do not import the engine.
"""
from __future__ import annotations

from collections.abc import Callable


class SchemaError(Exception):
    """Unknown or unreadable schema_version."""


def _fill_missing_v1(state: dict) -> dict:
    state.setdefault("interest", [])
    state.setdefault("dividends", [])
    state.setdefault("write_offs", [])
    state.setdefault("transfers", [])
    state.setdefault("ledger", [])
    state.setdefault("pending", [])
    for sleeve in (state.get("sleeves") or {}).values():
        for tr in sleeve.get("tranches") or []:
            tr.setdefault("stale", {})
            tr.setdefault("units", {})
            tr.setdefault("last_px", {})
            tr.setdefault("cash", 0.0)
    if state.get("schema_version") is None:
        state["schema_version"] = 1
    return state


MIGRATIONS: dict[int, Callable[[dict], dict]] = {
    1: _fill_missing_v1,
}


def migrate(state: dict) -> dict:
    """Idempotent. Unknown version -> SchemaError. Does not bump v1."""
    if not isinstance(state, dict):
        raise SchemaError("state is not a dict")
    raw = state.get("schema_version", 1)
    try:
        ver = int(raw)
    except (TypeError, ValueError) as e:
        raise SchemaError(f"schema_version {raw!r} is not an int") from e
    if ver not in MIGRATIONS:
        known = ", ".join(str(k) for k in sorted(MIGRATIONS))
        raise SchemaError(f"unknown schema_version {ver}; known: {known}")
    return MIGRATIONS[ver](state)
