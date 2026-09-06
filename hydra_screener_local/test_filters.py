"""
Unit tests for core.filters: apply_practical_filters and remove_zombie_tickers.

Standalone runner (auto-discovered by run_all_tests.py):
    python test_filters.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np
from datetime import datetime

from core.filters import apply_practical_filters, remove_zombie_tickers


def _prices(columns, last_values, n_days=30, noise=0.01):
    """Synthetic close prices: n_days of mild noise, last row = last_values."""
    dates = pd.date_range(end=datetime(2026, 6, 1), periods=n_days, freq="B")
    data = {}
    rng = np.random.default_rng(0)
    for col, last in zip(columns, last_values, strict=True):
        if last is None or (isinstance(last, float) and np.isnan(last)):
            series = 20.0 + rng.normal(0, noise, n_days).cumsum()
            series[-1] = np.nan
        else:
            series = float(last) + rng.normal(0, noise, n_days).cumsum()
            series[-1] = float(last)
        data[col] = series
    return pd.DataFrame(data, index=dates)


def test_min_price_drops_cheap_keeps_valid():
    prices = _prices(["CHEAP", "OK", "NANLAST"], [1.0, 10.0, np.nan])
    filtered, breakdown = apply_practical_filters(
        prices, min_avg_volume=0, min_price=5.0, max_price=None
    )
    cols = set(filtered.columns)
    assert "CHEAP" not in cols, f"CHEAP should drop: {cols}"
    assert "NANLAST" not in cols, f"NaN last price should drop: {cols}"
    assert "OK" in cols, f"OK should survive: {cols}"
    assert breakdown["min_price"] == 2
    assert breakdown["remaining"] == 1
    print("[OK] test_min_price_drops_cheap_keeps_valid")
    return True


def test_max_price_drops_expensive():
    prices = _prices(["MID", "EXP"], [50.0, 500.0])
    filtered, breakdown = apply_practical_filters(
        prices, min_avg_volume=0, min_price=5.0, max_price=100.0
    )
    cols = set(filtered.columns)
    assert "MID" in cols
    assert "EXP" not in cols
    assert breakdown["max_price"] == 1
    print("[OK] test_max_price_drops_expensive")
    return True


def test_volume_filter_drops_illiquid_when_volumes_passed():
    prices = _prices(["LIQ", "DRY"], [20.0, 20.0])
    volumes = pd.DataFrame(
        {"LIQ": [2_000_000] * len(prices), "DRY": [100] * len(prices)},
        index=prices.index,
    )
    filtered, breakdown = apply_practical_filters(
        prices, volumes=volumes, min_avg_volume=1_000_000, min_price=5.0
    )
    cols = set(filtered.columns)
    assert "LIQ" in cols
    assert "DRY" not in cols
    assert breakdown["volume"] == 1
    print("[OK] test_volume_filter_drops_illiquid_when_volumes_passed")
    return True


def test_volume_filter_noop_without_volumes_df():
    prices = _prices(["A", "B"], [20.0, 20.0])
    filtered, breakdown = apply_practical_filters(
        prices, volumes=None, min_avg_volume=1_000_000, min_price=5.0
    )
    assert set(filtered.columns) == {"A", "B"}
    assert breakdown["volume"] == 0
    print("[OK] test_volume_filter_noop_without_volumes_df")
    return True


def test_zombie_flat_last_n_days_removed():
    dates = pd.date_range(end=datetime(2026, 6, 1), periods=10, freq="B")
    live = pd.Series([10, 10.2, 10.1, 10.4, 10.3, 10.5, 10.6, 10.4, 10.7, 10.8], index=dates)
    zombie = pd.Series([5.0] * 10, index=dates)  # identical closes
    prices = pd.DataFrame({"LIVE": live, "ZOMBIE": zombie})
    out = remove_zombie_tickers(prices, max_flat_days=5, min_price=0.01)
    cols = set(out.columns)
    assert "ZOMBIE" not in cols, f"flat ticker should drop: {cols}"
    assert "LIVE" in cols
    print("[OK] test_zombie_flat_last_n_days_removed")
    return True


def test_zombie_zero_price_and_short_series_removed():
    dates = pd.date_range(end=datetime(2026, 6, 1), periods=8, freq="B")
    live = pd.Series(np.linspace(12, 13, 8), index=dates)
    pennies = pd.Series([0.001] * 8, index=dates)
    one_tick = pd.Series([np.nan] * 7 + [15.0], index=dates)
    prices = pd.DataFrame({"LIVE": live, "PENNY": pennies, "ONE": one_tick})
    out = remove_zombie_tickers(prices, max_flat_days=5, min_price=0.01)
    cols = set(out.columns)
    assert "PENNY" not in cols
    assert "ONE" not in cols
    assert "LIVE" in cols
    print("[OK] test_zombie_zero_price_and_short_series_removed")
    return True


def test_zombie_empty_passthrough():
    out = remove_zombie_tickers(pd.DataFrame())
    assert out.empty
    print("[OK] test_zombie_empty_passthrough")
    return True


def main():
    print("=== core.filters unit tests (TASK-302) ===\n")
    tests = [
        test_min_price_drops_cheap_keeps_valid,
        test_max_price_drops_expensive,
        test_volume_filter_drops_illiquid_when_volumes_passed,
        test_volume_filter_noop_without_volumes_df,
        test_zombie_flat_last_n_days_removed,
        test_zombie_zero_price_and_short_series_removed,
        test_zombie_empty_passthrough,
    ]
    all_ok = True
    for fn in tests:
        try:
            if not fn():
                print(f"[FAIL] {fn.__name__}")
                all_ok = False
        except Exception as e:
            print(f"[FAIL] {fn.__name__}: {e}")
            import traceback
            traceback.print_exc()
            all_ok = False
    if all_ok:
        print(f"\n=== ALL {len(tests)} FILTER TESTS PASSED ===")
        return 0
    print("\n=== SOME FILTER TESTS FAILED ===")
    return 1


if __name__ == "__main__":
    sys.exit(main())
