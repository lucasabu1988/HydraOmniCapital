"""
Git Auto-Sync for COMPASS Live Trading System
==============================================
Non-blocking git commit+push of state and log files after each save_state().
Uses a background daemon thread with a queue to serialize git operations.
Never crashes the trading engine -- all errors are logged and swallowed.
"""

import subprocess
import threading
import logging
import os

from datetime import datetime
from queue import Queue, Empty

logger = logging.getLogger(__name__)

_git_queue: Queue = Queue(maxsize=10)
_worker_thread: threading.Thread | None = None
_worker_started = False
_repo_dir = os.path.dirname(os.path.abspath(__file__))
_disabled_notice_logged = False

MIN_COMMIT_INTERVAL = 900  # 15 minutes between commits


def _git_sync_disabled() -> bool:
    value = os.environ.get('DISABLE_GIT_SYNC', '').strip().lower()
    return value in ('1', 'true', 'yes', 'on')


def _log_disabled_once():
    global _disabled_notice_logged
    if _disabled_notice_logged:
        return
    _disabled_notice_logged = True
    logger.info("git sync disabled via DISABLE_GIT_SYNC=1; skipping auto-commit worker")


def _run_git(*args, timeout=30, warn_on_fail=True) -> tuple[bool, str]:
    """Run a git command. Returns (success, output). Never raises."""
    cmd = ['git'] + list(args)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=_repo_dir,
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            if warn_on_fail:
                logger.warning(f"git {args[0]} failed (rc={result.returncode}): {output[:200]}")
            return False, output
        return True, output
    except subprocess.TimeoutExpired:
        logger.warning(f"git {args[0]} timed out after {timeout}s")
        return False, "timeout"
    except FileNotFoundError:
        logger.error("git executable not found")
        return False, "git not found"
    except Exception as e:
        logger.error(f"git {args[0]} unexpected error: {e}")
        return False, str(e)


def _git_worker():
    """Background worker: pulls from queue, runs git add+commit+push.
    Daemon thread -- exits when main process exits."""
    last_commit_time = None

    while True:
        try:
            item = _git_queue.get(timeout=60)
            if item is None:  # Poison pill
                break

            files_to_add = item.get('files', [])
            commit_msg = item.get('message', 'auto-sync state')

            # Throttle: skip if too soon since last commit
            if last_commit_time:
                elapsed = (datetime.now() - last_commit_time).total_seconds()
                if elapsed < MIN_COMMIT_INTERVAL:
                    logger.debug(f"git sync: {int(elapsed)}s since last commit, skipping (min {MIN_COMMIT_INTERVAL}s)")
                    _git_queue.task_done()
                    continue

            # Check for actual changes (diff --quiet exits 1 if changes exist, not an error)
            ok_diff, _ = _run_git('diff', '--quiet', '--', *files_to_add, warn_on_fail=False)
            ok_staged, _ = _run_git('diff', '--cached', '--quiet', '--', *files_to_add, warn_on_fail=False)

            # Check for untracked new files (new dated state/log files)
            _, ls_output = _run_git('ls-files', '--others', '--exclude-standard', '--', *files_to_add)
            has_untracked = bool(ls_output.strip())

            if ok_diff and ok_staged and not has_untracked:
                logger.debug("git sync: no changes to commit, skipping")
                _git_queue.task_done()
                continue

            # git add (only specific files, never git add -A)
            # Filter out gitignored files to prevent git add from failing entirely
            addable = []
            for f in files_to_add:
                ok_check, _ = _run_git('check-ignore', '-q', f, warn_on_fail=False)
                if not ok_check:  # rc=1 means NOT ignored → addable
                    addable.append(f)
                else:
                    logger.debug(f"git sync: skipping ignored file {f}")
            if not addable:
                logger.debug("git sync: all files ignored, skipping")
                _git_queue.task_done()
                continue
            ok, output = _run_git('add', '--', *addable)
            if not ok:
                logger.warning(f"git add failed, skipping: {output[:100]}")
                _git_queue.task_done()
                continue

            # Verify something is staged (rc=1 means there are staged changes)
            ok_check, _ = _run_git('diff', '--cached', '--quiet', warn_on_fail=False)
            if ok_check:
                logger.debug("git sync: nothing staged after add, skipping")
                _git_queue.task_done()
                continue

            # git commit
            ok, output = _run_git('commit', '-m', commit_msg)
            if not ok:
                logger.warning(f"git commit failed: {output[:200]}")
                _git_queue.task_done()
                continue

            logger.info(f"git sync: committed ({commit_msg})")
            last_commit_time = datetime.now()

            # git push (longer timeout for network)
            ok, output = _run_git('push', 'origin', 'main', timeout=60)
            if not ok:
                logger.warning(f"git push failed (will retry next cycle): {output[:200]}")
            else:
                logger.info("git sync: pushed to origin/main")

            _git_queue.task_done()

        except Empty:
            continue
        except Exception as e:
            logger.error(f"git sync worker error: {e}")
            try:
                _git_queue.task_done()
            except ValueError:
                pass


def _ensure_worker():
    """Start the background worker thread if not already running."""
    global _worker_thread, _worker_started
    if _git_sync_disabled():
        _log_disabled_once()
        return False
    if _worker_started and _worker_thread and _worker_thread.is_alive():
        return True
    _worker_thread = threading.Thread(
        target=_git_worker,
        daemon=True,
        name='GitSync',
    )
    _worker_thread.start()
    _worker_started = True
    logger.info("git sync: background worker started")
    return True


def _update_live_chart_baseline():
    """Update the live_chart_baseline.json with current state file data.

    Reads all dated state files, builds a clean timeline, and writes
    the baseline so the cloud live-chart survives Render deploys.
    """
    import json, glob
    baseline_path = os.path.join(_repo_dir, 'state', 'live_chart_baseline.json')
    try:
        # Read existing baseline
        existing = {}
        if os.path.exists(baseline_path):
            with open(baseline_path, 'r') as f:
                bl = json.load(f)
            for dt, val in zip(bl.get('dates', []), bl.get('values', [])):
                existing[dt] = val

        # Overlay with current state files
        pattern = os.path.join(_repo_dir, 'state', 'compass_state_2*.json')
        for sf in sorted(glob.glob(pattern)):
            if 'pre_rotation' in sf or 'latest' in sf:
                continue
            try:
                with open(sf, 'r') as f:
                    s = json.load(f)
                dt = s.get('last_trading_date')
                val = s.get('portfolio_value')
                if dt and val and val > 0:
                    existing[dt] = val
            except Exception:
                continue

        if not existing:
            return None

        dates = sorted(existing.keys())
        values = [existing[d] for d in dates]
        payload = {
            'dates': dates,
            'values': values,
            'initial_capital': 100000.0,
            'note': f'Auto-updated {datetime.now().strftime("%Y-%m-%d %H:%M")} by git_sync'
        }
        tmp = baseline_path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, baseline_path)
        logger.debug(f"live_chart_baseline updated: {len(dates)} dates")
        return baseline_path
    except Exception as e:
        logger.warning(f"Failed to update live_chart_baseline: {e}")
        return None


def git_sync_async(state_file: str, latest_file: str):
    """Queue a git sync operation. Non-blocking. Called from save_state().

    Args:
        state_file: e.g. 'state/compass_state_20260223.json'
        latest_file: e.g. 'state/compass_state_latest.json'
    """
    # Local dashboard keeps this opt-in so state snapshots do not pollute main history.
    if not _ensure_worker():
        return

    files = [state_file, latest_file]

    # Update live chart baseline so cloud chart survives deploys
    baseline = _update_live_chart_baseline()
    if baseline:
        files.append(baseline)

    # Normalize to forward slashes (git on Windows)
    files = list(set(f.replace('\\', '/') for f in files))

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    message = f"auto: COMPASS state sync {timestamp}"

    try:
        _git_queue.put_nowait({'files': files, 'message': message})
    except Exception:
        logger.debug("git sync: queue full, skipping this cycle")


def git_sync_rotation(cycle_num: int, hydra_return: float, status: str):
    """Queue a git sync after a 5-day rotation. Includes cycle_log + state files."""
    if not _ensure_worker():
        return

    files = [
        'state/cycle_log.json',
        'state/compass_state_latest.json',
    ]

    # Add today's dated state file
    today = datetime.now().strftime('%Y%m%d')
    dated_state = f'state/compass_state_{today}.json'
    if os.path.exists(os.path.join(_repo_dir, dated_state)):
        files.append(dated_state)

    # Update live chart baseline
    baseline = _update_live_chart_baseline()
    if baseline:
        files.append(baseline)

    files = list(set(f.replace('\\', '/') for f in files))

    sign = '+' if hydra_return >= 0 else ''
    message = f"auto: cycle #{cycle_num} closed ({sign}{hydra_return:.2f}% {status}) — rotation complete"

    try:
        _git_queue.put_nowait({'files': files, 'message': message})
        logger.info(f"git sync: rotation commit queued (cycle #{cycle_num})")
    except Exception:
        logger.warning("git sync: queue full, rotation commit not queued")
