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
  --top N     : número máximo de tickers recomendados a incluir (default 15)
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

def load_recommended_tickers(history_path: Path, top_n: int = 15) -> list[str]:
    """Carga los tickers recomendados del history JSON (top N por rank)."""
    with open(history_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    top_candidates = data.get("top_candidates", [])
    if not top_candidates:
        return []

    # Preferir los que tienen recommended=True, ordenados por rank
    recommended = [c for c in top_candidates if c.get("recommended")]
    if recommended:
        recommended.sort(key=lambda c: c.get("rank", 999))
        tickers = [c["ticker"] for c in recommended[:top_n]]
    else:
        # Fallback: top N por rank/composite aunque no marcados recommended
        top_candidates.sort(key=lambda c: c.get("rank", 999))
        tickers = [c["ticker"] for c in top_candidates[:top_n]]

    return tickers

def generate_watchlist_string(tickers: list[str]) -> str:
    """Genera el string comma-separated para el input del Pine."""
    return ",".join(tickers)

def run_feeder(top_n: int = 15, output_path: Optional[str] = None, history_dir: str = "history", silent: bool = False) -> str:
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
    if not tickers:
        if not silent:
            print("[WARN] No recommended tickers found in history.")
        # fallback to top N overall
        with open(latest, "r", encoding="utf-8") as f:
            data = json.load(f)
        top_cands = data.get("top_candidates", [])[:top_n]
        tickers = [c["ticker"] for c in top_cands]

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
    parser.add_argument("--top", type=int, default=15, help="Máximo de tickers recomendados (default 15)")
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
