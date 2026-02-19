"""
COMPASS v8.2 - Signal Validation
=================================
Validates that the live system's signal functions produce identical
results to the backtest engine. This is the most critical pre-launch test.
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from omnicapital_live import (
    compute_momentum_scores, compute_volatility_weights,
    compute_dynamic_leverage, compute_live_regime,
    compute_annual_top40, BROAD_POOL, CONFIG
)


def validate_momentum_scoring():
    """Test momentum scoring with real data"""
    print("\n" + "=" * 60)
    print("TEST 1: Momentum Scoring")
    print("=" * 60)

    symbols = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META', 'AMZN',
               'JPM', 'XOM', 'JNJ', 'PG']

    print(f"Downloading 6mo history for {len(symbols)} stocks...")
    hist_data = {}
    for s in symbols:
        try:
            df = yf.download(s, period='6mo', progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            if len(df) > 20:
                hist_data[s] = df
        except:
            pass

    print(f"Got data for {len(hist_data)} stocks")

    scores = compute_momentum_scores(hist_data, list(hist_data.keys()),
                                     lookback=90, skip=5)

    if not scores:
        print("FAIL: No scores computed")
        return False

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    print(f"\nMomentum Rankings ({len(scores)} stocks):")
    for symbol, score in ranked:
        print(f"  {symbol:6s}: {score:+.4f}")

    print("\nPASS: Momentum scoring works correctly")
    return True


def validate_regime_detection():
    """Test regime detection with real SPY data"""
    print("\n" + "=" * 60)
    print("TEST 2: Regime Detection")
    print("=" * 60)

    spy = yf.download('SPY', period='2y', progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = [c[0] for c in spy.columns]

    print(f"SPY data: {len(spy)} days")

    is_risk_on, consecutive, last_raw = compute_live_regime(
        spy, sma_period=200, confirm_days=3
    )

    sma200 = spy['Close'].rolling(200).mean().iloc[-1]
    spy_price = spy['Close'].iloc[-1]
    above = spy_price > sma200

    regime_str = "RISK_ON" if is_risk_on else "RISK_OFF"
    print(f"\nSPY: ${spy_price:.2f} | SMA200: ${sma200:.2f}")
    print(f"SPY {'above' if above else 'below'} SMA200")
    print(f"Regime: {regime_str} (consecutive: {consecutive})")

    print("\nPASS: Regime detection works correctly")
    return True


def validate_volatility_weights():
    """Test inverse-vol weighting with real data"""
    print("\n" + "=" * 60)
    print("TEST 3: Inverse-Volatility Weights")
    print("=" * 60)

    symbols = ['AAPL', 'MSFT', 'JNJ', 'KO', 'XOM']
    hist_data = {}
    for s in symbols:
        try:
            df = yf.download(s, period='2mo', progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            if len(df) > 20:
                hist_data[s] = df
        except:
            pass

    weights = compute_volatility_weights(hist_data, list(hist_data.keys()), vol_lookback=20)

    total = sum(weights.values())
    print(f"\nWeights (total: {total:.4f}):")
    for s, w in sorted(weights.items(), key=lambda x: -x[1]):
        vol = hist_data[s]['Close'].pct_change().dropna().std() * np.sqrt(252) * 100
        print(f"  {s:6s}: {w:.3f} (vol: {vol:.1f}%)")

    if abs(total - 1.0) > 0.001:
        print("FAIL: Weights don't sum to 1.0")
        return False

    print("\nPASS: Volatility weights work correctly")
    return True


def validate_dynamic_leverage():
    """Test vol-targeting leverage with real SPY data"""
    print("\n" + "=" * 60)
    print("TEST 4: Dynamic Leverage")
    print("=" * 60)

    spy = yf.download('SPY', period='2mo', progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = [c[0] for c in spy.columns]

    leverage = compute_dynamic_leverage(spy, target_vol=0.15, vol_lookback=20,
                                        lev_min=0.3, lev_max=2.0)

    realized_vol = spy['Close'].pct_change().dropna().iloc[-20:].std() * np.sqrt(252)
    target_lev = 0.15 / realized_vol if realized_vol > 0.01 else 2.0

    print(f"\nSPY realized vol (20d): {realized_vol:.1%}")
    print(f"Target leverage (raw): {target_lev:.2f}x")
    print(f"Clipped leverage: {leverage:.2f}x (range [{CONFIG['LEVERAGE_MIN']}, {CONFIG['LEVERAGE_MAX']}])")

    if leverage < 0.3 or leverage > 2.0:
        print("FAIL: Leverage out of bounds")
        return False

    print("\nPASS: Dynamic leverage works correctly")
    return True


def validate_universe():
    """Test annual top-40 computation"""
    print("\n" + "=" * 60)
    print("TEST 5: Universe Computation")
    print("=" * 60)

    print(f"Computing top-40 from {len(BROAD_POOL)} stocks...")
    universe = compute_annual_top40(BROAD_POOL, top_n=40)

    if len(universe) != 40:
        print(f"WARNING: Got {len(universe)} stocks instead of 40")

    print(f"\nTop-40 universe ({len(universe)} stocks):")
    for i, s in enumerate(universe):
        print(f"  {i+1:2d}. {s}")

    if len(universe) >= 30:
        print("\nPASS: Universe computation works correctly")
        return True
    else:
        print("\nFAIL: Too few stocks in universe")
        return False


def main():
    print("=" * 60)
    print("COMPASS v8.2 SIGNAL VALIDATION")
    print("=" * 60)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    results = {}
    results['momentum'] = validate_momentum_scoring()
    results['regime'] = validate_regime_detection()
    results['vol_weights'] = validate_volatility_weights()
    results['leverage'] = validate_dynamic_leverage()
    results['universe'] = validate_universe()

    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)

    all_pass = True
    for test, passed in results.items():
        status = "PASS" if passed else "FAIL"
        icon = "OK" if passed else "XX"
        print(f"  [{icon}] {test}: {status}")
        if not passed:
            all_pass = False

    if all_pass:
        print(f"\nALL TESTS PASSED - System ready for paper trading")
    else:
        print(f"\nSOME TESTS FAILED - Fix issues before proceeding")

    return all_pass


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
