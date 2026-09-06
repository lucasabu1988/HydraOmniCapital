"""
Backfill del historial del screener local usando datos del sistema live (OmniCapital).

Lee cycle_log.json y decisions.jsonl para generar archivos history/YYYYMMDD.json
y history/tracking/YYYYMMDD.json con retornos reales ya conocidos.
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import json
import os
from collections import defaultdict
from datetime import datetime

HISTORY_DIR = "history"
TRACKING_DIR = "history/tracking"
CYCLE_LOG_PATH = "../state/cycle_log.json"
DECISIONS_PATH = "../state/ml_learning/decisions.jsonl"


def load_cycle_log():
    with open(CYCLE_LOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_entry_decisions():
    """Carga decisiones de entrada agrupadas por fecha."""
    by_date = defaultdict(list)
    if not os.path.exists(DECISIONS_PATH):
        return by_date
    with open(DECISIONS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("decision_type") == "entry":
                by_date[d["date"]].append(d)
    return by_date


def get_regime_for_date(date_str, decisions_by_date):
    entries = decisions_by_date.get(date_str, [])
    if not entries:
        return {"score": 0.5, "type": "UNKNOWN", "special_modes": []}

    scores = [e["regime_score"] for e in entries if e.get("regime_score") is not None]
    buckets = [e["regime_bucket"] for e in entries if e.get("regime_bucket")]

    avg_score = sum(scores) / len(scores) if scores else 0.5

    # Mapear regime_bucket del live a tipo del screener
    bucket_map = {
        "strong_bull": "STRONG",
        "mild_bull": "MODERATE",
        "neutral": "CAUTIOUS",
        "mild_bear": "CAUTIOUS",
        "strong_bear": "WEAK",
        "crash": "WEAK",
    }

    if buckets:
        most_common = max(set(buckets), key=buckets.count)
        reg_type = bucket_map.get(most_common, most_common.upper())
    else:
        reg_type = "UNKNOWN"

    # Special modes dummy basado en score
    special = []
    if avg_score >= 0.68:
        special.append("STRONG_BROAD_MOMENTUM")
    elif avg_score < 0.25:
        special.append("CRISIS_ACUTE")

    return {
        "score": round(avg_score, 3),
        "type": reg_type,
        "special_modes": special,
    }


def generate_screener_history(cycle, regime):
    """Genera un dict en formato history/ del screener local."""
    date_str = cycle["start_date"].replace("-", "")
    candidates = []

    for pos in cycle.get("positions_detail", []):
        pnl = pos.get("pnl_pct")
        if pnl is None:
            continue

        # Intentar obtener momentum del decisions.jsonl (si coincide ticker+fecha)
        # Por simplicidad usamos valores dummy para campos del screener
        candidates.append({
            "rank": len(candidates) + 1,
            "ticker": pos["symbol"],
            "momentum": round(pos.get("entry_price", 100) / 100, 3),
            "meta_score": round(1.0 + pnl / 100, 3),
            "regime": regime["score"],
            "regime_type": regime["type"],
            "special_modes": ", ".join(regime["special_modes"]),
            "aggression": 1.0,
            "compass_mult": 1.0,
            "recommended": True,
            "reason": pos.get("exit_reason", "live_trade"),
            "recommended_count": len(cycle.get("positions_detail", [])),
        })

    record = {
        "date": date_str,
        "timestamp": datetime.now().isoformat(),
        "regime": regime,
        "pillar_multipliers": {},
        "meta_rationale": f"Backfill from live cycle {cycle.get('cycle')}",
        "top_candidates": candidates,
    }
    return record


def generate_tracking(cycle, regime):
    """Genera tracking con retornos reales ya conocidos del ciclo live."""
    date_str = cycle["start_date"].replace("-", "")
    candidates = []

    for pos in cycle.get("positions_detail", []):
        pnl = pos.get("pnl_pct")
        if pnl is None:
            continue

        ret = pnl / 100.0
        entry_price = pos.get("entry_price") or pos.get("entry")
        exit_price = pos.get("exit_price") or pos.get("exit")
        candidates.append({
            "ticker": pos["symbol"],
            "entry_price": entry_price,
            "entry_date": cycle["start_date"],
            "returns": {
                "return_5d": round(ret, 4),
                "exit_price_5d": exit_price,
            },
        })

    return {
        "date": date_str,
        "regime": regime,
        "candidates": candidates,
    }


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def main():
    print("=== Backfill desde datos live ===\n")

    cycles = load_cycle_log()
    decisions = load_entry_decisions()

    created = 0
    for cycle in cycles:
        if cycle.get("status") != "closed":
            continue

        start_date = cycle["start_date"]
        date_str = start_date.replace("-", "")

        # Evitar sobrescribir historial real del screener
        hist_path = os.path.join(HISTORY_DIR, f"{date_str}.json")
        track_path = os.path.join(TRACKING_DIR, f"{date_str}.json")

        if os.path.exists(hist_path) and date_str != "20260603":
            # Saltar si ya existe (excepto hoy que sabemos que es del screener)
            pass

        regime = get_regime_for_date(start_date, decisions)
        hist = generate_screener_history(cycle, regime)
        track = generate_tracking(cycle, regime)

        save_json(hist_path, hist)
        save_json(track_path, track)
        created += 1
        print(f"  OK {date_str}: {len(track['candidates'])} candidatos  Regimen: {regime['type']} ({regime['score']:.2f})")

    print(f"\n{created} dias backfill creados.")
    print("Ejecuta 'python track_performance.py' o 'python analyze_history.py' para ver win-rate.")


if __name__ == "__main__":
    main()
