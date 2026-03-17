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
