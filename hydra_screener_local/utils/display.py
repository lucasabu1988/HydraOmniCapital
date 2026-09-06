"""
Salida limpia con print() para el Screener HYDRA Local.
Compatible con cualquier terminal Windows sin dependencias de Unicode.
"""
from datetime import datetime


def print_header():
    line = "+" + "-" * 34 + "+"
    print(line)
    print("| HYDRA SCREENER LOCAL" + " " * 13 + "|")
    print(f"| {datetime.now().strftime('%Y-%m-%d %H:%M')} | Modo Manual" + " " * 9 + "|")
    print(line)


def print_candidates_table(df, top_n: int = 15):
    """Muestra la tabla principal de candidatos en formato texto plano."""
    print("\n   Candidatos del Dia (Meta-Layer + Pillar Multipliers)")
    print("-" * 95)
    print(f"{'Rank':>5} {'Ticker':<8} {'Mom':>7} {'Meta':>7} {'Mult':>7} {'Tipo':<8} {'Mode':<16} {'Agg':>5} {'Rec':>4} {'Razon'}")
    print("-" * 95)

    for _, row in df.head(top_n).iterrows():
        rec = "SI" if row.get('recommended', False) else "NO"
        reason = str(row.get('reason', ''))[:28]
        mode = str(row.get('special_modes', ''))[:14]
        print(
            f"{int(row['rank']):>5} "
            f"{row['ticker']:<8} "
            f"{row.get('momentum', 0):>7.2f} "
            f"{row.get('meta_score', 0):>7.2f} "
            f"{row.get('compass_mult', 1.0):>6.2f}x "
            f"{str(row.get('regime_type', '')):<8} "
            f"{mode:<16} "
            f"{row.get('aggression', 1.0):>5.2f} "
            f"{rec:>4} "
            f"{reason}"
        )

    print("-" * 95)


def print_pillar_multipliers(pillar_mults: dict):
    """Muestra los Pillar Multipliers de forma textual."""
    if not pillar_mults:
        return

    print("\n   Pillar Multipliers (Meta-Layer)")
    print("-" * 65)
    print(f"{'Pillar':<14} {'Mult':>8} {'Tilt':>6} {'Accion'}")
    print("-" * 65)

    for pillar, mult in pillar_mults.items():
        if mult > 1.08:
            tilt = "++"
            action = "Aumentar significativamente"
        elif mult > 1.03:
            tilt = "+"
            action = "Aumentar"
        elif mult < 0.92:
            tilt = "--"
            action = "Reducir significativamente"
        elif mult < 0.97:
            tilt = "-"
            action = "Reducir"
        else:
            tilt = "="
            action = "Mantener"

        print(f"{pillar:<14} {mult:>7.2f}x {tilt:>6} {action}")

    print("-" * 65)


def print_summary(regime_score: float, total_candidates: int, meta_info: dict = None, pillar_mults: dict = None, recommended_count: int = None):
    """Resumen rapido con informacion de Meta-Layer + Pillar Multipliers."""
    print("\n+" + "-" * 35 + "+")
    if regime_score >= 0.5:
        color_word = "STRONG"
    elif regime_score >= 0.35:
        color_word = "MODERATE"
    else:
        color_word = "WEAK"

    print(f"| Regimen Score: {regime_score:.2f}  Tipo: {meta_info.get('regime_type', color_word) if meta_info else color_word:<8} |")
    print("|" + " " * 35 + "|")
    print(f"| Candidatos analizados: {total_candidates:<17} |")
    if recommended_count:
        print(f"| Recomendados hoy (dinamico): {recommended_count:<10} |")
    else:
        print(f"| Top recomendados: {min(15, total_candidates):<23} |")
    print("+" + "-" * 35 + "+")
    print_pillar_multipliers(pillar_mults)


def print_footer():
    print("\nEjecuta de nuevo cuando quieras. Datos de Yahoo Finance.")
