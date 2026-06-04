"""
Script CLI para tracking de rendimiento forward del Screener HYDRA Local.

Uso:
    python track_performance.py          # Actualiza tracking y muestra reporte
    python track_performance.py --force  # Fuerza recalculo de todo
"""
import argparse

from core.tracking import update_tracking, aggregate_winrate, print_winrate_report, get_detailed_trades, print_detailed_report


def main():
    parser = argparse.ArgumentParser(description="HYDRA Screener - Performance Tracking")
    parser.add_argument("--force", action="store_true", help="Fuerza recalculo de tracking existente")
    args = parser.parse_args()

    print("=== HYDRA Screener - Forward Return Tracking ===\n")

    # 1. Actualizar tracking
    update_tracking(force_recompute=args.force)

    # 2. Generar y mostrar reporte
    report = aggregate_winrate()
    print_winrate_report(report)

    # 3. Mostrar detalle por ticker
    trades_df = get_detailed_trades()
    print_detailed_report(trades_df)


if __name__ == "__main__":
    main()
