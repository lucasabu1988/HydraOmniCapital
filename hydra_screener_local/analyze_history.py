"""
Analizador de Historico del Screener HYDRA Local.

Permite ver el rendimiento de las recomendaciones pasadas.
"""
import pandas as pd
from core.history import get_recent_runs, list_available_dates
from core.tracking import aggregate_winrate, print_winrate_report, get_detailed_trades, print_detailed_report


def show_summary():
    dates = list_available_dates()
    print("\n=== Historico disponible ===")
    print(f"Total de dias guardados: {len(dates)}")
    if dates:
        print(f"Rango: {dates[0]} -> {dates[-1]}")
    print()


def show_last_runs(limit: int = 10):
    runs = get_recent_runs(limit)
    print(f"\n=== Ultimos {len(runs)} dias ===\n")

    for run in runs:
        date = run["date"]
        regime = run.get("regime", {})
        pillars = run.get("pillar_multipliers", {})
        candidates = run.get("top_candidates", [])

        print(f"[FECHA] {date}")
        print(f"   Regimen: {regime.get('score', 0):.2f} ({regime.get('type', '')})")
        if regime.get("special_modes"):
            print(f"   Special Modes: {', '.join(regime['special_modes'])}")

        if pillars:
            print("   Multipliers:", end=" ")
            for p, m in pillars.items():
                print(f"{p}={m:.2f}", end="  ")
            print()

        if candidates:
            recs = [c for c in candidates if c.get("recommended")]
            print(f"   Recomendados ese dia: {len(recs)}")
        print()


def show_winrate():
    report = aggregate_winrate()
    print_winrate_report(report)
    trades_df = get_detailed_trades()
    print_detailed_report(trades_df)


if __name__ == "__main__":
    print("=== HYDRA Screener - Analizador de Historico ===\n")
    show_summary()
    show_last_runs(15)
    show_winrate()

    print("\nNota: El win-rate requiere tracking de retornos forward.")
    print("Ejecuta 'python track_performance.py' para actualizarlos.")
