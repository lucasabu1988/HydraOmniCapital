import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from compass_montecarlo import COMPASSMonteCarlo, CYCLE_DAYS, MIN_LIVE_CYCLES


def write_cycle_log(path, cycle_returns_pct):
    payload = []
    for idx, cycle_return in enumerate(cycle_returns_pct, start=1):
        payload.append({
            'cycle': idx,
            'status': 'closed',
            'cycle_return_pct': cycle_return,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')


def write_backtest_daily(path, values):
    df = pd.DataFrame({
        'date': pd.date_range('2025-01-01', periods=len(values), freq='B'),
        'value': values,
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def write_state(path, portfolio_value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'portfolio_value': portfolio_value}, indent=2), encoding='utf-8')


def test_montecarlo_prefers_live_cycle_log_when_enough_cycles(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_cycle_log(tmp_path / 'state' / 'cycle_log.json', [1.5, -0.5, 2.0, 1.2, -0.8, 0.7, 1.0, 0.3])
    write_backtest_daily(tmp_path / 'backtests' / 'hydra_clean_daily.csv', [100000 + (idx * 1000) for idx in range(30)])

    mc = COMPASSMonteCarlo(
        cycle_log_path='state/cycle_log.json',
        daily_csv_path='backtests/hydra_clean_daily.csv',
        n_simulations=128,
    )
    mc.load_input_returns()

    assert mc.source == 'live_cycle_log'
    assert len(mc.cycle_returns) == 8


def test_montecarlo_falls_back_to_backtest_when_live_history_is_short(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_cycle_log(tmp_path / 'state' / 'cycle_log.json', [1.5, -0.5, 2.0])
    write_backtest_daily(
        tmp_path / 'backtests' / 'hydra_clean_daily.csv',
        [100000, 101000, 102500, 103000, 104000, 105500, 106000, 106800, 107500, 108500, 109000, 110000],
    )

    mc = COMPASSMonteCarlo(
        cycle_log_path='state/cycle_log.json',
        daily_csv_path='backtests/hydra_clean_daily.csv',
        n_simulations=128,
    )
    mc.load_input_returns()

    assert mc.source == 'backtest_fallback'
    assert len(mc.cycle_returns) > 0


def test_montecarlo_uses_state_portfolio_value_as_starting_point(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_state(tmp_path / 'state' / 'compass_state_latest.json', 123456.78)
    write_backtest_daily(tmp_path / 'backtests' / 'hydra_clean_daily.csv', [100000 + (idx * 1000) for idx in range(20)])

    mc = COMPASSMonteCarlo(
        cycle_log_path='state/cycle_log.json',
        daily_csv_path='backtests/hydra_clean_daily.csv',
        n_simulations=64,
    )

    assert mc.initial_value == pytest.approx(123456.78)


def test_montecarlo_run_all_returns_expected_summary_shape(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_cycle_log(tmp_path / 'state' / 'cycle_log.json', [1.5, -0.5, 2.0, 1.2, -0.8, 0.7, 1.0, 0.3, -1.1])

    mc = COMPASSMonteCarlo(
        cycle_log_path='state/cycle_log.json',
        daily_csv_path='backtests/hydra_clean_daily.csv',
        n_simulations=256,
    )
    summary = mc.run_all()

    assert summary['seed'] == 666
    assert summary['source'] == 'live_cycle_log'
    assert set(summary['fan_chart'].keys()) == {'days', 'p5', 'p10', 'p25', 'p50', 'p75', 'p90', 'p95'}
    assert len(summary['fan_chart']['days']) == len(summary['fan_chart']['p50'])
    assert 'median_outcome' in summary['summary']
    assert 'prob_gain_10_pct' in summary['summary']


def test_montecarlo_is_reproducible_with_seed_666(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_cycle_log(tmp_path / 'state' / 'cycle_log.json', [1.5, -0.5, 2.0, 1.2, -0.8, 0.7, 1.0, 0.3, -1.1])

    first = COMPASSMonteCarlo(
        cycle_log_path='state/cycle_log.json',
        daily_csv_path='backtests/hydra_clean_daily.csv',
        n_simulations=128,
        seed=666,
    ).run_all()
    second = COMPASSMonteCarlo(
        cycle_log_path='state/cycle_log.json',
        daily_csv_path='backtests/hydra_clean_daily.csv',
        n_simulations=128,
        seed=666,
    ).run_all()

    assert first['summary'] == second['summary']
    assert first['fan_chart']['p50'] == second['fan_chart']['p50']


def test_simulate_paths_vectorized_returns_expected_shape_and_positive_values(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mc = COMPASSMonteCarlo(n_simulations=4, horizon_days=CYCLE_DAYS * 3)
    sampled = np.tile(np.array([[0.01, -0.01, 0.02]]), (4, 1))

    paths = mc._simulate_paths_vectorized(sampled)

    assert paths.shape == (4, 4)
    assert np.all(paths > 0)
    assert paths[0] == pytest.approx([100000.0, 101000.0, 99990.0, 101989.8])


def test_simulate_paths_vectorized_stays_flat_with_zero_returns(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mc = COMPASSMonteCarlo(n_simulations=3, horizon_days=CYCLE_DAYS * 4)
    sampled = np.zeros((3, 4), dtype=float)

    paths = mc._simulate_paths_vectorized(sampled)

    assert np.all(paths == 100000.0)


def test_run_simulation_with_single_positive_return_grows_geometrically(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mc = COMPASSMonteCarlo(n_simulations=3, horizon_days=CYCLE_DAYS * 3, seed=666)
    mc.cycle_returns = np.array([0.10], dtype=float)

    mc.run_simulation()

    expected_path = np.array([100000.0, 110000.0, 121000.0, 133100.0])
    assert mc.paths.shape == (3, 4)
    assert np.allclose(mc.paths, expected_path)


def test_run_simulation_is_reproducible_with_same_seed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    first = COMPASSMonteCarlo(n_simulations=16, horizon_days=CYCLE_DAYS * 5, seed=666)
    second = COMPASSMonteCarlo(n_simulations=16, horizon_days=CYCLE_DAYS * 5, seed=666)
    first.cycle_returns = np.array([0.01, -0.01, 0.02], dtype=float)
    second.cycle_returns = np.array([0.01, -0.01, 0.02], dtype=float)

    first.run_simulation()
    second.run_simulation()

    assert np.array_equal(first.paths, second.paths)


def test_montecarlo_historical_stats_reports_distribution_metrics(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mc = COMPASSMonteCarlo(n_simulations=8)
    mc.source = 'live_cycle_log'
    mc.cycle_returns = np.array([0.02, 0.01, 0.03, 0.0], dtype=float)

    stats = mc._historical_stats()

    assert stats['source'] == 'live_cycle_log'
    assert stats['sample_size'] == 4
    assert stats['avg_cycle_return_pct'] == pytest.approx(1.5)
    assert stats['median_cycle_return_pct'] == pytest.approx(1.5)
    assert stats['cycle_vol_pct'] > 0
    assert stats['win_rate_pct'] == pytest.approx(75.0)


def test_montecarlo_fan_chart_returns_expected_percentile_arrays(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mc = COMPASSMonteCarlo(n_simulations=4, horizon_days=CYCLE_DAYS * 2)
    mc.paths = np.array([
        [100000.0, 110000.0, 120000.0],
        [100000.0, 100000.0, 100000.0],
        [100000.0, 90000.0, 80000.0],
        [100000.0, 105000.0, 115000.0],
    ])

    fan = mc._fan_chart()

    assert set(fan) == {'days', 'p5', 'p10', 'p25', 'p50', 'p75', 'p90', 'p95'}
    assert fan['days'] == [0, 5, 10]
    assert fan['p50'][0] == 100000.0
    assert len(fan['p5']) == 3
    assert fan['p95'][-1] > fan['p5'][-1]


def test_montecarlo_summary_is_positive_for_winning_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mc = COMPASSMonteCarlo(n_simulations=3)
    mc.initial_value = 100000.0
    mc.paths = np.array([
        [100000.0, 105000.0, 110250.0],
        [100000.0, 102000.0, 104040.0],
        [100000.0, 98000.0, 100940.0],
    ])

    summary = mc._summary()

    assert summary['median_outcome'] > mc.initial_value
    assert summary['median_return_pct'] > 0
    assert summary['prob_drawdown_better_than_20_pct'] == pytest.approx(100.0)
    assert summary['median_max_drawdown_pct'] <= 0


def test_montecarlo_summary_is_negative_for_losing_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mc = COMPASSMonteCarlo(n_simulations=3)
    mc.initial_value = 100000.0
    mc.paths = np.array([
        [100000.0, 95000.0, 90000.0],
        [100000.0, 97000.0, 93000.0],
        [100000.0, 96000.0, 92000.0],
    ])

    summary = mc._summary()

    assert summary['median_outcome'] < mc.initial_value
    assert summary['median_return_pct'] < 0
    assert summary['p95_outcome'] < mc.initial_value
    assert summary['median_max_drawdown_pct'] < 0


def test_montecarlo_raises_when_no_cycle_returns_are_available(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_cycle_log(tmp_path / 'state' / 'cycle_log.json', [])
    write_backtest_daily(tmp_path / 'backtests' / 'hydra_clean_daily.csv', [100000.0] * CYCLE_DAYS)

    mc = COMPASSMonteCarlo(
        cycle_log_path='state/cycle_log.json',
        daily_csv_path='backtests/hydra_clean_daily.csv',
        n_simulations=64,
    )

    with pytest.raises(ValueError, match='enough data for 5-day cycles'):
        mc.run_all()


def test_montecarlo_uses_live_cycle_log_at_exact_minimum_threshold(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_cycle_log(
        tmp_path / 'state' / 'cycle_log.json',
        [1.0, -0.8, 0.6, 1.2, -0.5, 0.4, 0.9, -0.3],
    )

    mc = COMPASSMonteCarlo(
        cycle_log_path='state/cycle_log.json',
        daily_csv_path='backtests/hydra_clean_daily.csv',
        n_simulations=64,
    )
    mc.load_input_returns()

    assert mc.source == 'live_cycle_log'
    assert len(mc.cycle_returns) == MIN_LIVE_CYCLES


def test_montecarlo_negative_only_returns_produce_downside_projection(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_cycle_log(
        tmp_path / 'state' / 'cycle_log.json',
        [-2.5, -1.8, -1.2, -2.0, -0.9, -1.5, -2.2, -1.1],
    )

    summary = COMPASSMonteCarlo(
        cycle_log_path='state/cycle_log.json',
        daily_csv_path='backtests/hydra_clean_daily.csv',
        n_simulations=128,
    ).run_all()

    assert summary['source'] == 'live_cycle_log'
    assert summary['summary']['median_return_pct'] < 0
    assert summary['summary']['prob_gain_10_pct'] == 0.0
    assert summary['summary']['p95_outcome'] < summary['initial_value']
