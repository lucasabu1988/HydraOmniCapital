<p align="center">
  <img src="static/img/omnicapital_logo.png" alt="OmniCapital Logo" width="180">
</p>

# OmniCapital — HYDRA
## Manifiesto del Sistema Multi-Estrategia

**COMPASS momentum + Rattlesnake mean-reversion + Catalyst trend + EFA international + Cash Recycling**

Versión: HYDRA v8.4 (COMPASS v8.4)
Fecha: 8 de Abril de 2026
Estado: ALGORITMO LOCKED — 64 experimentos, paper trading en vivo desde 16-Mar-2026

---

## 1. FILOSOFÍA

HYDRA nace de tres lecciones dolorosas que cuestan entender en carne propia:

1. **El edge en una sola estrategia es frágil.** COMPASS standalone (16% CAGR pre-corrección) cae a 8.75% al eliminar el survivorship bias. Sin diversificación, la aleatoriedad domina.
2. **La complejidad es enemiga del alpha concentrado.** 5 capas de ML sobre COMPASS perdieron −8.08% CAGR. Cada layer de inteligencia diluyó el signal.
3. **Las correlaciones colapsan a 1.0 en crisis.** El long-only concentrado tiene un techo de protección que ningún stop puede romper.

HYDRA responde con una idea simple: **cuatro estrategias complementarias compartiendo capital, cada una capturando un edge distinto del mercado, sin leverage, sin ML, sin overfitting paramétrico.** La diversificación absorbe el survivorship bias (HYDRA solo pierde +0.50% CAGR vs +5.24% que perdería COMPASS standalone). El ring-fencing del 15% Catalyst protege parte del capital cuando las otras tres caen juntas. El cash recycling evita que el dinero idle de Rattlesnake quede sin trabajar.

**Principio rector**: cada componente debe tener décadas de evidencia académica, una razón clara de existir, y un experimento que prueba que su ausencia degrada el resultado.

---

## 2. RESULTADOS (Backtest 2000-2026, 26 años)

### HYDRA — corregido por survivorship bias (882 tickers PIT)

| Métrica | Valor | Comentario |
|---|---|---|
| **CAGR** | **14.45%** | Survivorship-corrected, 882 tickers point-in-time |
| **Sharpe** | **0.91** | Risk-adjusted return |
| **Sortino** | ~1.30 | Downside-adjusted |
| **Max Drawdown** | **−27.0%** | vs −66% que tenía COMPASS standalone corregido |
| **$100k → final** | **~$3.3M** | 33x en 26 años |
| **Survivorship bias** | **+0.50%** | Diversificación absorbe el sesgo (vs +5.24% en COMPASS solo) |

### Comparación con componentes individuales (corregidos)

| Estrategia | CAGR | Sharpe | MaxDD | Notas |
|---|---|---|---|---|
| **HYDRA (todo)** | **14.45%** | **0.91** | **−27.0%** | Diversificado, sin leverage |
| COMPASS standalone | 8.75% | 0.55 | −58% | Sin Rattlesnake/Catalyst/EFA |
| Rattlesnake standalone | 10.51% | 0.74 | −31% | Mean-reversion S&P 100 |
| Catalyst standalone | 11.95% | 0.58 | −33% | Trend cross-asset |
| EFA standalone | 7.46% | 0.40 | −25% | Pasivo international (overflow) |

**Conclusión empírica**: el conjunto rinde más que la suma de sus partes (CAGR), con menos riesgo (Sharpe) y mucho menor drawdown que cualquier componente individual. Esa es la firma de la diversificación real.

---

## 3. LAS CUATRO ESTRATEGIAS

### 3.1 COMPASS v8.4 — Cross-sectional risk-adjusted momentum (42.5%)

**Universo**: 40 large-caps S&P 500 (selección por volumen promedio en dólares, rotación anual).

**Score (formula verificada en `omnicapital_v84_compass.py:517-528`)**:
```
momentum_raw = (precio[t-5] / precio[t-90]) - 1
skip_5d      = (precio[t]   / precio[t-5])  - 1
raw_score    = momentum_raw - skip_5d
ann_vol      = std(retornos[t-63:t]) × sqrt(252)
SCORE        = raw_score / ann_vol              # risk-adjusted
```

**Por qué funciona**:
- `momentum_raw` captura la tendencia de 90 días excluyendo la última semana (Jegadeesh & Titman 1993).
- `skip_5d` resta el efecto de micro-reversión de corto plazo (Lo & MacKinlay 1990).
- Dividir por la volatilidad realizada de 63 días convierte el momentum en **información ratio**: penaliza acciones que solo suben porque son volátiles.

**Selección**: top N por score, donde N = `NUM_POSITIONS = 5` (risk-on) o 2 (risk-off). Sector limit: máximo 3 posiciones por sector. Bull override: si SPY > SMA200·1.03 y regime score > 0.40, se permite +1 posición extra.

**Sizing**: inverse-volatility weighted dentro del slot COMPASS. Acciones más estables (JNJ, PG) reciben más peso que las volátiles (TSLA, NVDA).

### 3.2 Rattlesnake v1.0 — Mean-reversion dip-buying (42.5%)

**Universo**: S&P 100 (large-caps líquidas).

**Señal**: RSI(14) < 25 sobre acciones que mantienen filtro de uptrend (no cae cuchillos). Posiciones se mantienen hasta que el RSI normaliza o se cumplen exits estructurales.

**Por qué funciona**: en large-caps líquidas, las caídas extremas (RSI<25) sin ruptura de tendencia tienden a revertir en pocos días. Es el complemento natural de COMPASS — mientras COMPASS compra ganadores en momentum positivo, Rattlesnake compra perdedores temporales en uptrend.

**Cap de cash recycling**: el cash idle de Rattlesnake fluye a COMPASS hasta un máximo del 75% de la porción C+R combinada. Cuando el mercado está calmo y Rattlesnake no encuentra dips, COMPASS recibe más capital sin tener que esperar.

### 3.3 Catalyst — Trend cross-asset (15%, ring-fenced)

**Activos**: `['TLT', 'ZROZ', 'GLD', 'DBC']` (verificado en `catalyst_signals.py:25`).

**Señal**: cada activo entra **solo cuando cotiza por encima de su propia SMA200**. Si todos pasan el filtro, el 15% del portfolio se reparte equitativamente entre los que califiquen. Si ninguno pasa, el budget de Catalyst se mantiene en cash (o pasa a EFA vía overflow).

**Sin oro permanente**: en EXP71 se probó una asignación fija del 5% en GLD. El experimento falló: el sistema sin oro permanente rindió +1.10% CAGR y +0.073 Sharpe vs el sistema con oro permanente. La conclusión es que **GLD pertenece al filtro de tendencia, no a una asignación estructural**. Verificación en código:
```python
CATALYST_TREND_ASSETS = ['TLT', 'ZROZ', 'GLD', 'DBC']
CATALYST_GOLD_SYMBOL  = None  # no permanent gold
CATALYST_GOLD_WEIGHT  = 0.0   # EXP71: +1.10% CAGR, +0.073 Sharpe
```

**Por qué funciona**: TLT/ZROZ proveen exposure a duration (rate trends), GLD a real assets / inflation, DBC a commodities. Cuando los cuatro están en uptrend simultáneo, suelen ser regímenes inflacionarios donde la diversificación cross-asset paga. El filtro SMA200 es el más simple y robusto (Faber 2007).

**Ring-fenced**: el 15% de Catalyst NUNCA participa del recycling. Es capital intocable para los otros pilares. Esto garantiza que aunque COMPASS y Rattlesnake colapsen juntos, Catalyst sigue ejecutando su trend filter sin verse drenado.

### 3.4 EFA — International equity (overflow pasivo)

**Activo único**: `EFA` (iShares MSCI EAFE — Europa, Australasia, Far East).

**Lógica**: el cash residual del sistema (idle de Rattlesnake POST-recycling, cuando ya alcanzó el cap del 75% a COMPASS, y el budget Catalyst no puede colocar) se invierte en EFA en bloques mínimos de $1,000. Es exposure pasiva internacional como **destino del overflow**, no una estrategia activa.

**Por qué funciona**: evita que el cash quede ganando solo el yield Aaa IG cuando hay capital deployable. EFA tiene baja correlación intra-día con COMPASS (que es US-only) y reduce la volatilidad agregada del portfolio sin tomar decisiones tácticas.

### 3.5 Cash Recycling — `HydraCapitalManager`

**Reglas (verificadas en `hydra_capital.py:22-26`)**:
```
BASE_COMPASS_ALLOC   = 0.425
BASE_RATTLE_ALLOC    = 0.425
BASE_CATALYST_ALLOC  = 0.15      # ring-fenced
MAX_COMPASS_ALLOC    = 0.75      # cap del recycling sobre la porción C+R
EFA_MIN_BUY          = $1000     # umbral mínimo para destinar overflow a EFA
```

**Flujo**:
1. Capital se distribuye al inicio: 42.5% COMPASS, 42.5% Rattlesnake, 15% Catalyst (ring-fenced).
2. Si Rattlesnake tiene cash sin desplegar, fluye a COMPASS hasta llegar al 75% de (C+R).
3. El cash recycled gana los retornos de COMPASS mientras está prestado.
4. Lo que queda idle después del recycling y no cabe en Catalyst, se destina a EFA en bloques de $1k+.
5. Cuando Rattlesnake encuentra dips, COMPASS le devuelve el capital prestado (settlement).

---

## 4. PARÁMETROS COMPLETOS (HYDRA v8.4)

### COMPASS v8.4 — `omnicapital_v84_compass.py`

```
SIGNAL
  momentum_lookback         = 90 días
  momentum_skip             = 5 días
  risk_adj_vol_window       = 63 días (3 meses)

CYCLE
  hold_days                 = 5 (días de trading por ciclo)
  hold_days_max             = 10 (cap absoluto con extensión)
  exit_renewal_min_profit   = +4% (renueva hold solo si gana)
  exit_renewal_pctl         = 85% (top 15% del momentum)

POSICIONES
  num_positions             = 5  (RISK_ON)
  num_positions_off         = 2  (RISK_OFF)
  sector_limit              = 3  (máx por sector)

BULL OVERRIDE
  threshold_pct_above_sma   = 1.03  (SPY > SMA200 × 1.03)
  min_regime_score          = 0.40
  effect                    = +1 posición extra

STOPS POR POSICIÓN (vol-scaled adaptive)
  position_stop_loss_base   = -8%  (escala -6% a -15% según vol)
  trailing_activation       = +5%  (vol-scaled)
  trailing_stop_pct         = -3%  (vol-scaled, desde el máximo)
  trailing_vol_baseline     = 25%  (annualized vol baseline para escalar)

DRAWDOWN TIERS (leverage scaling)
  dd_tier1                  = -10%  (start reducing exposure)
  dd_tier2                  = -20%  (medium DD)
  dd_tier3                  = -35%  (deep DD floor)

CRASH BRAKE
  trigger                   = 5d return -6% OR 10d return -10%
  effect                    = leverage colapsa a 15%

REGIMEN
  regime_sma_period         = 200 días (SPY)
  regime_confirm_days       = 3

LEVERAGE
  leverage_max              = 1.0   (NO LEVERAGE en producción)
  cash_yield                = Moody's Aaa IG Corporate (FRED variable, ~4.8% avg)
```

### Rattlesnake v1.0 — `rattlesnake_signals.py`
```
rsi_threshold               = 25
rsi_window                  = 14
universe                    = S&P 100
filter                      = uptrend (no falling knives)
```

### Catalyst — `catalyst_signals.py`
```
trend_assets                = ['TLT', 'ZROZ', 'GLD', 'DBC']
sma_period                  = 200
trend_weight                = 1.0  (100% del budget Catalyst en trend)
gold_weight                 = 0.0  (sin asignación permanente — EXP71)
gate                        = cada activo solo entra si Close > SMA200
```

### Cash Recycling — `hydra_capital.py`
```
base_compass_alloc          = 0.425
base_rattle_alloc           = 0.425
base_catalyst_alloc         = 0.15  (ring-fenced)
max_compass_alloc           = 0.75  (cap del recycling sobre C+R)
efa_min_buy                 = $1,000
```

---

## 5. EJECUCIÓN Y FRICCIÓN

### Modelo de ejecución

| Concepto | Valor |
|---|---|
| Señal calculada | 15:30 ET (Close[T-1]) |
| Ejecución | Same-day MOC at Close[T] |
| Slippage modelado | ~2 bps (MOC en large-caps líquidos) |
| Commission | $0.001 / acción (IBKR tier) |
| Margin rate | N/A (LEVERAGE_MAX = 1.0) |
| Cash yield | Moody's Aaa IG Corporate (FRED) |

**Pre-close execution**: signal a las 15:30 ET con `Close[T-1]`, ejecución same-day MOC a `Close[T]`. Esto recupera +0.79% CAGR y mejora MaxDD por 7.8 puntos vs el modelo Close[T+1] tradicional.

**Por qué no hay leverage**: el broker margin al 6% destruye -1.10% CAGR. Box Spread (SOFR+20bps) sería viable (+0.15%) pero requiere IBKR portfolio margin que activa solo a $500K+. Para el capital actual, **sin leverage es óptimo**.

**Tax drag (no modelado en backtest)**: ~209 trades/año en COMPASS = short-term capital gains. Operar en cuenta IRA/401(k) es crítico para mantener el alpha post-tax. En cuenta gravable, ~12-13% CAGR after-tax estimado.

---

## 6. FLUJO DIARIO DE OPERACIÓN

```
CADA DÍA DE TRADING:

  1. PRECIO Y VALORACIÓN (15:30 ET)
     - Fetch live prices vía Yahoo v8 / IBKR
     - Calcular portfolio_value = cash + Σ(shares × price)
     - Update peak_value si hay nuevo máximo
     - Calcular drawdown actual

  2. CASH RECYCLING (HydraCapitalManager)
     - Settle recycled amount (gana retorno COMPASS del día)
     - Recalcular hydra_account, rattle_account, catalyst_account
     - Determinar EFA overflow disponible

  3. RÉGIMEN DE MERCADO
     - SPY vs SMA200 con confirmación 3 días
     - Calcular regime_score (sigmoid)
     - Determinar si bull override aplica

  4. CRASH BRAKE
     - 5d return ≤ -6% OR 10d return ≤ -10% → leverage 15%
     - DD ≤ -35% → posiciones reducidas a 2

  5. CATALYST (15% ring-fenced)
     - Para cada activo en [TLT, ZROZ, GLD, DBC]:
       · Si Close > SMA200 → mantener / añadir
       · Si Close ≤ SMA200 → vender
     - Re-equilibrar pesos entre los que califiquen

  6. RATTLESNAKE
     - Calcular RSI(14) sobre S&P 100
     - Entries: RSI < 25 + filtro uptrend
     - Exits: RSI normalizado, hold expirado, o stop

  7. COMPASS (con cash recycled de Rattlesnake)
     a. Cerrar posiciones con hold ≥ 5 días (evaluar exit_renewal)
     b. Cerrar position stops (vol-scaled, -6% a -15%)
     c. Cerrar trailing stops activos
     d. Calcular SCORE risk-adjusted para cada elegible
     e. Filtrar por sector limit (max 3 por sector)
     f. Aplicar bull override si corresponde
     g. Abrir top N por score con sizing inverse-vol

  8. EFA OVERFLOW
     - Cash residual ≥ $1,000 → comprar EFA
     - No hay sell signal: solo se libera cuando hay demanda en otros pilares

  9. PERSISTIR
     - save_state() atómico en JSON
     - Log ML decisions (entry/exit/skip/signal)
     - Audit trail al broker
```

---

## 7. COMPORTAMIENTO HISTÓRICO

### Crisis Dot-com (2000-2002)
COMPASS entra en RISK_OFF, Catalyst (TLT) captura el rally de bonos (rates collapsing), Rattlesnake encuentra pocos dips porque casi todo cae. Net: pequeño DD vs el -49% del SPY.

### Bull market 2003-2007
COMPASS captura momentum sostenido. Rattlesnake aprovecha pullbacks pequeños para entrar en mid-trend. Catalyst rota entre TLT (rates falling) y DBC (commodity boom). Crecimiento sostenido sin stops mayores.

### Crisis financiera 2008-2009
RISK_OFF persistente todo 2008. Catalyst (TLT) captura el flight-to-quality. Rattlesnake bloqueado por crash brakes. EFA overflow drenado al recycling. Recovery gradual desde Jun 2009.

### Crash COVID Mar 2020
Crash brake activado. Posiciones reducidas. Catalyst (GLD + TLT) absorbe parte del flight-to-quality. Recovery ágil: vol targeting + bull override capturan el rally post-COVID. Mejor año de la historia del sistema.

### Bear 2022
COMPASS en RISK_OFF gran parte del año. Catalyst falla porque tanto bonos como acciones caen juntos (caso atípico). Rattlesnake encuentra menos dips de calidad. DD moderado vs SPY -25%.

### 2023-2026 (current)
Recovery completa. COMPASS captura el rally AI/Mag7. Rattlesnake aprovecha pullbacks. Catalyst rota entre activos según trend. Live paper trading desde 16-Mar-2026.

---

## 8. EXPERIMENTOS Y LECCIONES (64 totales)

**Resumen**: 64 experimentos corridos sobre el motor. **El motor está LOCKED**. Cualquier modificación paramétrica degrada el resultado. Las únicas mejoras vienen del chassis (ejecución, costos, recycling, EFA overflow), no del motor.

### Experimentos clave

| # | Experimento | Resultado | Lección |
|---|---|---|---|
| Exp34 | IG Cash Yield (Moody's Aaa) | **APROBADO +1.15% CAGR** | Cash yield variable > T-bill fijo |
| Exp36 | Gold protection mode | FAILED | El cash es óptimo durante protection |
| Exp37 | v9 Genius (5 ML layers) | FAILED -8.08% CAGR | ML mata el momentum concentrado |
| Exp38 | Cash deploy (deploy buffer) | FAILED -0.21% CAGR | El cash es vol cushion, no idle |
| Exp39 | Conviction tilt + crowding | FAILED -1.18% CAGR | Inv-vol ya es óptimo |
| Exp40 | Survivorship bias quantification | INFORMATIONAL | +5.24% bias en COMPASS standalone |
| Exp61 | HYDRA con 882 PIT tickers | **APROBADO** | Solo +0.50% bias en HYDRA (diversificación absorbe) |
| **Exp71** | **Catalyst sin gold permanente** | **APROBADO +1.10% CAGR, +0.073 Sharpe** | **Gold pertenece al trend filter, no a allocación fija** |
| Exp64 | Geopolitical overlays (VIX, GPR) | REJECTED | Yield curve inversion crea drag inaceptable |
| EU/Asia | COMPASS sobre EU/Asia | FAILED -20% CAGR | Algoritmo es US-specific |

### Lecciones generales

1. **Algorithm inelasticity**: el motor está en un máximo local fuerte. Cualquier parámetro tocado degrada.
2. **Diversificación absorbe survivorship bias**: HYDRA pierde solo +0.50% al corregir, COMPASS standalone pierde +5.24%.
3. **ML overlays destruyen alpha**: 5 capas (MLP, HMM, graph, sector, Thompson) = -8.08% CAGR.
4. **Cash buffer es vol cushion, no capital idle**: deployearlo en picks de segundo orden diluye alpha.
5. **Geographic expansion FAILED**: COMPASS sobre EU/Asia es catastrófico, depende de US market microstructure.
6. **Crisis correlations → 1.0**: long-only concentrado tiene techo de protección que ningún stop puede romper.

---

## 9. ARQUITECTURA TÉCNICA

### Componentes principales

| Archivo | Rol |
|---|---|
| `compass_dashboard_cloud.py` | Flask app cloud (Render) — entrypoint deployado |
| `compass_dashboard.py` | Flask app local + engine runner |
| `omnicapital_live.py` | Core engine `COMPASSLive` — orquesta las 4 estrategias |
| `omnicapital_v84_compass.py` | Algoritmo COMPASS v8.4 (LOCKED) |
| `rattlesnake_signals.py` | Señales Rattlesnake (RSI dip-buying) |
| `catalyst_signals.py` | Señales Catalyst (trend SMA200 cross-asset) |
| `hydra_capital.py` | `HydraCapitalManager` — cash recycling + EFA overflow |
| `compass_ml_learning.py` | Sistema ML de aprendizaje (3 fases, fail-safe) |
| `omnicapital_broker.py` | `PaperBroker` + `IBKRBroker` (mock + live) |

### Stack
- Python 3.11 (cloud) / 3.14 (local Windows)
- Flask + gunicorn (cloud) — health check `/api/health`
- yfinance (primary), FRED (cash yield), Tiingo (opcional)
- IBKR API mock + live (paper trading port 7497)
- GitHub → Render auto-deploy via webhook

### Sistema ML (3 fases)
| Fase | Decisiones | Componentes |
|---|---|---|
| Phase 1 | < 100 | DecisionLogger — logea entries, exits, skips |
| Phase 2 | 100–500 | FeatureStore + OutcomeTracker |
| Phase 3 | > 500 | LearningEngine + InsightReporter |

Toda la capa ML está envuelta en `try/except` — **nunca puede crashear el live engine**.

---

## 10. REGLAS INQUEBRANTABLES

1. **NO modificar el motor sin backtest completo de 26 años**. Cada cambio debe correrse sobre el período 2000-2026 con 882 tickers PIT antes de aprobarse.

2. **NO agregar leverage**. `LEVERAGE_MAX = 1.0` es definitivo. Margin broker al 6% destruye -1.10% CAGR.

3. **NO añadir capas de ML sobre el motor**. EXP37 lo probó y costó -8.08% CAGR. La complejidad mata alpha concentrado.

4. **NO modificar la fórmula del score COMPASS**. `risk-adjusted momentum / 63d vol` está en máximo local fuerte.

5. **NO romper el ring-fence de Catalyst**. El 15% es intocable. Su función es protección estructural cuando los otros pilares colapsan juntos.

6. **NO añadir asignaciones permanentes a Catalyst**. EXP71 demostró que +5% gold permanente cuesta -1.10% CAGR. Todos los activos pasan por el filtro SMA200.

7. **NO operar sin cash recycling**. Es lo que conecta los pilares y evita capital idle.

8. **SIEMPRE respetar los stops**. Adaptive position stops, trailing stops, DD tiers, crash brake — sin excepciones.

9. **SIEMPRE persistir state atómicamente**. `tmp + os.replace()` para `compass_state_latest.json`. Es la fuente de verdad del live trading.

10. **Paper trading mínimo 3-6 meses antes de capital real**. Capturar al menos un ciclo earnings completo.

---

## 11. EVOLUCIÓN: DE COMPASS A HYDRA

| Versión | Fecha | Descripción | CAGR | Sharpe | MaxDD |
|---|---|---|---|---|---|
| v1-v5 | Feb 2026 | Iteraciones tempranas (intraday, fundamentales) | — | — | — |
| v6 | Feb 2026 | Random selection + 2x leverage + survivorship bias | 16.92%* | — | -59.4% |
| v6 corrected | Feb 2026 | Top-40 rotation (sin sesgo) | 5.40% | 0.22 | -59.4% |
| **v8 COMPASS** | Feb 2026 | Momentum + regime + vol target | 16.16% | 0.73 | -34.8% |
| v8.2 COMPASS | Feb 2026 | Cash yield Aaa + chassis upgrades | 17.42% | 0.98 | -31.2% |
| v8.4 COMPASS | Mar 2026 | Adaptive stops + bull override + sector limits | 18.61% | 1.05 | -29.5% |
| **HYDRA v1** | Mar 2026 | COMPASS v8.4 + Rattlesnake + Cash Recycling | 14.95% | 1.12 | -22.25% |
| **HYDRA v1.4** | Apr 2026 | + Catalyst (4to pilar) + EFA overflow | **15.62%** | **1.08** | **-21.7%** |
| **HYDRA corrected** | Apr 2026 | + Survivorship correction (882 PIT tickers) | **14.45%** | **0.91** | **-27.0%** |

*v6 con sesgo de supervivencia. Sin sesgo: 5.40%.

---

## 12. ESTADO ACTUAL Y ROADMAP

### Live paper trading

| Item | Valor |
|---|---|
| Inicio | 16 de Marzo de 2026 |
| Capital inicial | $100,000 |
| Días de trading | 18 (al 8 de Abril 2026) |
| Portfolio actual | ~$100,400 |
| Cycle activo | 5 (de un máximo de 5d antes de rotación) |
| Posiciones | 5 (GLD, EFA, DBC, JNJ, XOM) |

### Completado
- [x] HYDRA v8.4 LOCKED (64 experimentos)
- [x] 4 estrategias integradas + cash recycling
- [x] Backtest survivorship-corrected (882 PIT tickers)
- [x] Dashboard cloud (Render) + local (Flask)
- [x] IBKR mock mode (53 unit tests passing)
- [x] Sistema ML 3 fases (Phase 1 activo)
- [x] Pre-close execution (15:30 ET signal + same-day MOC)
- [x] Live paper trading desde 2026-03-16

### En progreso
- [ ] Live paper trading 3-6 meses (capturar earnings cycle completo)
- [ ] Sistema ML Phase 2 (~18 días para 500 decisiones)

### Pendiente
- [ ] Norgate Data — S&P 500 point-in-time membership
- [ ] IBKR live paper trading (`ibkr_mock: false` + TWS port 7497)
- [ ] Optimización fiscal — operar en IRA/401(k)
- [ ] Escalado $500K+ — IBKR portfolio margin + Box Spread financing

---

## 13. CONCLUSIÓN

HYDRA es la respuesta a tres preguntas dolorosas:

1. **¿Qué pasa cuando el survivorship bias revela que tu alpha era ficción?** → Diversificás. Cuatro estrategias complementarias absorben el sesgo: HYDRA pierde solo +0.50% CAGR al corregir, COMPASS standalone pierde +5.24%.

2. **¿Qué pasa cuando agregar inteligencia (ML) destruye el signal?** → Volvés a la simplicidad. Cada componente de HYDRA es académicamente fundamentado, sin caja negra, sin overfitting, sin parámetros ajustados sobre el dataset.

3. **¿Qué pasa cuando las correlaciones colapsan a 1.0 en crisis?** → Ring-fenceás capital. El 15% de Catalyst nunca participa del recycling: es protección estructural contra el peor caso del long-only concentrado.

El resultado es un sistema con 14.45% CAGR, 0.91 Sharpe y -27% MaxDD sobre 26 años, sin leverage, sin ML, sin promesas. **Ese es el techo honesto del trading sistemático cuantitativo retail con $100k de capital y datos públicos.** Cualquiera que prometa más, está mintiendo o midiendo mal.

---

*"COMPASS knows the difference between randomness and edge. HYDRA knows that edge alone is not enough."*
