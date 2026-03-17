import importlib
import logging
import os
import sys
from pathlib import Path
from queue import Queue
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import compass_dashboard


@pytest.fixture(params=['git_sync', 'compass.git_sync'])
def git_sync_module(request, monkeypatch):
    module = importlib.import_module(request.param)
    monkeypatch.setattr(module, '_git_queue', Queue(maxsize=10))
    monkeypatch.setattr(module, '_worker_thread', None)
    monkeypatch.setattr(module, '_worker_started', False)
    monkeypatch.setattr(module, '_disabled_notice_logged', False)
    return module


@pytest.fixture
def compass_git_sync_module(monkeypatch):
    module = importlib.import_module('compass.git_sync')
    monkeypatch.setattr(module, '_git_queue', Queue(maxsize=20))
    monkeypatch.setattr(module, '_worker_thread', None)
    monkeypatch.setattr(module, '_worker_started', False)
    monkeypatch.setattr(module, '_disabled_notice_logged', False)
    monkeypatch.setenv('DISABLE_GIT_SYNC', '0')
    return module


def _git_change_stub(
    *,
    commit_messages=None,
    processed_state_files=None,
    commit_success=True,
    commit_output='',
    push_success=True,
    push_output='',
):
    def fake_run_git(*args, timeout=30, warn_on_fail=True):
        cmd = args[0]

        if cmd == 'diff' and args[1:3] == ('--quiet', '--'):
            return False, ''
        if cmd == 'diff' and args[1:4] == ('--cached', '--quiet', '--'):
            return True, ''
        if cmd == 'ls-files':
            return True, ''
        if cmd == 'check-ignore':
            return False, ''
        if cmd == 'add':
            if processed_state_files is not None:
                state_file = next(
                    (
                        path for path in args[2:]
                        if path.startswith('state/')
                        and 'latest' not in path
                        and 'cycle_log' not in path
                    ),
                    None,
                )
                processed_state_files.append(state_file)
            return True, ''
        if cmd == 'diff' and args[1:3] == ('--cached', '--quiet') and len(args) == 3:
            return False, ''
        if cmd == 'commit':
            if commit_messages is not None:
                commit_messages.append(args[2])
            return commit_success, commit_output
        if cmd == 'push':
            return push_success, push_output

        return True, ''

    return fake_run_git


def test_git_sync_async_noops_when_disabled(git_sync_module, monkeypatch):
    monkeypatch.setenv('DISABLE_GIT_SYNC', '1')

    git_sync_module.git_sync_async('state/compass_state_20260316.json', 'state/compass_state_latest.json')

    assert git_sync_module._git_queue.qsize() == 0
    assert git_sync_module._worker_started is False


def test_git_sync_rotation_noops_when_disabled(git_sync_module, monkeypatch):
    monkeypatch.setenv('DISABLE_GIT_SYNC', 'true')

    git_sync_module.git_sync_rotation(7, 1.23, 'WIN')

    assert git_sync_module._git_queue.qsize() == 0
    assert git_sync_module._worker_started is False


def test_git_sync_async_queues_when_enabled(git_sync_module, monkeypatch):
    monkeypatch.setenv('DISABLE_GIT_SYNC', '0')
    monkeypatch.setattr(git_sync_module, '_ensure_worker', lambda: True)

    git_sync_module.git_sync_async('state/daily.json', 'state/latest.json')

    queued = git_sync_module._git_queue.get_nowait()
    assert set(queued['files']) == {'state/daily.json', 'state/latest.json'}
    assert queued['message'].startswith('auto: COMPASS state sync ')


def test_configure_local_git_sync_defaults_to_disabled(monkeypatch):
    monkeypatch.delenv('DISABLE_GIT_SYNC', raising=False)

    compass_dashboard._configure_local_git_sync()

    assert os.environ['DISABLE_GIT_SYNC'] == '1'


def test_configure_local_git_sync_preserves_explicit_value(monkeypatch):
    monkeypatch.setenv('DISABLE_GIT_SYNC', '0')

    compass_dashboard._configure_local_git_sync()

    assert os.environ['DISABLE_GIT_SYNC'] == '0'


def test_run_git_returns_error_output_for_invalid_command(compass_git_sync_module, monkeypatch, caplog):
    def fake_run(*args, **kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout='',
            stderr='git: unknown subcommand invalid-cmd',
        )

    monkeypatch.setattr(compass_git_sync_module.subprocess, 'run', fake_run)

    with caplog.at_level(logging.WARNING):
        ok, output = compass_git_sync_module._run_git('invalid-cmd')

    assert ok is False
    assert 'unknown subcommand' in output
    assert 'git invalid-cmd failed' in caplog.text


def test_run_git_returns_timeout_when_subprocess_times_out(compass_git_sync_module, monkeypatch, caplog):
    def fake_run(*args, **kwargs):
        raise compass_git_sync_module.subprocess.TimeoutExpired(cmd='git status', timeout=3)

    monkeypatch.setattr(compass_git_sync_module.subprocess, 'run', fake_run)

    with caplog.at_level(logging.WARNING):
        ok, output = compass_git_sync_module._run_git('status', timeout=3)

    assert ok is False
    assert output == 'timeout'
    assert 'git status timed out after 3s' in caplog.text


def test_git_sync_async_when_disabled_never_calls_git(compass_git_sync_module, monkeypatch):
    calls = []

    def fake_run_git(*args, **kwargs):
        calls.append(args)
        return True, ''

    monkeypatch.setenv('DISABLE_GIT_SYNC', '1')
    monkeypatch.setattr(compass_git_sync_module, '_run_git', fake_run_git)

    compass_git_sync_module.git_sync_async(
        'state/compass_state_20260316.json',
        'state/compass_state_latest.json',
    )

    assert calls == []
    assert compass_git_sync_module._git_queue.qsize() == 0


def test_git_sync_async_logs_push_failure_without_crashing(compass_git_sync_module, monkeypatch, caplog):
    monkeypatch.setattr(compass_git_sync_module, '_ensure_worker', lambda: True)
    monkeypatch.setattr(
        compass_git_sync_module,
        '_run_git',
        _git_change_stub(push_success=False, push_output='remote rejected'),
    )

    compass_git_sync_module.git_sync_async('state/daily.json', 'state/latest.json')
    compass_git_sync_module._git_queue.put_nowait(None)

    with caplog.at_level(logging.WARNING):
        compass_git_sync_module._git_worker()

    assert 'git push failed (will retry next cycle): remote rejected' in caplog.text


def test_ensure_git_identity_logs_failures_without_crashing(compass_git_sync_module, monkeypatch, caplog):
    responses = iter([
        SimpleNamespace(returncode=1, stdout='', stderr='missing user.name'),
        SimpleNamespace(returncode=1, stdout='', stderr='cannot set user.name'),
        SimpleNamespace(returncode=1, stdout='', stderr='cannot set user.email'),
    ])

    monkeypatch.setattr(compass_git_sync_module.subprocess, 'run', lambda *args, **kwargs: next(responses))

    with caplog.at_level(logging.WARNING):
        compass_git_sync_module._ensure_git_identity()

    assert 'git config failed' in caplog.text
    assert 'cannot set user.name' in caplog.text
    assert 'cannot set user.email' in caplog.text


def test_git_worker_continues_processing_after_three_consecutive_failures(
    compass_git_sync_module,
    monkeypatch,
    caplog,
):
    commit_messages = []
    monkeypatch.setattr(
        compass_git_sync_module,
        '_run_git',
        _git_change_stub(
            commit_messages=commit_messages,
            commit_success=False,
            commit_output='commit failed',
        ),
    )

    for idx in range(3):
        compass_git_sync_module._git_queue.put_nowait(
            {'files': [f'state/failure_{idx}.json'], 'message': f'failure-{idx}'}
        )
    compass_git_sync_module._git_queue.put_nowait(None)

    with caplog.at_level(logging.WARNING):
        compass_git_sync_module._git_worker()

    assert commit_messages == ['failure-0', 'failure-1', 'failure-2']
    assert caplog.text.count('git commit failed: commit failed') == 3


def test_git_worker_processes_rapid_sync_requests_in_order(compass_git_sync_module, monkeypatch):
    processed_state_files = []
    monkeypatch.setattr(compass_git_sync_module, 'MIN_COMMIT_INTERVAL', 0)
    monkeypatch.setattr(compass_git_sync_module, '_ensure_worker', lambda: True)
    monkeypatch.setattr(
        compass_git_sync_module,
        '_run_git',
        _git_change_stub(processed_state_files=processed_state_files),
    )

    for idx in range(10):
        compass_git_sync_module.git_sync_async(
            f'state/request_{idx}.json',
            'state/compass_state_latest.json',
        )

    compass_git_sync_module._git_queue.put_nowait(None)
    compass_git_sync_module._git_worker()

    assert processed_state_files == [
        f'state/request_{idx}.json' for idx in range(10)
    ]
