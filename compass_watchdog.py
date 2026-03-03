"""
COMPASS Watchdog — Keep the trading engine alive forever
=========================================================
Monitors compass_dashboard.py. If it crashes, restarts it immediately.
Logs all events. Runs silently in the background.

Usage:
    python compass_watchdog.py          # Run watchdog (foreground)
    python compass_watchdog.py --install # Install as Windows Task Scheduler job (auto-start on login)
    python compass_watchdog.py --remove  # Remove scheduled task
    python compass_watchdog.py --status  # Check if engine is alive
"""

import subprocess
import sys
import os
import time
import signal
import logging
import json
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

ET = ZoneInfo('America/New_York')
PROJECT_DIR = Path(__file__).parent.resolve()
DASHBOARD_SCRIPT = PROJECT_DIR / 'compass_dashboard.py'
LOG_DIR = PROJECT_DIR / 'logs'
STATE_FILE = PROJECT_DIR / 'state' / 'compass_state_latest.json'
WATCHDOG_LOG = LOG_DIR / 'compass_watchdog.log'
WATCHDOG_PID = PROJECT_DIR / 'state' / 'watchdog.pid'
KILL_FILE = PROJECT_DIR / 'STOP_TRADING'

HEALTH_CHECK_URL = 'http://localhost:5000/api/state'
HEALTH_CHECK_INTERVAL = 60
RESTART_COOLDOWN = 30
MAX_RAPID_RESTARTS = 5
RAPID_RESTART_WINDOW = 300

PYTHON_EXE = sys.executable
TASK_NAME = 'COMPASS-Watchdog'


def setup_logging():
    LOG_DIR.mkdir(exist_ok=True)
    handler = logging.FileHandler(WATCHDOG_LOG, encoding='utf-8')
    handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logger = logging.getLogger('watchdog')
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.addHandler(console)
    return logger


def write_pid():
    WATCHDOG_PID.parent.mkdir(exist_ok=True)
    WATCHDOG_PID.write_text(str(os.getpid()))


def clear_pid():
    if WATCHDOG_PID.exists():
        WATCHDOG_PID.unlink(missing_ok=True)


def is_watchdog_running():
    if not WATCHDOG_PID.exists():
        return False
    try:
        pid = int(WATCHDOG_PID.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, OSError, ProcessLookupError):
        return False


def health_check():
    try:
        import urllib.request
        req = urllib.request.Request(HEALTH_CHECK_URL, method='GET')
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            engine = data.get('engine', {})
            return engine.get('running', False)
    except Exception:
        return False


def find_dashboard_process():
    try:
        result = subprocess.run(
            ['wmic', 'process', 'where', "name='python.exe'", 'get', 'ProcessId,CommandLine'],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            if 'compass_dashboard.py' in line:
                parts = line.strip().split()
                pid = int(parts[-1])
                return pid
    except Exception:
        pass
    return None


def kill_dashboard():
    pid = find_dashboard_process()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(3)
            try:
                os.kill(pid, 0)
                os.kill(pid, 9)
            except OSError:
                pass
        except OSError:
            pass


def start_dashboard(log):
    log.info(f"Starting compass_dashboard.py from {PROJECT_DIR}")

    if KILL_FILE.exists():
        log.warning("STOP_TRADING kill switch found — removing it")
        KILL_FILE.unlink()

    proc = subprocess.Popen(
        [PYTHON_EXE, str(DASHBOARD_SCRIPT)],
        cwd=str(PROJECT_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
    )
    log.info(f"Dashboard started (PID {proc.pid})")
    return proc


def run_watchdog():
    log = setup_logging()
    log.info("=" * 60)
    log.info("COMPASS Watchdog starting")
    log.info(f"Project: {PROJECT_DIR}")
    log.info(f"Python:  {PYTHON_EXE}")
    log.info(f"PID:     {os.getpid()}")
    log.info("=" * 60)

    if is_watchdog_running():
        log.warning("Another watchdog is already running. Exiting.")
        return

    write_pid()

    restart_times = []
    proc = None
    running = True

    # Check if dashboard is already running (e.g. started manually)
    existing_pid = find_dashboard_process()
    if existing_pid:
        log.info(f"Dashboard already running (PID {existing_pid}), adopting it")
        if health_check():
            log.info("Engine is healthy — monitoring existing process")
            # Create a dummy proc-like object to track it
            proc = type('ExistingProc', (), {'pid': existing_pid, 'poll': lambda self: None, 'returncode': None})()
        else:
            log.warning("Dashboard running but engine not healthy — will monitor and restart if needed")

    def handle_signal(sig, frame):
        nonlocal running
        log.info(f"Received signal {sig}, shutting down watchdog")
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    try:
        while running:
            # Check if dashboard process is alive
            needs_restart = False

            if proc is None:
                needs_restart = True
                log.info("No dashboard process — starting")
            elif proc.poll() is not None:
                needs_restart = True
                log.warning(f"Dashboard process died (exit code {proc.returncode})")
            elif not health_check():
                # Process alive but engine not responding
                existing_pid = find_dashboard_process()
                if existing_pid:
                    log.warning(f"Engine not responding (PID {existing_pid}). Killing and restarting.")
                    kill_dashboard()
                    time.sleep(5)
                needs_restart = True

            if needs_restart:
                # Before starting a new one, check if there's already a process
                existing_pid = find_dashboard_process()
                if existing_pid and health_check():
                    log.info(f"Found healthy existing dashboard (PID {existing_pid}), adopting")
                    proc = type('ExistingProc', (), {'pid': existing_pid, 'poll': lambda self: None, 'returncode': None})()
                    continue

                # Kill any zombie dashboard
                if existing_pid:
                    log.warning(f"Killing unresponsive dashboard (PID {existing_pid})")
                    kill_dashboard()
                    time.sleep(5)

                # Check for rapid restart loop
                now = time.time()
                restart_times = [t for t in restart_times if now - t < RAPID_RESTART_WINDOW]

                if len(restart_times) >= MAX_RAPID_RESTARTS:
                    log.error(
                        f"Too many restarts ({MAX_RAPID_RESTARTS} in {RAPID_RESTART_WINDOW}s). "
                        f"Waiting 10 minutes before next attempt."
                    )
                    time.sleep(600)
                    restart_times.clear()

                proc = start_dashboard(log)
                restart_times.append(time.time())

                # Wait for startup
                log.info("Waiting for engine to initialize...")
                time.sleep(RESTART_COOLDOWN)

                # Verify it started
                if health_check():
                    log.info("Engine is healthy after restart")
                else:
                    log.warning("Engine not healthy after restart — will retry next cycle")

            # Sleep between checks
            for _ in range(HEALTH_CHECK_INTERVAL):
                if not running:
                    break
                time.sleep(1)

    except Exception as e:
        log.error(f"Watchdog error: {e}")
    finally:
        clear_pid()
        log.info("Watchdog stopped")


def install_task():
    script_path = Path(__file__).resolve()
    cmd = (
        f'schtasks /create /tn "{TASK_NAME}" '
        f'/tr "\"{PYTHON_EXE}\" \"{script_path}\"" '
        f'/sc ONLOGON '
        f'/rl HIGHEST '
        f'/f '
        f'/delay 0000:30'
    )
    print(f"Installing Windows Task Scheduler job: {TASK_NAME}")
    print(f"Command: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Installed successfully. COMPASS will auto-start 30s after login.")
        print(f"Task name: {TASK_NAME}")
        print(f"Script: {script_path}")
    else:
        print(f"Failed to install: {result.stderr}")
        print("Try running this script as Administrator.")
    return result.returncode == 0


def remove_task():
    cmd = f'schtasks /delete /tn "{TASK_NAME}" /f'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Removed task: {TASK_NAME}")
    else:
        print(f"Failed to remove (maybe doesn't exist): {result.stderr}")
    return result.returncode == 0


def check_status():
    print("COMPASS System Status")
    print("=" * 40)

    # Watchdog
    if is_watchdog_running():
        pid = int(WATCHDOG_PID.read_text().strip())
        print(f"  Watchdog:  RUNNING (PID {pid})")
    else:
        print(f"  Watchdog:  NOT RUNNING")

    # Dashboard process
    dash_pid = find_dashboard_process()
    if dash_pid:
        print(f"  Dashboard: RUNNING (PID {dash_pid})")
    else:
        print(f"  Dashboard: NOT RUNNING")

    # Engine health
    if health_check():
        print(f"  Engine:    HEALTHY")
        try:
            import urllib.request
            data = json.loads(urllib.request.urlopen(HEALTH_CHECK_URL, timeout=10).read())
            engine = data.get('engine', {})
            print(f"  Cycles:    {engine.get('cycles', '?')}")
            print(f"  Started:   {engine.get('started_at', '?')}")
            print(f"  Error:     {engine.get('error', 'None')}")
        except Exception:
            pass
    else:
        print(f"  Engine:    NOT RESPONDING")

    # Task Scheduler
    result = subprocess.run(
        f'schtasks /query /tn "{TASK_NAME}" 2>nul',
        shell=True, capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"  Auto-start: ENABLED ({TASK_NAME})")
    else:
        print(f"  Auto-start: NOT CONFIGURED")

    # Kill switch
    if KILL_FILE.exists():
        print(f"  Kill switch: ACTIVE (STOP_TRADING file exists)")
    else:
        print(f"  Kill switch: inactive")

    print("=" * 40)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='COMPASS Watchdog')
    parser.add_argument('--install', action='store_true', help='Install auto-start task')
    parser.add_argument('--remove', action='store_true', help='Remove auto-start task')
    parser.add_argument('--status', action='store_true', help='Check system status')
    args = parser.parse_args()

    if args.install:
        install_task()
    elif args.remove:
        remove_task()
    elif args.status:
        check_status()
    else:
        run_watchdog()
