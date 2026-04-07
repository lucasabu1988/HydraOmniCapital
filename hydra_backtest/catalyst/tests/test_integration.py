"""CLI smoke test for hydra_backtest.catalyst."""
import json
import pickle
import subprocess
import sys

import numpy as np
import pandas as pd


def _make_synth_assets(n_days: int = 300) -> dict:
    """4 trending-up synthetic ETFs with enough history for SMA200."""
    np.random.seed(666)
    dates = pd.bdate_range('2020-01-01', periods=n_days)
    out = {}
    for sym, p0 in [('TLT', 95), ('ZROZ', 85), ('GLD', 180), ('DBC', 25)]:
        rets = 0.0004 + np.random.normal(0, 0.008, n_days)
        closes = p0 * np.cumprod(1 + rets)
        out[sym] = pd.DataFrame(
            {
                'Open': closes,
                'High': closes * 1.005,
                'Low': closes * 0.995,
                'Close': closes,
                'Volume': 1_000_000,
            },
            index=dates,
        )
    return out


def test_cli_runs_end_to_end(tmp_path):
    # 1. Synthetic assets pickle
    assets = _make_synth_assets()
    pkl = tmp_path / 'catalyst_assets.pkl'
    with open(pkl, 'wb') as f:
        pickle.dump(assets, f)

    # 2. Synthetic Aaa + T-bill yield CSVs (FRED column shape)
    dates = pd.bdate_range('2020-01-01', periods=300)
    aaa_csv = tmp_path / 'aaa.csv'
    pd.DataFrame(
        {'observation_date': dates, 'yield_pct': [4.5] * len(dates)}
    ).to_csv(aaa_csv, index=False)
    tbill_csv = tmp_path / 'tbill.csv'
    pd.DataFrame({'DATE': dates, 'DGS3MO': [3.5] * len(dates)}).to_csv(tbill_csv, index=False)

    # 3. Pick a window AFTER SMA200 has enough history
    out_dir = tmp_path / 'out'
    cmd = [
        sys.executable, '-m', 'hydra_backtest.catalyst',
        '--start', '2020-12-01',
        '--end', '2021-02-26',
        '--out-dir', str(out_dir),
        '--catalyst-assets', str(pkl),
        '--aaa', str(aaa_csv),
        '--tbill', str(tbill_csv),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, (
        f"CLI failed:\nstdout=\n{res.stdout}\nstderr=\n{res.stderr}"
    )

    daily_csv = out_dir / 'catalyst_v2_daily.csv'
    trades_csv = out_dir / 'catalyst_v2_trades.csv'
    waterfall_json = out_dir / 'catalyst_v2_waterfall.json'
    assert daily_csv.exists()
    assert trades_csv.exists()
    assert waterfall_json.exists()

    # Sanity-check waterfall structure
    with open(waterfall_json) as f:
        wf = json.load(f)
    assert 'tiers' in wf
    tier_names = [t['name'] for t in wf['tiers']]
    # build_waterfall produces baseline, t_bill, next_open, real_costs, net_honest
    assert 'baseline' in tier_names
    assert 'net_honest' in tier_names
