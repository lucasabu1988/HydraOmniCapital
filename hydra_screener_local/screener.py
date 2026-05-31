"""
HYDRA Screener Local - Versión inicial ligera
Ejecutar con: python screener.py

Soporta universo pequeño o S&P 500 completo.
"""
from datetime import datetime

from config import TOP_CANDIDATES, EXPORT_EXCEL, OUTPUT_FILENAME_PREFIX, USE_FULL_SP500, FILTERS
from data.universe import get_universe
from data.fetch import fetch_prices, fetch_spy
from core.signals import generate_daily_candidates, compute_regime_score
from core.filters import apply_practical_filters, get_filter_summary
from core.history import save_daily_run
from utils.display import print_header, print_candidates_table, print_summary, print_footer


def main():
    print_header()
    
    # 1. Definir universo
    tickers = get_universe(full_sp500=USE_FULL_SP500)
    print(f"Universo seleccionado: {'S&P 500 completo' if USE_FULL_SP500 else 'Lista reducida'} ({len(tickers)} tickers)\n")
    
    # 2. Obtener datos
    prices = fetch_prices(tickers)
    spy = fetch_spy()
    
    if len(prices) < 50:
        print("⚠️  Datos insuficientes. Intenta más tarde o reduce el universo.")
        return

    # 3. Aplicar filtros prácticos (liquidez, precio, etc.)
    original_count = len(prices.columns)
    prices = apply_practical_filters(
        prices,
        min_avg_volume=FILTERS.get("min_avg_volume", 1_000_000),
        min_price=FILTERS.get("min_price", 5.0),
        max_price=FILTERS.get("max_price"),
    )
    
    filter_summary = get_filter_summary(original_count, prices)
    print(f"Filtros aplicados → {filter_summary['remaining']} tickers restantes "
          f"({filter_summary['removed']} eliminados, {filter_summary['removal_pct']}%)\n")
    
    # 4. Generar candidatos (ya incluye Meta-Layer)
    candidates = generate_daily_candidates(prices, spy)
    regime_score = compute_regime_score(spy)
    
    # Extraer info de meta para el resumen
    meta_info = {}
    pillar_mults = {}
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
    
    # 5. Mostrar resultados
    print_candidates_table(candidates, top_n=TOP_CANDIDATES)
    
    recommended_count = None
    if len(candidates) > 0:
        recommended_count = int(candidates.iloc[0].get('recommended_count', TOP_CANDIDATES))
    
    print_summary(regime_score, len(candidates), meta_info, pillar_mults, recommended_count)
    
    # 6. Exportar Excel
    today = datetime.now().strftime("%Y%m%d")
    if EXPORT_EXCEL:
        filename = f"output/{OUTPUT_FILENAME_PREFIX}_{today}.xlsx"
        candidates.to_excel(filename, index=False)
        print(f"\n[green]✓[/green] Exportado a: {filename}")

    # 7. Guardar histórico para análisis de rendimiento (persistencia)
    try:
        top_for_history = candidates.head(20).to_dict("records")
        meta_rationale = candidates.iloc[0]["reason"] if len(candidates) > 0 else ""

        save_daily_run(
            date=today,
            regime_score=regime_score,
            regime_type=meta_info.get("regime_type", ""),
            special_modes=[],  # podemos mejorarlo después
            pillar_multipliers=pillar_mults,
            top_candidates=top_for_history,
            meta_rationale=meta_rationale
        )
        print(f"[green]✓[/green] Histórico guardado en history/{today}.json")
    except Exception as e:
        print(f"[yellow]⚠[/yellow] No se pudo guardar histórico: {e}")
    
    print_footer()


if __name__ == "__main__":
    main()