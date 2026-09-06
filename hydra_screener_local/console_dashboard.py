#!/usr/bin/env python
"""
Console Execution Dashboard for HYDRA (local, rich terminal UI).

No HTML/GUI. Pure console. Designed to be left running or called
periodically to monitor "execution" state:

- Latest screener run (regime, rationale, exact recommended list from hybrid)
- Pillar multipliers
- Recent cycles + live PnL tracker status (from portfolio_cycles.xlsx)
- Key artifacts and next-action hints

Usage:
    python console_dashboard.py                    # plain text (default, reliable)
    python console_dashboard.py --watch --interval 30
    python console_dashboard.py --rich             # fancy Rich layout (optional)

After `pip install -e .` (or from the package):
    hydra-console
"""

# The rich imports below are optional (RICH_AVAILABLE); the annotations that name
# Panel/Table/Layout are evaluated lazily so this module still imports without rich.
# Without this, `import console_dashboard` raised NameError on a machine (or a wheel
# install) that had no rich — the fallback the module advertises never worked.
from __future__ import annotations

import argparse
import json
import sys
import time

# Consolas Windows usan cp1252 por defecto y rompen con bullets/emojis UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# Rich is optional — plain-text rendering is the default; --rich uses it if installed
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.layout import Layout
    from rich.live import Live
    from rich.text import Text
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    Console = None

# Data locations (same conventions as live_watcher / generate_html_dashboard)
PINE_SUMMARY = ROOT / "pine" / "hydra_last_summary.json"
HISTORY_DIR = ROOT / "history"
EXCEL_PATH = ROOT / "backtest" / "portfolio_cycles.xlsx"


def load_latest_summary():
    """Load the rich hybrid summary (preferred) or fall back to latest history JSON."""
    candidates = [
        PINE_SUMMARY,
        *sorted(HISTORY_DIR.glob("*.json"), reverse=True)[:3],
    ]
    for p in candidates:
        if p and p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data, p
            except Exception:
                continue
    return None, None


def load_recent_cycles(n: int = 6):
    """Load last N cycles from the dynamic PnL tracker."""
    if not EXCEL_PATH.exists():
        return pd.DataFrame()
    try:
        xls = pd.ExcelFile(EXCEL_PATH)
        if "Cycle_Summaries" not in xls.sheet_names:
            return pd.DataFrame()
        df = pd.read_excel(xls, sheet_name="Cycle_Summaries")
        if df.empty:
            return df
        df = df.sort_values("start_date", ascending=False).head(n).iloc[::-1]
        return df
    except Exception:
        return pd.DataFrame()


def format_regime_panel(data: dict) -> Panel:
    regime = data.get("regime", {})
    rtype = regime.get("type", "UNKNOWN")
    score = regime.get("score", 0.0)
    special = ", ".join(regime.get("special_modes", [])) or "—"
    rationale = data.get("rationale", "—")

    color = {
        "STRONG": "green",
        "MODERATE": "yellow",
        "CAUTIOUS": "orange1",
        "WEAK": "red",
    }.get(rtype, "white")

    text = Text()
    text.append("Regime: ", style="bold")
    text.append(f"{rtype}", style=f"bold {color}")
    text.append(f"  (score: {score:.3f})\n")
    text.append(f"Special: {special}\n")
    text.append(f"Rationale: {rationale}", style="dim")

    return Panel(text, title="[bold]Latest Execution", border_style=color, box=box.ROUNDED)


def format_pillars_table(data: dict) -> Table:
    pillars = data.get("pillars", {})
    table = Table(title="Pillar Multipliers", box=box.SIMPLE, show_header=True)
    table.add_column("Pillar", style="cyan")
    table.add_column("Multiplier", justify="right")
    table.add_column("Tilt", justify="center")

    for name, mult in pillars.items():
        if mult >= 1.08:
            tilt = "++"
            style = "green"
        elif mult > 1.0:
            tilt = "+"
            style = "green"
        elif mult < 0.92:
            tilt = "--"
            style = "red"
        elif mult < 1.0:
            tilt = "-"
            style = "red"
        else:
            tilt = "="
            style = "dim"
        table.add_row(name, f"{mult:.3f}x", tilt, style=style)
    return table


def format_recommended_table(data: dict) -> Table:
    recs = set(data.get("recommended_tickers", []))
    top = data.get("top_details", [])

    table = Table(
        title=f"Recommended Execution List (showing all {len(recs)})",
        box=box.MINIMAL_DOUBLE_HEAD,
    )
    table.add_column("Rank", justify="right", style="dim", width=4)
    table.add_column("Ticker", style="bold", width=6)
    table.add_column("Composite", justify="right", width=8)
    table.add_column("Momentum", justify="right", width=7)
    table.add_column("Strict", justify="center", width=5)
    table.add_column("Rec?", justify="center", width=4)

    for item in top:  # show all (usually 15)
        ticker = item.get("ticker", "?")
        is_rec = ticker in recs
        rec_badge = "[green]✓[/green]" if is_rec else "[dim]—[/dim]"
        strict_badge = "[green]✓[/green]" if item.get("passes_strict") else "[dim]—[/dim]"

        table.add_row(
            str(item.get("rank", "")),
            ticker,
            f"{item.get('composite', 0):.4f}",
            f"{item.get('momentum', 0):.4f}",
            strict_badge,
            rec_badge,
        )
    return table


def format_cycles_table(df: pd.DataFrame) -> Table:
    if df.empty:
        t = Table(title="Cycle Tracker (no data yet)")
        t.add_row("[dim]Run log_cycle_positions or daily.py to start tracking[/dim]")
        return t

    table = Table(title="Recent Cycles / Execution PnL", box=box.SIMPLE)
    table.add_column("Cycle", justify="right")
    table.add_column("Start")
    table.add_column("Tickers", style="cyan")
    table.add_column("Cycle PnL %", justify="right")
    table.add_column("Notes", style="dim")

    for _, row in df.iterrows():
        start = pd.to_datetime(row.get("start_date")).strftime("%Y-%m-%d") if pd.notna(row.get("start_date")) else "?"
        tickers = str(row.get("tickers", ""))[:35]
        pnl = row.get("cycle_pnl_pct")
        pnl_str = f"{pnl:.2f}%" if pd.notna(pnl) else "—"
        notes = str(row.get("notes", ""))[:25] or "—"
        table.add_row(str(int(row.get("cycle_id", 0))), start, tickers, pnl_str, notes)
    return table


def build_dashboard(data: dict, cycles_df: pd.DataFrame) -> Layout:
    """Build a rich Layout for the full console dashboard."""
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main"),
        Layout(name="footer", size=14),  # increased to fit cycles + guide
    )
    layout["main"].split_row(
        Layout(name="left"),
        Layout(name="right", ratio=2),
    )

    # Header
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date = data.get("date", "unknown") if data else "no data"
    header_text = Text(f"HYDRA EXECUTION DASHBOARD  •  {now}  •  Last Run: {date}", style="bold blue")
    layout["header"].update(Panel(header_text, box=box.MINIMAL))

    if not data:
        layout["left"].update(Panel("[red]No summary data found.[/red]\nRun daily.py or the screener first.", title="Error"))
        layout["right"].update(Panel(str(cycles_df.head(3)) if not cycles_df.empty else "No cycle data", title="Cycles"))
        return layout

    # Left column: regime + pillars
    regime_panel = format_regime_panel(data)
    pillars = format_pillars_table(data)
    left = Layout()
    left.split_column(
        Layout(regime_panel, name="regime", size=7),
        Layout(Panel(pillars, box=box.ROUNDED), name="pillars"),
    )
    layout["left"].update(left)

    # Right: recommended list (main execution artifact)
    rec_table = format_recommended_table(data)
    layout["right"].update(Panel(rec_table, box=box.ROUNDED))

    # Footer: cycles + actions + interpretation guide
    cycles_table = format_cycles_table(cycles_df)
    actions = Text()
    actions.append("Next actions:\n", style="bold")
    actions.append("  • hydra-daily          (full run + artifacts)\n")
    actions.append("  • hydra-refresh        (update live PnL in Excel)\n")
    actions.append("  • hydra-watch --interval 60 --refresh-pnl\n")
    actions.append("  • python console_dashboard.py --watch\n")
    actions.append("\nArtifacts: pine/watchlist.txt + pine/hydra_last_summary.json\n")
    actions.append(f"PnL tracker: {EXCEL_PATH} (open in Excel for live formulas)")

    footer = Layout()
    footer.split_row(
        Layout(Panel(cycles_table, title="Execution History", box=box.ROUNDED), ratio=3),
        Layout(Panel(actions, title="Quick Commands", box=box.ROUNDED), ratio=2),
    )
    layout["footer"].update(footer)

    return layout


def render_plain(data: dict, cycles_df: pd.DataFrame):
    """Reliable plain-text console dashboard. Always shows full data, no fancy rendering issues."""
    print("\n" + "=" * 75)
    print("HYDRA LOCAL EXECUTION DASHBOARD")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 75)

    if not data:
        print("\n[ERROR] No summary data found. Run the screener (daily.py) first.")
        print("=" * 75 + "\n")
        return

    # === Regime & Summary ===
    reg = data.get("regime", {})
    print(f"\nREGIME: {reg.get('type', 'UNKNOWN')} (score: {reg.get('score', 0):.3f})")
    print(f"Special Modes: {', '.join(reg.get('special_modes', [])) or '—'}")
    print(f"Rationale: {data.get('rationale', '—')}")
    print(f"Pillars: {data.get('pillars', {})}")

    # === Recommended List - FULL 15, reliable format ===
    recs = data.get("recommended_tickers", [])
    top = data.get("top_details", [])
    print(f"\nRECOMMENDED TICKERS ({len(recs)} total) - Full list for execution:")
    print("-" * 75)
    print(f"{'Rank':>4}  {'Ticker':<8}  {'Composite':>9}  {'Momentum':>8}  {'Strict':<6}  {'Rec?':<4}  Special")
    print("-" * 75)

    for item in top:  # show every one
        ticker = item.get("ticker", "?")
        is_rec = "YES" if ticker in recs else "NO"
        strict = "YES" if item.get("passes_strict") else "NO"
        special = str(item.get("special_modes", ""))[:20]
        print(f"{item.get('rank', 0):>4}  {ticker:<8}  {item.get('composite', 0):>9.4f}  "
              f"{item.get('momentum', 0):>8.4f}  {strict:<6}  {is_rec:<4}  {special}")

    print("-" * 75)
    print("Note: Trade the top ~5 from the 'YES' (Rec?) list. Equal weight, hold 5 trading days.")

    # === Cycles / PnL ===
    print("\nRECENT CYCLES / PnL TRACKER:")
    if not cycles_df.empty:
        print(cycles_df[["cycle_id", "start_date", "tickers", "cycle_pnl_pct"]].to_string(index=False))
    else:
        print("  (No portfolio_cycles.xlsx data yet. Run log_cycle_positions or daily.py)")

    # === Interpretation Guide ===
    print("\n" + "=" * 75)
    print("GUIDE TO INTERPRETING THE SCREENER (for execution)")
    print("=" * 75)
    print("""
• Regime & Score: STRONG / MODERATE / CAUTIOUS / WEAK.
  Higher score = more aggressive (more recommended names, stronger pillar tilts).

• Composite: The main score used for ranking. Higher = better (risk-adjusted momentum
  + special modes + current pillar multipliers from the 4 strategies).

• Rec? (YES/NO): The exact list the system recommends right now (dynamic count per SPEC 4.7).
  These are the ones that should be considered for positions. The "top 5" from this list
  is the standard execution set.

• Strict (YES/NO): Whether the ticker passed the strict filter
  (strong recent return + close to recent high + volume surge).
  Historically this filter has shown strong edge on the next day.

• Pillars: Current multipliers for the 4 strategy buckets (COMPASS, Rattlesnake, Catalyst, EFA).
  Values > 1.0 mean the strategy is favored in the current market regime.

• How to execute (recommended):
  1. Take the top 5 from the Rec? = YES list.
  2. Equal weight (e.g. 20% each).
  3. Hold exactly 5 trading days.
  4. Rotate at the end of the cycle.
  5. Use the backtest/portfolio_cycles.xlsx (with refresh_current_prices.py) to track live PnL.

Full formal rules: See HYDRA_ALGORITHM_SPEC.md
Fresh data: Run `python daily.py` (or hydra-daily after install)
""")
    print("=" * 75)
    print("Artifacts: pine/watchlist.txt + pine/hydra_last_summary.json")
    print("PnL tracker: backtest/portfolio_cycles.xlsx")
    print("=" * 75 + "\n")


def main():
    parser = argparse.ArgumentParser(description="HYDRA Console Execution Dashboard (reliable plain text by default)")
    parser.add_argument("--watch", action="store_true", help="Live updating mode (simple clear+reprint)")
    parser.add_argument("--interval", type=int, default=30, help="Seconds between refreshes in watch mode")
    parser.add_argument("--rich", action="store_true", help="Try the fancy Rich version (may have width issues on some terminals)")
    parser.add_argument("--once", action="store_true", help="Single print and exit")
    args = parser.parse_args()

    data, _ = load_latest_summary()
    cycles = load_recent_cycles(8)

    if args.rich and RICH_AVAILABLE:
        console = Console()
        def refresh():
            d, _ = load_latest_summary()
            c = load_recent_cycles(8)
            if d is None:
                return Panel("[red]No execution data found. Run daily.py first.[/red]")
            return build_dashboard(d, c)

        if args.watch or not args.once:
            layout = refresh()
            with Live(layout, console=console, refresh_per_second=1, screen=True) as live:
                try:
                    while True:
                        live.update(refresh())
                        time.sleep(args.interval)
                except KeyboardInterrupt:
                    console.print("\n[cyan]Dashboard stopped.[/cyan]")
        else:
            console.print(refresh())
        return

    # === Default: reliable plain text (always shows full data) ===
    render_plain(data or {}, cycles)

    if args.watch:
        import os
        try:
            while True:
                time.sleep(args.interval)
                # Clear screen (Windows + Unix)
                os.system('cls' if os.name == 'nt' else 'clear')
                d, _ = load_latest_summary()
                c = load_recent_cycles(8)
                render_plain(d or {}, c)
        except KeyboardInterrupt:
            print("\nDashboard stopped.")


if __name__ == "__main__":
    main()
