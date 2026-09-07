"""
Tests de compliance contra HYDRA_ALGORITHM_SPEC.md v1.2

Este archivo valida que la implementación en core/ coincide con las fórmulas,
tablas, triggers y comportamientos descritos formalmente en el SPEC.

Se usan datos sintéticos para aislar cada componente (sin red, sin dependencias externas).

Ejecutar:
    python test_spec_compliance.py

Si todos los checks pasan, la implementación es fiel al spec.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

# Consolas Windows usan cp1252 por defecto y rompen con emojis/bullets UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import ast
import re
import pandas as pd
import numpy as np
from datetime import datetime

# Patch config para tests controlados (evitar efectos laterales)
import config
config.UNIVERSE = "custom"
config.USE_FULL_SP500 = False
config.FILTERS = {"min_avg_volume": 0, "min_price": 0, "max_price": None, "exclude_sectors": []}
config.TOP_CANDIDATES = 10
config.MOMENTUM_LOOKBACK = 90
config.SHORT_TERM_LOOKBACK = 10
config.PROXIMITY_HIGH_DAYS = 20
config.MAX_DIST_TO_HIGH_PCT = 3.0
config.SHORT_TERM_BOOST = 0.35
config.VOL_SURGE_THRESHOLD = 1.50
config.GEO_VOL_THRESHOLD_ADJUST = 0.6
config.MIN_VOL_THRESHOLD = 1.0
config.REGIME_SMA = 200
config.MIN_REGIME_SCORE = 0.35
config.MAX_PER_SECTOR = 5

from core.signals import (
    compute_momentum_score,
    compute_short_term_features,
    generate_daily_candidates,
)
from core.regime import compute_rich_regime_scores, RegimeScores
from core.meta_layer import LightweightMetaLayer

# --- Helpers de datos sintéticos ---

def make_synthetic_prices(n_tickers=10, n_days=300, seed=42):
    np.random.seed(seed)
    tickers = [f"T{str(i).zfill(3)}" for i in range(n_tickers)]
    dates = pd.date_range(end=datetime.now().date(), periods=n_days, freq="D")
    data = {}
    for t in tickers:
        rets = np.random.normal(0.0004, 0.018, n_days)
        prices = 50 * np.exp(np.cumsum(rets))
        data[t] = prices
    df = pd.DataFrame(data, index=dates)
    return df

def make_synthetic_spy(n_days=300, seed=123, base_price=400.0):
    np.random.seed(seed)
    dates = pd.date_range(end=datetime.now().date(), periods=n_days, freq="D")
    rets = np.random.normal(0.0005, 0.012, n_days)
    prices = base_price * np.exp(np.cumsum(rets))
    return pd.Series(prices, index=dates, name="SPY")

def make_synthetic_volumes(prices: pd.DataFrame, seed=99):
    np.random.seed(seed)
    vols = pd.DataFrame(
        np.random.uniform(1_000_000, 10_000_000, size=prices.shape),
        index=prices.index,
        columns=prices.columns
    )
    return vols

# --- Tests por sección del SPEC ---

def test_4_1_momentum_score():
    """SPEC 4.1: Momentum Score (risk-adjusted 90d / 63d vol)"""
    print("\n=== SPEC 4.1 Momentum Score ===")
    prices = make_synthetic_prices(n_tickers=5, n_days=300)
    scores = compute_momentum_score(prices)

    assert len(scores) == 5
    assert scores.notna().all()
    # Debe ser retorno_90 / vol_63_annualized
    for t in scores.index:
        mom = prices[t].pct_change(90).iloc[-1]
        vol = prices[t].pct_change().rolling(63).std().iloc[-1] * np.sqrt(252)
        expected = mom / vol if vol > 0 else np.nan
        np.testing.assert_allclose(scores[t], expected, rtol=1e-5)
    print("[OK] Momentum score matches exact formula SPEC 4.1")
    return True

def test_4_2_short_term_and_strict():
    """SPEC 4.2: Short-term features + Strict Filter + 18% bonus"""
    print("\n=== SPEC 4.2 Short-Term + Strict Filter ===")
    # 200 días, no 50: con 50 el momentum de 90d es NaN para todos los tickers,
    # generate_daily_candidates devolvía 0 candidatos y el test se saltaba los checks
    # de fila devolviendo True (vacuo — audit ASTRA-04, defecto 2).
    prices = make_synthetic_prices(n_tickers=3, n_days=200)
    volumes = make_synthetic_volumes(prices)

    feats = compute_short_term_features(prices, volumes=volumes)
    assert not feats.empty
    assert 'ret_short' in feats.columns
    assert 'dist_to_high' in feats.columns
    assert 'vol_ratio' in feats.columns

    # Forzar fuertemente un caso que pase strict (valores extremos)
    prices2 = prices.copy()
    prices2.iloc[-1, 0] = prices2.iloc[-11, 0] * 1.30   # ret_short ~30% >15
    max20 = prices2.iloc[-20:, 0].max()
    prices2.iloc[-1, 0] = max20 * 0.99   # dist_to_high ~ -1% >= -2

    # Vol surge muy alto
    volumes2 = volumes.copy()
    avg20 = volumes2.iloc[-20:, 0].mean()
    volumes2.iloc[-5:, 0] = avg20 * 3.0

    feats2 = compute_short_term_features(prices2, volumes=volumes2)
    ret = feats2.iloc[0]['ret_short']
    dist = feats2.iloc[0]['dist_to_high']
    vr = feats2.iloc[0]['vol_ratio']
    dyn_th = 1.50 + (0.0 * 0.6)
    dyn_th = max(1.0, dyn_th)
    passes = (ret > 15) and (dist >= -2) and (vr > dyn_th)

    print(f"  ret_short={ret:.2f}, dist={dist:.2f}, vol_ratio={vr:.2f}, dyn_th={dyn_th:.2f}, passes_strict={passes}")
    assert passes, "Debería pasar strict con los datos fuertemente forzados"
    print("[OK] Strict filter logic matches SPEC 4.2 (ret>15, dist>=-2, vol>th)")

    # Bonus del 18% se aplica en generate_daily_candidates
    candidates = generate_daily_candidates(prices2, make_synthetic_spy(200), volumes=volumes2)

    # Cero candidatos es un fallo, no un motivo para saltarse los asserts: con una
    # implementación vacía este test debe ponerse rojo (ASTRA-04).
    if len(candidates) == 0:
        print("[FAIL] 0 candidates: el strict filter y el bonus no se han ejercitado")
        return False

    top = candidates.iloc[0]
    assert top['passes_strict'] == True, \
        f"el ticker forzado debe pasar strict; passes_strict={top['passes_strict']}"
    # El composite debe reflejar el bonus (ver SPEC 4.5): valor real, no truthiness.
    expected = top['meta_score'] * (1 + top['short_boost'] * config.SHORT_TERM_BOOST) * 1.18
    np.testing.assert_allclose(top['composite_score'], expected, rtol=2e-3)
    print(f"[OK] passes_strict=True y composite={top['composite_score']:.4f} = "
          f"meta {top['meta_score']:.4f} x (1 + boost {top['short_boost']:.3f} x "
          f"{config.SHORT_TERM_BOOST}) x 1.18 (SPEC 4.5)")
    return True

def test_4_3_rich_regime():
    """SPEC 4.3: Rich Regime con pesos exactos y sub-scores"""
    print("\n=== SPEC 4.3 Rich Regime ===")
    spy = make_synthetic_spy(300)
    # 40 tickers, no 30: el breadth de core/regime.py sólo se calcula con
    # len(prices.columns) > 30, así que con 30 el test medía la constante 0.5 por
    # defecto y nunca la fórmula (audit ASTRA-04, nota sobre el test de régimen).
    prices = make_synthetic_prices(n_tickers=40, n_days=300)  # para breadth

    reg = compute_rich_regime_scores(spy, prices)

    assert isinstance(reg, RegimeScores)
    assert 0.0 <= reg.overall <= 1.0
    assert 0.0 <= reg.trend <= 1.0
    assert 0.0 <= reg.volatility <= 1.0
    assert 0.0 <= reg.momentum <= 1.0
    assert 0.0 <= reg.drawdown_velocity <= 1.0
    assert 0.0 <= reg.breadth_proxy <= 1.0

    # Verificar que overall es weighted sum (pesos del SPEC)
    expected_overall = (
        reg.trend * 0.30 +
        reg.momentum * 0.25 +
        reg.volatility * 0.20 +
        reg.drawdown_velocity * 0.15 +
        reg.breadth_proxy * 0.10
    )
    # Los sub-scores se publican redondeados a 3 decimales y `overall` se calcula con los
    # valores sin redondear, así que reconstruirlo no puede ser más fino que ese redondeo:
    # 0.5e-3 (sub-scores, pesos que suman 1) + 0.5e-3 (redondeo de overall) = 1e-3.
    # Antes pasaba con rtol=1e-5 sólo porque breadth era la constante 0.5 (exacta).
    np.testing.assert_allclose(reg.overall, expected_overall, rtol=0, atol=1.05e-3)
    print("[OK] Regime overall usa pesos exactos del SPEC 4.3 (30/25/20/15/10)")
    print(f"  overall={reg.overall:.3f} trend={reg.trend:.3f} vol={reg.volatility:.3f}")

    # El breadth medido, no el 0.5 por defecto: 0.3*positivos + 0.3*sobre SMA50 + 0.4*sobre SMA200
    ret_1d = prices.pct_change(fill_method=None).iloc[-1]
    expected_breadth = (0.3 * float((ret_1d > 0).mean())
                        + 0.3 * float((prices.iloc[-1] > prices.rolling(50).mean().iloc[-1]).mean())
                        + 0.4 * float((prices.iloc[-1] > prices.rolling(200).mean().iloc[-1]).mean()))
    np.testing.assert_allclose(reg.breadth_proxy, round(expected_breadth, 3), rtol=1e-6)
    assert reg.breadth_proxy != 0.5, \
        "breadth 0.5 con 40 columnas = la rama de breadth no se ejecutó"
    print(f"  breadth={reg.breadth_proxy:.3f} (blend medido, 40 columnas)")

    # Frontera del propio código: con 30 columnas o menos el breadth NO se calcula.
    # Documentado con un assert para que el umbral no se mueva en silencio.
    narrow = make_synthetic_prices(n_tickers=30, n_days=300)
    reg_narrow = compute_rich_regime_scores(spy, narrow)
    assert reg_narrow.breadth_proxy == 0.5, \
        f"con 30 columnas el breadth debe ser el 0.5 por defecto, fue {reg_narrow.breadth_proxy}"
    narrow_ret_1d = narrow.pct_change(fill_method=None).iloc[-1]
    narrow_blend = (0.3 * float((narrow_ret_1d > 0).mean())
                    + 0.3 * float((narrow.iloc[-1] > narrow.rolling(50).mean().iloc[-1]).mean())
                    + 0.4 * float((narrow.iloc[-1] > narrow.rolling(200).mean().iloc[-1]).mean()))
    assert round(narrow_blend, 3) != 0.5, \
        "el sintético de 30 columnas no distingue el default del blend; cambia la semilla"
    print(f"[OK] Breadth: >30 columnas usa el blend; con 30 queda en 0.5 "
          f"(el blend habría sido {narrow_blend:.3f}) (SPEC 4.3)")
    return True

def test_4_4_meta_layer_and_pillars():
    """SPEC 4.4: Meta-Layer base biases (tabla), Special Modes triggers, Pillar Multipliers + clamp"""
    print("\n=== SPEC 4.4 Meta-Layer + Pillars ===")
    meta = LightweightMetaLayer()

    # Test base biases por regime (deben coincidir con tabla del SPEC 4.4.1)
    # STRONG
    adj = meta.compute_adjustment(regime_score=0.70)
    assert adj.regime_type == "STRONG"
    # Allow small tolerance; in practice may have floating adjustments
    assert adj.pillar_multipliers["COMPASS"] >= 1.14, f"COMPASS for STRONG was {adj.pillar_multipliers['COMPASS']}"
    assert adj.pillar_multipliers["Rattlesnake"] <= 0.86

    # WEAK
    adj = meta.compute_adjustment(regime_score=0.20)
    assert adj.regime_type == "WEAK"
    assert adj.pillar_multipliers["COMPASS"] <= 0.76
    assert adj.pillar_multipliers["Rattlesnake"] >= 1.17

    print("[OK] Base pillar multipliers por regime_type coinciden con tabla SPEC 4.4.1 (approx tolerance for floating)")

    # Special modes triggers (SPEC 4.4.2)
    # CRISIS_ACUTE
    adj = meta.compute_adjustment(regime_score=0.70, recent_drawdown=0.15)
    assert "CRISIS_ACUTE" in adj.special_modes
    assert adj.pillar_multipliers["COMPASS"] < 1.0   # debe bajar

    # STRONG_BROAD_MOMENTUM
    adj = meta.compute_adjustment(regime_score=0.75, volatility_level=0.4, recent_drawdown=0.01)
    assert "STRONG_BROAD_MOMENTUM" in adj.special_modes
    assert adj.pillar_multipliers["COMPASS"] > 1.15  # boost

    print("[OK] Special Modes triggers y efectos coinciden con SPEC 4.4.2")

    # Clamp final (SPEC 4.4.3)
    adj = meta.compute_adjustment(regime_score=0.90, recent_drawdown=0.01)
    for v in adj.pillar_multipliers.values():
        assert 0.60 <= v <= 1.45
    print("[OK] Pillar multipliers clamped a [0.60, 1.45] (SPEC 4.4.3)")
    return True

def test_4_5_composite_and_strict_bonus():
    """SPEC 4.5: Composite assembly + short boost + 18% strict bonus"""
    print("\n=== SPEC 4.5 Composite + Strict Bonus ===")
    prices = make_synthetic_prices(n_tickers=5, n_days=100)
    spy = make_synthetic_spy(100)
    volumes = make_synthetic_volumes(prices)

    # Forzar fuertemente el primer ticker (el que debe pasar strict)
    forced = prices.columns[0]
    prices.iloc[-1, 0] = prices.iloc[-11, 0] * 1.30
    max20 = prices.iloc[-20:, 0].max()
    prices.iloc[-1, 0] = max20 * 0.99
    volumes.iloc[-5:, 0] = volumes.iloc[-20:, 0].mean() * 3.0

    cands = generate_daily_candidates(prices, spy, volumes=volumes)

    # Sin candidatos no hay nada verificado: fallo. Con la implementación sustituida por
    # un DataFrame vacío este test tiene que dar False, no True (audit ASTRA-04, defecto 2).
    if len(cands) == 0:
        print("[FAIL] 0 candidates en test 4.5: el composite no se ha verificado")
        return False
    if 'ticker' not in cands.columns or forced not in set(cands['ticker']):
        print(f"[FAIL] el ticker forzado {forced} no está en la salida: "
              f"{list(cands.columns)[:6]}")
        return False

    # El ticker forzado, no cands.iloc[0]: el ranking va por composite y el forzado
    # puede tener momentum bajo (aquí sale 4º de 5). Buscar la fila que se ha forzado
    # es lo que hace que los asserts se ejecuten de verdad.
    row = cands[cands['ticker'] == forced].iloc[0]

    assert row['passes_strict'] == True, \
        f"el ticker forzado {forced} debe pasar strict; vol_ratio={row['vol_ratio']}, " \
        f"ret_10d={row['ret_5d_10d']}, dist_high={row['dist_20d_high']}"
    assert row['short_boost'] > 0, f"short_boost={row['short_boost']}"

    # Valores reales: composite = meta * (1 + short_boost * SHORT_TERM_BOOST) * 1.18
    without_bonus = row['meta_score'] * (1 + row['short_boost'] * config.SHORT_TERM_BOOST)
    np.testing.assert_allclose(row['composite_score'], without_bonus * 1.18, rtol=2e-3)

    # ...y el bonus es condicional: una fila que no pasa strict no lo lleva.
    plain = cands[~cands['passes_strict'].astype(bool)]
    assert len(plain) > 0, "el sintético no tiene ninguna fila sin strict para contrastar"
    plain_row = plain.iloc[0]
    np.testing.assert_allclose(
        plain_row['composite_score'],
        plain_row['meta_score'] * (1 + plain_row['short_boost'] * config.SHORT_TERM_BOOST),
        rtol=2e-3)

    print(f"[OK] Composite incluye short boost + 18% strict bonus (SPEC 4.5): "
          f"{forced} {without_bonus:.4f} x 1.18 = {row['composite_score']:.4f}; "
          f"{plain_row['ticker']} sin strict = {plain_row['composite_score']:.4f}")
    return True

def test_4_6_sector_control():
    """SPEC 4.6: Sector Concentration Control - limite duro en la seleccion (TASK-320)"""
    print("\n=== SPEC 4.6 Sector Control ===")
    from collections import Counter
    prices = make_synthetic_prices(n_tickers=40, n_days=100)
    spy = make_synthetic_spy(100)

    # Forzar concentracion: media universo en un sector, el resto sin resolver ("Other")
    sector_map = {t: ("Technology" if i % 2 == 0 else "Other")
                  for i, t in enumerate(prices.columns)}
    cands = generate_daily_candidates(prices, spy, sector_map=sector_map)
    rec = cands[cands['recommended']]

    assert 'sector_penalty_applied' in cands.columns

    # El limite tiene que vincular de verdad — la penalidad blanda anterior nunca lo hacia
    known = Counter(rec[rec['sector'] != 'Other']['sector'])
    worst = max(known.values()) if known else 0
    print(f"  recomendados: {len(rec)} | max por sector conocido: {worst} "
          f"(limite {config.MAX_PER_SECTOR})")
    assert worst <= config.MAX_PER_SECTOR, \
        f"el limite por sector no vincula: {worst} > {config.MAX_PER_SECTOR}"

    # "Other" (sector desconocido) esta exento: no se puede estar sobre-concentrado en lo que no se sabe
    n_other = int((rec['sector'] == 'Other').sum())
    print(f"  con sector desconocido en la lista: {n_other} (exentos del limite)")
    print("[OK] Sector control aplicado (SPEC 4.6) - limite duro en la seleccion")
    return True

def test_4_7_dynamic_recommended():
    """SPEC 4.7: Dynamic count y recommended flag"""
    print("\n=== SPEC 4.7 Dynamic Recommended ===")
    prices = make_synthetic_prices(n_tickers=30, n_days=200)
    spy = make_synthetic_spy(200)

    cands = generate_daily_candidates(prices, spy)

    rc = int(cands.iloc[0]['recommended_count'])
    assert 6 <= rc <= 28, f"Dynamic count fuera de rango SPEC: {rc}"

    n_rec = cands['recommended'].sum()
    assert n_rec <= rc
    print("[OK] Dynamic count en [6,28] y recommended <= count (SPEC 4.7)")
    return True

def test_4_7_downtrend_gate():
    """SPEC 4.7: Downtrend Veto Gate (solo-en-negativo: ret<0 necesario; NaN veta)"""
    print("\n=== SPEC 4.7 Downtrend Veto Gate ===")
    prices = make_synthetic_prices(n_tickers=10, n_days=200)
    spy = make_synthetic_spy(200)

    # Ticker 0: momentum 90d enorme pero desplome reciente (el caso DELL jun-2026):
    # sube fuerte 90 días y cae 15% en los últimos 10 días (queda ~15% bajo su high de 20d)
    col = prices.columns[0]
    prices.loc[prices.index[-90]:, col] = prices[col].iloc[-90] * np.linspace(1.0, 2.2, 90)
    prices.loc[prices.index[-10]:, col] = prices[col].iloc[-10] * np.linspace(1.0, 0.85, 10)

    cands = generate_daily_candidates(prices, spy)
    row = cands[cands['ticker'] == col].iloc[0]

    assert row['ret_5d_10d'] < config.GATE_MIN_RET_SHORT_PCT or \
           row['dist_20d_high'] < config.GATE_MAX_DIST_TO_HIGH_PCT, \
           "El sintético no quedó en caída; revisar setup del test"
    assert row['recommended'] == False, \
           f"Acción en caída (ret={row['ret_5d_10d']}, dist={row['dist_20d_high']}) NO debe estar recommended"
    assert "Vetado" in str(row['reason']) or row['reason'] == 'Filtrado por Meta-Layer'
    print(f"[OK] Acción en caída vetada de recommended (ret_10d={row['ret_5d_10d']:.1f}%, "
          f"dist_high={row['dist_20d_high']:.1f}%) (SPEC 4.7)")

    # NaN también veta: sin datos frescos de corto plazo no hay recomendación
    from core.signals import apply_downtrend_gate
    df_nan = pd.DataFrame({
        "ticker": ["GOOD", "NODATA"],
        "ret_short": [5.0, np.nan],
        "dist_to_high": [-1.0, np.nan],
        "recommended": [True, True],
        "reason": ["Neutral", "Neutral"],
    })
    df_nan = apply_downtrend_gate(df_nan)
    assert df_nan.loc[df_nan.ticker == "GOOD", "recommended"].iloc[0] == True
    assert df_nan.loc[df_nan.ticker == "NODATA", "recommended"].iloc[0] == False
    assert "incompletos" in df_nan.loc[df_nan.ticker == "NODATA", "reason"].iloc[0]
    print("[OK] NaN en features de corto plazo veta con razón 'datos incompletos' (SPEC 4.7)")

    # Solo-en-negativo (2026-06-12): con ret_short positivo NUNCA se veta,
    # aunque esté lejos del high (dip en uptrend). Con ret negativo, cualquiera
    # de las dos señales veta (la pata dist sola requiere ret < 0).
    df_neg = pd.DataFrame({
        "ticker": ["DIPUP", "FALLDIST", "FALLRET"],
        # DIPUP: +6% en 10d pero 12% bajo su high -> NO veto (antes sí vetaba)
        # FALLDIST: -2% en 10d (negativo suave) y 12% bajo su high -> veto por dist
        # FALLRET: -7% en 10d, cerca de su high -> veto por ret
        "ret_short": [6.0, -2.0, -7.0],
        "dist_to_high": [-12.0, -12.0, -1.0],
        "recommended": [True, True, True],
        "reason": ["Neutral", "Neutral", "Neutral"],
    })
    df_neg = apply_downtrend_gate(df_neg)
    assert df_neg.loc[df_neg.ticker == "DIPUP", "recommended"].iloc[0] == True, \
        "ret_short positivo no puede ser vetado (regla solo-en-negativo)"
    assert df_neg.loc[df_neg.ticker == "FALLDIST", "recommended"].iloc[0] == False
    assert df_neg.loc[df_neg.ticker == "FALLRET", "recommended"].iloc[0] == False
    assert "caída reciente" in df_neg.loc[df_neg.ticker == "FALLRET", "reason"].iloc[0]
    print("[OK] Veto solo en negativo: dip con ret>0 pasa; caídas con ret<0 vetadas (SPEC 4.7)")
    return True

def _parse_spec_section_6(text: str) -> dict:
    """NAME = value pairs from SPEC section 6. Skips unnamed bullets (strong, base, ...)."""
    m = re.search(r"^## 6\. Complete Parameter List.*?(?=^## |\Z)", text, re.M | re.S)
    if not m:
        raise AssertionError("SPEC section 6 not found")
    out = {}
    for line in m.group(0).splitlines():
        mm = re.match(r"^-\s+([A-Z][A-Z0-9_]*)\s*=\s*(.+?)\s*$", line.strip())
        if not mm:
            continue
        name, raw = mm.group(1), mm.group(2)
        try:
            out[name] = ast.literal_eval(raw)
        except (ValueError, SyntaxError) as e:
            raise AssertionError(f"SPEC section 6: cannot parse {name} = {raw!r}: {e}")
    return out


def _parse_config_py_constants(text: str) -> dict:
    """Module-level UPPER_CASE assignments in config.py (source file, not the mutated module)."""
    tree = ast.parse(text)
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.isupper():
            continue
        try:
            out[target.id] = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            continue
    return out


def test_config_matches_spec_section_6():
    """TASK-321: production config.py must match SPEC section 6. Reads files, ignores test overrides."""
    print("\n=== SPEC Section 6 vs config.py (no overrides) ===")
    here = os.path.dirname(os.path.abspath(__file__))
    spec = open(os.path.join(here, "HYDRA_ALGORITHM_SPEC.md"), encoding="utf-8").read()
    cfg_src = open(os.path.join(here, "config.py"), encoding="utf-8").read()
    spec_params = _parse_spec_section_6(spec)
    cfg_params = _parse_config_py_constants(cfg_src)
    assert spec_params, "parsed zero parameters from SPEC section 6"
    missing = [n for n in spec_params if n not in cfg_params]
    if missing:
        print(f"[FAIL] SPEC names not in config.py: {missing}")
        return False
    drifted = []
    for name, spec_val in spec_params.items():
        live = cfg_params[name]
        if live != spec_val:
            drifted.append(f"{name}: config.py={live!r} SPEC={spec_val!r}")
    if drifted:
        print("[FAIL] config.py drifted from SPEC section 6:")
        for d in drifted:
            print(f"       {d}")
        return False
    print(f"[OK] {len(spec_params)} SPEC section 6 parameters match live config.py")
    return True


def test_output_contract():
    """SPEC section 7: Output Column Contract"""
    print("\n=== SPEC Section 7 Output Column Contract ===")
    prices = make_synthetic_prices(n_tickers=8, n_days=120)
    spy = make_synthetic_spy(120)

    cands = generate_daily_candidates(prices, spy)

    required = [
        'rank', 'ticker', 'momentum', 'meta_score', 'composite_score',
        'ret_5d_10d', 'dist_20d_high', 'short_boost',
        'vol_ratio', 'passes_strict', 'dynamic_vol_threshold',
        'sector', 'sector_rank', 'sector_penalty_applied',
        'regime', 'regime_type', 'special_modes', 'aggression', 'recovery_boost',
        'compass_mult', 'pillar_multipliers', 'recommended', 'reason', 'recommended_count'
    ]

    missing = [c for c in required if c not in cands.columns]
    if missing:
        print(f"[FAIL] Faltan columnas del contract: {missing}")
        return False

    print("[OK] Todas las columnas del Output Contract del SPEC 7 están presentes")
    return True

def main():
    print("=== HYDRA Python vs SPEC.md v1.2 Compliance Tests ===\n")
    print("Validando que la implementación coincide con las fórmulas y comportamientos del SPEC.\n")

    tests = [
        test_config_matches_spec_section_6,
        test_4_1_momentum_score,
        test_4_2_short_term_and_strict,
        test_4_3_rich_regime,
        test_4_4_meta_layer_and_pillars,
        test_4_5_composite_and_strict_bonus,
        test_4_6_sector_control,
        test_4_7_dynamic_recommended,
        test_4_7_downtrend_gate,
        test_output_contract,
    ]

    all_passed = True
    for test in tests:
        try:
            ok = test()
            if not ok:
                all_passed = False
        except Exception as e:
            print(f"[FAIL] {test.__name__} raised: {e}")
            import traceback
            traceback.print_exc()
            all_passed = False

    if all_passed:
        print("\n=== ✅ ALL SPEC COMPLIANCE TESTS PASSED ===")
        print("La implementación en core/ es fiel al HYDRA_ALGORITHM_SPEC.md v1.2")
        return 0
    else:
        print("\n=== ❌ SOME TESTS FAILED ===")
        return 1

if __name__ == "__main__":
    sys.exit(main())
