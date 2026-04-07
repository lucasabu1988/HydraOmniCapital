"""End-to-end Catalyst backtest with real data. Slow, requires data_cache/."""
from pathlib import Path

import pandas as pd
import pytest

from hydra_backtest.catalyst import (
    run_catalyst_backtest,
    run_catalyst_smoke_tests,
)
from hydra_backtest.data import load_catalyst_assets, load_yield_series

DATA_PKL = Path('data_cache/catalyst_assets.pkl')
AAA_CSV = Path('data_cache/moody_aaa_yield.csv')


def _load_inputs():
    asset_data = load_catalyst_assets(str(DATA_PKL))
    aaa = load_yield_series(
        str(AAA_CSV), date_col='observation_date', value_col='yield_pct'
    )
    all_dates = sorted({d for df in asset_data.values() for d in df.index})
    aaa_daily = aaa.reindex(all_dates).ffill().fillna(0.0)
    return asset_data, aaa_daily


@pytest.mark.slow
@pytest.mark.skipif(not DATA_PKL.exists(),
                    reason="data_cache/catalyst_assets.pkl not built (Task 14)")
@pytest.mark.skipif(not AAA_CSV.exists(),
                    reason="data_cache/moody_aaa_yield.csv missing")
def test_e2e_2year_window():
    """Real-data 2-year run + Layer A smoke tests."""
    asset_data, aaa_daily = _load_inputs()
    config = {'INITIAL_CAPITAL': 100_000.0, 'COMMISSION_PER_SHARE': 0.0035}
    result = run_catalyst_backtest(
        config, asset_data, aaa_daily,
        pd.Timestamp('2020-01-01'), pd.Timestamp('2021-12-31'),
        execution_mode='same_close',
    )
    run_catalyst_smoke_tests(result)
    assert len(result.daily_values) > 100
    assert (result.daily_values['n_positions'] >= 0).all()
    assert (result.daily_values['n_positions'] <= 4).all()


@pytest.mark.slow
@pytest.mark.skipif(not DATA_PKL.exists(),
                    reason="data_cache/catalyst_assets.pkl not built (Task 14)")
@pytest.mark.skipif(not AAA_CSV.exists(),
                    reason="data_cache/moody_aaa_yield.csv missing")
def test_e2e_determinism():
    """Two consecutive runs must produce byte-identical daily output."""
    asset_data, aaa_daily = _load_inputs()
    config = {'INITIAL_CAPITAL': 100_000.0, 'COMMISSION_PER_SHARE': 0.0035}
    r1 = run_catalyst_backtest(
        config, asset_data, aaa_daily,
        pd.Timestamp('2020-01-01'), pd.Timestamp('2020-12-31'),
    )
    r2 = run_catalyst_backtest(
        config, asset_data, aaa_daily,
        pd.Timestamp('2020-01-01'), pd.Timestamp('2020-12-31'),
    )
    pd.testing.assert_frame_equal(r1.daily_values, r2.daily_values)
    pd.testing.assert_frame_equal(r1.trades, r2.trades)
