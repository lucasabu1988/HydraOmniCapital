"""Tests for compass_watchdog.py — dashboard auto-restart daemon."""

import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from compass_watchdog import CompassWatchdog


@pytest.fixture
def watchdog(tmp_path):
    """Create a watchdog instance with temp dirs and no real I/O."""
    wd = CompassWatchdog(
        project_dir=str(tmp_path),
        python_exe='/usr/bin/python3',
        max_restarts=3,
        check_interval=1,
        health_url='http://localhost:5000/api/state',
    )
    return wd


# ── 1. Detects crashed process ──────────────────────────────────────

def test_detects_crashed_process(watchdog):
    """Watchdog detects a process that exited with non-zero code."""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 1  # process exited
    mock_proc.returncode = 1
    mock_proc.pid = 12345
    watchdog.process = mock_proc

    assert watchdog.is_process_alive() is False


# ── 2. Restarts after crash ─────────────────────────────────────────

@patch('compass_watchdog.subprocess.Popen')
@patch('compass_watchdog.requests.get')
def test_restarts_after_crash(mock_get, mock_popen, watchdog):
    """Watchdog starts a new process after detecting a crash."""
    # Simulate health check success on restart
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    # Simulate crashed process
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 1
    mock_proc.returncode = 1
    watchdog.process = mock_proc

    # New process from Popen
    new_proc = MagicMock()
    new_proc.pid = 99999
    mock_popen.return_value = new_proc

    result = watchdog.handle_crash()

    assert result is True
    mock_popen.assert_called_once()
    assert watchdog.restart_count == 1


# ── 3. Max restart limit respected ──────────────────────────────────

@patch('compass_watchdog.subprocess.Popen')
@patch('compass_watchdog.requests.get')
def test_max_restart_limit(mock_get, mock_popen, watchdog):
    """Watchdog stops restarting after max_restarts is reached."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    new_proc = MagicMock()
    new_proc.pid = 11111
    mock_popen.return_value = new_proc

    # Exhaust restart budget (max_restarts=3)
    for i in range(3):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        watchdog.process = mock_proc
        watchdog.handle_crash()

    assert watchdog.restart_count == 3

    # Next crash should be refused
    watchdog.process = MagicMock()
    watchdog.process.returncode = 1
    result = watchdog.handle_crash()

    assert result is False
    assert watchdog._running is False


# ── 4. Logs restart events ──────────────────────────────────────────

@patch('compass_watchdog.subprocess.Popen')
@patch('compass_watchdog.requests.get')
def test_logs_restart_events(mock_get, mock_popen, watchdog, caplog):
    """Watchdog emits log messages on crash detection and restart."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    new_proc = MagicMock()
    new_proc.pid = 55555
    mock_popen.return_value = new_proc

    crashed = MagicMock()
    crashed.returncode = 1
    crashed.pid = 44444
    watchdog.process = crashed

    with caplog.at_level(logging.WARNING, logger='compass_watchdog'):
        watchdog.handle_crash()

    assert any('died' in r.message.lower() or 'exit code' in r.message.lower()
               for r in caplog.records)


# ── 5. Health check works ───────────────────────────────────────────

@patch('compass_watchdog.requests.get')
def test_health_check_success(mock_get, watchdog):
    """Health check returns True when API responds 200."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    assert watchdog.check_health() is True
    mock_get.assert_called_once_with(watchdog.health_url, timeout=10)


@patch('compass_watchdog.requests.get')
def test_health_check_failure_on_error(mock_get, watchdog):
    """Health check returns False when request raises an exception."""
    mock_get.side_effect = ConnectionError('refused')

    assert watchdog.check_health() is False


@patch('compass_watchdog.requests.get')
def test_health_check_failure_on_bad_status(mock_get, watchdog):
    """Health check returns False on non-200 status codes."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_get.return_value = mock_resp

    assert watchdog.check_health() is False


# ── 6. Handles missing process gracefully ───────────────────────────

@patch('compass_watchdog.subprocess.Popen')
@patch('compass_watchdog.requests.get')
def test_handles_missing_process(mock_get, mock_popen, watchdog):
    """Watchdog handles None process (never started) without error."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    new_proc = MagicMock()
    new_proc.pid = 77777
    mock_popen.return_value = new_proc

    assert watchdog.process is None
    assert watchdog.is_process_alive() is False

    # handle_crash with no process should still attempt start
    result = watchdog.handle_crash()
    assert result is True
    mock_popen.assert_called_once()


# ── 7. Startup command is correct ───────────────────────────────────

def test_startup_command(watchdog):
    """Startup command uses configured python exe and dashboard script."""
    cmd = watchdog.get_startup_command()
    assert cmd[0] == '/usr/bin/python3'
    assert cmd[1].endswith('compass_dashboard.py')
    assert len(cmd) == 2


# ── 8. Clean shutdown behavior ──────────────────────────────────────

def test_clean_shutdown_stops_process(watchdog):
    """Shutdown terminates the dashboard process and clears state."""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # still alive
    watchdog.process = mock_proc
    watchdog._running = True

    watchdog.shutdown()

    mock_proc.terminate.assert_called_once()
    assert watchdog._running is False
    assert watchdog.process is None


def test_clean_shutdown_no_process(watchdog):
    """Shutdown with no running process completes without error."""
    watchdog._running = True
    watchdog.process = None

    watchdog.shutdown()  # should not raise

    assert watchdog._running is False


# ── 9. Monitor cycle — healthy path ─────────────────────────────────

@patch('compass_watchdog.requests.get')
def test_monitor_cycle_healthy(mock_get, watchdog):
    """Monitor cycle returns True when process is alive and healthy."""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # alive
    watchdog.process = mock_proc

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    result = watchdog.monitor_cycle()
    assert result is True


# ── 10. Unresponsive process gets killed and restarted ──────────────

@patch('compass_watchdog.subprocess.Popen')
@patch('compass_watchdog.requests.get')
def test_handle_unresponsive_kills_and_restarts(mock_get, mock_popen, watchdog):
    """Unresponsive process is terminated before restart."""
    # First call: health check fails (unresponsive) -> used by handle_unresponsive
    # Second call: health check succeeds after restart
    mock_resp_ok = MagicMock()
    mock_resp_ok.status_code = 200
    mock_get.return_value = mock_resp_ok

    old_proc = MagicMock()
    old_proc.pid = 11111
    old_proc.poll.return_value = None  # still alive but unresponsive
    watchdog.process = old_proc

    new_proc = MagicMock()
    new_proc.pid = 22222
    mock_popen.return_value = new_proc

    result = watchdog.handle_unresponsive()

    old_proc.terminate.assert_called_once()
    assert result is True
    assert watchdog.restart_count == 1


# ── 11. PID file is written ─────────────────────────────────────────

def test_pid_file_written(watchdog, tmp_path):
    """Watchdog writes its own PID to the state directory."""
    watchdog._write_pid()

    pid_file = os.path.join(str(tmp_path), 'state', 'watchdog.pid')
    assert os.path.exists(pid_file)

    with open(pid_file) as f:
        content = f.read().strip()
    assert content == str(os.getpid())


# ── 12. Startup logging includes key info ───────────────────────────

def test_startup_logging(watchdog, caplog):
    """Startup log block includes project dir, python path, and PID."""
    with caplog.at_level(logging.INFO, logger='compass_watchdog'):
        watchdog._log_startup()

    messages = ' '.join(r.message for r in caplog.records)
    assert 'COMPASS Watchdog starting' in messages
    assert 'Project:' in messages
    assert 'Python:' in messages
    assert 'PID:' in messages
