"""End-to-end EFA backtest with real data. Slow, requires data_cache/."""
from pathlib import Path

import pandas as pd
import pytest

from hydra_backtest.data import load_efa_series, load_yield_series
from hydra_backtest.efa import run_efa_backtest, run_efa_smoke_tests

DATA_PKL = Path('data_cache/efa_history.pkl')
AAA_CSV = Path('data_cache/moody_aaa_yield.csv')


def _load_inputs():
    efa_data = load_efa_series(str(DATA_PKL))
    aaa = load_yield_series(
        str(AAA_CSV), date_col='observation_date', value_col='yield_pct'
    )
    aaa_daily = aaa.reindex(efa_data.index).ffill().fillna(0.0)
    return efa_data, aaa_daily


@pytest.mark.slow
@pytest.mark.skipif(not DATA_PKL.exists(),
                    reason="data_cache/efa_history.pkl not built (Task 15)")
@pytest.mark.skipif(not AAA_CSV.exists(),
                    reason="data_cache/moody_aaa_yield.csv missing")
def test_e2e_2year_window():
    """Real-data 2-year run + Layer A smoke tests."""
    efa_data, aaa_daily = _load_inputs()
    config = {'INITIAL_CAPITAL': 100_000.0, 'COMMISSION_PER_SHARE': 0.0035}
    result = run_efa_backtest(
        config, efa_data, aaa_daily,
        pd.Timestamp('2020-01-01'), pd.Timestamp('2021-12-31'),
        execution_mode='same_close',
    )
    run_efa_smoke_tests(result)
    assert len(result.daily_values) > 100
    assert (result.daily_values['n_positions'] >= 0).all()
    assert (result.daily_values['n_positions'] <= 1).all()


@pytest.mark.slow
@pytest.mark.skipif(not DATA_PKL.exists(),
                    reason="data_cache/efa_history.pkl not built (Task 15)")
@pytest.mark.skipif(not AAA_CSV.exists(),
                    reason="data_cache/moody_aaa_yield.csv missing")
def test_e2e_determinism():
    """Two consecutive runs must produce byte-identical daily output."""
    efa_data, aaa_daily = _load_inputs()
    config = {'INITIAL_CAPITAL': 100_000.0, 'COMMISSION_PER_SHARE': 0.0035}
    r1 = run_efa_backtest(
        config, efa_data, aaa_daily,
        pd.Timestamp('2020-01-01'), pd.Timestamp('2020-12-31'),
    )
    r2 = run_efa_backtest(
        config, efa_data, aaa_daily,
        pd.Timestamp('2020-01-01'), pd.Timestamp('2020-12-31'),
    )
    pd.testing.assert_frame_equal(r1.daily_values, r2.daily_values)
    pd.testing.assert_frame_equal(r1.trades, r2.trades)
