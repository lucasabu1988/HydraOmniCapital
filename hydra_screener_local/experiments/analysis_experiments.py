import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
#!/usr/bin/env python
"""
Temporary analysis & experimentation script for HYDRA Screener improvements.
Run with the project venv.
"""
import json
import os
from collections import Counter, defaultdict
import pandas as pd

HISTORY_DIR = "history"
OUTPUT_DIR = "output"

def load_history(date_str):
    path = os.path.join(HISTORY_DIR, f"{date_str}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None

def get_recommended_tickers(hist):
    if not hist:
        return []
    return [c["ticker"] for c in hist.get("top_candidates", []) if c.get("recommended")]

def analyze_overlap_and_stability():
    print("=" * 60)
    print("OVERLAP & STABILITY ANALYSIS (05-31 vs 06-01)")
    print("=" * 60)
    h31 = load_history("20260531")
    h01 = load_history("20260601")
    
    r31 = get_recommended_tickers(h31)
    r01 = get_recommended_tickers(h01)
    
    print(f"20260531 recommended: {len(r31)} -> {r31}")
    print(f"20260601 recommended: {len(r01)} -> {r01}")
    
    common = set(r31) & set(r01)
    only31 = set(r31) - set(r01)
    only01 = set(r01) - set(r31)
    
    print(f"\nOverlap: {len(common)} names")
    print(f"  {sorted(common)}")
    print(f"\nOnly in 05-31: {sorted(only31)}")
    print(f"Only in 06-01: {sorted(only01)}")
    
    # Rank stability for common names
    print("\nRank movement for overlapping names:")
    for t in sorted(common):
        c31 = next((c for c in h31["top_candidates"] if c["ticker"]==t), {})
        c01 = next((c for c in h01["top_candidates"] if c["ticker"]==t), {})
        print(f"  {t}: 05-31 rank {c31.get('rank')} (comp {c31.get('composite_score')}) -> 06-01 rank {c01.get('rank')} (comp {c01.get('composite_score')})")

def analyze_short_term_boost_impact():
    print("\n" + "=" * 60)
    print("SHORT-TERM BOOST IMPACT (the post-31may addition)")
    print("=" * 60)
    h01 = load_history("20260601")
    if not h01: return
    
    cands = h01.get("top_candidates", [])
    df = pd.DataFrame(cands)
    
    # Top by pure momentum vs by composite (which includes short boost)
    print("Top 10 by raw 'momentum' (old way):")
    print(df.nlargest(10, "momentum")[["rank", "ticker", "momentum", "meta_score", "composite_score", "ret_5d_10d", "short_boost", "recommended"]].to_string(index=False))
    
    print("\nTop 10 by 'composite_score' (current with short boost):")
    print(df.nlargest(10, "composite_score")[["rank", "ticker", "momentum", "meta_score", "composite_score", "ret_5d_10d", "short_boost", "recommended"]].to_string(index=False))
    
    # How many in top 15 would change without the boost?
    top15_comp = set(df.nsmallest(15, "rank")["ticker"])  # already sorted by composite in the json? Wait, rank is by composite
    # Actually in the saved json the 'rank' reflects the final composite order
    print("\nNote: current rank already reflects composite_score ordering (short boost applied).")

def inspect_data_quality_issues():
    print("\n" + "=" * 60)
    print("DATA QUALITY & SUSPICIOUS TICKERS")
    print("=" * 60)
    h01 = load_history("20260601")
    cands = h01.get("top_candidates", [])[:25]
    
    suspicious = []
    for c in cands:
        t = c["ticker"]
        # Known delisted or problematic
        if t in ["SNDK", "BRK.B", "BF.B", "FB"]:  # FB old ticker
            suspicious.append((t, c.get("ret_5d_10d"), c.get("dist_20d_high")))
    
    if suspicious:
        print("Suspicious/delisted tickers appearing in top candidates:")
        for t, ret, dist in suspicious:
            print(f"  {t}: 5/10d_ret={ret}%, dist_high={dist}")
    else:
        print("No obvious delisted in top 25 of latest run.")
    
    # Check volume-related (all have dynamic_vol_threshold but no real vol data in screener)
    print("\nAll candidates have dynamic_vol_threshold=1.5 but volume filter is DISABLED in live screener (min_avg_volume=0 in config).")
    print("This is the #1 known limitation per README and analyze_history.py comments.")

def check_backtest_insights():
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS (from analyze_history)")
    print("=" * 60)
    bt_path = os.path.join("backtest", "backtest_results.json")
    if os.path.exists(bt_path):
        bt = json.load(open(bt_path))
        print(json.dumps(bt, indent=2))
        s = bt.get("summary", {})
        print(f"\nKey signal: Strict filter (vol surge + short mom + near high) showed +4.54% next day, 100% WR on tiny sample (3 names).")
    else:
        print("No backtest results file yet. Run analyze_history.py to populate.")

def analyze_excel_outputs():
    print("\n" + "=" * 60)
    print("EXCEL OUTPUTS INSPECTION (richer data than history JSON)")
    print("=" * 60)
    xlsx_files = [
        os.path.join(OUTPUT_DIR, "hydra_screener_full_20260601.xlsx"),
        os.path.join(OUTPUT_DIR, "hydra_screener_full_20260531.xlsx"),
        os.path.join(OUTPUT_DIR, "hydra_screener_20260531.xlsx"),
    ]
    for xf in xlsx_files:
        if os.path.exists(xf):
            try:
                xl = pd.ExcelFile(xf)
                print(f"\n--- {os.path.basename(xf)} ---")
                print(f"Sheets: {xl.sheet_names}")
                for sn in xl.sheet_names[:3]:
                    df = pd.read_excel(xf, sheet_name=sn)
                    print(f"  Sheet '{sn}': {len(df)} rows, cols={list(df.columns)[:12]}...")
                    if len(df) > 0:
                        print(df.head(8).to_string())
            except Exception as e:
                print(f"  Error reading {xf}: {e}")

def sector_concentration_heuristic():
    """Crude sector guess from known names (no yf.info to stay lightweight)."""
    print("\n" + "=" * 60)
    print("SECTOR / THEME CONCENTRATION (heuristic from known names in latest recs)")
    print("=" * 60)
    h01 = load_history("20260601")
    recs = get_recommended_tickers(h01)
    
    # Very rough manual buckets
    buckets = {
        "Semis/Storage/HW": ["DELL","SNDK","STX","HPE","MU","WDC","AMD","INTC","NVDA","AVGO","QCOM","LRCX","AMAT","KLAC","ON","MRVL","NXPI"],
        "Software/SaaS/Cyber": ["CRWD","PANW","DDOG","FTNT","EQIX","CIEN","CSCO","KEYS","VRT","NTAP","SNOW","PLTR","ZS","NET"],
        "Other Tech/Comm": ["LITE"],
        "Materials/Industrials/Energy": ["NUE","STLD","TRGP"],
        "Healthcare": ["DVA"],
    }
    counts = defaultdict(int)
    for t in recs:
        placed = False
        for bucket, names in buckets.items():
            if t in names:
                counts[bucket] += 1
                placed = True
                break
        if not placed:
            counts["Other/Unknown"] += 1
    
    print("Distribution of 22 recommended (20260601):")
    for b, c in sorted(counts.items(), key=lambda x:-x[1]):
        print(f"  {b}: {c} ({c/22*100:.0f}%)")
    print("\nObservation: Heavy concentration in Semis + Software/Cyber under current STRONG momentum regime. Low diversification.")

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    analyze_overlap_and_stability()
    analyze_short_term_boost_impact()
    inspect_data_quality_issues()
    check_backtest_insights()
    analyze_excel_outputs()
    sector_concentration_heuristic()

def experiment_bad_ticker_filter():
    """Quick experiment: what if we had a hard blacklist for known delisted/zombie tickers?"""
    print("\n" + "=" * 60)
    print("EXPERIMENT: Hard Bad-Ticker Blacklist (kill SNDK etc.)")
    print("=" * 60)
    from config import DELISTED_OR_BAD_TICKERS
    
    h01 = load_history("20260601")
    cands = [c for c in h01.get("top_candidates", [])]
    
    bad_ones = [c for c in cands if c["ticker"] in DELISTED_OR_BAD_TICKERS]
    clean = [c for c in cands if c["ticker"] not in DELISTED_OR_BAD_TICKERS]
    
    print(f"DELISTED_OR_BAD_TICKERS en config: {sorted(DELISTED_OR_BAD_TICKERS)}")
    print(f"Top candidates actuales contienen {len(bad_ones)} tickers en la blacklist: {[b['ticker'] for b in bad_ones]}")
    
    # Re-rank the clean ones as if we had filtered before composite
    clean_df = pd.DataFrame(clean)
    if not clean_df.empty:
        clean_df = clean_df.sort_values("composite_score", ascending=False).reset_index(drop=True)
        clean_df["new_rank"] = range(1, len(clean_df)+1)
        
        print(f"\nSi se hubiera aplicado el filtro (como ahora hace el screener):")
        print("  - Se eliminan los bad antes de rankear -> se promueven los siguientes clean del universo.")
        print(f"  - Top 5 limpio sería:")
        print(clean_df.head(5)[["new_rank", "ticker", "composite_score", "ret_5d_10d", "short_boost"]].to_string(index=False))
        
        orig_rec = [c for c in cands if c.get("recommended")]
        clean_rec = [c for c in orig_rec if c["ticker"] not in DELISTED_OR_BAD_TICKERS]
        print(f"\nDe los 22 recomendados originales, ahora quedarían {len(clean_rec)} después del filtro.")
        print("  (El sistema habría incluido los siguientes tickers limpios del ranking completo de 501.)")


def show_strict_filter_potential():
    """Muestra qué habría pasado si el Strict Filter con volumen real hubiera estado activo."""
    print("\n" + "=" * 60)
    print("STRICT FILTER (vol + ret >15% + cerca de high) — ahora disponible en vivo")
    print("=" * 60)
    print("Con la extensión de fetch + signals, cada corrida ahora calcula:")
    print("  - vol_ratio (volumen 5d / 20d)")
    print("  - passes_strict")
    print("  - +18% bonus al composite_score para los que lo pasan")
    print()
    print("Ejemplo del backtest anterior (20260531): el Strict Filter dio +4.54% al día siguiente")
    print("con 100% win-rate (aunque solo 3 nombres lo pasaron).")
    print("Ahora estos nombres se verán claramente en la tabla y en el Excel con la columna 'passes_strict'.")


def simulate_sector_control_impact():
    """
    Simula el efecto del nuevo control sectorial sobre las corridas históricas reales.
    Usa la misma función que el screener en producción.
    """
    print("\n" + "=" * 70)
    print("SIMULACIÓN: IMPACTO DEL CONTROL SECTORIAL (sobre datos reales 31-may / 01-jun)")
    print("=" * 70)

    from core.filters import apply_sector_concentration_control
    import config

    for date_str in ["20260531", "20260601"]:
        hist = load_history(date_str)
        if not hist:
            continue

        cands = hist.get("top_candidates", [])
        df = pd.DataFrame(cands)

        # Solo los que habrían sido recomendados originalmente
        rec_df = df[df.get("recommended", False)].copy()
        if rec_df.empty:
            continue

        # Compatibilidad: archivos antiguos pueden no tener composite_score todavía
        if "composite_score" not in rec_df.columns:
            rec_df["composite_score"] = rec_df.get("meta_score", rec_df.get("momentum", 0))

        print(f"\n--- {date_str} ---")
        print(f"Recomendados originales: {len(rec_df)}")

        # Aplicar control (misma lógica que en producción)
        controlled = apply_sector_concentration_control(rec_df)

        # Ver concentración antes vs después
        orig_sectors = rec_df["ticker"].apply(lambda t: config.SECTOR_BUCKETS.get(t, "Other")).value_counts()
        new_sectors = controlled["sector"].value_counts()

        print("Concentración original:")
        for s, c in orig_sectors.items():
            print(f"  {s}: {c}")

        penalized = controlled[controlled.get("sector_penalty_applied", False)]
        if not penalized.empty:
            print(f"\nNombres penalizados por sector control: {penalized['ticker'].tolist()}")
        else:
            print("\nNingún nombre fue penalizado (dentro de límites).")

        print(f"Top 8 después de control sectorial:")
        print(controlled.head(8)[["rank", "ticker", "sector", "composite_score", "sector_penalty_applied"]].to_string(index=False))


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    experiment_bad_ticker_filter()
    show_strict_filter_potential()
    simulate_sector_control_impact()
    print("\n[Done] All experiments finished.")