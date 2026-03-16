import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import omnicapital_live as live


@pytest.mark.parametrize(
    ('entry_daily_vol', 'expected'),
    [
        (0.005, -0.06),
        (0.035, -0.0875),
        (0.060, -0.15),
    ],
)
def test_compute_adaptive_stop_matches_v84_vol_scaling(entry_daily_vol, expected):
    stop = live.compute_adaptive_stop(entry_daily_vol, live.CONFIG)

    assert stop == pytest.approx(expected, abs=1e-4)


def test_compute_adaptive_stop_is_bounded_and_widens_with_volatility():
    vol_points = [0.005, 0.02, 0.035, 0.06]
    stops = [live.compute_adaptive_stop(vol, live.CONFIG) for vol in vol_points]

    assert all(live.CONFIG['STOP_CEILING'] <= stop <= live.CONFIG['STOP_FLOOR'] for stop in stops)
    assert stops == sorted(stops, reverse=True)
    assert stops[0] > stops[-1]


@pytest.mark.parametrize('entry_daily_vol', [0.0, -0.01, None, float('nan'), float('inf')])
def test_compute_adaptive_stop_invalid_inputs_fall_back_to_floor(entry_daily_vol):
    stop = live.compute_adaptive_stop(entry_daily_vol, live.CONFIG)

    assert stop == live.CONFIG['STOP_FLOOR']
