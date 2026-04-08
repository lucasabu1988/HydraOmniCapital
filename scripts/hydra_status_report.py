#!/usr/bin/env python3
"""HYDRA System Status Report — SessionStart hook script.

Fetches live status from omnicapital.onrender.com and prints
a compact briefing for Claude Code context injection.
"""

import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

BASE_URL = "https://omnicapital.onrender.com"
TIMEOUT = 15  # seconds — Render cold start can be slow


def fetch_json(path):
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "HYDRA-StatusHook/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        return {"_error": f"Network error: {e.reason}"}
    except Exception as e:
        return {"_error": str(e)}


def format_currency(val):
    try:
        return f"${float(val):,.2f}"
    except (TypeError, ValueError):
        return str(val)


def format_pct(val):
    try:
        return f"{float(val):+.2f}%"
    except (TypeError, ValueError):
        return str(val)


def main():
    state = fetch_json("/api/state")
    ml = fetch_json("/api/ml")

    lines = []
    lines.append("HYDRA System Status Report")
    lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    # --- Cloud reachability ---
    if "_error" in state:
        lines.append(f"Cloud: UNREACHABLE ({state['_error']})")
        lines.append("  Render may be in cold start or down. Retry in 60s.")
        print("\n".join(lines))
        return

    lines.append("Cloud: ONLINE")

    # --- Engine status from /api/state.engine (authoritative) ---
    engine = state.get("engine", {}) if isinstance(state, dict) else {}
    portfolio = state.get("portfolio", {}) if isinstance(state, dict) else {}

    running = engine.get("running") is True
    heartbeat_age = engine.get("heartbeat_age_seconds")
    stale = heartbeat_age is None or (isinstance(heartbeat_age, (int, float)) and heartbeat_age > 300)

    if running and not stale:
        lines.append(f"Engine: RUNNING (hb {heartbeat_age:.0f}s)")
    elif running and stale:
        hb_str = f"{heartbeat_age:.0f}s" if isinstance(heartbeat_age, (int, float)) else "n/a"
        lines.append(f"Engine: STALE (hb {hb_str})")
    else:
        lines.append("Engine: STOPPED")

    lines.append(f"Cycle: {engine.get('cycles', '?')}")

    portfolio_value = portfolio.get("portfolio_value")
    if portfolio_value is None:
        portfolio_value = state.get("portfolio_value")
    if portfolio_value is not None:
        lines.append(f"Portfolio: {format_currency(portfolio_value)}")
        dd = portfolio.get("drawdown")
        daily = portfolio.get("daily_return")
        if dd is not None or daily is not None:
            lines.append(f"  DD: {format_pct(dd) if dd is not None else 'n/a'}  |  Daily: {format_pct(daily) if daily is not None else 'n/a'}")

    # --- Cash, regime, positions ---
    cash = portfolio.get("cash")
    if cash is None:
        cash = state.get("cash")
    regime = portfolio.get("regime", "unknown")
    position_details = state.get("position_details", [])

    lines.append(f"Regime: {regime}")
    if cash is not None:
        lines.append(f"Cash: {format_currency(cash)}")
    lines.append(f"Positions: {len(position_details)}")

    if position_details:
        lines.append("")
        for pos in position_details:
            ticker = pos.get("symbol", "?")
            pnl = pos.get("pnl_pct")
            entry = pos.get("entry_price")
            pnl_str = format_pct(pnl) if pnl is not None else "n/a"
            lines.append(f"  {ticker}: {pnl_str} (entry {format_currency(entry) if entry else '?'})")

    # --- ML interpretation snippet ---
    interpretation = ml.get("interpretation", "") if isinstance(ml, dict) else ""
    if interpretation and len(interpretation) > 20:
        # First 200 chars of interpretation
        snippet = interpretation[:200].replace("\n", " ").strip()
        lines.append("")
        lines.append(f"AI Analysis: {snippet}...")

    # --- Engine lifecycle info (from /api/state.engine) ---
    started_at = engine.get("started_at")
    restarts = engine.get("restarts") or []
    last_crash_error = engine.get("last_crash_error")
    if started_at or restarts or last_crash_error:
        lines.append("")
        if started_at:
            lines.append(f"Engine started: {started_at}")
        if restarts:
            lines.append(f"Restarts: {len(restarts)} (last: {restarts[-1]})")
        if last_crash_error:
            lines.append(f"Last crash: {last_crash_error[:120]}")

    print("\n".join(lines))


if __name__ == "__main__":
    import os, io
    # Suppress stderr to avoid Claude Code showing "error" label
    sys.stderr = io.StringIO()
    try:
        main()
    except Exception:
        print("HYDRA status check failed")
