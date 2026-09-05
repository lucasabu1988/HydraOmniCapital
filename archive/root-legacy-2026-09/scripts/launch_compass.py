"""
COMPASS v8.2 — Combined Launcher
==================================
Starts both the live trading system and the monitoring dashboard.
The dashboard opens in your browser automatically.

Usage:
    python launch_compass.py              # Start both
    python launch_compass.py --dashboard  # Dashboard only (monitoring)
    python launch_compass.py --live       # Live system only (no dashboard)
"""

import subprocess
import sys
import os
import time
import signal
import webbrowser
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
DASHBOARD_PORT = 5000
DASHBOARD_URL = f'http://localhost:{DASHBOARD_PORT}'


def print_banner():
    now_et = datetime.now(ET)
    print()
    print("=" * 62)
    print("   COMPASS v8.2 — Live Trading System")
    print("=" * 62)
    print(f"   Time (ET):    {now_et.strftime('%Y-%m-%d %H:%M:%S %A')}")
    print(f"   Market Open:  09:30 ET")
    print(f"   Dashboard:    {DASHBOARD_URL}")
    print(f"   Chassis:      async fetch | fill breaker 2%")
    print(f"                 order timeout 300s | data validation")
    print("=" * 62)
    print()


def check_prerequisites():
    """Quick sanity checks before launch."""
    errors = []

    # Config file
    if not os.path.exists('omnicapital_config.json'):
        errors.append("omnicapital_config.json not found")

    # State directory
    os.makedirs('state', exist_ok=True)
    os.makedirs('logs', exist_ok=True)

    # Kill switch (remove if exists from previous session)
    if os.path.exists('STOP_TRADING'):
        print("[!] Kill switch file found (STOP_TRADING). Removing...")
        os.remove('STOP_TRADING')

    # Flask installed
    try:
        import flask
    except ImportError:
        errors.append("Flask not installed: pip install flask")

    # yfinance
    try:
        import yfinance
    except ImportError:
        errors.append("yfinance not installed: pip install yfinance")

    # Quick data feed test (uses async-capable data feed module)
    try:
        from omnicapital_data_feed import YahooDataFeed
        import time as _time
        feed = YahooDataFeed(max_workers=5)
        t0 = _time.time()
        prices = feed.get_prices(['SPY', 'AAPL', 'MSFT'])
        elapsed = _time.time() - t0
        spy = prices.get('SPY')
        if spy and spy > 0:
            print(f"[OK] Data feed (async): {len(prices)} prices in {elapsed:.1f}s | SPY = ${spy:.2f}")
        else:
            errors.append("Data feed: SPY price unavailable")
    except Exception as e:
        # Fallback to direct yfinance
        try:
            import yfinance as yf
            t = yf.Ticker('SPY')
            price = t.fast_info.get('last_price')
            if price and price > 0:
                print(f"[OK] Data feed (fallback): SPY = ${price:.2f}")
            else:
                errors.append("Data feed: SPY price unavailable")
        except Exception as e2:
            errors.append(f"Data feed error: {e2}")

    if errors:
        print("\n[ERRORS]")
        for e in errors:
            print(f"  - {e}")
        print()
        return False

    print("[OK] All prerequisites passed")
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description='COMPASS v8.2 Launcher')
    parser.add_argument('--dashboard', action='store_true', help='Dashboard only')
    parser.add_argument('--live', action='store_true', help='Live system only')
    args = parser.parse_args()

    print_banner()

    if not check_prerequisites():
        print("Fix the errors above and try again.")
        sys.exit(1)

    processes = []

    try:
        # Start live trading system
        if not args.dashboard:
            print("\n[STARTING] Live trading system...")
            live_proc = subprocess.Popen(
                [sys.executable, 'omnicapital_live.py'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            processes.append(('Live System', live_proc))
            print(f"  PID: {live_proc.pid}")

            # Wait for initial state file
            print("  Waiting for first state save...", end='', flush=True)
            for i in range(30):
                time.sleep(1)
                if os.path.exists('state/compass_state_latest.json'):
                    print(f" ready ({i+1}s)")
                    break
                # Check if process died
                if live_proc.poll() is not None:
                    print(f" FAILED (exit code {live_proc.returncode})")
                    # Read error output
                    out = live_proc.stdout.read().decode('utf-8', errors='replace')
                    print(out[-500:] if len(out) > 500 else out)
                    sys.exit(1)
                print(".", end='', flush=True)
            else:
                print(" (no state yet, continuing)")

        # Start dashboard
        if not args.live:
            print("\n[STARTING] Dashboard...")
            dash_proc = subprocess.Popen(
                [sys.executable, 'compass_dashboard.py'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            processes.append(('Dashboard', dash_proc))
            print(f"  PID: {dash_proc.pid}")
            print(f"  URL: {DASHBOARD_URL}")

            # Wait for dashboard to be ready
            time.sleep(2)
            webbrowser.open(DASHBOARD_URL)

        # Status
        print("\n" + "-" * 62)
        print("Running processes:")
        for name, proc in processes:
            status = "running" if proc.poll() is None else f"exited ({proc.returncode})"
            print(f"  [{name}] PID {proc.pid} — {status}")
        print("-" * 62)
        print("Press Ctrl+C to stop all processes")
        print()

        # Keep running, forward signals
        while True:
            time.sleep(5)
            # Check if any process died
            for name, proc in processes:
                if proc.poll() is not None:
                    print(f"\n[!] {name} exited with code {proc.returncode}")
                    out = proc.stdout.read().decode('utf-8', errors='replace')
                    if out.strip():
                        print(out[-300:] if len(out) > 300 else out)

            # Remove dead processes
            processes = [(n, p) for n, p in processes if p.poll() is None]
            if not processes:
                print("\nAll processes stopped.")
                break

    except KeyboardInterrupt:
        print("\n\n[STOPPING] Shutting down...")
        for name, proc in processes:
            if proc.poll() is None:
                print(f"  Stopping {name} (PID {proc.pid})...")
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
        print("[DONE] All processes stopped.")


if __name__ == '__main__':
    main()
