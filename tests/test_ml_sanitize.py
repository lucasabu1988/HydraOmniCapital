import builtins
import json
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import compass_ml_learning as ml


def test_sanitize_for_json_replaces_nested_nan_and_infinities():
    payload = {
        'alpha': np.nan,
        'nested': [1.0, np.inf, {'beta': -np.inf}],
    }

    sanitized = ml._sanitize_for_json(payload)

    assert sanitized == {
        'alpha': None,
        'nested': [1.0, None, {'beta': None}],
    }


def test_sanitize_for_json_converts_numpy_arrays_to_lists():
    payload = {
        'matrix': np.array([[1, 2], [3, 4]]),
        'vector': np.array([np.float64(1.5), np.float64(2.5)]),
    }

    sanitized = ml._sanitize_for_json(payload)

    assert sanitized == {
        'matrix': [[1, 2], [3, 4]],
        'vector': [1.5, 2.5],
    }


def test_sanitize_for_json_converts_datetime_objects_to_iso_strings():
    payload = {
        'timestamp': datetime(2026, 3, 16, 9, 30, 15),
        'trade_date': date(2026, 3, 16),
    }

    sanitized = ml._sanitize_for_json(payload)

    assert sanitized == {
        'timestamp': '2026-03-16T09:30:15',
        'trade_date': '2026-03-16',
    }


def test_sanitize_for_json_rejects_circular_references():
    payload = {}
    payload['self'] = payload

    with pytest.raises(ValueError, match='Circular reference'):
        ml._sanitize_for_json(payload)


def test_sanitize_for_json_handles_deeply_nested_structures():
    payload = {'level_0': {}}
    cursor = payload['level_0']
    for level in range(1, 12):
        cursor[f'level_{level}'] = {}
        cursor = cursor[f'level_{level}']
    cursor['leaf'] = np.nan

    sanitized = ml._sanitize_for_json(payload)
    cursor = sanitized['level_0']
    for level in range(1, 12):
        cursor = cursor[f'level_{level}']

    assert cursor['leaf'] is None


def test_sanitize_for_json_preserves_empty_values():
    assert ml._sanitize_for_json({}) == {}
    assert ml._sanitize_for_json([]) == []
    assert ml._sanitize_for_json(None) is None


class StableStringObject:
    def __str__(self):
        return "stable-object"


def test_write_json_file_happy_path_writes_expected_content(tmp_path):
    target = tmp_path / 'payload.json'
    payload = {'alpha': 1, 'beta': [1, 2, 3]}

    ml._write_json_file(target, payload)

    assert json.loads(target.read_text(encoding='utf-8')) == payload


def test_write_json_file_uses_default_serializer_without_corrupting_output(tmp_path):
    target = tmp_path / 'payload.json'
    payload = {'custom': StableStringObject()}

    ml._write_json_file(target, payload)

    assert json.loads(target.read_text(encoding='utf-8')) == {'custom': 'stable-object'}


def test_write_json_file_preserves_original_file_when_replace_fails(monkeypatch, tmp_path):
    target = tmp_path / 'payload.json'
    original = {'status': 'original'}
    target.write_text(json.dumps(original), encoding='utf-8')

    monkeypatch.setattr(ml.os, 'replace', lambda *args, **kwargs: (_ for _ in ()).throw(OSError('replace failed')))

    with pytest.raises(OSError, match='replace failed'):
        ml._write_json_file(target, {'status': 'new'})

    assert json.loads(target.read_text(encoding='utf-8')) == original
    assert not target.with_suffix('.json.tmp').exists()


def test_write_json_file_cleans_partial_tmp_file_when_serializer_fails(tmp_path):
    target = tmp_path / 'payload.json'
    payload = {'custom': StableStringObject()}

    def failing_default(obj):
        raise TypeError('cannot serialize')

    with pytest.raises(TypeError, match='cannot serialize'):
        ml._write_json_file(target, payload, default=failing_default)

    assert not target.exists()
    assert not target.with_suffix('.json.tmp').exists()


def test_write_json_file_raises_permission_error_without_leaving_tmp(monkeypatch, tmp_path):
    target = tmp_path / 'payload.json'
    real_open = builtins.open

    def guarded_open(path, *args, **kwargs):
        if Path(path) == target.with_suffix('.json.tmp'):
            raise PermissionError('read-only directory')
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr('builtins.open', guarded_open)

    with pytest.raises(PermissionError, match='read-only directory'):
        ml._write_json_file(target, {'alpha': 1})

    assert not target.exists()
    assert not target.with_suffix('.json.tmp').exists()
