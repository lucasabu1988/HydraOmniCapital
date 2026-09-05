"""
Persistencia ligera para el Screener HYDRA Local.

Guarda cada corrida del screener en un archivo JSON para poder
medir el rendimiento real de las recomendaciones con el tiempo.
"""
import json
import os
from datetime import datetime
from typing import List, Dict, Any


HISTORY_DIR = "history"


def save_daily_run(
    date: str,
    regime_score: float,
    regime_type: str,
    special_modes: List[str],
    pillar_multipliers: Dict[str, float],
    top_candidates: List[Dict[str, Any]],
    meta_rationale: str = "",
    base_dir: str = None,
    vol_ratio_nan_share: float = 0.0,
    regime_gate_blocked: bool = False,
) -> str:
    """
    Guarda el resultado completo de un día del screener.
    base_dir: optional absolute path to use instead of the default "history" folder.
    vol_ratio_nan_share: from TASK-202 volume watchdog (share of tickers with missing volume data).
    regime_gate_blocked: True when scoring's rich regime was below MIN_REGIME_SCORE*0.85
    (zero recommended because of the regime flag, not because of the downtrend gate).
    """
    out_dir = base_dir or HISTORY_DIR
    os.makedirs(out_dir, exist_ok=True)

    record = {
        "date": date,
        "timestamp": datetime.now().isoformat(),
        "regime": {
            "score": regime_score,
            "type": regime_type,
            "special_modes": special_modes,
            "gate_blocked": regime_gate_blocked,
        },
        "pillar_multipliers": pillar_multipliers,
        "meta_rationale": meta_rationale,
        "top_candidates": top_candidates,
        "vol_ratio_nan_share": vol_ratio_nan_share,
        "regime_gate_blocked": regime_gate_blocked,
    }

    filename = os.path.join(out_dir, f"{date}.json")
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)

    return filename


def load_daily_run(date: str) -> Dict[str, Any]:
    """Carga un día específico."""
    filename = os.path.join(HISTORY_DIR, f"{date}.json")
    if not os.path.exists(filename):
        return {}
    with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)


def list_available_dates() -> List[str]:
    """Lista todas las fechas guardadas."""
    if not os.path.exists(HISTORY_DIR):
        return []
    files = [f for f in os.listdir(HISTORY_DIR) if f.endswith(".json")]
    dates = sorted([f.replace(".json", "") for f in files])
    return dates


def get_recent_runs(limit: int = 10) -> List[Dict[str, Any]]:
    """Devuelve los últimos N runs guardados."""
    dates = list_available_dates()[-limit:]
    runs = []
    for d in dates:
        run = load_daily_run(d)
        if run:
            runs.append(run)
    return runs