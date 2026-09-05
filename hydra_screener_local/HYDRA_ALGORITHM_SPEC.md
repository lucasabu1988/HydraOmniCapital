# HYDRA Scoring Algorithm - Language Agnostic Specification

**Version**: 1.2 (Expanded & Formal)  
**Date**: June 2026  
**Source of Truth**: Current production implementation in `hydra_screener_local/core/`

**Scope**: This document defines the **scoring and ranking logic** in a language-independent way.  
Final selection/portfolio construction rules are intentionally left as "implementation-specific".

---

## 1. Overview & Design Principles

HYDRA is a **momentum + regime-aware** equity selection system with the following pillars:

- Risk-adjusted momentum as the primary driver.
- Short-term confirmation (acceleration + volume surge) via the "Strict Filter".
- Dynamic regime detection that changes factor biases and aggression.
- "Special Modes" that qualitatively alter behavior in different market regimes.
- Pillar Multipliers that tilt the scoring toward different styles (trend vs mean-reversion vs catalyst).
- Sector concentration capped when the recommended list is picked.
- Dynamic number of recommendations based on overall conviction.

The system is explicitly designed for **5-day trading cycles**.

---

## 2. Inputs

- Daily adjusted close prices for the target universe (minimum ~200 trading days recommended).
- Daily volume (highly recommended for Strict Filter).
- SPY (or broad market proxy) price series for regime calculation.
- Optional: full universe price matrix for breadth calculation.
- Configuration parameters (listed in section 6).

---

## 3. Full Pipeline (Formal Pseudocode)

```pseudocode
function generate_daily_candidates(prices, spy, volumes=None):

    # 1. Core Momentum
    momentum = compute_momentum_score(prices)          # risk-adjusted, 90d / 63d vol

    # 2. Rich Regime (once per day)
    regime = compute_rich_regime_scores(spy, prices)   # returns overall + subscores
    regime_score = regime.overall

    # 3. Initial DataFrame
    df = DataFrame with ticker + momentum
    df = rename('momentum_score' -> 'momentum')

    # 4. Meta-Layer
    meta = LightweightMetaLayer.compute_adjustment(
        regime_score = regime_score,
        recent_drawdown = calculate_recent_dd(spy),
        spy_20d_return = ...,
        spy_60d_return = ...,
        volatility_level = normalized_vol(spy)
    )

    df = apply_meta_to_candidates(df, meta)            # applies pillar multipliers + aggression

    # 5. Short-term Features + Strict Filter
    short = compute_short_term_features(prices, volumes)
    df = merge(short)

    dynamic_vol_th = max(1.0, VOL_SURGE_THRESHOLD + GEOPOLITICAL_RISK_LEVEL * GEO_VOL_THRESHOLD_ADJUST)

    df['passes_strict'] = (df.ret_short > 15) & (df.dist_to_high >= -2) & (df.vol_ratio > dynamic_vol_th)

    # 6. Short-term Boost
    short_boost = normalized_function(df.ret_short, df.dist_to_high)
    df['composite_score'] = (df.meta_score * (1 + short_boost * SHORT_TERM_BOOST)).round(4)

    # 7. Strict Bonus
    if passes_strict:
        df.composite_score *= (1 + 0.18)

    # 8. Re-rank
    df = df.sort_values('composite_score', ascending=False).reset_index(drop=True)
    df['rank'] = 1 to N

    # 9. Dynamic Recommendation Count (BEFORE sector control: the cap applies to the
    #    list being picked, not to the scored universe)
    compass_mult = meta.pillar_multipliers['COMPASS']
    dynamic_count = clamp( round(14 * meta.overall_aggression * compass_mult), 6, 28 )

    # 10. Sector Concentration Control (hard cap at selection; scores untouched)
    df = apply_sector_concentration_control(df, dynamic_count, MAX_PER_SECTOR, sector_map)

    df['recommended'] = df.sector_selected & (regime_score >= 0.35 * 0.85)
    df['reason'] = if recommended            then meta.rationale
                   elif sector_penalty_applied then "Filtrado: límite por sector"
                   else                           "Filtrado por Meta-Layer"

    # 11. Downtrend Veto Gate (SPEC 4.7) - quita el flag a acciones en caída reciente
    df = apply_downtrend_gate(df)

    return df with rich columns
```

---

## 4. Detailed Component Specifications

### 4.1 Momentum Score

```pseudocode
returns = prices.pct_change()
mom = prices.pct_change(90)
vol = returns.rolling(63).std() * sqrt(252)
score = mom / vol.replace(0, NaN)
return score.iloc[-1]
```

**Parameters**:
- `MOMENTUM_LOOKBACK = 90`
- Volatility window = 63 (hardcoded in current implementation)

> **Decisiones cerradas (2026-09-06, delegadas por Lucas a Claude; TASK-319).**
>
> **Sin skip, a propósito.** El motor legacy v8.4 documentaba "90d lookback, 5d skip", pero su
> fórmula real era `(c[t-5]/c[t-90] − 1) − (c[t]/c[t-5] − 1)`: un momentum a medio plazo que
> además **resta** el retorno de los últimos 5 días — una apuesta de reversión de corto plazo,
> lo contrario del strict filter y del short-term boost de este screener, que premian la
> aceleración reciente. Medido con el pipeline actual (cap sectorial duro, gate, lag 1 día):
>
> ```
>                         in-sample 2020-26 (283 ciclos)     OOS PIT 2004-26 (1088 ciclos)
> sin skip (producción)   40.9 bp  Sharpe 1.16  maxDD -18.3%   18.6 bp  Sharpe 0.59  maxDD -44.2%
> skip-5 puro             -4.3 bp (p=0.34)  1.01   -20.3%      -0.7 bp (p=0.70)  0.57   -43.3%
> fórmula legacy v8.4     -5.2 bp (p=0.38)  0.97   -23.3%      -0.7 bp (p=0.77)  0.56   -45.0%
> ```
>
> Ninguna variante gana en ninguna muestra ni en ninguna era (2004-12 / 2013-19 / 2020-26);
> las dos son peores en Sharpe en ambos paneles. `MOMENTUM_SKIP` se eliminó de `config.py`.
>
> **Vol-scaling: k = 1 se queda** (`ret90 / vol63`). k=0 parecía +26.9 bp en 2020-26 pero era
> beta 1.51 vs 0.95; igualando volatilidad el residuo fue +14 bp con IC95% [−4.4, +33.5]. Fuera
> de muestra (TASK-324/325, 1088 ciclos) k=0 pierde: 20.6 vs 20.9 bp, Sharpe 0.53 vs 0.66,
> maxDD −41.3% vs −35.3%. Cerrado en las dos direcciones.

### 4.2 Short-Term Features & Strict Filter

```pseudocode
ret_short   = (price[-1] / price[-11] - 1) * 100     # SHORT_TERM_LOOKBACK=10
recent_high = max(price[-20:])                       # PROXIMITY_HIGH_DAYS=20
dist_high   = (price[-1] / recent_high - 1) * 100

if volume:
    vol_ratio = mean(volume[-5:]) / mean(volume[-20:])

dynamic_th = max(1.0, 1.50 + GEOPOLITICAL_RISK_LEVEL * 0.6)

passes_strict = (ret_short > 15) and (dist_high >= -2) and (vol_ratio > dynamic_th)
```

**Strict bonus**: +18% (0.18) on composite_score.

**Parameters** (exact from config):
- SHORT_TERM_LOOKBACK = 10
- PROXIMITY_HIGH_DAYS = 20
- MAX_DIST_TO_HIGH_PCT = 3.0 (used only in boost normalization)
- SHORT_TERM_BOOST = 0.35
- VOL_SURGE_THRESHOLD = 1.50
- GEO_VOL_THRESHOLD_ADJUST = 0.6
- MIN_VOL_THRESHOLD = 1.0

### 4.3 Rich Regime Calculation (from SPY)

```pseudocode
# 1. Trend
sma200 = sma(spy, 200)
trend = 1.0 if current > sma200 else 0.0
ret20 = (current / spy[20] - 1)
trend_strength = (trend * 0.6) + (clamp(ret20 + 0.04, -0.1, 0.15) / 0.15 * 0.4)

# 2. Volatility
vol20 = std(pct_change(spy), 20) * sqrt(252)
vol200 = std(pct_change(spy), 200) * sqrt(252)
vol_ratio = vol20 / max(vol200, 0.01)
vol_score = clamp(1 - (vol_ratio - 0.8)/1.2 , 0, 1)

# 3. Momentum
ret60 = (current / spy[60] - 1)
mom_score = clamp( (ret20*0.6 + ret60*0.4 + 0.05) / 0.20 , 0, 1)

# 4. Drawdown Velocity
max60 = highest(spy, 60)
curr_dd = max(0, (max60 - current) / max60)
dd20 = max(0, (max60 - spy[20]) / max60)
velocity = max(0, curr_dd - dd20) / 20
vel_score = 1 - clamp(velocity * 40, 0, 1)

# 5. Breadth (optional)
if full_universe_prices and n_tickers > 30:
    pct_positive  = share of tickers with a positive 1-day return
    above_sma50   = share of tickers above their own SMA50
    above_sma200  = share of tickers above their own SMA200
    breadth = clamp(0.3*pct_positive + 0.3*above_sma50 + 0.4*above_sma200, 0, 1)
else:
    breadth = 0.5

overall = 0.30*trend + 0.25*mom + 0.20*vol + 0.15*vel + 0.10*breadth
regime_score = round(clamp(overall, 0, 1), 3)
```

> **Nota (2026-09-05).** Hasta esta fecha el spec documentaba `0.4*sma50 + 0.6*sma200`,
> que nunca fue lo que hacía `core/regime.py`. Se corrigió el spec (el código es la fuente
> de verdad, sección de cabecera) sin tocar el scoring. El término `pct_positive` es de un
> solo día, así que inyecta ruido diario en el régimen: es un candidato razonable a revisar,
> pero cambiarlo SÍ es cambio de scoring y necesita aprobación explícita.

**Regime Type thresholds** (exact):
- STRONG   ≥ 0.62
- MODERATE ≥ 0.50
- CAUTIOUS ≥ 0.38
- WEAK     <  0.38

> **Nota (2026-09-06, auditoría R1).** El régimen — y con él el gate y `dynamic_count` — se
> calcula sobre **SPY**, mientras el universo de producción (`"all"`) es ~2/3 mid/small caps.
> 2020-2026: SPY sobre su SMA200 con IWM por debajo el 12.5% de los días (racha máxima 54
> sesiones); el retorno 5d de IWM en esos días promedió −15.8 bp frente a +31.6 bp cuando ambos
> coincidían. Cambiar el índice del régimen es cambio de scoring y no puede medirse hasta tener
> un panel point-in-time del universo real (el OOS actual es solo S&P 500). Mientras, el
> screener calcula el mismo régimen rico sobre `SECONDARY_REGIME_SYMBOL` (IWM), imprime el
> desacuerdo y lo persiste en `history` (`regime_secondary`). Observabilidad, no scoring.

### 4.4 Meta-Layer (LightweightMetaLayer)

> **Qué hace realmente la Meta-Layer (documentado 2026-09-05).**
>
> `meta_score = momentum × overall_aggression × pillar_factor`. En un día dado,
> `overall_aggression` y `pillar_factor` son **el mismo escalar positivo para todos los
> tickers**. Un escalar positivo común no puede alterar un orden, así que
> **la Meta-Layer NO cambia el ranking transversal**: ordenar por `composite_score` es
> idéntico a ordenar sin ella. Verificado: Spearman = 1.000000 entre el `meta_score` de un
> régimen STRONG y el de un WEAK_CRISIS sobre el mismo universo.
>
> La Meta-Layer influye exactamente en dos salidas:
> 1. `dynamic_count` (§4.6), vía `overall_aggression` y `pillar_multipliers["COMPASS"]`.
> 2. El flag de régimen `regime_score >= MIN_REGIME_SCORE * 0.85`.
>
> Corolario: los multiplicadores `Rattlesnake`, `Catalyst` y `EFA` **no participan en el
> scoring por ningún camino de código**. `bias_rattlesnake` entra en `pillar_factor`, que
> es global. Son observabilidad del régimen, no un tilt de estilo.
>
> Esto es una descripción, no un defecto: es una forma legítima de gestionar riesgo por
> tamaño de cartera. Se documenta porque el spec anterior sugería un tilt de estilo que no
> existe. Se probó construir ese tilt real (que el régimen cambie el *peso* de las features
> por ticker en vez de una escala global) y **no mejora**: −0.9 bp/ciclo (p=0.593) para un
> tilt suave y −2.9 bp (p=0.099) añadiendo sesgo mean-reversion en régimen débil, sobre
> 283 ciclos. Ver `.comms/claude-algo-deep-dive-2026-09-05.md` §4.4 y
> `experiments/backtest_variant_sweep.py`.

**Exact base biases by regime_type** (from code):

| Regime   | COMPASS | Rattlesnake | Catalyst | EFA   | Base Aggression |
|----------|---------|-------------|----------|-------|-----------------|
| STRONG   | 1.18    | 0.82        | 0.75     | 0.75  | 1.10            |
| MODERATE | 1.08    | 0.95        | 0.90     | 0.92  | 1.04            |
| CAUTIOUS | 0.85    | 1.12        | 1.05     | 0.98  | 0.93            |
| WEAK     | 0.70    | 1.20        | 0.95     | 0.90  | 0.82            |

**Special Modes triggers & effects** (exact):

- **CRISIS_ACUTE**: `recent_dd >= 0.12 or (regime < 0.25 and vol > 0.70)`
  - aggression *= 0.82
  - COMPASS *= 0.75

- **POST_CRISIS_RECOVERY**: `recent_dd >= 0.06 and spy20 > 0.025 and spy60 > -0.08 and regime > 0.35`
  - recovery_boost = min(1 + (dd-0.06)*1.5, 1.12)
  - COMPASS *= 1.08

- **STRONG_BROAD_MOMENTUM**: `regime >= 0.68 and vol < 0.55 and dd < 0.06`
  - COMPASS *= 1.22
  - Catalyst *= 0.65
  - EFA *= 0.65

- **ELEVATED_VOL_DEFENSIVE**: `vol_level > 0.68`
  - Rattlesnake *= 1.15
  - COMPASS *= 0.92

**Final multipliers**: clamped to [0.60, 1.45] after all adjustments.

### 4.5 Sector Concentration Control

A **hard cap applied while picking the recommended list**. Scores are never modified:
scoring stays separate from portfolio construction (see section 1).

```pseudocode
# sector_map is resolved upstream (screener.py), never inside scoring
df['sector'] = sector_map[ticker]  or  SECTOR_BUCKETS[ticker]  or  "Other"
df['sector_rank'] = rank_within_sector(df, 'composite_score')   # informative only

picked = []; counts = {}
for each row in df ordered by composite_score desc:
    if len(picked) >= dynamic_count: break
    if row.sector != "Other" and counts[row.sector] >= MAX_PER_SECTOR:
        mark sector_penalty_applied = True      # displaced by the cap
        continue
    picked.append(row); counts[row.sector] += 1

df['sector_selected'] = index in picked
```

The cap holds by construction, and still holds after the Downtrend Veto Gate (4.7),
since vetoing names can only lower a sector's count.

`"Other"` is **exempt**: it means "sector unknown", not a sector, and you cannot be
over-concentrated in the unknown.

**Parameters**:
- `ENABLE_SECTOR_CONTROL = True`
- `MAX_PER_SECTOR = 5` (GICS sectors)
- `SECTOR_FETCH_BUDGET_SECONDS = 120`

> **Nota (2026-09-05, TASK-320).** Hasta esta fecha era una penalidad blanda del 15% al
> `composite_score`, aplicada sobre el universo entero. Tenía dos defectos: penalizaba al
> 87% de los nombres por no estar en un mapa hecho a mano de 80 tickers, y por ser blanda
> no vinculaba nunca — el 100% de los ciclos simulados terminaba por encima del límite,
> con hasta 20 nombres de un mismo sector. `MAX_PER_SECTOR` pasa de 8 a 5 porque GICS es
> más grueso que aquellos buckets (Semis, Software/Cyber y Networking son todos
> "Technology"), así que 5 bajo GICS restringe la concentración tech más que el 3 que
> documenta `CLAUDE.md` para el motor legacy v8.4. Cambio de scoring aprobado por Lucas.

### 4.6 Final Recommended Logic (Current Implementation)

```pseudocode
compass_mult = pillar_multipliers["COMPASS"]
overall_aggression = meta.overall_aggression

dynamic_count = clamp( round(14 * overall_aggression * compass_mult) , 6, 28 )

recommended = sector_selected            # top dynamic_count respecting MAX_PER_SECTOR (4.5)
           AND (regime_score >= 0.35 * 0.85)
```

### 4.7 Downtrend Veto Gate (Jun 2026)

**Justificación**: el momentum de 90 días tiene tanta inercia que una acción puede
caer fuerte en los últimos días y seguir rankeando arriba. Filosofía: ranking
relativo (cross-sectional) para elegir, filtro absoluto (time-series) para vetar —
igual que Catalyst exige precio > SMA200 por activo.

Se aplica DESPUÉS del flag `recommended` de 4.6. No altera scores ni ranks;
solo puede quitar el flag (el conteo efectivo puede quedar < dynamic_count).

**Regla "solo en negativo" (2026-06-12)**: `ret_short < 0` es condición necesaria del
veto. Una acción con retorno reciente positivo nunca se veta, aunque esté >8% bajo su
máximo de 20d — eso es un dip dentro de un uptrend, no una caída. Motivación empírica:
en el selloff de jun-2026 la regla OR pura vetaba los nombres que rebotaban (seguían
positivos a 10d pese al crash) y costaba retorno cada día del rebote
(`experiments/backtest_gate_variants.py`).

```pseudocode
in_downtrend = (ret_short < 0)                               # condición necesaria
           AND (   (dist_to_high < GATE_MAX_DIST_TO_HIGH_PCT)
                OR (ret_short  < GATE_MIN_RET_SHORT_PCT) )   # OR sobre las señales
missing_data = isna(dist_to_high) OR isna(ret_short)
# NaN TAMBIÉN veta: en un sistema con capital real, un dato ausente no es luz verde.
# Con el universo ampliado (~3000 tickers) los huecos de descarga son más frecuentes.

if recommended AND in_downtrend:
    recommended = False
    reason = "Vetado: caída reciente (downtrend gate, SPEC 4.7)"
elif recommended AND missing_data:
    recommended = False
    reason = "Vetado: datos de corto plazo incompletos (gate, SPEC 4.7)"
```

**Parameters**:
- `ENABLE_DOWNTREND_GATE = True`
- `GATE_MAX_DIST_TO_HIGH_PCT = -8.0` (veto si está más de 8% bajo su máximo de 20d)
- `GATE_MIN_RET_SHORT_PCT = -5.0` (veto si el retorno de 10d es peor que -5%)

---

## 5. Edge Cases & Robustness Rules

- **Insufficient history**: Return neutral regime (0.5) and skip ticker if < required bars for any feature.
- **NaN / Inf handling**: Replace division by zero with NaN, then drop or fill conservatively in momentum and features.
- **Zombie / delisted tickers**: Hard blacklist in `DELISTED_OR_BAD_TICKERS` + post-filter `remove_zombie_tickers` (flat price detection).
- **Single-ticker or very small universe**: Breadth score falls back to 0.5.
- **Volume missing**: `vol_ratio` treated as 0 (fails strict filter). The Pine mirror follows
  the same rule since 2026-09-06 (it used to pass strict when volume was `na`).
- **Liquidity (selection rule, not scoring — see §1)**: names must clear both a 20-day mean
  share volume (`FILTERS["min_avg_volume"]`) and a 20-day mean dollar volume
  (`FILTERS["min_dollar_volume"]`, close × volume). A name with no volume data cannot prove
  its liquidity and is excluded. Added 2026-09-06: shares alone let $500k/day names into a
  weekly-rotation list on the Russell-heavy production universe.
- **Sector not mapped**: Falls into "Other" bucket.

---

## 6. Complete Parameter List (Current Production)

From `config.py`:

**Momentum & Short-term**
- MOMENTUM_LOOKBACK = 90
- SHORT_TERM_LOOKBACK = 10
- PROXIMITY_HIGH_DAYS = 20
- MAX_DIST_TO_HIGH_PCT = 3.0
- SHORT_TERM_BOOST = 0.35

**Volume / Strict**
- VOL_SURGE_THRESHOLD = 1.50
- GEO_VOL_THRESHOLD_ADJUST = 0.6
- MIN_VOL_THRESHOLD = 1.0

**Regime**
- REGIME_SMA = 200
- MIN_REGIME_SCORE = 0.35

**Meta-Layer thresholds**
- strong = 0.62
- moderate/cautious boundary = 0.50 / 0.38

**Sector**
- MAX_PER_SECTOR = 5
- SECTOR_FETCH_BUDGET_SECONDS = 120

**Downtrend Veto Gate (SPEC 4.7)**
- ENABLE_DOWNTREND_GATE = True
- GATE_MAX_DIST_TO_HIGH_PCT = -8.0
- GATE_MIN_RET_SHORT_PCT = -5.0

**Dynamic Recommendations**
- base = 14
- min = 6, max = 28

---

## 7. Output Column Contract (Rich)

The final ranked DataFrame must include (standardized names after column renaming):

rank, ticker, momentum, meta_score, composite_score,  
ret_5d_10d, dist_20d_high, short_boost,  
vol_ratio, passes_strict, dynamic_vol_threshold, vol_ratio_nan_share,  
sector, sector_rank, sector_penalty_applied,  
regime, regime_type, special_modes, aggression, recovery_boost,  
compass_mult, pillar_multipliers, recommended, reason, recommended_count

`vol_ratio_nan_share` is a run-level scalar (same value on every row): share of scored
tickers whose `vol_ratio` is missing. The screener watchdog reads this column; if it is
dropped from the contract the warning cannot fire.

### 7.1 Persistence and export contract (audit 2026-09-06, findings A and B)

- **`recommended` is authoritative and never substituted.** Zero recommended is a valid
  result (regime gate or veto closed the cycle) and must stay zero in `history/`, in
  `pine/hydra_last_summary.json`, in `pine/watchlist.txt` and in the cycle log. No consumer
  may fall back to the top N of the ranking.
- **`history/<date>.json` keeps every recommended row** plus the top-20 of the ranking as
  context (`screener.history_records`). Recommendations beyond rank 20 exist (sector cap,
  veto) and are persisted.
- **`hydra_last_summary.json`: `recommended_tickers` and `recommended_count` are the full
  list** (contract 1.2 unchanged). `top_details` carries the full list unless the producer
  declares `display_limit: N`, in which case only `top_details` is capped. Display caps are
  explicit: `display_limit` in the JSON, `i_max_watchlist` in Pine (table rows only).
- **Watch list ≠ recommendations ≠ executed positions.** `watchlist.txt` = the recommended
  tickers (what the user pastes); the Top5 cycle log = the first five recommended, or nothing.
- `validate_pine_contract.py` enforces: keys present, `recommended_count == len(list)`,
  `top_details` tickers == list unless `display_limit`. An empty list passes; a missing key fails.

---

## 8. Implementation Notes

**Pine Script**:
- Heavy lifting (universe scan + initial ranking) must stay in Python.
- Pine focuses on accurate per-symbol scoring + nice table for a user watchlist.
- Sector control can be approximated or omitted in Pine due to complexity.

**Python**:
- The code in `core/signals.py`, `core/meta_layer.py`, `core/regime.py`, `core/filters.py` is the reference implementation of this spec.

---

**This document (v1.2) is now the authoritative language-agnostic specification of the HYDRA scoring logic.**

---

**Tarea completada**: SPEC.md ha sido significativamente expandido con:
- Pseudocódigo formal del pipeline completo
- Lógica exacta de Meta-Layer con todos los triggers y multiplicadores
- Cálculo completo del régimen con pesos
- Edge cases
- Lista completa de parámetros con valores actuales
- Output contract detallado

---

### Próximas 4 opciones (elegí una o combiná):

1. **Mejorar el Pine Script ahora mismo**  
   (Hacer la tabla más completa, agregar más visualizaciones, mejorar detección de Special Modes y Pillars, manejo de múltiples símbolos en watchlist, etc.)

2. **Alinear el Python actual al spec**  
   (Revisar `core/signals.py`, `meta_layer.py`, etc. para que sean 100% fieles a esta especificación formal, limpiar cualquier diferencia histórica.)

3. **Definir la capa de integración híbrida**  
   (Cómo el Python le "sugiere" los candidatos diarios al usuario para que los agregue al watchlist de TradingView: webhook + alert, formato de mensaje, archivo, etc.)

4. **Otra cosa**  
   (Por ejemplo: crear tests automáticos contra el spec, generar documentación visual de los componentes, empezar a implementar una versión "lite" del algoritmo en otro lenguaje, etc.)

---

¿Qué querés hacer ahora? (podés decir el número o describir)