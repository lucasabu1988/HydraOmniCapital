"""
HYDRA Screener Local - Versión inicial ligera
Ejecutar con: python screener.py

Soporta universo pequeño o S&P 500 completo.
"""
from datetime import datetime

from config import TOP_CANDIDATES, EXPORT_EXCEL, OUTPUT_FILENAME_PREFIX, USE_FULL_SP500
from data.universe import get_universe
from data.fetch import fetch_prices, fetch_spy
from core.signals import generate_daily_candidates, compute_regime_score
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
    
    # 3. Generar candidatos (ya incluye Meta-Layer)
    candidates = generate_daily_candidates(prices, spy)
    regime_score = compute_regime_score(spy)
    
    # Extraer info de meta para el resumen (del primer candidato)
    meta_info = {}
    if len(candidates) > 0:
        meta_info = {
            'aggression': candidates.iloc[0].get('aggression', 1.0),
            'recovery_boost': candidates.iloc[0].get('recovery_boost', 1.0)
        }
    
    # 4. Mostrar resultados
    print_candidates_table(candidates, top_n=TOP_CANDIDATES)
    print_summary(regime_score, len(candidates), meta_info)
    
    # 5. Exportar
    if EXPORT_EXCEL:
        today = datetime.now().strftime("%Y%m%d")
        filename = f"output/{OUTPUT_FILENAME_PREFIX}_{today}.xlsx"
        candidates.to_excel(filename, index=False)
        print(f"\n[green]✓[/green] Exportado a: {filename}")
    
    print_footer()


if __name__ == "__main__":
    main()