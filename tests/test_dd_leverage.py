import pytest

from compass_montecarlo import _dd_leverage as mc_dd_leverage
from omnicapital_live import _dd_leverage as live_dd_leverage


V84_CONFIG = {
    'DD_SCALE_TIER1': -0.10,
    'DD_SCALE_TIER2': -0.20,
    'DD_SCALE_TIER3': -0.35,
    'LEV_FULL': 1.0,
    'LEV_MID': 0.60,
    'LEV_FLOOR': 0.30,
}


@pytest.mark.parametrize("drawdown", [
    0,
    -0.05,
    -0.10,
    -0.15,
    -0.20,
    -0.25,
    -0.35,
    -0.50,
])
def test_dd_leverage_cross_module_consistency(drawdown):
    """Both _dd_leverage implementations must return the same result."""
    result_live = live_dd_leverage(drawdown, V84_CONFIG)
    result_mc = mc_dd_leverage(drawdown, V84_CONFIG)
    # If they ever diverge, this assertion will flag the discrepancy.
    # Do NOT fix either implementation — just report.
    assert result_live == pytest.approx(result_mc), (
        f"Discrepancy at drawdown={drawdown}: "
        f"live={result_live}, montecarlo={result_mc}"
    )


@pytest.mark.parametrize("drawdown,expected", [
    # Exactly at T1 boundary (-0.10): should return LEV_FULL
    (-0.10, 1.0),
    # Exactly at T2 boundary (-0.20): should return LEV_MID
    (-0.20, 0.60),
    # Exactly at T3 boundary (-0.35): should return LEV_FLOOR
    (-0.35, 0.30),
])
def test_dd_leverage_boundary_values(drawdown, expected):
    """Boundary values at T1, T2, T3 must match expected leverage."""
    result_live = live_dd_leverage(drawdown, V84_CONFIG)
    result_mc = mc_dd_leverage(drawdown, V84_CONFIG)
    assert result_live == pytest.approx(expected)
    assert result_mc == pytest.approx(expected)


def test_dd_leverage_extreme_drawdown():
    """100% loss must not crash either implementation."""
    drawdown = -1.0
    result_live = live_dd_leverage(drawdown, V84_CONFIG)
    result_mc = mc_dd_leverage(drawdown, V84_CONFIG)
    # Beyond T3: both should return LEV_FLOOR
    assert result_live == pytest.approx(0.30)
    assert result_mc == pytest.approx(0.30)
    assert result_live == pytest.approx(result_mc)
