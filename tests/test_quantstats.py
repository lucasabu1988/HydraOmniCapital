import pytest
import pandas as pd
import numpy as np
from pathlib import Path


class TestLoadReturns:
    def test_load_returns_backtest_returns_series(self):
        from compass_quantstats import load_returns, BACKTEST_CSV
        if not BACKTEST_CSV.exists():
            pytest.skip("Backtest CSV not available")
        returns = load_returns(source="backtest")
        assert isinstance(returns, pd.Series)
        assert isinstance(returns.index, pd.DatetimeIndex)
        assert len(returns) > 100

    def test_load_returns_backtest_no_nans(self):
        from compass_quantstats import load_returns, BACKTEST_CSV
        if not BACKTEST_CSV.exists():
            pytest.skip("Backtest CSV not available")
        returns = load_returns(source="backtest")
        assert not returns.isna().any()

    def test_load_returns_live_excludes_today(self):
        from compass_quantstats import load_returns, STATE_JSON
        if not STATE_JSON.exists():
            pytest.skip("State JSON not available")
        returns = load_returns(source="live")
        if len(returns) > 0:
            assert returns.index[-1].date() < pd.Timestamp.now().date()


class TestComputeMetrics:
    @pytest.fixture
    def sample_returns(self):
        np.random.seed(666)
        dates = pd.bdate_range("2020-01-01", periods=252)
        returns = pd.Series(np.random.normal(0.0004, 0.01, 252), index=dates)
        return returns

    def test_compute_metrics_returns_dict(self, sample_returns):
        from compass_quantstats import compute_metrics
        metrics = compute_metrics(sample_returns)
        assert isinstance(metrics, dict)

    def test_compute_metrics_has_required_keys(self, sample_returns):
        from compass_quantstats import compute_metrics
        metrics = compute_metrics(sample_returns)
        required = ['sharpe', 'sortino', 'max_drawdown', 'cagr', 'volatility']
        for key in required:
            assert key in metrics, f"Missing key: {key}"

    def test_compute_metrics_sharpe_reasonable(self, sample_returns):
        from compass_quantstats import compute_metrics
        metrics = compute_metrics(sample_returns)
        assert -3.0 < metrics['sharpe'] < 5.0

    def test_compute_metrics_max_drawdown_negative(self, sample_returns):
        from compass_quantstats import compute_metrics
        metrics = compute_metrics(sample_returns)
        assert metrics['max_drawdown'] <= 0


class TestGenerateTearsheet:
    def test_generate_tearsheet_creates_file(self, tmp_path):
        from compass_quantstats import generate_tearsheet
        np.random.seed(666)
        dates = pd.bdate_range("2020-01-01", periods=252)
        returns = pd.Series(np.random.normal(0.0004, 0.01, 252), index=dates)
        output = str(tmp_path / "test_tearsheet.html")
        result = generate_tearsheet(returns, output_path=output)
        assert Path(result).exists()
        content = Path(result).read_text()
        assert "<html" in content.lower()


class TestRollingMetrics:
    def test_rolling_metrics_shape(self):
        from compass_quantstats import get_rolling_metrics
        np.random.seed(666)
        dates = pd.bdate_range("2020-01-01", periods=252)
        returns = pd.Series(np.random.normal(0.0004, 0.01, 252), index=dates)
        df = get_rolling_metrics(returns, window=63)
        assert isinstance(df, pd.DataFrame)
        assert 'rolling_sharpe' in df.columns
        assert 'rolling_sortino' in df.columns
        assert 'rolling_vol' in df.columns
        assert len(df) == len(returns)
