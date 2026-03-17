import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

import compass_ml_learning as ml


class StubFeatureStore:
    def __init__(self, outcomes):
        self._outcomes = pd.DataFrame(outcomes)

    def load_outcomes(self):
        return self._outcomes.copy()


def test_stop_parameter_optimizer_returns_insufficient_data_for_small_samples():
    optimizer = ml.StopParameterOptimizer(StubFeatureStore([
        {'entry_daily_vol': 0.01, 'was_stopped': True, 'gross_return': -0.03},
        {'entry_daily_vol': 0.02, 'was_stopped': False, 'gross_return': 0.02},
        {'entry_daily_vol': 0.03, 'was_stopped': True, 'gross_return': -0.05},
        {'entry_daily_vol': 0.04, 'was_stopped': False, 'gross_return': 0.01},
    ]))

    result = optimizer.analyze()

    assert result['status'] == 'insufficient_data'
    assert result['n'] == 4


def test_stop_parameter_optimizer_suggests_looser_floor_for_low_vol_stopouts():
    optimizer = ml.StopParameterOptimizer(StubFeatureStore([
        {'entry_daily_vol': 0.010, 'was_stopped': True, 'gross_return': -0.03},
        {'entry_daily_vol': 0.011, 'was_stopped': True, 'gross_return': -0.035},
        {'entry_daily_vol': 0.012, 'was_stopped': True, 'gross_return': -0.025},
        {'entry_daily_vol': 0.020, 'was_stopped': False, 'gross_return': 0.01},
        {'entry_daily_vol': 0.022, 'was_stopped': False, 'gross_return': 0.02},
    ]))

    result = optimizer.analyze()

    floor_suggestion = next(
        suggestion for suggestion in result['suggestions']
        if suggestion['parameter'] == 'STOP_FLOOR'
    )

    assert result['n_outcomes'] == 5
    assert result['n_stops'] == 3
    assert floor_suggestion['direction'] == 'loosen'
    assert floor_suggestion['confidence'] == 'low'
    assert floor_suggestion['n_observations'] == 3
    assert any('Stopped positions avg return' in warning for warning in result['warnings'])


def test_stop_parameter_optimizer_suggests_tighter_ceiling_for_high_vol_names():
    optimizer = ml.StopParameterOptimizer(StubFeatureStore([
        {'entry_daily_vol': 0.040, 'was_stopped': False, 'gross_return': 0.03},
        {'entry_daily_vol': 0.050, 'was_stopped': False, 'gross_return': 0.015},
        {'entry_daily_vol': 0.060, 'was_stopped': False, 'gross_return': -0.005},
        {'entry_daily_vol': 0.018, 'was_stopped': True, 'gross_return': -0.06},
        {'entry_daily_vol': 0.019, 'was_stopped': False, 'gross_return': 0.01},
    ]))

    result = optimizer.analyze()

    ceiling_suggestion = next(
        suggestion for suggestion in result['suggestions']
        if suggestion['parameter'] == 'STOP_CEILING'
    )

    assert result['n_outcomes'] == 5
    assert ceiling_suggestion['direction'] == 'tighten'
    assert ceiling_suggestion['n_observations'] == 3
    assert 'high_vol' in ceiling_suggestion['reasoning']


def test_stop_parameter_optimizer_handles_zero_variance_volatility_without_division_error():
    optimizer = ml.StopParameterOptimizer(StubFeatureStore([
        {'entry_daily_vol': 0.020, 'was_stopped': False, 'gross_return': 0.01},
        {'entry_daily_vol': 0.020, 'was_stopped': False, 'gross_return': 0.00},
        {'entry_daily_vol': 0.020, 'was_stopped': True, 'gross_return': -0.06},
        {'entry_daily_vol': 0.020, 'was_stopped': False, 'gross_return': 0.02},
        {'entry_daily_vol': 0.020, 'was_stopped': True, 'gross_return': -0.06},
        {'entry_daily_vol': 0.020, 'was_stopped': False, 'gross_return': 0.03},
    ]))

    result = optimizer.analyze()

    assert result['n_outcomes'] == 6
    assert result['n_stops'] == 2
    assert result['suggestions'] == []
    assert result['warnings'] == []


def test_stop_parameter_optimizer_does_not_warn_when_stops_cluster_at_floor():
    optimizer = ml.StopParameterOptimizer(StubFeatureStore([
        {'entry_daily_vol': 0.010, 'was_stopped': True, 'gross_return': -0.06},
        {'entry_daily_vol': 0.011, 'was_stopped': True, 'gross_return': -0.06},
        {'entry_daily_vol': 0.012, 'was_stopped': True, 'gross_return': -0.06},
        {'entry_daily_vol': 0.013, 'was_stopped': True, 'gross_return': -0.06},
        {'entry_daily_vol': 0.020, 'was_stopped': False, 'gross_return': 0.02},
    ]))

    result = optimizer.analyze()

    assert result['n_outcomes'] == 5
    assert result['n_stops'] == 4
    assert not any('Stopped positions avg return' in warning for warning in result['warnings'])
