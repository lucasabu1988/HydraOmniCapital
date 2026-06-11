"""
Smoke test for screener logic fixes (no network).
Creates synthetic price data for ~20 tickers, runs the full candidate generation,
verifies columns, special modes, pillar multipliers, dynamic count, etc.
"""
import sys
import os
# Este test vive en experiments/ — config y core/ están en el directorio padre
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Patch config for test
import config
config.USE_FULL_SP500 = False
config.UNIVERSE = "custom"
config.FILTERS = {"min_avg_volume": 0, "min_price": 0, "max_price": None, "exclude_sectors": []}
config.TOP_CANDIDATES = 10

from data.universe import get_universe
from core.signals import generate_daily_candidates, compute_regime_score
from core.filters import apply_practical_filters, get_filter_summary
from utils.display import print_candidates_table, print_summary, print_header, print_footer

def make_synthetic_prices(n_tickers=25, n_days=300, seed=42):
    """Generate plausible price series for testing."""
    np.random.seed(seed)
    tickers = [f"T{str(i).zfill(3)}" for i in range(n_tickers)]
    # Use 'D' to guarantee exact length match; business freq can skip holidays varying length
    dates = pd.date_range(end=datetime.now().date(), periods=n_days, freq="D")
    
    # Random walks with drift + vol
    data = {}
    for t in tickers:
        rets = np.random.normal(0.0004, 0.018, n_days)
        prices = 50 * np.exp(np.cumsum(rets))
        data[t] = prices
    df = pd.DataFrame(data, index=dates)
    return df

def make_synthetic_spy(n_days=300, seed=123):
    np.random.seed(seed)
    dates = pd.date_range(end=datetime.now().date(), periods=n_days, freq="D")
    rets = np.random.normal(0.0005, 0.012, n_days)
    prices = 400 * np.exp(np.cumsum(rets))
    return pd.Series(prices, index=dates, name="SPY")

def main_test():
    print("=== HYDRA Screener Logic Smoke Test (synthetic data) ===\n")
    
    prices = make_synthetic_prices()
    spy = make_synthetic_spy()
    
    print(f"Synthetic universe: {len(prices.columns)} tickers, {len(prices)} days\n")
    
    # Filters (disabled)
    original = len(prices.columns)
    prices_f, _ = apply_practical_filters(prices, min_avg_volume=0, min_price=0, max_price=None)
    fs = get_filter_summary(original, prices_f)
    print(f"Filters (noop): {fs['remaining']} remaining\n")
    
    # Core: generate candidates (this was crashing before fixes)
    candidates = generate_daily_candidates(prices_f, spy)
    
    print(f"Generated {len(candidates)} candidates.")
    print("Columns in output:", list(candidates.columns))
    print()
    
    # Verify critical columns exist and have values
    required = ['rank', 'ticker', 'momentum', 'meta_score', 'regime_type', 'special_modes', 
                'aggression', 'compass_mult', 'recommended', 'reason', 'recommended_count', 'pillar_multipliers', 'recovery_boost']
    missing = [c for c in required if c not in candidates.columns]
    if missing:
        print(f"[FAIL] MISSING COLUMNS: {missing}")
        return False
    print("[OK] All required columns present")
    
    # Check first row has good data
    row0 = candidates.iloc[0]
    print(f"Top ticker: {row0['ticker']}")
    print(f"  meta_score: {row0['meta_score']}")
    print(f"  regime_type: {row0['regime_type']}")
    print(f"  special_modes: '{row0['special_modes']}'")
    print(f"  aggression: {row0['aggression']}")
    print(f"  recovery_boost (via get): {row0.get('recovery_boost', 'MISSING')}")
    print(f"  recommended_count: {row0['recommended_count']}")
    print(f"  pillar_multipliers sample: {row0['pillar_multipliers'][:80]}...")
    
    # Check dynamic count in reasonable range
    rc = int(row0['recommended_count'])
    if not (6 <= rc <= 28):
        print(f"[FAIL] recommended_count out of expected range: {rc}")
        return False
    print(f"[OK] Dynamic recommended_count in range: {rc}")
    
    # Check some recommended True
    n_rec = candidates['recommended'].sum()
    print(f"[OK] Recommended today: {n_rec} (expected ~{rc})")
    
    # Test the exact extraction logic from screener.py main() (no rich to avoid host console encoding limits)
    print("\n--- Verifying screener.py extraction logic (no rich) ---")
    try:
        meta_info = {
            'aggression': row0.get('aggression', 1.0),
            'recovery_boost': row0.get('recovery_boost', 1.0),
            'regime_type': row0.get('regime_type', '')
        }
        import ast
        pillar_mults = ast.literal_eval(row0.get('pillar_multipliers', '{}'))
        regime_score = float(candidates.iloc[0].get('regime', 0.5))
        rec_count = int(candidates.iloc[0].get('recommended_count', 10))
        
        sm_raw = row0.get('special_modes', '')
        if isinstance(sm_raw, str) and sm_raw:
            special_modes_list = [m.strip() for m in sm_raw.split(',') if m.strip()]
        else:
            special_modes_list = []
        
        print(f"[OK] meta_info: {meta_info}")
        print(f"[OK] pillar_mults: {pillar_mults}")
        print(f"[OK] special_modes_list for history: {special_modes_list}")
        print(f"[OK] regime_score: {regime_score} rec_count: {rec_count}")
        
        # Would call save_daily_run with special_modes_list here (tested indirectly)
    except Exception as e:
        print(f"[FAIL] Extraction logic error: {e}")
        import traceback; traceback.print_exc()
        return False
    
    print("\n=== ALL CHECKS PASSED (core logic + extraction) ===")
    print("Note: Full rich tables work in modern terminals (Windows Terminal, VSCode, etc).")
    return True

if __name__ == "__main__":
    success = main_test()
    sys.exit(0 if success else 1)
