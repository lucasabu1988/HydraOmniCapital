"""
Script CLI para tracking de rendimiento forward del Screener HYDRA Local.

Uso:
    python track_performance.py          # Actualiza tracking y muestra reporte
    python track_performance.py --force  # Fuerza recalculo de todo
    python track_performance.py --hybrid-only  # Focus on lists sent to Pine/TV
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import argparse

# Load .env early via centralized loader (for consistency across all tools)
try:
    from utils.env import load_hydra_env
    load_hydra_env()
except Exception as _e:
    print(f"[WARN] .env loader skipped: {_e}")

from config import COST_BP_PER_SIDE
from core.tracking import update_tracking, aggregate_winrate, print_winrate_report, get_detailed_trades, print_detailed_report


def main():
    parser = argparse.ArgumentParser(description="HYDRA Screener - Performance Tracking")
    parser.add_argument("--force", action="store_true", help="Fuerza recalculo de tracking existente")
    parser.add_argument("--hybrid-only", action="store_true",
                        help="Focus on Hybrid Recommended lists sent to Pine/TV (when data is tagged)")
    args = parser.parse_args()

    if args.hybrid_only:
        print("*** HYBRID RECOMMENDED ONLY MODE ***")
        print("   Reporting focused on the exact lists that went to the TradingView dashboard.\n")

    print("=== HYDRA Screener - Forward Return Tracking ===")
    print(f"Cost assumption: {COST_BP_PER_SIDE} bp/side modelled (not fills)\n")

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
