"""
Analizador de Histórico del Screener HYDRA Local.

Permite ver el rendimiento de las recomendaciones pasadas.
"""
import pandas as pd
from core.history import get_recent_runs, list_available_dates


def show_summary():
    dates = list_available_dates()
    print(f"\n=== Histórico disponible ===")
    print(f"Total de días guardados: {len(dates)}")
    if dates:
        print(f"Rango: {dates[0]} → {dates[-1]}")
    print()


def show_last_runs(limit: int = 10):
    runs = get_recent_runs(limit)
    print(f"\n=== Últimos {len(runs)} días ===\n")

    for run in runs:
        date = run["date"]
        regime = run.get("regime", {})
        pillars = run.get("pillar_multipliers", {})
        candidates = run.get("top_candidates", [])

        print(f"📅 {date}")
        print(f"   Régimen: {regime.get('score', 0):.2f} ({regime.get('type', '')})")
        if regime.get("special_modes"):
            print(f"   Special Modes: {', '.join(regime['special_modes'])}")

        if pillars:
            print("   Multipliers:", end=" ")
            for p, m in pillars.items():
                print(f"{p}={m:.2f}", end="  ")
            print()

        if candidates:
            recs = [c for c in candidates if c.get("recommended")]
            print(f"   Recomendados ese día: {len(recs)}")
        print()


if __name__ == "__main__":
    print("=== HYDRA Screener - Analizador de Histórico ===\n")
    show_summary()
    show_last_runs(15)

    print("\nNota: Esta es una versión inicial.")
    print("Próximamente se podrá calcular win-rate real una vez que tengamos precios forward.")