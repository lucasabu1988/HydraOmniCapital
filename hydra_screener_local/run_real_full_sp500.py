"""
Headless FULL index real-data run for HYDRA Screener.
- Respects config.UNIVERSE ("sp500", "nasdaq100", "dow30", "russell1000", "russell2000", "russell3000", or "all")
- When "all": fetches the union of SP500 + Nasdaq100 + Dow30 + Russell1000 + Russell2000 (ampliado para integrar más acciones: large + mid + small caps ~2500+ tickers) and selects the absolute best
  candidates across all indices (no distinction between them during scoring/selection).
- Batched yfinance downloads (safe for rate limits)
- Full Meta-Layer + Pillar Multipliers + Special Modes + dynamic recommendations + volume + sector control
- Plain text output only (no rich → no encoding crashes)
- ALWAYS writes the Excel and history JSON (with robust paths)
- Runtime depends on index size (Nasdaq100/Dow30 faster; "all" ~2500+ unique tickers)
"""
import os
import sys
import ast
from datetime import datetime

# Robust paths: always relative to this script file (works even if run from temp dir or another cwd)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(_SCRIPT_DIR, "output")
HISTORY_DIR = os.path.join(_SCRIPT_DIR, "history")

os.chdir(_SCRIPT_DIR)
sys.path.insert(0, '.')

# Load .env early via centralized loader (webhooks, future config, etc.)
try:
    from utils.env import load_hydra_env
    load_hydra_env()
except Exception as _e:
    print(f"[WARN] .env loader skipped: {_e}")

import config
config.USE_FULL_SP500 = True
config.UNIVERSE = "all"               # <--- COMBINED AMPLIADO: SP500 + Nasdaq100 + Dow30 + Russell1000 (más acciones mid/large)
config.FILTERS['min_avg_volume'] = 0  # keep disabled until we add real Volume fetching
config.EXPORT_EXCEL = True

print("=" * 65)
u = config.UNIVERSE
print(f"HYDRA SCREENER - REAL DATA (FULL {u.upper() if u != 'all' else 'COMBINED AMPLIADO'})")
print(f"Started: {datetime.now().isoformat()}")
print(f"Universe: {'COMBINED AMPLIADO (SP500 + Nasdaq100 + Dow30 + R1000 + R2000 ~2500+ tickers)' if u.lower()=='all' else u.upper()}")
print("This will take several minutes (longer for 'all' with R2000). Please be patient...")
print("=" * 65)

from data.universe import get_universe
from data.fetch import fetch_prices_and_volume, fetch_spy
from core.signals import generate_daily_candidates, compute_regime_score
from core.filters import apply_practical_filters, get_filter_summary, remove_zombie_tickers
from core.history import save_daily_run

start_time = datetime.now()

# 1. Universe (supports sp500 / nasdaq100 / dow30 / "all" via config.UNIVERSE)
u = config.UNIVERSE
print(f"\n[1/5] Obteniendo universo {u.upper()}...")
# Force real fetches for widest possible universe (no cache for Russell and others to get full lists)
import os
for cache_name in ['russell1000_tickers.csv', 'russell2000_tickers.csv', 'russell3000_tickers.csv', 'sp500_tickers.csv', 'nasdaq100_tickers.csv', 'dow30_tickers.csv']:
    p = os.path.join(OUTPUT_DIR, cache_name)
    if os.path.exists(p):
        os.remove(p)
        print(f'  Cleared cache: {cache_name}')
tickers = get_universe(universe=u, full_sp500=True)  # inside get, russell calls now use use_cache=False in all path
if u.lower() == "all":
    print(f"      Universo combinado: {len(tickers)} tickers únicos (SP500 + Nasdaq100 + Dow30)")
print(f"      Universo: {len(tickers)} tickers ({config.UNIVERSE})")

# 2. Data download (the long part) — ahora también con volumen para Strict Filter
print("\n[2/5] Descargando precios + volumen reales (lotes de 75 con pausas)...")
prices, volumes = fetch_prices_and_volume(tickers, batch_size=75)
spy = fetch_spy()

if len(prices.columns) < 50:
    print("ERROR: Muy pocos tickers con datos. Abortando.")
    sys.exit(1)

print(f"      Precios obtenidos: {prices.shape[1]} tickers x {prices.shape[0]} días")

# 3. Filters (price only for now)
print("\n[3/5] Aplicando filtros prácticos (precio mínimo)...")
original_count = len(prices.columns)
prices = apply_practical_filters(
    prices,
    min_avg_volume=config.FILTERS.get("min_avg_volume", 0),
    min_price=config.FILTERS.get("min_price", 5.0),
)
fs = get_filter_summary(original_count, prices)
print(f"      Después de filtros: {fs['remaining']} tickers "
      f"({fs['removed']} eliminados, {fs['removal_pct']}%)")

# Defensa adicional contra zombies (complementa el filtro temprano en fetch + blacklist)
prices = remove_zombie_tickers(prices)
if len(prices.columns) < original_count:
    zfs = get_filter_summary(original_count, prices)
    print(f"      + sanity zombie: {zfs['remaining']} restantes ({zfs['removed']} adicionales)")

# 4. The actual HYDRA + Meta-Layer logic (ahora con volumen para Strict Filter)
print("\n[4/5] Ejecutando lógica completa HYDRA + Meta-Layer + Pillar Multipliers + Strict Filter...")
candidates = generate_daily_candidates(prices, spy, volumes=volumes)
regime_score = compute_regime_score(spy)

print(f"      Candidatos generados: {len(candidates)}")
print(f"      Regime Score: {regime_score:.3f}")

if len(candidates) == 0:
    print("No se generaron candidatos.")
    sys.exit(0)

# Extract rich meta information
row0 = candidates.iloc[0]
meta_info = {
    'aggression': float(row0.get('aggression', 1.0)),
    'recovery_boost': float(row0.get('recovery_boost', 1.0)),
    'regime_type': str(row0.get('regime_type', '')),
}
try:
    pillar_mults = ast.literal_eval(row0.get('pillar_multipliers', '{}'))
except Exception:
    pillar_mults = {}

sm_raw = row0.get('special_modes', '')
special_modes_list = [m.strip() for m in sm_raw.split(',') if m.strip()] if isinstance(sm_raw, str) else (list(sm_raw) if sm_raw else [])

recommended_count = int(row0.get('recommended_count', 10))

print("\n" + "=" * 65)
print("RESULTADO DEL DÍA - FULL SCREENER (UNIVERSE=all AMPLIADO)")
print("=" * 65)
print(f"  Régimen Score     : {regime_score:.3f}")
print(f"  Tipo de Régimen   : {meta_info['regime_type']}")
print(f"  Aggression        : {meta_info['aggression']:.3f}")
print(f"  Recovery Boost    : {meta_info['recovery_boost']:.3f}")
print(f"  Special Modes     : {special_modes_list or '(ninguno)'}")
print(f"  Recomendados hoy  : {recommended_count} (dinámico)")

print("\nPILLAR MULTIPLIERS (Meta-Layer):")
for p, m in sorted(pillar_mults.items()):
    if m > 1.10:
        tilt = "UP++"
    elif m > 1.03:
        tilt = "UP"
    elif m < 0.90:
        tilt = "DOWN--"
    elif m < 0.97:
        tilt = "DOWN"
    else:
        tilt = "FLAT"
    try:
        print(f"  {p:12s} : {m:.3f}x   ({tilt})")
    except UnicodeEncodeError:
        print(f"  {p:12s} : {m:.3f}x   ({tilt})")

# Top recommended (plain text) - ahora con nuevas reglas de short-term
print("\nTOP CANDIDATOS RECOMENDADOS (máx 15) - Con Short-Term Boost + Umbral Vol Geo-ajustado:")
print(f"{'Rank':>4}  {'Ticker':<6}  {'Comp':>7}  {'5/10d%':>7}  {'DistH':>6}  {'Boost':>6}  {'VolThr':>6}  {'Rec':>3}")
print("-" * 70)
for _, r in candidates.head(15).iterrows():
    rec = "YES" if r.get('recommended') else "NO"
    try:
        print(f"{int(r['rank']):>4}  {r['ticker']:<6}  {r.get('composite_score',0):>7.3f}  "
              f"{r.get('ret_5d_10d',0):>7.1f}  {r.get('dist_20d_high',0):>6.1f}  "
              f"{r.get('short_boost',0):>6.2f}  {r.get('dynamic_vol_threshold',0):>6.2f}  {rec:>3}")
    except Exception:
        print(f"  Rank {int(r['rank'])}: {r['ticker']} comp={r.get('composite_score',0):.3f}")

# 5. Persistencia (Excel + History JSON) - always happens with robust paths
print("\n[5/5] Guardando resultados...")
today = datetime.now().strftime("%Y%m%d")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)

if config.EXPORT_EXCEL:
    filename = os.path.join(OUTPUT_DIR, f"hydra_screener_full_{today}.xlsx")
    candidates.to_excel(filename, index=False)
    print(f"      [OK] Excel: {filename}")

top_for_history = candidates.head(25).to_dict("records")
meta_rationale = str(row0.get("reason", ""))

save_daily_run(
    date=today,
    regime_score=regime_score,
    regime_type=meta_info['regime_type'],
    special_modes=special_modes_list,
    pillar_multipliers=pillar_mults,
    top_candidates=top_for_history,
    meta_rationale=meta_rationale,
    base_dir=HISTORY_DIR
)

print(f"      [OK] Historial: {os.path.join(HISTORY_DIR, f'{today}_full.json')}")

# Log top5 cycle for the DYNAMIC PnL Excel (entry ~ last close, PnL formulas, refreshable current)
try:
    if len(candidates) >= 5:
        top5 = candidates.head(5)['ticker'].tolist()
        entry_prices = {}
        for t in top5:
            if t in prices.columns and len(prices[t].dropna()) > 0:
                entry_prices[t] = float(prices[t].dropna().iloc[-1])
        import log_cycle_positions
        log_cycle_positions.log_cycle(datetime.now(), top5, candidates, notes=f"live FULL run UNIVERSE={u}", entry_prices=entry_prices)
        print("      [OK] Cycle PnL logged (dynamic entry/current/PnL) -> backtest/portfolio_cycles.xlsx")
except Exception as e:
    print(f"      [warn] cycle log skipped: {e}")

elapsed = (datetime.now() - start_time).total_seconds()
u = getattr(config, 'UNIVERSE', 'sp500')
label = "COMBINED (SP500 + Nasdaq100 + Dow30)" if u.lower() == "all" else u.upper()
print("\n" + "=" * 65)
print(f"FULL {label} RUN COMPLETADO en {elapsed:.0f} segundos")
print("=" * 65)
print("Archivos generados:")
print(f"  - output/hydra_screener_full_{today}.xlsx")
print(f"  - history/{today}_full.json")
if u.lower() == "all":
    print("(Note: candidates selected from the merged multi-index pool AMPLIADO with Russell1000 + Russell2000 - no index distinction, más acciones incluidas)")
print("  - backtest/portfolio_cycles.xlsx (Cycle_Summaries + All_Positions with entry/current + PnL formulas for the 5 per cycle)")

# Hybrid integration (same as in screener.py)
try:
    print("\n[Hybrid] Generating Pine watchlist...")
    import generate_pine_watchlist
    generate_pine_watchlist.run_feeder(top_n=15, output_path="pine/watchlist.txt", silent=True)
    print("[Hybrid] Sending daily summary...")
    import send_hydra_summary
    send_hydra_summary.run_sender(top_n=15, silent=True)
    print("[Hybrid] Done.")
    print("  → pine/watchlist.txt           (paste into Pine 'Watchlist Symbols')")
    print("  → pine/hydra_last_summary.json (paste the FULL file into Pine i_summary_json input)")
    print("     This gives you exact 'Rec?' flags from Python + enriched composite/strict/special per row.")
except Exception as e:
    print(f"[warn] hybrid layer skipped: {e}")
