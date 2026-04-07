"""Integration tests for hydra_backtest.rattlesnake CLI."""
import subprocess
import sys


def test_cli_help():
    """python -m hydra_backtest.rattlesnake --help should succeed."""
    result = subprocess.run(
        [sys.executable, '-m', 'hydra_backtest.rattlesnake', '--help'],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0
    out = result.stdout.lower()
    assert 'start' in out
    assert 'end' in out
    assert 'vix' in out
