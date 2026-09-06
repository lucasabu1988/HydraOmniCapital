"""
Headless real-data test runner for HYDRA Screener.
- Uses reduced universe for speed
- Full yfinance download + logic (Meta-Layer, Pillars, Special Modes, dynamic count)
- Plain text output (no rich, no unicode symbols that crash legacy consoles)
- ALWAYS writes Excel + history JSON even if display would fail
- Prints key results in readable form
"""
import os
import sys
import ast
from datetime import datetime

os.chdir(os.path.dirname(__file__))
sys.path.insert(0, '.')

import config
config.USE_FULL_SP500 = False
config.UNIVERSE = "custom"
config.FILTERS['min_avg_volume'] = 0
config.EXPORT_EXCEL = True

print("=" * 60)
print("HYDRA SCREENER - REAL DATA HEADLESS TEST")
print(f"Time: {datetime.now().isoformat()}")
print(f"Universe: {config.UNIVERSE}")
print("=" * 60)

from data.universe import get_universe
from data.fetch import fetch_prices, fetch_spy
from core.signals import generate_daily_candidates, compute_regime_score
from core.filters import apply_practical_filters, get_filter_summary
from core.history import save_daily_run

# 1. Universe
tickers = get_universe(universe=config.UNIVERSE, full_sp500=config.USE_FULL_SP500)
print(f"\nUniverse: {len(tickers)} tickers")

# 2. Data
prices = fetch_prices(tickers)
spy = fetch_spy()

if len(prices) < 20:
    print("ERROR: Insufficient price data")
    sys.exit(1)

print(f"Prices shape: {prices.shape}")

# 3. Filters
original_count = len(prices.columns)
prices = apply_practical_filters(
    prices,
    min_avg_volume=config.FILTERS.get("min_avg_volume", 0),
    min_price=config.FILTERS.get("min_price", 5.0),
)
fs = get_filter_summary(original_count, prices)
print(f"After filters: {fs['remaining']} tickers (removed {fs['removed']})")

# 4. Core logic (this is what we care about)
candidates = generate_daily_candidates(prices, spy)
regime_score = compute_regime_score(spy)

print(f"\nGenerated {len(candidates)} ranked candidates")
print(f"Regime Score: {regime_score:.3f}")

if len(candidates) == 0:
    print("No candidates generated.")
    sys.exit(0)

# 5. Extract real meta info (the important part)
row0 = candidates.iloc[0]
meta_info = {
    'aggression': float(row0.get('aggression', 1.0)),
    'recovery_boost': float(row0.get('recovery_boost', 1.0)),
    'regime_type': str(row0.get('regime_type', '')),
}
try:
    pillar_mults = ast.literal_eval(row0.get('pillar_multipliers', '{}'))
except:
    pillar_mults = {}

sm_raw = row0.get('special_modes', '')
special_modes_list = [m.strip() for m in sm_raw.split(',') if m.strip()] if isinstance(sm_raw, str) else (list(sm_raw) if sm_raw else [])

recommended_count = int(row0.get('recommended_count', 10))

print("\n" + "=" * 60)
print("REGIME & META-LAYER")
print("=" * 60)
print(f"  Regime Score : {regime_score:.3f}")
print(f"  Regime Type  : {meta_info['regime_type']}")
print(f"  Aggression   : {meta_info['aggression']:.3f}")
print(f"  Recovery Boost: {meta_info['recovery_boost']:.3f}")
print(f"  Special Modes: {special_modes_list or '(none)'}")
print(f"  Recommended today (dynamic): {recommended_count}")

print("\n" + "=" * 60)
print("PILLAR MULTIPLIERS (Meta-Layer)")
print("=" * 60)
for p, m in sorted(pillar_mults.items()):
    tilt = "UP  " if m > 1.05 else ("DOWN" if m < 0.95 else "FLAT")
    print(f"  {p:12s} : {m:.3f}x   ({tilt})")

# 6. Top candidates (plain text table)
print("\n" + "=" * 60)
print(f"TOP CANDIDATES (showing up to {min(12, len(candidates))})")
print("=" * 60)
print(f"{'Rank':>4}  {'Ticker':<8}  {'Momentum':>8}  {'MetaScore':>9}  {'COMPx':>6}  {'Reg':>6}  {'Rec':>3}")
print("-" * 60)

for _, r in candidates.head(12).iterrows():
    rec = "YES" if r.get('recommended') else "NO"
    print(f"{int(r['rank']):>4}  {r['ticker']:<8}  {r.get('momentum',0):>8.3f}  "
          f"{r.get('meta_score',0):>9.3f}  {r.get('compass_mult',1):>6.2f}  "
          f"{r.get('regime_type','')[:6]:>6}  {rec:>3}")

# 7. Export + History (GUARANTEED)
today = datetime.now().strftime("%Y%m%d")

if config.EXPORT_EXCEL:
    filename = f"output/hydra_screener_{today}.xlsx"
    candidates.to_excel(filename, index=False)
    print(f"\n[OK] Excel exported: {filename}")

# Save history with REAL special_modes
top_for_history = candidates.head(20).to_dict("records")
meta_rationale = str(row0.get("reason", ""))

save_daily_run(
    date=today,
    regime_score=regime_score,
    regime_type=meta_info['regime_type'],
    special_modes=special_modes_list,
    pillar_multipliers=pillar_mults,
    top_candidates=top_for_history,
    meta_rationale=meta_rationale
)
print(f"[OK] History saved: history/{today}.json")

print("\n" + "=" * 60)
print("HEADLESS REAL-DATA TEST COMPLETE")
print("=" * 60)
print("Artifacts ready for inspection:")
print(f"  - output/hydra_screener_{today}.xlsx")
print(f"  - history/{today}.json")
print(f"  - backtest/portfolio_cycles.xlsx (dynamic: entry + current + PnL per position/cycle)")
