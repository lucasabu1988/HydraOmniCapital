"""Build a name -> Sleeve map from cfg (TASK-366). Unknown names fail closed."""
from __future__ import annotations

from sleeves.etf_trend import EtfTrend
from sleeves.stocks_t20 import StocksT20

KNOWN = {
    "stocks": StocksT20,
    "etf": EtfTrend,
}
DEFAULT_NAMES = ["stocks", "etf"]


def build(cfg: dict | None = None) -> dict:
    """`cfg.get("sleeves", ["stocks", "etf"])` -> `{name: Sleeve}`. Unknown name -> KeyError."""
    cfg = dict(cfg or {})
    names = list(cfg.get("sleeves") or DEFAULT_NAMES)
    out = {}
    for name in names:
        if name not in KNOWN:
            known = ", ".join(sorted(KNOWN))
            raise KeyError(f"unknown sleeve {name!r}; known: {known}")
        cls = KNOWN[name]
        if name == "stocks":
            inst = cls(cost_bp=cfg.get("stock_cost_bp"))
        elif name == "etf":
            inst = cls(cost_bp=cfg.get("etf_cost_bp"))
        else:
            inst = cls()
        out[name] = inst
    return out
