import json
import os
import tempfile

import pytest


# ---------------------------------------------------------------------------
# Helpers — replicate the cycle-log data contract from omnicapital_live.py
# (_update_cycle_log, _ensure_active_cycle, _update_cycle_log_stop)
# ---------------------------------------------------------------------------

ALL_CYCLE_FIELDS = {
    'cycle', 'start_date', 'end_date', 'status', 'portfolio_start',
    'portfolio_end', 'spy_start', 'spy_end', 'positions',
    'positions_current', 'hydra_return', 'spy_return', 'alpha',
    'stop_events', 'positions_detail', 'sector_breakdown',
    'exits_by_reason', 'cycle_return_pct', 'spy_return_pct', 'alpha_pct',
}


def _new_cycle(cycle_number, start_date, portfolio_start, spy_start,
               positions):
    """Build an active cycle dict following the schema in _update_cycle_log."""
    return {
        'cycle': cycle_number,
        'start_date': start_date,
        'end_date': None,
        'status': 'active',
        'portfolio_start': round(portfolio_start, 2),
        'portfolio_end': None,
        'spy_start': round(spy_start, 2) if spy_start else None,
        'spy_end': None,
        'positions': list(positions),
        'positions_current': list(positions),
        'hydra_return': None,
        'spy_return': None,
        'alpha': None,
        'stop_events': [],
        'positions_detail': [],
        'sector_breakdown': {},
        'exits_by_reason': {},
        'cycle_return_pct': None,
        'spy_return_pct': None,
        'alpha_pct': None,
    }


def _close_cycle(cycle, end_date, spy_end, pre_rot_positions, prices):
    """Close a cycle using the exact formulas from _update_cycle_log."""
    cycle['end_date'] = end_date
    cycle['status'] = 'closed'

    # SPY return
    if spy_end and cycle.get('spy_start'):
        cycle['spy_end'] = round(spy_end, 2)
        cycle['spy_return'] = round(
            (spy_end - cycle['spy_start']) / cycle['spy_start'] * 100, 2)

    # HYDRA return (holdings-only, excludes cash)
    invested_now = sum(
        p['shares'] * prices.get(sym, p['avg_cost'])
        for sym, p in pre_rot_positions.items())
    invested_at_cost = sum(
        p['shares'] * p['avg_cost']
        for p in pre_rot_positions.values())
    if invested_at_cost > 0:
        cycle['hydra_return'] = round(
            (invested_now / invested_at_cost - 1) * 100, 2)
    else:
        cycle['hydra_return'] = 0.0

    # Alpha
    if cycle.get('hydra_return') is not None and cycle.get('spy_return') is not None:
        cycle['alpha'] = round(cycle['hydra_return'] - cycle['spy_return'], 2)

    # Portfolio end (cash + holdings at close prices)
    portfolio_end = sum(
        p['shares'] * prices.get(sym, p['avg_cost'])
        for sym, p in pre_rot_positions.items())
    cycle['portfolio_end'] = round(portfolio_end, 2)
    if cycle.get('portfolio_start'):
        cycle['cycle_return_pct'] = round(
            (cycle['portfolio_end'] - cycle['portfolio_start']) / cycle['portfolio_start'] * 100, 2)
    cycle['spy_return_pct'] = cycle.get('spy_return')
    if cycle.get('cycle_return_pct') is not None and cycle.get('spy_return_pct') is not None:
        cycle['alpha_pct'] = round(cycle['cycle_return_pct'] - cycle['spy_return_pct'], 2)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestNewCycleCreation:

    def test_new_cycle_has_all_required_fields(self):
        cycle = _new_cycle(1, '2026-03-06', 100_000.0, 5800.0,
                           ['AAPL', 'MSFT', 'NVDA'])
        assert set(cycle.keys()) == ALL_CYCLE_FIELDS

    def test_new_cycle_stores_correct_values(self):
        cycle = _new_cycle(3, '2026-03-17', 105_000.0, 5850.0,
                           ['GOOG', 'AMZN'])
        assert cycle['cycle'] == 3
        assert cycle['start_date'] == '2026-03-17'
        assert cycle['status'] == 'active'
        assert cycle['portfolio_start'] == 105_000.0
        assert cycle['spy_start'] == 5850.0
        assert cycle['positions'] == ['GOOG', 'AMZN']
        assert cycle['positions_current'] == ['GOOG', 'AMZN']

    def test_new_cycle_has_null_end_fields(self):
        cycle = _new_cycle(1, '2026-03-06', 100_000.0, 5800.0, ['AAPL'])
        assert cycle['end_date'] is None
        assert cycle['portfolio_end'] is None
        assert cycle['spy_end'] is None
        assert cycle['hydra_return'] is None
        assert cycle['spy_return'] is None
        assert cycle['alpha'] is None
        assert cycle['stop_events'] == []
        assert cycle['positions_detail'] == []
        assert cycle['sector_breakdown'] == {}
        assert cycle['exits_by_reason'] == {}
        assert cycle['cycle_return_pct'] is None
        assert cycle['spy_return_pct'] is None
        assert cycle['alpha_pct'] is None


class TestCycleClosure:

    def test_closure_sets_status_to_closed(self):
        cycle = _new_cycle(1, '2026-03-06', 100_000.0, 5800.0,
                           ['AAPL', 'MSFT'])
        pre_rot = {
            'AAPL': {'shares': 100, 'avg_cost': 200.0},
            'MSFT': {'shares': 50, 'avg_cost': 400.0},
        }
        prices = {'AAPL': 210.0, 'MSFT': 420.0}
        _close_cycle(cycle, '2026-03-12', 5900.0, pre_rot, prices)
        assert cycle['status'] == 'closed'
        assert cycle['end_date'] == '2026-03-12'

    def test_spy_return_calculation(self):
        cycle = _new_cycle(1, '2026-03-06', 100_000.0, 5800.0, ['AAPL'])
        pre_rot = {'AAPL': {'shares': 100, 'avg_cost': 200.0}}
        _close_cycle(cycle, '2026-03-12', 5916.0, pre_rot, {'AAPL': 200.0})

        expected_spy_return = round((5916.0 - 5800.0) / 5800.0 * 100, 2)
        assert cycle['spy_return'] == pytest.approx(expected_spy_return)
        assert cycle['spy_end'] == 5916.0

    def test_hydra_return_calculation(self):
        cycle = _new_cycle(1, '2026-03-06', 100_000.0, 5800.0,
                           ['AAPL', 'MSFT'])
        pre_rot = {
            'AAPL': {'shares': 100, 'avg_cost': 200.0},  # cost = 20000
            'MSFT': {'shares': 50, 'avg_cost': 400.0},   # cost = 20000
        }
        prices = {'AAPL': 210.0, 'MSFT': 380.0}
        _close_cycle(cycle, '2026-03-12', 5800.0, pre_rot, prices)

        # invested_now  = 100*210 + 50*380 = 21000 + 19000 = 40000
        # invested_cost = 100*200 + 50*400 = 20000 + 20000 = 40000
        # hydra_return  = (40000/40000 - 1) * 100 = 0.0%
        assert cycle['hydra_return'] == pytest.approx(0.0)

    def test_hydra_return_with_gains(self):
        cycle = _new_cycle(1, '2026-03-06', 100_000.0, 5800.0, ['NVDA'])
        pre_rot = {'NVDA': {'shares': 200, 'avg_cost': 500.0}}
        prices = {'NVDA': 530.0}
        _close_cycle(cycle, '2026-03-12', 5800.0, pre_rot, prices)

        # invested_now = 200*530 = 106000, cost = 200*500 = 100000
        # return = (106000/100000 - 1) * 100 = 6.0%
        assert cycle['hydra_return'] == pytest.approx(6.0)

    def test_alpha_equals_hydra_minus_spy(self):
        cycle = _new_cycle(1, '2026-03-06', 100_000.0, 5800.0, ['AAPL'])
        pre_rot = {'AAPL': {'shares': 100, 'avg_cost': 200.0}}
        prices = {'AAPL': 210.0}
        _close_cycle(cycle, '2026-03-12', 5858.0, pre_rot, prices)

        # hydra = (21000/20000 - 1)*100 = 5.0%
        # spy   = (5858 - 5800)/5800*100 = 1.0%
        # alpha = 5.0 - 1.0 = 4.0
        assert cycle['hydra_return'] == pytest.approx(5.0)
        assert cycle['spy_return'] == pytest.approx(1.0)
        assert cycle['alpha'] == pytest.approx(4.0)

    def test_hydra_return_zero_when_no_positions(self):
        cycle = _new_cycle(1, '2026-03-06', 100_000.0, 5800.0, [])
        _close_cycle(cycle, '2026-03-12', 5800.0, {}, {})
        assert cycle['hydra_return'] == 0.0

    def test_cycle_return_pct_uses_portfolio_start_and_end(self):
        cycle = _new_cycle(1, '2026-03-06', 100_000.0, 5800.0, ['AAPL'])
        pre_rot = {'AAPL': {'shares': 100, 'avg_cost': 200.0}}
        _close_cycle(cycle, '2026-03-12', 5858.0, pre_rot, {'AAPL': 210.0})

        assert cycle['portfolio_end'] == 21_000.0
        assert cycle['cycle_return_pct'] == -79.0
        assert cycle['spy_return_pct'] == pytest.approx(1.0)
        assert cycle['alpha_pct'] == pytest.approx(-80.0)


class TestCycleLogSerialization:

    def test_cycle_log_roundtrips_through_json(self):
        cycles = [
            _new_cycle(1, '2026-03-06', 100_000.0, 5800.0,
                       ['AAPL', 'MSFT', 'NVDA']),
        ]
        serialized = json.dumps(cycles, indent=2)
        deserialized = json.loads(serialized)

        assert deserialized == cycles
        assert isinstance(deserialized, list)
        assert deserialized[0]['cycle'] == 1

    def test_closed_cycle_roundtrips_through_json(self):
        cycle = _new_cycle(1, '2026-03-06', 100_000.0, 5800.0, ['AAPL'])
        pre_rot = {'AAPL': {'shares': 100, 'avg_cost': 200.0}}
        _close_cycle(cycle, '2026-03-12', 5900.0, pre_rot, {'AAPL': 210.0})

        serialized = json.dumps([cycle], indent=2)
        restored = json.loads(serialized)[0]

        assert restored['status'] == 'closed'
        assert restored['hydra_return'] == cycle['hydra_return']
        assert restored['spy_return'] == cycle['spy_return']
        assert restored['alpha'] == cycle['alpha']

    def test_atomic_write_produces_valid_json_file(self, tmp_path):
        cycles = [_new_cycle(1, '2026-03-06', 100_000.0, 5800.0, ['AAPL'])]
        log_file = tmp_path / 'cycle_log.json'

        fd, tmp_file = tempfile.mkstemp(dir=str(tmp_path), suffix='.json.tmp')
        with os.fdopen(fd, 'w') as fp:
            json.dump(cycles, fp, indent=2)
        os.replace(tmp_file, str(log_file))

        with open(log_file, 'r') as f:
            loaded = json.load(f)
        assert loaded == cycles


class TestEmptyCycleLog:

    def test_empty_log_is_valid_json_list(self):
        cycles = []
        assert json.dumps(cycles) == '[]'
        assert json.loads('[]') == []

    def test_next_cycle_number_defaults_to_one_on_empty_log(self):
        cycles = []
        next_cycle = max((c.get('cycle', 0) for c in cycles), default=0) + 1
        assert next_cycle == 1


class TestMultipleCyclesAccumulating:

    def test_three_cycles_accumulate_correctly(self):
        cycles = []
        positions_sequence = [
            ['AAPL', 'MSFT', 'NVDA'],
            ['GOOG', 'AMZN', 'META'],
            ['TSLA', 'V', 'JPM'],
        ]

        for i, positions in enumerate(positions_sequence, start=1):
            start_value = 100_000.0 + (i - 1) * 2_000
            spy_start = 5800.0 + (i - 1) * 50
            cycle = _new_cycle(i, f'2026-03-{6 + (i-1)*5:02d}',
                               start_value, spy_start, positions)
            cycles.append(cycle)

        assert len(cycles) == 3
        assert [c['cycle'] for c in cycles] == [1, 2, 3]
        assert all(c['status'] == 'active' for c in cycles)

    def test_next_cycle_number_increments_from_max_existing(self):
        cycles = [
            _new_cycle(1, '2026-03-06', 100_000.0, 5800.0, ['AAPL']),
            _new_cycle(2, '2026-03-11', 102_000.0, 5850.0, ['MSFT']),
        ]
        next_cycle = max((c.get('cycle', 0) for c in cycles), default=0) + 1
        assert next_cycle == 3

    def test_closed_then_new_cycle_preserves_history(self):
        cycle1 = _new_cycle(1, '2026-03-06', 100_000.0, 5800.0,
                            ['AAPL', 'MSFT'])
        pre_rot = {
            'AAPL': {'shares': 100, 'avg_cost': 200.0},
            'MSFT': {'shares': 50, 'avg_cost': 400.0},
        }
        prices = {'AAPL': 210.0, 'MSFT': 420.0}
        _close_cycle(cycle1, '2026-03-12', 5900.0, pre_rot, prices)

        cycle2 = _new_cycle(2, '2026-03-12',
                            cycle1['portfolio_end'], cycle1['spy_end'],
                            ['GOOG', 'NVDA'])

        cycles = [cycle1, cycle2]

        assert cycles[0]['status'] == 'closed'
        assert cycles[1]['status'] == 'active'
        assert cycles[1]['portfolio_start'] == cycles[0]['portfolio_end']
        assert cycles[1]['spy_start'] == cycles[0]['spy_end']
