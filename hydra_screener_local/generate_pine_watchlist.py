"""
Watchlist Feeder for Pine Script (HYDRA Hybrid)

Este helper genera automáticamente el string de tickers listo para pegar
en el input `i_watchlist` del Pine Script `pine/HYDRA_Screener.pine`.

Uso típico (después de correr el screener diario):

    python generate_pine_watchlist.py
    python generate_pine_watchlist.py --top 12 --output pine/watchlist.txt

El output es algo como:
AAPL,MSFT,NVDA,AMD,AVGO,...

Opciones:
  --top N     : tope de visualización explícito (default: lista completa; Pine i_max_watchlist limita la tabla)
  --output F  : escribir a archivo en vez de solo imprimir
  --latest    : forzar usar el history más reciente (default)
"""

import argparse
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

def find_latest_history(history_dir: Path = Path("history")) -> Path:
    """Encuentra el archivo de history más reciente."""
    files = list(history_dir.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"No se encontraron archivos en {history_dir}")
    return max(files, key=lambda p: p.stat().st_mtime)

def load_recommended_tickers(history_path: Path, top_n: Optional[int] = None) -> list[str]:
    """Tickers marcados `recommended` en el history JSON, ordenados por rank.

    Solo los marcados: cero recomendados devuelve [] (auditoría A — el fallback anterior
    publicaba candidatos rechazados como watchlist). `top_n` es un tope de visualización
    explícito; por defecto se devuelve la lista completa y es Pine quien limita la tabla
    (`i_max_watchlist`).
    """
    with open(history_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    recommended = sorted((c for c in data.get("top_candidates", []) if c.get("recommended")),
                         key=lambda c: c.get("rank", 10**6))
    tickers = list(dict.fromkeys(c["ticker"] for c in recommended))     # one entry per ticker, best rank first
    return tickers[:top_n] if top_n else tickers

def generate_watchlist_string(tickers: list[str]) -> str:
    """Genera el string comma-separated para el input del Pine."""
    return ",".join(tickers)

def run_feeder(top_n: Optional[int] = None, output_path: Optional[str] = None, history_dir: str = "history", silent: bool = False) -> str:
    """Core function to generate the Pine watchlist string.

    Returns the comma-separated watchlist string.
    If output_path is given, also writes it to the file.
    """
    history_dir_p = Path(history_dir)
    try:
        latest = find_latest_history(history_dir_p)
    except FileNotFoundError as e:
        if not silent:
            print(f"[ERROR] {e}")
            print("Run the screener first (python screener.py) to generate history.")
        raise

    if not silent:
        print(f"Using latest history: {latest.name} (date: {datetime.fromtimestamp(latest.stat().st_mtime).strftime('%Y-%m-%d %H:%M')})")

    tickers = load_recommended_tickers(latest, top_n=top_n)
    if not tickers and not silent:
        # No fallback: an empty watchlist is the correct output of a closed cycle.
        print("[INFO] 0 recommended tickers in the latest run - the watchlist is empty on purpose (no positions).")

    watchlist_str = generate_watchlist_string(tickers)

    if not silent:
        print("\n=== PINE WATCHLIST ===")
        print(watchlist_str)
        print(f"\n({len(tickers)} tickers — ready to paste into Pine 'i_watchlist')")

    if output_path:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            f.write(watchlist_str)
        if not silent:
            print(f"\n[OK] Saved to: {out_p}")

    return watchlist_str


def main():
    parser = argparse.ArgumentParser(description="Genera watchlist para el Pine HYDRA_Screener.pine")
    parser.add_argument("--top", type=int, default=None, help="Tope de visualización explícito; por defecto la lista completa (Pine i_max_watchlist limita la tabla)")
    parser.add_argument("--output", type=str, default=None, help="Archivo de salida (ej: pine/watchlist.txt). Si no se da, solo imprime.")
    parser.add_argument("--history-dir", type=str, default="history", help="Directorio de history (default: history)")
    args = parser.parse_args()

    try:
        run_feeder(top_n=args.top, output_path=args.output, history_dir=args.history_dir, silent=False)
    except Exception as e:
        print(f"[ERROR] {e}")
        return 1

    # Print usage reminder
    print("\nCómo usarlo:")
    print("1. Copia el string de arriba.")
    print("2. En TradingView, edita el Pine 'HYDRA_Screener [Hybrid v1.2]'.")
    print("3. Pega en el campo 'Watchlist Symbols (comma separated - paste from Python)'.")
    print("4. Aplica el script a un chart de uno de tus símbolos HYDRA o úsalo como overlay.")
    print("5. La tabla mostrará el ranking de tu watchlist con scoring HYDRA (ver SPEC).")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
