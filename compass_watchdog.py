"""
COMPASS Watchdog — Auto-restart daemon for the dashboard process.
Monitors compass_dashboard.py and restarts it if it crashes or becomes unresponsive.
Launched by compass_watchdog.vbs (hidden window).
"""

import logging
import os
import signal
import subprocess
import sys
import time

import requests

logger = logging.getLogger(__name__)

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON_EXE = sys.executable
DASHBOARD_SCRIPT = os.path.join(PROJECT_DIR, 'compass_dashboard.py')
PID_FILE = os.path.join(PROJECT_DIR, 'state', 'watchdog.pid')
LOG_FILE = os.path.join(PROJECT_DIR, 'logs', 'compass_watchdog.log')

HEALTH_URL = 'http://localhost:5000/api/state'
HEALTH_TIMEOUT = 10
CHECK_INTERVAL = 60
STARTUP_WAIT = 30
MAX_RESTARTS = 10


class CompassWatchdog:

    def __init__(self, project_dir=None, python_exe=None, max_restarts=MAX_RESTARTS,
                 check_interval=CHECK_INTERVAL, health_url=HEALTH_URL):
        self.project_dir = project_dir or PROJECT_DIR
        self.python_exe = python_exe or PYTHON_EXE
        self.dashboard_script = os.path.join(self.project_dir, 'compass_dashboard.py')
        self.pid_file = os.path.join(self.project_dir, 'state', 'watchdog.pid')
        self.max_restarts = max_restarts
        self.check_interval = check_interval
        self.health_url = health_url
        self.restart_count = 0
        self.process = None
        self._running = False

    def _setup_logging(self):
        log_dir = os.path.join(self.project_dir, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'compass_watchdog.log')

        handler = logging.FileHandler(log_file, encoding='utf-8')
        handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    def _write_pid(self):
        os.makedirs(os.path.dirname(self.pid_file), exist_ok=True)
        with open(self.pid_file, 'w') as f:
            f.write(str(os.getpid()))

    def _log_startup(self):
        logger.info('=' * 60)
        logger.info('COMPASS Watchdog starting')
        logger.info('Project: %s', self.project_dir)
        logger.info('Python:  %s', self.python_exe)
        logger.info('PID:     %s', os.getpid())
        logger.info('=' * 60)

    def get_startup_command(self):
        return [self.python_exe, self.dashboard_script]

    def check_health(self):
        try:
            resp = requests.get(self.health_url, timeout=HEALTH_TIMEOUT)
            return resp.status_code == 200
        except Exception:
            return False

    def is_process_alive(self):
        if self.process is None:
            return False
        return self.process.poll() is None

    def start_dashboard(self):
        cmd = self.get_startup_command()
        logger.info('Starting compass_dashboard.py from %s', self.project_dir)
        self.process = subprocess.Popen(
            cmd,
            cwd=self.project_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info('Dashboard started (PID %s)', self.process.pid)
        logger.info('Waiting for engine to initialize...')

        # Wait for engine to become healthy
        deadline = time.time() + STARTUP_WAIT
        while time.time() < deadline:
            if self.check_health():
                logger.info('Engine is healthy after restart')
                return True
            time.sleep(2)

        logger.warning('Engine not healthy after restart \u2014 will retry next cycle')
        return False

    def stop_dashboard(self):
        if self.process is None:
            return
        try:
            self.process.terminate()
            self.process.wait(timeout=10)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass
        self.process = None

    def handle_crash(self):
        if self.process is not None:
            exit_code = self.process.returncode
            logger.warning('Dashboard process died (exit code %s)', exit_code)
            self.process = None

        if self.restart_count >= self.max_restarts:
            logger.error('Max restarts (%d) reached — stopping watchdog', self.max_restarts)
            self._running = False
            return False

        self.restart_count += 1
        return self.start_dashboard()

    def handle_unresponsive(self):
        if self.process:
            logger.warning('Engine not responding (PID %s). Killing and restarting.',
                           self.process.pid)
            self.stop_dashboard()
        return self.handle_crash()

    def monitor_cycle(self):
        if not self.is_process_alive():
            return self.handle_crash()

        if not self.check_health():
            return self.handle_unresponsive()

        return True

    def shutdown(self):
        self._running = False
        self.stop_dashboard()
        logger.info('Watchdog shutting down')

    def run(self):
        self._setup_logging()
        self._write_pid()
        self._log_startup()
        self._running = True

        # Initial check — start if nothing running
        if not self.check_health():
            logger.info('No dashboard process \u2014 starting')
            self.start_dashboard()
        else:
            logger.info('Dashboard already running, adopting it')

        while self._running:
            time.sleep(self.check_interval)
            self.monitor_cycle()

            if self.restart_count >= self.max_restarts:
                break


if __name__ == '__main__':
    watchdog = CompassWatchdog()
    try:
        watchdog.run()
    except KeyboardInterrupt:
        watchdog.shutdown()
