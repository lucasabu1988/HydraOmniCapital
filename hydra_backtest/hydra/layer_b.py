"""hydra_backtest.hydra.layer_b — informational comparison vs the
dashboard's hydra_clean_daily.csv source-of-truth.

Non-blocking. Computes correlation, MAE, and max abs error between
v1.4's daily portfolio_value and the existing hydra_clean_daily.csv.
"""
from pathlib import Path
from typing import Optional

import pandas as pd

DEFAULT_CLEAN_CSV = Path('backtests/hydra_clean_daily.csv')


def compute_layer_b_report(
    daily: pd.DataFrame,
    clean_csv_path: Optional[Path] = None,
) -> dict:
    """Compute correlation/MAE between v1.4 daily PV and hydra_clean_daily.csv.

    Returns a dict with status, n_overlap, spearman, mae, max_err,
    and a verdict ('PASS' if spearman >= 0.95 else 'INVESTIGATE').
    Status='SKIPPED' if the reference CSV is missing or unusable.
    """
    path = clean_csv_path or DEFAULT_CLEAN_CSV
    if not path.exists():
        return {'status': 'SKIPPED', 'reason': f'{path} not found'}

    clean = pd.read_csv(path, parse_dates=['date'])
    if 'value' not in clean.columns:
        return {'status': 'SKIPPED', 'reason': 'reference CSV missing "value" column'}
    clean = clean.set_index('date')['value']

    if 'date' not in daily.columns or 'portfolio_value' not in daily.columns:
        return {'status': 'SKIPPED', 'reason': 'daily missing date or portfolio_value'}

    v14 = daily.copy()
    v14['date'] = pd.to_datetime(v14['date'])
    v14 = v14.set_index('date')['portfolio_value']

    overlap = v14.index.intersection(clean.index)
    if len(overlap) < 100:
        return {
            'status': 'SKIPPED',
            'reason': f'only {len(overlap)} overlapping days (need ≥ 100)',
        }

    v14_aligned = v14.loc[overlap]
    clean_aligned = clean.loc[overlap]
    spearman = float(v14_aligned.corr(clean_aligned, method='spearman'))
    pearson = float(v14_aligned.corr(clean_aligned, method='pearson'))
    mae = float((v14_aligned - clean_aligned).abs().mean())
    max_err = float((v14_aligned - clean_aligned).abs().max())
    verdict = 'PASS' if spearman >= 0.95 else 'INVESTIGATE'

    return {
        'status': 'COMPLETE',
        'verdict': verdict,
        'n_overlap': int(len(overlap)),
        'spearman': spearman,
        'pearson': pearson,
        'mae': mae,
        'max_err': max_err,
        'reference_csv': str(path),
    }
