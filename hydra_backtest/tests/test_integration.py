"""Integration tests for hydra_backtest (CLI + end-to-end smoke)."""
import os
import subprocess
import sys

import pytest


def test_cli_help():
    """Running `python -m hydra_backtest --help` should succeed."""
    result = subprocess.run(
        [sys.executable, '-m', 'hydra_backtest', '--help'],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0
    out = result.stdout.lower()
    assert 'start' in out
    assert 'end' in out


@pytest.mark.skipif(
    not os.path.exists('data_cache/sp500_universe_prices.pkl'),
    reason="Requires real PIT cache",
)
def test_package_imports_load_real_data():
    """Smoke check that the real PIT cache can be loaded via the public API."""
    from hydra_backtest import load_pit_universe, load_price_history
    pit = load_pit_universe('data_cache/sp500_constituents_history.pkl')
    prices = load_price_history('data_cache/sp500_universe_prices.pkl')
    assert len(pit) > 0
    assert len(prices) > 0
