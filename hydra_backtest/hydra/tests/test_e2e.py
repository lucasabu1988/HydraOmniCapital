"""End-to-end HYDRA backtest with real data. Slow, requires data_cache/."""
from pathlib import Path

import pandas as pd
import pytest

from hydra_backtest.data import (
    load_catalyst_assets,
    load_efa_series,
    load_pit_universe,
    load_price_history,
    load_sector_map,
    load_spy_data,
    load_vix_series,
    load_yield_series,
)
from hydra_backtest.hydra import (
    compute_layer_b_report,
    run_hydra_backtest,
    run_hydra_smoke_tests,
)


PIT_PKL = Path('data_cache/sp500_constituents_history.pkl')
PRICES_PKL = Path('data_cache/sp500_universe_prices.pkl')
SECTORS_JSON = Path('data_cache/sp500_sector_map.json')
SPY_CSV = Path('data_cache/SPY_2000-01-01_2027-01-01.csv')
VIX_CSV = Path('data_cache/vix_history.csv')
CATALYST_PKL = Path('data_cache/catalyst_assets.pkl')
EFA_PKL = Path('data_cache/efa_history.pkl')
AAA_CSV = Path('data_cache/moody_aaa_yield.csv')
TBILL_CSV = Path('data_cache/tbill_3m_fred.csv')

_REQUIRED = [PIT_PKL, PRICES_PKL, SECTORS_JSON, SPY_CSV, VIX_CSV,
             CATALYST_PKL, EFA_PKL, AAA_CSV, TBILL_CSV]


_MIN_CONFIG = {
    'MOMENTUM_LOOKBACK': 90, 'MOMENTUM_SKIP': 5, 'MIN_MOMENTUM_STOCKS': 20,
    'NUM_POSITIONS': 5, 'NUM_POSITIONS_RISK_OFF': 2, 'HOLD_DAYS': 5,
    'HOLD_DAYS_MAX': 10, 'RENEWAL_PROFIT_MIN': 0.04,
    'MOMENTUM_RENEWAL_THRESHOLD': 0.85, 'POSITION_STOP_LOSS': -0.08,
    'TRAILING_ACTIVATION': 0.05, 'TRAILING_STOP_PCT': 0.03,
    'STOP_DAILY_VOL_MULT': 2.5, 'STOP_FLOOR': -0.06, 'STOP_CEILING': -0.15,
    'TRAILING_VOL_BASELINE': 0.25, 'BULL_OVERRIDE_THRESHOLD': 0.03,
    'BULL_OVERRIDE_MIN_SCORE': 0.40, 'MAX_PER_SECTOR': 3,
    'DD_SCALE_TIER1': -0.10, 'DD_SCALE_TIER2': -0.20, 'DD_SCALE_TIER3': -0.35,
    'LEV_FULL': 1.0, 'LEV_MID': 0.60, 'LEV_FLOOR': 0.30,
    'CRASH_VEL_5D': -0.06, 'CRASH_VEL_10D': -0.10, 'CRASH_LEVERAGE': 0.15,
    'CRASH_COOLDOWN': 10, 'QUALITY_VOL_MAX': 0.60, 'QUALITY_VOL_LOOKBACK': 63,
    'QUALITY_MAX_SINGLE_DAY': 0.50, 'TARGET_VOL': 0.15, 'LEVERAGE_MAX': 1.0,
    'VOL_LOOKBACK': 20, 'TOP_N': 40, 'MIN_AGE_DAYS': 63,
    'INITIAL_CAPITAL': 100_000, 'MARGIN_RATE': 0.06,
    'COMMISSION_PER_SHARE': 0.001,
    'BASE_COMPASS_ALLOC': 0.425, 'BASE_RATTLE_ALLOC': 0.425,
    'BASE_CATALYST_ALLOC': 0.15, 'MAX_COMPASS_ALLOC': 0.75,
    'EFA_LIQUIDATION_CASH_THRESHOLD_PCT': 0.20,
}


def _load_all():
    pit = load_pit_universe(str(PIT_PKL))
    prices = load_price_history(str(PRICES_PKL))
    sectors = load_sector_map(str(SECTORS_JSON))
    spy = load_spy_data(str(SPY_CSV))
    vix = load_vix_series(str(VIX_CSV))
    catalyst = load_catalyst_assets(str(CATALYST_PKL))
    efa = load_efa_series(str(EFA_PKL))
    aaa = load_yield_series(
        str(AAA_CSV), date_col='observation_date', value_col='yield_pct'
    )
    return pit, prices, sectors, spy, vix, catalyst, efa, aaa


@pytest.mark.slow
@pytest.mark.timeout(900)
@pytest.mark.skipif(not all(p.exists() for p in _REQUIRED),
                    reason="data_cache missing one or more required files")
def test_e2e_3month_window():
    """Real-data Q1 2020 run + Layer A smoke tests."""
    pit, prices, sectors, spy, vix, catalyst, efa, aaa = _load_all()
    result = run_hydra_backtest(
        config=_MIN_CONFIG, price_data=prices, pit_universe=pit, spy_data=spy,
        vix_data=vix, catalyst_assets=catalyst, efa_data=efa,
        cash_yield_daily=aaa, sector_map=sectors,
        start_date=pd.Timestamp('2020-01-01'),
        end_date=pd.Timestamp('2020-03-31'),
        execution_mode='same_close',
    )
    run_hydra_smoke_tests(result)
    assert len(result.daily_values) > 30
    assert (result.daily_values['n_compass'] >= 0).all()
    assert (result.daily_values['n_catalyst'] <= 4).all()
    assert (result.daily_values['n_efa'] <= 1).all()


@pytest.mark.slow
@pytest.mark.timeout(900)
@pytest.mark.skipif(not all(p.exists() for p in _REQUIRED),
                    reason="data_cache missing one or more required files")
def test_e2e_determinism():
    """Two runs over a 1-month window must produce byte-identical daily output."""
    pit, prices, sectors, spy, vix, catalyst, efa, aaa = _load_all()
    common = dict(
        config=_MIN_CONFIG, price_data=prices, pit_universe=pit, spy_data=spy,
        vix_data=vix, catalyst_assets=catalyst, efa_data=efa,
        cash_yield_daily=aaa, sector_map=sectors,
        start_date=pd.Timestamp('2020-01-01'),
        end_date=pd.Timestamp('2020-01-31'),
    )
    r1 = run_hydra_backtest(**common)
    r2 = run_hydra_backtest(**common)
    pd.testing.assert_frame_equal(r1.daily_values, r2.daily_values)
    pd.testing.assert_frame_equal(r1.trades, r2.trades)


@pytest.mark.slow
@pytest.mark.timeout(900)
@pytest.mark.skipif(not all(p.exists() for p in _REQUIRED),
                    reason="data_cache missing one or more required files")
def test_e2e_layer_b_correlation():
    """Layer B correlation against hydra_clean_daily.csv (informational)."""
    pit, prices, sectors, spy, vix, catalyst, efa, aaa = _load_all()
    result = run_hydra_backtest(
        config=_MIN_CONFIG, price_data=prices, pit_universe=pit, spy_data=spy,
        vix_data=vix, catalyst_assets=catalyst, efa_data=efa,
        cash_yield_daily=aaa, sector_map=sectors,
        start_date=pd.Timestamp('2020-01-01'),
        end_date=pd.Timestamp('2020-06-30'),
        execution_mode='same_close',
    )
    report = compute_layer_b_report(result.daily_values)
    # Informational only — print the verdict but do not assert.
    if report.get('status') == 'COMPLETE':
        print(
            f"\nLayer B: spearman={report['spearman']:.4f}, "
            f"verdict={report['verdict']}, n={report['n_overlap']}",
            flush=True,
        )
    else:
        print(f"\nLayer B: {report['status']} ({report.get('reason')})", flush=True)
