import importlib
import os
import sys
from pathlib import Path
from queue import Queue

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
