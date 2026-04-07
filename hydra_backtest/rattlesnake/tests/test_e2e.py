"""End-to-end tests for hydra_backtest.rattlesnake. SLOW.

Run with: pytest hydra_backtest/rattlesnake/tests/test_e2e.py -m slow
"""
import hashlib
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.slow


@pytest.mark.skipif(
    not os.path.exists('data_cache/sp500_universe_prices.pkl'),
    reason="Requires real PIT cache",
)
@pytest.mark.skipif(
    not os.path.exists('data_cache/vix_history.csv'),
    reason="Requires VIX history (download via yfinance ^VIX)",
)
def test_e2e_full_rattlesnake_runs_to_completion(tmp_path):
    """Full Rattlesnake backtest over the available PIT range runs without errors."""
    out = tmp_path / 'run1'
    result = subprocess.run(
        [sys.executable, '-m', 'hydra_backtest.rattlesnake',
         '--start', '2000-01-01',
         '--end', '2026-03-04',
         '--out-dir', str(out)],
        capture_output=True, text=True, timeout=1800,
    )
    assert result.returncode == 0, (
        f"CLI failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert (out / 'rattlesnake_v2_daily.csv').exists()
    assert (out / 'rattlesnake_v2_waterfall.json').exists()
    assert (out / 'rattlesnake_v2_trades.csv').exists()
    for tier in ('baseline', 't_bill', 'next_open', 'real_costs', 'net_honest'):
        assert tier in result.stdout


@pytest.mark.skipif(
    not os.path.exists('data_cache/sp500_universe_prices.pkl'),
    reason="Requires real PIT cache",
)
@pytest.mark.skipif(
    not os.path.exists('data_cache/vix_history.csv'),
    reason="Requires VIX history",
)
def test_e2e_rattlesnake_determinism(tmp_path):
    """Two runs with identical inputs produce byte-identical daily CSVs."""
    out1 = tmp_path / 'run1'
    out2 = tmp_path / 'run2'
    for out_dir in (out1, out2):
        result = subprocess.run(
            [sys.executable, '-m', 'hydra_backtest.rattlesnake',
             '--start', '2010-01-01',
             '--end', '2012-12-31',
             '--out-dir', str(out_dir)],
            capture_output=True, text=True, timeout=900,
        )
        assert result.returncode == 0

    def _sha(path):
        with open(path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()

    assert _sha(out1 / 'rattlesnake_v2_daily.csv') == _sha(out2 / 'rattlesnake_v2_daily.csv')
