"""TASK-352 — refuse to plan on bad data.

Pure function over already-fetched frames (no network). `daily.py` / `portfolio_v9.py`
print the table and stop on a hard fail unless `--force`.
"""
from __future__ import annotations

import os
import pandas as pd

from config import SECTOR_UNKNOWN_MAX_SHARE, V9
from core.portfolio_engine import STATE_SCHEMA
from data.sectors import sector_degraded_message
from utils.trading_calendar import first_bar_after, last_nyse_session_on_or_before

KNOWN_SCHEMA_VERSIONS = {STATE_SCHEMA}
PRINT_SHARE_WARN = 0.90
ETF_UNIVERSE = list(V9["etf_universe"])


def last_bar_date(frame) -> str | None:
    if frame is None or getattr(frame, "empty", True) or len(frame) == 0:
        return None
    return str(pd.Timestamp(frame.index[-1]).normalize().date())


def last_weekday_session(asof) -> str:
    """Last regular NYSE session on or before `asof` (weekends and holidays skipped)."""
    return last_nyse_session_on_or_before(asof)


def _row(check: str, status: str, detail: str) -> dict:
    return {"check": check, "status": status, "detail": detail}


def evaluate(
    prices: pd.DataFrame | None,
    etf: pd.DataFrame | None,
    irx: pd.Series | pd.DataFrame | None,
    *,
    state: dict | None = None,
    ranking: pd.DataFrame | None = None,
    asof=None,
    last_session: str | None = None,
    backup_dir: str | None = None,
    etf_universe: list[str] | None = None,
) -> dict:
    """Run every check. `asof` is the wall-clock (or test clock) used to name the
    last NYSE session when `last_session` is omitted."""
    rows: list[dict] = []
    names = list(etf_universe or ETF_UNIVERSE)

    stock_d = last_bar_date(prices)
    etf_d = last_bar_date(etf)
    if irx is None or len(irx) == 0:
        irx_d = None
    else:
        irx_d = last_bar_date(irx)

    session = last_session or last_weekday_session(asof if asof is not None else pd.Timestamp.now())
    bars = {"stocks": stock_d, "etf": etf_d, "^IRX": irx_d}
    if None in bars.values():
        missing = [k for k, v in bars.items() if v is None]
        rows.append(_row("last bars", "HARD", f"missing frame(s): {', '.join(missing)}"))
    elif len(set(bars.values())) != 1:
        rows.append(_row(
            "last bars", "HARD",
            f"stocks {stock_d}  etf {etf_d}  ^IRX {irx_d} — must match",
        ))
    elif stock_d != session:
        rows.append(_row(
            "last bars", "HARD",
            f"last bar {stock_d} != last NYSE session {session} (stale yfinance would price yesterday)",
        ))
    else:
        rows.append(_row("last bars", "OK", f"stocks/etf/^IRX = {stock_d} = session"))

    if prices is None or len(prices) == 0:
        rows.append(_row("universe print share", "HARD", "no stock prices"))
        share = 0.0
    else:
        last = prices.iloc[-1]
        share = float(pd.to_numeric(last, errors="coerce").notna().mean()) if len(last) else 0.0
        if share < PRINT_SHARE_WARN:
            rows.append(_row(
                "universe print share", "WARN",
                f"{share:.0%} with a print on {stock_d} (threshold {PRINT_SHARE_WARN:.0%})",
            ))
        else:
            rows.append(_row("universe print share", "OK", f"{share:.0%} with a print on {stock_d}"))

    if etf is None or len(etf) == 0:
        rows.append(_row("ETFs present", "HARD", f"0/{len(names)} — empty ETF frame"))
        n_ok = 0
    else:
        last_e = etf.iloc[-1]
        present = []
        missing_etf = []
        for t in names:
            p = float("nan")
            if t in etf.columns:
                p = pd.to_numeric(last_e.get(t), errors="coerce")
            if pd.notna(p):
                present.append(t)
            else:
                missing_etf.append(t)
        n_ok = len(present)
        if n_ok != len(names):
            rows.append(_row("ETFs present", "HARD", f"{n_ok}/{len(names)} missing {missing_etf}"))
        else:
            rows.append(_row("ETFs present", "OK", f"{n_ok}/{len(names)}"))

    if ranking is None:
        rows.append(_row("sector-unknown", "SKIP", "no ranking"))
    else:
        msg = sector_degraded_message(ranking)
        if msg:
            rows.append(_row("sector-unknown", "WARN", msg))
        else:
            rows.append(_row(
                "sector-unknown", "OK",
                f"Other share in 2n pool <= {SECTOR_UNKNOWN_MAX_SHARE:.0%}",
            ))

    pending = (state or {}).get("pending") or []
    today = stock_d or (str(pd.Timestamp(asof).date()) if asof is not None else None)
    if not pending:
        rows.append(_row("pending age", "SKIP", "no pending"))
    elif prices is None or len(prices) == 0 or not today:
        rows.append(_row("pending age", "WARN", "pending set but no price calendar"))
    else:
        planned = pending[0].get("planned")
        nxt = first_bar_after(prices.index, planned) if planned else None
        sessions = 0
        if planned:
            idx = pd.DatetimeIndex(prices.index).normalize()
            sessions = int(((idx > pd.Timestamp(planned).normalize())
                            & (idx <= pd.Timestamp(today).normalize())).sum())
        if sessions > 1:
            rows.append(_row(
                "pending age", "WARN",
                f"planned {planned}, {sessions} sessions behind today={today}"
                + (f" (t+1 was bar {nxt})" if nxt is not None else ""),
            ))
        else:
            rows.append(_row("pending age", "OK", f"planned {planned}, {sessions} session(s) behind"))

    env_dir = backup_dir if backup_dir is not None else os.environ.get("HYDRA_BACKUP_DIR")
    if not env_dir:
        rows.append(_row("HYDRA_BACKUP_DIR", "WARN", "unset — state/ backup stays on the same disk"))
    else:
        rows.append(_row("HYDRA_BACKUP_DIR", "OK", env_dir))

    if state is None:
        rows.append(_row("schema_version", "SKIP", "no state yet"))
    else:
        ver = state.get("schema_version")
        if ver not in KNOWN_SCHEMA_VERSIONS:
            rows.append(_row(
                "schema_version", "HARD",
                f"{ver!r} not in {sorted(KNOWN_SCHEMA_VERSIONS)}",
            ))
        else:
            rows.append(_row("schema_version", "OK", f"schema_version={ver}"))

    hard = any(r["status"] == "HARD" for r in rows)
    warn = any(r["status"] == "WARN" for r in rows)
    return {
        "ok": not hard,
        "hard": hard,
        "warn": warn,
        "rows": rows,
        "session": session,
        "print_share": share,
        "etfs_ok": n_ok,
    }


def format_table(result: dict) -> str:
    rows = result.get("rows") or []
    width = max((len(r["check"]) for r in rows), default=8)
    lines = ["[v9] preflight"]
    for r in rows:
        lines.append(f"  {r['check']:<{width}}  {r['status']:<4}  {r['detail']}")
    if result.get("hard"):
        lines.append("[v9] preflight HARD fail")
    return "\n".join(lines)


def raise_if_hard(result: dict, force: bool = False) -> None:
    if result.get("hard") and not force:
        raise SystemExit("preflight hard fail; pass --force to plan anyway")
