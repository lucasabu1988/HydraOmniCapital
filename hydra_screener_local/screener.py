"""
HYDRA Screener Local - Versión inicial ligera
Ejecutar con: python screener.py

Soporta universo pequeño o S&P 500 completo.
"""
import os
import sys
from datetime import datetime

# Consolas/pipes Windows usan cp1252 por defecto y rompen con flechas/emojis UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Robust paths relative to this file (works from any cwd)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(_SCRIPT_DIR, "output")

# Load .env early (centralized loader) so any webhook or future env config is available
try:
    from utils.env import load_hydra_env
    load_hydra_env()
except Exception as _e:
    print(f"[WARN] .env loader skipped: {_e}")

from config import TOP_CANDIDATES, EXPORT_EXCEL, OUTPUT_FILENAME_PREFIX, USE_FULL_SP500, FILTERS, UNIVERSE, VOL_NAN_WARN_THRESHOLD
from data.universe import get_universe
from data.fetch import fetch_prices_and_volume, fetch_spy
from core.signals import generate_daily_candidates, compute_regime_score
from core.filters import apply_practical_filters, get_filter_summary, remove_zombie_tickers
from core.history import save_daily_run
from utils.display import print_header, print_candidates_table, print_summary, print_footer


def main():
    print_header()
    
    # 1. Definir universo (soporta sp500, nasdaq100, dow30, "all", custom)
    # Prioridad: env UNIVERSE (lo setea daily.py --universe) > config.UNIVERSE > legacy flag
    effective_universe = os.environ.get("UNIVERSE") or UNIVERSE or ("sp500" if USE_FULL_SP500 else "custom")
    tickers = get_universe(universe=effective_universe, full_sp500=USE_FULL_SP500)
    if effective_universe.lower() == "all":
        print(f"Universo seleccionado: COMBINADO AMPLIADO (SP500 + Nasdaq100 + Dow30 + R1000 + R2000) → {len(tickers)} tickers únicos\n")
    else:
        print(f"Universo seleccionado: {effective_universe.upper()} ({len(tickers)} tickers)\n")
    
    # 2. Obtener datos (precios + volumen para Strict Filter)
    prices, volumes = fetch_prices_and_volume(tickers)
    spy = fetch_spy()
    
    if len(prices) < 50:
        print("(!) Datos insuficientes. Intenta mas tarde o reduce el universo.")
        return

    # 3. Aplicar filtros prácticos (liquidez, precio, etc.)
    original_count = len(prices.columns)
    prices, filter_breakdown = apply_practical_filters(
        prices,
        volumes=volumes,
        min_avg_volume=FILTERS.get("min_avg_volume", 1_000_000),
        min_price=FILTERS.get("min_price", 5.0),
        max_price=FILTERS.get("max_price"),
    )
    
    filter_summary = get_filter_summary(original_count, prices)
    print(f"Filtros aplicados → {filter_summary['remaining']} tickers restantes "
          f"({filter_summary['removed']} eliminados, {filter_summary['removal_pct']}%)\n")

    # Defensa adicional contra zombies (hard blacklist + sanity de precios planos)
    prices = remove_zombie_tickers(prices)
    if len(prices.columns) < original_count:
        zfs = get_filter_summary(original_count, prices)
        print(f"   + sanity zombie → {zfs['remaining']} restantes ({zfs['removed']} adicionales)\n")
    
    # 4. Generar candidatos (ya incluye Meta-Layer)
    candidates = generate_daily_candidates(prices, spy, volumes=volumes)
    regime_score = compute_regime_score(spy)

    # TASK-202: Volume data watchdog — warn if too many NaN vol_ratio (missing volume breaks strict filter)
    nan_share = float(candidates.iloc[0].get("vol_ratio_nan_share", 0.0)) if len(candidates) > 0 else 0.0
    if nan_share > VOL_NAN_WARN_THRESHOLD:
        print(f"⚠ {nan_share:.0%} of tickers have no usable volume data — strict filter coverage degraded")
    
    # Extraer info de meta para el resumen
    meta_info = {}
    pillar_mults = {}
    special_modes_list = []
    if len(candidates) > 0:
        meta_info = {
            'aggression': candidates.iloc[0].get('aggression', 1.0),
            'recovery_boost': candidates.iloc[0].get('recovery_boost', 1.0),
            'regime_type': candidates.iloc[0].get('regime_type', '')
        }
        # Intentar extraer pillar multipliers del primer candidato
        try:
            import ast
            pillar_mults = ast.literal_eval(candidates.iloc[0].get('pillar_multipliers', '{}'))
        except:
            pillar_mults = {}
        # Special modes reales para guardar en history
        sm_raw = candidates.iloc[0].get('special_modes', '')
        if isinstance(sm_raw, str) and sm_raw:
            special_modes_list = [m.strip() for m in sm_raw.split(',') if m.strip()]
        elif isinstance(sm_raw, (list, tuple)):
            special_modes_list = list(sm_raw)
    
    # 5. Mostrar resultados
    total_candidates = len(candidates)
    recommended_df = candidates[candidates['recommended'] == True].copy() if 'recommended' in candidates.columns else candidates.head(TOP_CANDIDATES)
    n_recommended = len(recommended_df)
    
    # 5a. Mostrar TODOS los candidatos rankeados
    print(f"\n{'='*70}")
    print(f"   ANALISIS COMPLETO: {total_candidates} CANDIDATOS RANKEADOS")
    print(f"{'='*70}")
    print_candidates_table(candidates, top_n=total_candidates)
    
    # 5b. Mostrar solo RECOMENDADOS
    if n_recommended > 0:
        print(f"\n{'='*70}")
        print(f"   RECOMENDADOS HOY: {n_recommended} CANDIDATOS")
        print(f"{'='*70}")
        print_candidates_table(recommended_df, top_n=n_recommended)
    
    recommended_count = n_recommended if n_recommended > 0 else None
    
    # Mostrar resumen + multipliers de forma visual
    print_summary(regime_score, total_candidates, meta_info, pillar_mults, recommended_count)
    
    # 6. Exportar Excel (con ruta robusta)
    today = datetime.now().strftime("%Y%m%d")
    if EXPORT_EXCEL:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        filename = os.path.join(OUTPUT_DIR, f"{OUTPUT_FILENAME_PREFIX}_{today}.xlsx")
        candidates.to_excel(filename, index=False)
        print(f"\n[OK] Exportado a: {filename}")

    # 7. Guardar histórico para análisis de rendimiento (persistencia)
    try:
        # Guardar top 20 del ranking completo + marcar cuales fueron recomendados
        top_for_history = candidates.head(20).to_dict("records")
        meta_rationale = candidates.iloc[0]["reason"] if len(candidates) > 0 else ""

        special_modes = (candidates.iloc[0].get('special_modes') or '').split(', ') if len(candidates) > 0 else []
        save_daily_run(
            date=today,
            regime_score=regime_score,
            regime_type=meta_info.get("regime_type", ""),
            special_modes=special_modes_list,
            pillar_multipliers=pillar_mults,
            top_candidates=top_for_history,
            meta_rationale=meta_rationale,
            vol_ratio_nan_share=nan_share
        )
        print(f"[OK] Historico guardado en history/{today}.json")
    except Exception as e:
        print(f"[yellow]⚠[/yellow] No se pudo guardar histórico: {e}")

    # 8. Log the top-5 cycle for dynamic PnL tracking (entry=last close from fetch, current starts=entry, formulas for PnL)
    # This turns every screener run (esp. UNIVERSE=all) into an auditable entry for the 5/5 rotation strategy.
    try:
        # Top5 ejecutable = top 5 de los RECOMENDADOS (post downtrend gate, SPEC 4.7).
        # Antes usaba head(5) crudo, que podía incluir nombres vetados por caída reciente.
        exec_pool = candidates[candidates['recommended'] == True] if 'recommended' in candidates.columns else candidates
        if len(exec_pool) == 0:
            exec_pool = candidates
        if len(exec_pool) >= 5:
            top5 = exec_pool.head(5)['ticker'].tolist()
            # entry price = most recent close used by the screener (point-in-time for signal)
            entry_prices = {}
            for t in top5:
                if t in prices.columns and len(prices[t].dropna()) > 0:
                    entry_prices[t] = float(prices[t].dropna().iloc[-1])
            import log_cycle_positions
            log_cycle_positions.log_cycle(datetime.now(), top5, candidates.head(20), notes=f"live run UNIVERSE={effective_universe}", entry_prices=entry_prices)
            # Note: entry from the live prices df; current starts=entry (PnL=0), later refresh_current_prices() or manual edit current -> formulas recalc PnL for the 5
            print(f"[CycleLog] Top5 cycle logged to backtest/portfolio_cycles.xlsx for dynamic PnL tracking")
    except Exception as e:
        print(f"[yellow]⚠[/yellow] Cycle PnL log skipped: {e}")

    # 9. Hybrid integration layer (task 1+2)
    # - Auto-generate Pine watchlist string/file
    # - Send rich summary (Discord webhook if DISCORD_WEBHOOK_URL is set in env)
    if os.environ.get("HYDRA_SKIP_HYBRID", "").lower() in ("1", "true", "yes"):
        print("\n[Hybrid] Skipped (HYDRA_SKIP_HYBRID=1) - dry-run mode for testing")
    else:
        try:
            print("\n[Hybrid] Generating Pine watchlist from latest history...")
            import generate_pine_watchlist
            generate_pine_watchlist.run_feeder(top_n=15, output_path="pine/watchlist.txt", silent=True)
            print("[Hybrid] Sending daily HYDRA summary (webhook if configured)...")
            import send_hydra_summary
            send_hydra_summary.run_sender(top_n=15, silent=True)
            print("[Hybrid] Hybrid layer complete.")
            print("  → pine/watchlist.txt          (paste into Pine 'Watchlist Symbols' input)")
            print("  → pine/hydra_last_summary.json (paste FULL contents into Pine 'i_summary_json' for exact Rec? + values)")
            print("  → pine/hydra_last_summary.txt  (human readable summary)")
            print("  In TradingView: the dashboard table will now use Python's exact recommended_tickers for the 'Rec?' column.")

            # Close the loop: also log the *exact* recommended list that was sent to Pine (the one user pastes)
            # This allows PnL tracking specifically for the lists that appeared in the TV dashboard.
            try:
                rec_col = 'recommended' if 'recommended' in candidates.columns else None
                if rec_col:
                    hybrid_recs = candidates[candidates[rec_col] == True]['ticker'].tolist()
                else:
                    hybrid_recs = candidates.head(15)['ticker'].tolist()
                if hybrid_recs:
                    entry_prices = {}
                    for t in hybrid_recs:
                        if t in prices.columns and len(prices[t].dropna()) > 0:
                            entry_prices[t] = float(prices[t].dropna().iloc[-1])
                    import log_cycle_positions
                    log_cycle_positions.log_cycle(
                        datetime.now(), hybrid_recs, candidates,
                        notes=f"HYBRID exact recommended list sent to Pine/TV (UNIVERSE={effective_universe})",
                        entry_prices=entry_prices
                    )
                    print(f"[CycleLog] Exact hybrid recommended list ({len(hybrid_recs)}) logged for Pine-matched PnL tracking")
                    print("           Run: python refresh_current_prices.py --lookback 5   (to update live current prices & PnL)")
            except Exception as e:
                print(f"[yellow]⚠[/yellow] Hybrid recommended cycle log skipped: {e}")
        except Exception as e:
            print(f"[yellow]⚠[/yellow] Hybrid integration skipped: {e}")
    
    print_footer()

    # Observable final summary for the daily run (what was sent to Pine, what was logged)
    try:
        rec_count = int(candidates['recommended'].sum()) if 'recommended' in candidates.columns else 0
        print("\n=== DAILY RUN SUMMARY (observable) ===")
        print(f"  Recommended for Pine/TV : {rec_count}")
        print(f"  Cycle logs written      : Top5 + exact hybrid recommended list")
        print(f"  History saved           : history/{today}.json")
        print(f"  Artifacts for TV        : pine/watchlist.txt + pine/hydra_last_summary.json (use both for exact Rec?)")
        print("  Use HYDRA_SKIP_HYBRID=1 to dry-run the hybrid layer (no files written for TV).")
    except Exception:
        pass


if __name__ == "__main__":
    main()