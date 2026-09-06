"""Build a name -> Sleeve map from cfg (TASK-366 / TASK-386). Unknown names fail closed.

`cfg["sleeves"]` entries are either a known type name (`"stocks"`, `"etf"`; the sleeve is named after
its type) or a table `{"name": ..., "type": ..., "cost_bp": ...}` so two instances of one type can run
side by side (e.g. a second ETF sleeve with its own cost). Insertion order is the engine's order.
"""
from __future__ import annotations

from sleeves.etf_trend import EtfTrend
from sleeves.stocks_t20 import StocksT20

KNOWN = {
    "stocks": StocksT20,
    "etf": EtfTrend,
}
DEFAULT_NAMES = ["stocks", "etf"]
_DEFAULT_COST_KEY = {"stocks": "stock_cost_bp", "etf": "etf_cost_bp"}


def _instantiate(kind: str, cfg: dict, cost_bp=None):
    if kind not in KNOWN:
        known = ", ".join(sorted(KNOWN))
        raise KeyError(f"unknown sleeve {kind!r}; known: {known}")
    if cost_bp is None:
        cost_bp = cfg.get(_DEFAULT_COST_KEY.get(kind, ""))
    return KNOWN[kind](cost_bp=cost_bp)


def build(cfg: dict | None = None) -> dict:
    """`cfg.get("sleeves", ["stocks", "etf"])` -> `{name: Sleeve}`. Unknown type -> KeyError;
    duplicate name -> ValueError."""
    cfg = dict(cfg or {})
    entries = list(cfg.get("sleeves") or DEFAULT_NAMES)
    out: dict = {}
    for entry in entries:
        if isinstance(entry, str):
            name, kind, cost = entry, entry, None
        elif isinstance(entry, dict):
            kind = str(entry.get("type") or entry.get("name") or "")
            name = str(entry.get("name") or kind)
            cost = entry.get("cost_bp")
        else:
            raise TypeError(f"sleeve entry must be a name or a table, got {type(entry).__name__}")
        if name in out:
            raise ValueError(f"duplicate sleeve name {name!r}")
        inst = _instantiate(kind, cfg, cost)
        inst.name = name
        out[name] = inst
    return out
