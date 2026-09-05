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

# v1 (until 2026-09-05): no version field, regime = compute_regime_score (the simple formula,
#    NOT the one scoring used), no record of which bar was scored.
# v2: schema_version + regime_source + data_last_bar. Files without a version are v1; run
#    relabel_history_regime.py to bring them forward.
HISTORY_SCHEMA_VERSION = 2


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
    data_last_bar: str = None,
) -> str:
    """
    Guarda el resultado completo de un día del screener.
    base_dir: optional absolute path to use instead of the default "history" folder.
    vol_ratio_nan_share: from TASK-202 volume watchdog (share of tickers with missing volume data).
    regime_gate_blocked: True when scoring's rich regime was below MIN_REGIME_SCORE*0.85
    (zero recommended because of the regime flag, not because of the downtrend gate).
    data_last_bar: date (YYYY-MM-DD) of the last price bar that was actually scored. The run
    date is when the screener ran; this is what it saw. Tracking enters at the bar after it.
    """
    out_dir = base_dir or HISTORY_DIR
    os.makedirs(out_dir, exist_ok=True)

    record = {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "regime_source": "rich",          # compute_rich_regime_scores, the one scoring uses
        "date": date,
        "data_last_bar": data_last_bar,
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


def backup_history(dest_dir: str, history_dir: str = None) -> str:
    """Zip history/ (runs + tracking/) into dest_dir. Returns the archive path, '' if nothing to back up.

    history/ is gitignored and is the only record of what the system recommended each day
    (audit 2026-09-06, S3). Point dest_dir at something that is not this disk - a synced
    folder or a second drive - or the backup is theatre.
    """
    import shutil
    src = history_dir or HISTORY_DIR
    if not os.path.isdir(src) or not any(f.endswith(".json") for f in os.listdir(src)):
        return ""
    os.makedirs(dest_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(dest_dir, f"hydra_history_{stamp}")
    return shutil.make_archive(base, "zip", root_dir=src)


def get_recent_runs(limit: int = 10) -> List[Dict[str, Any]]:
    """Devuelve los últimos N runs guardados."""
    dates = list_available_dates()[-limit:]
    runs = []
    for d in dates:
        run = load_daily_run(d)
        if run:
            runs.append(run)
    return runs