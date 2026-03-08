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

    # --- Engine status from /api/ml ---
    kpis = ml.get("kpis", {}) if isinstance(ml, dict) else {}
    engine_running = kpis.get("engine_running", "unknown")
    current_cycle = kpis.get("current_cycle", "?")
    portfolio_value = kpis.get("portfolio_value")

    lines.append(f"Engine: {'RUNNING' if engine_running else 'STOPPED'}")
    lines.append(f"Cycle: {current_cycle}")
    if portfolio_value is not None:
        lines.append(f"Portfolio: {format_currency(portfolio_value)}")

    # --- Positions from /api/state ---
    positions = state.get("positions", {})
    cash = state.get("cash")
    regime = state.get("regime", "unknown")

    lines.append(f"Regime: {regime}")
    if cash is not None:
        lines.append(f"Cash: {format_currency(cash)}")
    lines.append(f"Positions: {len(positions)}")

    if positions:
        lines.append("")
        for ticker, pos in positions.items():
            pnl = pos.get("unrealized_pnl_pct")
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

    # --- Recent cycle log ---
    log_entries = ml.get("log_entries", []) if isinstance(ml, dict) else []
    if log_entries:
        last = log_entries[-1] if isinstance(log_entries[-1], dict) else {}
        cycle_num = last.get("cycle", "?")
        cycle_return = last.get("return_pct")
        lines.append("")
        lines.append(f"Last Cycle #{cycle_num}: {format_pct(cycle_return) if cycle_return is not None else 'n/a'}")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
