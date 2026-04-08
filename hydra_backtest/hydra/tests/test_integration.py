"""CLI smoke test for hydra_backtest.hydra.

Builds synthetic versions of all 7 input files in tmp_path, spawns
python -m hydra_backtest.hydra against them, and verifies the
4 expected output files exist with the right schema.
"""
import json
import pickle
import subprocess
import sys

import numpy as np
import pandas as pd


def _make_ohlcv(start: str, n_days: int, start_price: float, drift: float = 0.0005,
                noise: float = 0.008) -> pd.DataFrame:
    np.random.seed(666)
    dates = pd.bdate_range(start, periods=n_days)
    rets = drift + np.random.normal(0, noise, n_days)
    closes = start_price * np.cumprod(1 + rets)
    return pd.DataFrame(
        {
            'Open': closes,
            'High': closes * 1.005,
            'Low': closes * 0.995,
            'Close': closes,
            'Volume': 1_000_000,
        },
        index=dates,
    )


def _build_synthetic_inputs(tmp_path):
    """Create all 7 input files in tmp_path. Returns the path dict."""
    n_days = 400
    start = '2020-01-01'
    dates = pd.bdate_range(start, periods=n_days)

    # 1. Synthetic PIT universe (small — 8 tickers)
    universe_tickers = ['AAA', 'BBB', 'CCC', 'DDD', 'EEE', 'FFF', 'GGG', 'HHH']
    pit_records = []
    for t in universe_tickers:
        pit_records.append({'date': dates[0], 'ticker': t, 'action': 'added'})
    pit_df = pd.DataFrame(pit_records)
    pit_path = tmp_path / 'pit.pkl'
    with open(pit_path, 'wb') as f:
        pickle.dump(pit_df, f)

    # 2. Price history (one OHLCV per ticker)
    prices = {t: _make_ohlcv(start, n_days, start_price=100 + i * 10)
              for i, t in enumerate(universe_tickers)}
    prices_path = tmp_path / 'prices.pkl'
    with open(prices_path, 'wb') as f:
        pickle.dump(prices, f)

    # 3. Sector map (one sector per ticker)
    sectors = {t: 'Technology' for t in universe_tickers}
    sectors_path = tmp_path / 'sectors.json'
    with open(sectors_path, 'w') as f:
        json.dump(sectors, f)

    # 4. SPY data
    spy = _make_ohlcv(start, n_days, start_price=300, drift=0.0005)
    spy_path = tmp_path / 'spy.csv'
    spy.to_csv(spy_path, index_label='Date')

    # 5. VIX history
    vix_dates = dates
    vix_values = 18.0 + np.random.normal(0, 2, n_days)
    vix_df = pd.DataFrame({'Date': vix_dates, 'Close': vix_values})
    vix_path = tmp_path / 'vix.csv'
    vix_df.to_csv(vix_path, index=False)

    # 6. Catalyst assets pickle
    catalyst = {sym: _make_ohlcv(start, n_days, start_price=p)
                for sym, p in [('TLT', 95), ('ZROZ', 85),
                                ('GLD', 180), ('DBC', 25)]}
    catalyst_path = tmp_path / 'catalyst.pkl'
    with open(catalyst_path, 'wb') as f:
        pickle.dump(catalyst, f)

    # 7. EFA history pickle
    efa = _make_ohlcv(start, n_days, start_price=50)
    efa_path = tmp_path / 'efa.pkl'
    with open(efa_path, 'wb') as f:
        pickle.dump(efa, f)

    # 8. Yield CSVs
    aaa_csv = tmp_path / 'aaa.csv'
    pd.DataFrame(
        {'observation_date': dates, 'yield_pct': [4.5] * len(dates)}
    ).to_csv(aaa_csv, index=False)
    tbill_csv = tmp_path / 'tbill.csv'
    pd.DataFrame(
        {'DATE': dates, 'DGS3MO': [3.5] * len(dates)}
    ).to_csv(tbill_csv, index=False)

    return {
        'pit': pit_path, 'prices': prices_path, 'sectors': sectors_path,
        'spy': spy_path, 'vix': vix_path, 'catalyst': catalyst_path,
        'efa': efa_path, 'aaa': aaa_csv, 'tbill': tbill_csv,
    }


def test_cli_runs_end_to_end(tmp_path):
    paths = _build_synthetic_inputs(tmp_path)
    out_dir = tmp_path / 'out'
    cmd = [
        sys.executable, '-m', 'hydra_backtest.hydra',
        '--start', '2020-12-01',
        '--end', '2021-02-26',
        '--out-dir', str(out_dir),
        '--constituents', str(paths['pit']),
        '--prices', str(paths['prices']),
        '--sectors', str(paths['sectors']),
        '--spy', str(paths['spy']),
        '--vix', str(paths['vix']),
        '--catalyst-assets', str(paths['catalyst']),
        '--efa', str(paths['efa']),
        '--aaa', str(paths['aaa']),
        '--tbill', str(paths['tbill']),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    assert res.returncode == 0, (
        f"CLI failed:\nstdout=\n{res.stdout}\nstderr=\n{res.stderr}"
    )

    daily_csv = out_dir / 'hydra_v2_daily.csv'
    trades_csv = out_dir / 'hydra_v2_trades.csv'
    waterfall_json = out_dir / 'hydra_v2_waterfall.json'
    layer_b_json = out_dir / 'layer_b_report.json'
    assert daily_csv.exists()
    assert trades_csv.exists()
    assert waterfall_json.exists()
    assert layer_b_json.exists()

    # Sanity-check waterfall structure
    with open(waterfall_json) as f:
        wf = json.load(f)
    tier_names = [t['name'] for t in wf['tiers']]
    assert 'baseline' in tier_names
    assert 'net_honest' in tier_names

    # Layer B should be SKIPPED (synthetic CLI doesn't produce a
    # comparable hydra_clean_daily.csv reference)
    with open(layer_b_json) as f:
        lb = json.load(f)
    assert lb.get('status') in ('SKIPPED', 'COMPLETE')
