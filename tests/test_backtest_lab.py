import sys
import pytest
import numpy as np
import pandas as pd


@pytest.fixture(autouse=True)
def _isolate_backtest_lab():
    """Remove omnicapital_live from sys.modules so backtest_lab's safety check passes."""
    removed = {}
    for mod_name in list(sys.modules):
        if 'omnicapital_live' in mod_name:
            removed[mod_name] = sys.modules.pop(mod_name)
    # Also clear backtest_lab so it reimports fresh with the check
    sys.modules.pop('backtest_lab', None)
    yield
    # Restore
    sys.modules.update(removed)


def test_patch_and_restore():
    """Verify module attributes are restored after experiment."""
    import omnicapital_v84_compass as v84
    original_top_n = v84.TOP_N

    from backtest_lab import _patch_module, _restore_module

    patches = {'TOP_N': 80}
    originals = _patch_module(v84, patches)
    assert v84.TOP_N == 80
    _restore_module(v84, originals)
    assert v84.TOP_N == original_top_n


def test_safety_assertion():
    """Verify lab has safety check enabled."""
    from backtest_lab import SAFETY_CHECK
    assert SAFETY_CHECK is True


def test_universe_80_patches_top_n():
    """Universe experiment patches TOP_N to 80."""
    import omnicapital_v84_compass as v84
    from backtest_lab import _patch_module, _restore_module

    patches = {'TOP_N': 80}
    originals = _patch_module(v84, patches)
    assert v84.TOP_N == 80
    _restore_module(v84, originals)
    assert v84.TOP_N == 40


# ─── Correlation filter tests ───────────────────────────────

def test_correlation_filter_reduces_correlated_picks():
    """Highly correlated candidates should be penalized."""
    from backtest_lab import correlation_aware_filter

    dates = pd.date_range('2020-01-01', periods=60, freq='B')
    base = np.cumsum(np.random.RandomState(666).randn(60)) + 100
    noise = np.cumsum(np.random.RandomState(42).randn(60)) + 100

    price_data = {
        'A': pd.DataFrame({'Close': base}, index=dates),
        'B': pd.DataFrame({'Close': base * 1.01 + 0.5}, index=dates),
        'C': pd.DataFrame({'Close': noise}, index=dates),
    }

    candidates = [('B', 1.0), ('C', 0.95)]
    already_selected = ['A']

    result = correlation_aware_filter(
        candidates, already_selected, price_data, dates[-1], lookback=60
    )

    symbols = [s for s, _ in result]
    assert symbols[0] == 'C', f"Expected C first (uncorrelated), got {symbols[0]}"


def test_correlation_filter_empty_positions():
    """First candidate should get zero penalty (no positions to correlate against)."""
    from backtest_lab import correlation_aware_filter

    dates = pd.date_range('2020-01-01', periods=60, freq='B')
    price_data = {
        'A': pd.DataFrame({'Close': np.random.RandomState(1).randn(60).cumsum() + 100}, index=dates),
    }
    candidates = [('A', 1.0)]
    result = correlation_aware_filter(candidates, [], price_data, dates[-1], lookback=60)
    assert len(result) == 1
    assert result[0][1] == 1.0


def test_correlation_wrapper_returns_list_of_strings():
    """Wrapper must return List[str] to match v84's filter_by_sector_concentration."""
    from backtest_lab import make_correlation_filter_wrapper, _current_sim_date

    dates = pd.date_range('2020-01-01', periods=60, freq='B')
    base = np.cumsum(np.random.RandomState(666).randn(60)) + 100
    noise = np.cumsum(np.random.RandomState(42).randn(60)) + 100
    price_data = {
        'A': pd.DataFrame({'Close': base}, index=dates),
        'B': pd.DataFrame({'Close': base * 1.01}, index=dates),
        'C': pd.DataFrame({'Close': noise}, index=dates),
    }

    ranked = [('A', 1.0), ('B', 0.9), ('C', 0.8)]
    positions = {'A': {'shares': 10}}

    _current_sim_date[0] = dates[-1]
    wrapper = make_correlation_filter_wrapper(price_data)
    result = wrapper(ranked, positions)

    assert all(isinstance(s, str) for s in result)


# ─── Risk parity tests ─────────────────────────────────────

def test_risk_parity_weights_sum_to_one():
    """Risk parity weights must sum to 1.0."""
    from backtest_lab import compute_risk_parity_weights

    dates = pd.date_range('2020-01-01', periods=120, freq='B')
    rs = np.random.RandomState(666)
    price_data = {}
    for sym in ['A', 'B', 'C']:
        price_data[sym] = pd.DataFrame(
            {'Close': 100 + rs.randn(120).cumsum()},
            index=dates
        )

    weights = compute_risk_parity_weights(price_data, ['A', 'B', 'C'], dates[-1])
    assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_risk_parity_equalizes_risk_contributions():
    """Risk parity should produce roughly equal risk contributions."""
    from backtest_lab import compute_risk_parity_weights, _ledoit_wolf_shrink

    dates = pd.date_range('2020-01-01', periods=120, freq='B')
    rs = np.random.RandomState(666)

    price_data = {}
    for sym in ['A', 'B', 'C']:
        price_data[sym] = pd.DataFrame(
            {'Close': 100 + rs.randn(120).cumsum() * 0.5},
            index=dates
        )

    weights = compute_risk_parity_weights(price_data, ['A', 'B', 'C'], dates[-1])

    # Verify risk contributions are roughly equal
    w = np.array([weights['A'], weights['B'], weights['C']])
    rets = np.column_stack([
        price_data[s]['Close'].pct_change().dropna().tail(60).values
        for s in ['A', 'B', 'C']
    ])
    cov = np.cov(rets, rowvar=False)
    mrc = w * (cov @ w)
    rc = mrc / mrc.sum()

    # Each risk contribution should be close to 1/3
    for i, r in enumerate(rc):
        assert abs(r - 1/3) < 0.1, f"Risk contribution {i} = {r:.3f}, expected ~0.333"


def test_risk_parity_fallback_on_singular():
    """Fallback to equal weight when cov matrix is degenerate."""
    from backtest_lab import compute_risk_parity_weights

    dates = pd.date_range('2020-01-01', periods=10, freq='B')
    price_data = {
        'A': pd.DataFrame({'Close': [100]*10}, index=dates),
        'B': pd.DataFrame({'Close': [100]*10}, index=dates),
    }

    weights = compute_risk_parity_weights(price_data, ['A', 'B'], dates[-1])
    assert len(weights) == 2
    assert all(w >= 0 for w in weights.values())
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    assert abs(weights['A'] - 0.5) < 0.1
