# OMNICAPITAL HYDRA v8.4
## Manifiesto del Algoritmo

**Multi-Strategy Adaptive Momentum with Macro Overlays**

Fecha: 9 Marzo 2026
Version: 8.4
Status: Paper Trading (live desde 6 Marzo 2026)

---

## 1. FILOSOFIA

HYDRA nace de una evolucion disciplinada. El v6 original reportaba 16.92% CAGR, pero al eliminar el sesgo de supervivencia, la realidad era 5.40% con -59.4% de drawdown maximo. No habia signal. Era compra aleatoria con leverage. El "alpha" era una ilusion.

COMPASS (v8.0) reemplazo la aleatoriedad con un edge real basado en momentum cross-seccional. HYDRA (v8.4) lleva esa base un paso mas alla: integra multiples estrategias complementarias, overlays macroeconomicos, y gestion de riesgo adaptativa continua.

El nombre HYDRA refleja la arquitectura multi-cabeza del sistema:

1. **COMPASS** — Momentum cross-seccional (cabeza principal)
2. **Rattlesnake** — Mean-reversion en dips extremos (cabeza tactica)
3. **EFA** — Exposicion internacional pasiva (cabeza diversificadora)
4. **Cash Recycling** — Optimizacion de capital idle entre estrategias
5. **Macro Overlays** — Senales macroeconomicas que modulan exposicion

Cada componente es independiente pero sinergico. Las estrategias operan en diferentes regimenes de mercado, y el capital fluye dinamicamente entre ellas.

### Principios Rectores

- **Simplicidad con profundidad**: Cada componente usa pocos parametros, pero la combinacion genera complejidad emergente.
- **Base academica**: Cada decision de diseno esta respaldada por decadas de investigacion en finanzas cuantitativas.
- **Adaptabilidad continua**: No hay switches binarios. Regime score, drawdown leverage, y adaptive stops son todos funciones continuas.
- **Fail-safe by design**: Overlays son multiplicativos con floor en 0.25. Ningun componente puede crashear el sistema.

---

## 2. RESULTADOS (Backtest 2000-2026)

### HYDRA Composite (COMPASS + Rattlesnake + EFA + Cash Recycling)

| Metrica | v6 (aleatorio) | v8.0 COMPASS | **v8.4 HYDRA** | S&P 500 |
|---------|---------------|--------------|----------------|---------|
| **CAGR** | 5.40% | 16.16% | **14.92%** | ~10% |
| **Sharpe** | 0.22 | 0.73 | **1.12** | ~0.45 |
| **Sortino** | — | 1.02 | **1.54** | — |
| **Max Drawdown** | -59.4% | -34.8% | **-22.25%** | -55.2% |
| **Calmar** | — | 0.46 | **0.67** | ~0.18 |
| **Anos positivos** | — | 21/26 | **23/27** | — |
| **Mejor ano** | — | +128.1% | **+47.1%** (2003) | — |
| **Peor ano** | — | -32.7% | **-20.8%** (2022) | — |
| **$100k se convierte en** | ~$400k | $4.95M | **$3.77M** | ~$1.1M |

> **Nota critica sobre v8.0 vs v8.4**: El CAGR de v8.4 es menor que v8.0 porque v8.4 opera sin leverage (LEVERAGE_MAX=1.0) y con overlays que reducen exposicion en periodos de estres. A cambio, el max drawdown se reduce de -34.8% a -22.25% y el Sharpe casi se duplica (0.73 → 1.12). **HYDRA maximiza retorno ajustado por riesgo, no retorno absoluto.**

### COMPASS Standalone (sin HYDRA multi-strategy)

| Metrica | Valor |
|---------|-------|
| CAGR | 10.41% |
| Max Drawdown | -33.04% |
| Sharpe | 0.77 |
| Sortino | 1.07 |
| Calmar | 0.32 |

### Retornos Anuales HYDRA Composite

| Ano | Retorno | Ano | Retorno | Ano | Retorno |
|-----|---------|-----|---------|-----|---------|
| 2000 | +34.8% | 2009 | +29.6% | 2018 | +13.5% |
| 2001 | -6.5% | 2010 | +10.6% | 2019 | +21.6% |
| 2002 | -11.5% | 2011 | +4.5% | 2020 | +44.9% |
| 2003 | +47.1% | 2012 | +15.4% | 2021 | +37.9% |
| 2004 | +9.5% | 2013 | +20.8% | 2022 | -20.8% |
| 2005 | +20.8% | 2014 | +1.0% | 2023 | +24.2% |
| 2006 | +4.7% | 2015 | +11.0% | 2024 | +28.4% |
| 2007 | +27.5% | 2016 | +17.3% | 2025 | +10.4% |
| 2008 | -8.1% | 2017 | +20.8% | 2026* | +3.0% |

*2026 parcial (hasta Feb 20)

---

## 3. ARQUITECTURA MULTI-ESTRATEGIA

### 3.0 Vision General

```
                        HYDRA Capital Manager
                    ┌───────────┴───────────┐
                    │                       │
              Base: 50%                Base: 50%
                    │                       │
            ┌───────┴───────┐         ┌─────┴─────┐
            │   COMPASS     │         │ RATTLESNAKE│
            │  (Momentum)   │         │(Mean-Rev)  │
            │  5 posiciones │         │ 5 posiciones│
            └───────┬───────┘         └─────┬─────┘
                    │                       │
                    │    Cash Recycling      │
                    │◄──── idle cash ────────│
                    │     (cap 75%)          │
                    │                       │
                    │              Remaining idle
                    │                   │
                    │              ┌────┴────┐
                    │              │   EFA   │
                    │              │(Intl Eq)│
                    │              └─────────┘
                    │
            ┌───────┴───────────────────────┐
            │      MACRO OVERLAYS (v3)      │
            │  BSO · M2 · FOMC · FedEmerg   │
            │  CreditFilter · CashOptim     │
            │  capital_scalar ∈ [0.25, 1.0] │
            └───────────────────────────────┘
```

### 3.1 COMPASS — Momentum Cross-Seccional (Cabeza Principal)

#### Universo de Inversion

**Pool amplio**: ~113 acciones del S&P 500 distribuidas en 9 sectores (Technology, Financials, Healthcare, Consumer, Energy, Industrials, Utilities, Real Estate, Telecom).

**Rotacion anual**: Cada 1 de enero, las acciones se rankean por volumen promedio diario en dolares (Close × Volume) del ano anterior. Solo las **top 40** son elegibles. Esto evita sesgo de supervivencia: no se invierte en acciones que solo sabemos que son grandes "hoy".

**Filtro de antiguedad**: Minimo 63 dias de historia (3 meses) para ser elegible. Evita IPOs recientes.

**Quality filter** (v8.4): Volatilidad anualizada < 60% (63d lookback). Movimiento maximo en un dia < 50%. Elimina acciones con comportamiento erratico.

#### El Score COMPASS

La pieza central del algoritmo. Para cada accion elegible, diariamente:

```
momentum_90d = (Precio[t-5] / Precio[t-90]) - 1
reversal_5d  = (Precio[t] / Precio[t-5]) - 1

SCORE = momentum_90d - reversal_5d
```

Se seleccionan las acciones con **mayor score** (top N disponibles).

**Interpretacion de un score alto**:
- **momentum_90d alto**: Ganador de mediano plazo (3 meses, excluyendo la ultima semana).
- **reversal_5d bajo/negativo**: Pullback reciente — la accion "respiro" dentro de la tendencia.
- **Combinacion**: Ganador con pullback = oportunidad de compra en la tendencia.

**Base academica**:
- Jegadeesh & Titman (1993): Momentum cross-seccional funciona en horizontes de 3-12 meses.
- Lo & MacKinlay (1990): Retornos de corto plazo (1-5 dias) muestran reversion a la media.
- Novy-Marx (2012): El momentum intermedio (7-12 meses) es mas robusto que el reciente.
- El "skip" de los ultimos 5 dias elimina el efecto de micro-reversion que cancela el momentum — hallazgo robusto en la literatura (Asness, Moskowitz, Pedersen 2013).

#### Filtro de Regimen: Score Continuo (v8.4)

A diferencia de v8.0 (binario RISK_ON/RISK_OFF), v8.4 usa un **score continuo** [0.0, 1.0]:

**Funcion**: `compute_live_regime_score(spy_hist) → float`

**Componentes (ponderacion 60/40)**:

1. **Trend Score (60%)** — Promedio de 3 funciones sigmoide:
   - `sig_200`: Distancia a SMA(200), sigmoid k=15.0
   - `sig_cross`: Cruce SMA(50)/SMA(200), sigmoid k=30.0
   - `sig_mom`: Momentum 20 dias, sigmoid k=15.0

2. **Vol Score (40%)** — Percentil invertido:
   - Volatilidad realizada (10d) vs distribucion historica (252d rolling)
   - Alta vol = score bajo

**Mapeo a posiciones** (gradual, no binario):

| Regime Score | Max Posiciones | Interpretacion |
|-------------|----------------|----------------|
| >= 0.65 | 5 | Mercado fuerte |
| >= 0.50 | 4 | Mercado mixto |
| >= 0.35 | 3 | Mercado debil |
| < 0.35 | 2 | Bear market |

**Bull Override** (v8.4): Cuando SPY > SMA(200) × 1.03 AND regime_score > 0.40 → +1 posicion adicional (cap en max). Captura mercados claramente alcistas que el score continuo puede subestimar.

**Base academica**: El uso de funciones sigmoide para regime detection sigue el enfoque de Hamilton (1989) — regime switching models — pero con la ventaja de evitar clasificacion binaria. Ang & Bekaert (2002) demostraron que los modelos de regimen continuo superan a los discretos en gestion de portafolios.

#### Concentracion Sectorial (v8.4)

**MAX_PER_SECTOR = 3**: Ningun sector puede tener mas de 3 posiciones simultaneas. Fuerza diversificacion incluso cuando el momentum favorece un solo sector.

**Base academica**: Moskowitz & Grinblatt (1999) demostraron que parte del momentum individual es atribuible a momentum sectorial. Limitar concentracion reduce exposicion a reversiones sectoriales.

#### Position Sizing: Inverse Volatility

```
vol_20d(stock) = std(retornos_diarios, 20d) × sqrt(252)
peso_raw(stock) = 1 / vol_20d(stock)
peso(stock) = peso_raw / sum(todos_pesos_raw)
tamano_posicion = peso × capital_efectivo
```

- Acciones estables (JNJ, PG, KO) → mas capital
- Acciones volatiles (TSLA, NVDA, AMD) → menos capital
- **Limite**: Ninguna posicion > 40% del cash disponible

**Base academica**: Risk parity (Maillard, Roncalli, Teiletche 2010) demuestra que igualar contribucion de riesgo mejora Sharpe. Inverse vol es la implementacion mas simple de este principio.

#### Reglas de Salida

##### Adaptive Stops (v8.4 — vol-scaled, no binarios)

```
raw_stop = -2.5 × entry_daily_vol
adaptive_stop = clamp(raw_stop, floor=-0.06, ceiling=-0.15)
```

| Volatilidad diaria | Stop resultante | Tipo de accion |
|--------------------|-----------------|-|
| 1.0% | -6.0% (floor) | Blue chips (JNJ, PG) |
| 2.5% | -6.25% | Large caps estables |
| 3.5% | -8.75% | Growth moderado |
| 4.5% | -11.25% | High beta |
| 6.0%+ | -15.0% (ceiling) | Acciones muy volatiles |

**Base academica**: Los stops fijos penalizan acciones volatiles (se activan demasiado rapido) y dejan correr perdidas en acciones estables. Los stops adaptativos por volatilidad (Acar & Satchell, 2002) ajustan el umbral al comportamiento natural de cada accion.

##### Trailing Stop (vol-scaled)

- **Activacion**: Ganancia >= +5% desde entrada
- **Stop**: high_price × (1 - 0.03 × entry_vol/0.25)
- Escala con la volatilidad de entrada

##### Hold Time & Exit Renewal (v8.4)

| Mecanismo | Condicion | Proposito |
|-----------|-----------|-----------|
| **Hold minimo** | >= 5 dias | Capturar momentum de corto plazo |
| **Hold maximo** | 10 dias (hard cap) | Prevenir stale positions |
| **Renewal** | profit >= +4% AND momentum pctl >= 85th | Extender ganadores en tendencia |

**Renewal logic**: Si al cumplir 5 dias la posicion tiene +4% y su momentum esta en el percentil 85+, el hold se renueva (hasta el cap de 10 dias). Esto evita cerrar ganadores prematuramente.

---

### 3.2 RATTLESNAKE — Mean-Reversion Tactica (Cabeza 2)

Estrategia de dip-buying en el S&P 100 (OEX) que opera en el extremo opuesto a COMPASS: compra acciones en panico y vende en recuperacion.

#### Condiciones de Entrada (TODAS deben cumplirse)

1. **Caida >= 8% en 5 dias** — La accion sufrio un golpe significativo
2. **RSI(5) < 25** — Tecnicamante oversold
3. **Precio > SMA(200)** — Tendencia de largo plazo intacta (no atrapar cuchillos cayendo)
4. **Volumen promedio >= 500k shares** — Liquidez suficiente
5. **No held por COMPASS** — Evitar superposicion

#### Condiciones de Salida

| Mecanismo | Umbral | Tiempo tipico |
|-----------|--------|---------------|
| **Profit target** | +4% | 2-3 dias |
| **Stop loss** | -5% | Inmediato |
| **Time exit** | 8 dias | Fallback |

#### Dimensionamiento

- Tamano por posicion: 20% del account Rattlesnake
- Max posiciones: 5 (RISK_ON) / 2 (RISK_OFF)
- Filtro de regimen: SPY > SMA(200) AND VIX <= 35

#### Base Academica

- De Bondt & Thaler (1985): Overreaction hypothesis — acciones que caen excesivamente tienden a revertir.
- Jegadeesh (1990): Retornos de corto plazo muestran mean-reversion, especialmente en caidas extremas.
- Cooper (1999): La reversion funciona mejor en acciones con fundamentales intactos (proxy: precio > SMA200).

#### Sinergia con COMPASS

COMPASS compra ganadores. Rattlesnake compra perdedores temporales. En un mercado normal, COMPASS genera retornos. En ventas de panico (VIX spikes), Rattlesnake activa mientras COMPASS reduce exposicion. El capital fluye donde la oportunidad es mayor.

---

### 3.3 EFA — Exposicion Internacional (Cabeza 3)

**Instrumento**: EFA (iShares MSCI EAFE ETF) — mercados desarrollados ex-US

**Logica**:
- Cash idle en Rattlesnake (no reciclado a COMPASS) se invierte en EFA
- **Condicion de compra**: EFA > SMA(200) AND idle cash >= $1,000
- Posicion pasiva — no hay trading activo

**Proposito**: Diversificacion geografica. Cuando COMPASS y Rattlesnake no usan todo el capital, EFA genera exposicion a Europa y Asia-Pacifico sin correlation 1:1 con US equities.

---

### 3.4 Cash Recycling — Optimizacion de Capital

#### Arquitectura de Capital

```
Capital Total = COMPASS Account + Rattlesnake Account
Base Allocation: 50% / 50%
```

#### Logica de Reciclaje Diario

1. Calcular R_idle = Rattlesnake_account × (1 - exposure)
2. max_loan = (Total × 0.75) - COMPASS_account
3. recycle = min(R_idle, max_loan)
4. COMPASS usa el capital reciclado para mas posiciones
5. EFA recibe el capital sobrante

**Cap**: COMPASS nunca supera 75% del capital total. Esto preserva reservas para Rattlesnake cuando se active.

---

## 4. SISTEMA DE OVERLAYS MACROECONOMICOS (v3)

Los overlays son un sistema de modulacion de exposicion basado en datos macroeconomicos de la Federal Reserve (FRED). Operan como **multiplicadores del capital disponible**, nunca como decisiones binarias.

### 4.1 Banking Stress Overlay (BSO)

**Indicadores compositos** (ponderacion):
- NFCI — Chicago Fed National Financial Conditions Index (40%)
- STLFSI — St. Louis Fed Financial Stress Index (25%)
- BAMLH0A0HYM2 — ICE BofA US High Yield OAS en bps (35%)

**Escalado**:

| Indicador | Nivel Normal (1.0) | Alerta (transitorio) | Estres (0.25) |
|-----------|-------------------|---------------------|---------------|
| NFCI | <= 0.5 | 1.5 (0.60) | >= 3.0 |
| STLFSI | <= 1.0 | — | >= 3.0 |
| HY OAS | <= 700 bps | 1000 bps (0.60) | >= 1500 bps |

**Base academica**: Adrian & Shin (2010) — las condiciones financieras predicen volatilidad futura mejor que la volatilidad historica. El HY spread es el predictor mas robusto de recesiones (Gilchrist & Zakrajsek 2012).

### 4.2 M2 Momentum Indicator

**Signal**: Cambio YoY de M2 (masa monetaria) vs 3 meses atras

**Logica**:
- Si la tasa de crecimiento de M2 esta acelerandose → positivo para equities
- Si se desacelera > 1.5pp → reduce exposicion
- Desaceleracion > 3.0pp → scalar = 0.40

**ZIRP Guard**: Desactivado cuando Fed Funds Rate < 1.0% (QE distorsiona la senal)

**Base academica**: Friedman & Schwartz (1963) — cambios en masa monetaria preceden actividad economica. Revisitado por Belongia & Ireland (2015) para el entorno post-QE.

### 4.3 FOMC Surprise Signal

**Deteccion**: Movimiento de 3 dias en DFF (Fed Funds Effective Rate)

| Movimiento | Scalar | Interpretacion |
|-----------|--------|----------------|
| > 50 bps | 0.50 | Shock monetario significativo |
| > 25 bps | 0.75 | Cambio moderado inesperado |
| <= 25 bps | 1.00 | Normal |

**Decay**: Lineal sobre 10 dias de trading (14 calendario)

**Base academica**: Bernanke & Kuttner (2005) — los shocks de politica monetaria no anticipados tienen efectos significativos e inmediatos en precios de acciones.

### 4.4 Fed Emergency Signal

**Deteccion**: Aumento de WALCL (activos totales de la Fed) > 5% en 30 dias

**Efecto**: No reduce capital — impone **floor de 2 posiciones minimas** por 90 dias calendario

**Logica**: Cuando la Fed expande balance agresivamente, esta inyectando liquidez. Historicamente, esto precede rallies — no es momento de estar en cash. El floor previene salida total en panico.

**Ejemplo historico**: Marzo 2020 — la Fed duplico su balance en semanas. Este overlay habria mantenido exposicion minima durante el bottom.

### 4.5 Credit Sector Pre-Filter

**Logica basada en HY spread**:

| HY OAS | Accion |
|--------|--------|
| > 1500 bps | Excluir Financials + Energy del universo |
| > 1000 bps | Excluir Financials del universo |
| <= 1000 bps | Sin exclusiones |

**Base academica**: Los sectores Financials y Energy tienen la mayor correlacion con credit spreads (Collin-Dufresne, Goldstein, Martin 2001). En estres crediticio, estos sectores sufren desproporcionadamente.

### 4.6 Cash Optimization

**Fuente**: DTB3 (3-month T-Bill rate)
- Aplica tasa diaria (annual/252) al cash idle
- No es un scalar — override de la tasa de interes en cash

### 4.7 Agregacion de Overlays

```
capital_scalar = BSO_scalar × M2_scalar × FOMC_scalar
capital_scalar = clamp(capital_scalar, 0.25, 1.0)

# OVERLAY_FLOOR = 0.25 — nunca reduce a menos de 25%
# position_floor from FedEmergency (if active)
# excluded_sectors from CreditFilter
```

**Damping**: `overlay_damping = 0.25` — los overlays reducen exposicion gradualmente, no de golpe.

**Diseno fail-safe**: Si FRED no responde, overlays se desactivan silenciosamente (scalar = 1.0). El sistema nunca para por falta de datos macro.

---

## 5. GESTION DE RIESGO ADAPTATIVA

### 5.1 Smooth Drawdown Leverage (v8.4 — no binario)

A diferencia de v8.0 (portfolio stop → protection mode → recovery stages), v8.4 usa escalado lineal continuo:

```
Si DD >= -10%: leverage = 1.0 (full)
Si -20% <= DD < -10%: leverage = interpolacion lineal [1.0 → 0.60]
Si -35% <= DD < -20%: leverage = interpolacion lineal [0.60 → 0.30]
Si DD < -35%: leverage = 0.30 (floor)
```

**Ventaja**: No hay "cliff" binario que fuerce liquidacion total en -15%. La reduccion es gradual y proporcional al dolor.

**Base academica**: Grossman & Zhou (1993) demostraron que la gestion optima de drawdown es una funcion continua de la distancia al peak, no un stop binario. El escalado lineal es la aproximacion mas practica.

### 5.2 Crash Brake (v8.4)

Mecanismo de emergencia separado del DD scaling — detecta **velocidad** de caida, no solo nivel:

| Condicion | Accion |
|-----------|--------|
| S&P 500 cae >= 6% en 5 dias | Leverage → 0.15, cooldown = 10 dias |
| S&P 500 cae >= 10% en 10 dias | Leverage → 0.15, cooldown = 10 dias |

**Cooldown**: Durante 10 dias post-trigger, leverage permanece en minimo 0.15x independientemente de DD scaling.

**Base academica**: Los crash events tienen dinamica no-lineal (Johansen, Ledoit, Sornette 2000). La velocidad de caida es mejor predictor de crash continuation que el nivel absoluto de drawdown.

### 5.3 Volatility Targeting (desactivado en produccion)

```
leverage = TARGET_VOL / realized_vol(SPY, 20d)
leverage = clamp(leverage, 0.5, LEVERAGE_MAX)
```

**LEVERAGE_MAX = 1.0 en produccion**: El costo de margen (6% anual) destruye valor neto despues de friccion. El vol targeting actua como modulador de exposicion, no como amplificador.

---

## 6. DATOS MACROECONOMICOS (FRED)

Todas las series se descargan via FRED API y se forward-fill a frecuencia diaria:

| FRED ID | Serie | Uso | Frecuencia |
|---------|-------|-----|------------|
| NFCI | Chicago Fed Financial Conditions | BSO (40%) | Semanal |
| STLFSI4 | St. Louis Fed Financial Stress | BSO (25%) | Semanal |
| BAMLH0A0HYM2 | ICE BofA US HY OAS | BSO (35%) + CreditFilter | Diaria |
| M2SL | M2 Money Stock (SA) | M2 Momentum | Mensual |
| FEDFUNDS | Fed Funds Rate | ZIRP guard | Mensual |
| DFF | Fed Funds Effective Rate | FOMC Surprise | Diaria |
| WALCL | Fed Total Assets | Fed Emergency | Semanal |
| DTB3 | 3-Month T-Bill Rate | Cash Optimization | Diaria |

---

## 7. PARAMETROS COMPLETOS (v8.4)

```
UNIVERSO
  broad_pool              = ~113 stocks (S&P 500 multi-sector)
  top_n                   = 40 (rotacion anual por dollar volume)
  min_age_days            = 63
  quality_vol_max         = 0.60 (max vol anualizada)
  quality_max_single_day  = 0.50 (max movimiento en un dia)

SIGNAL (COMPASS)
  momentum_lookback       = 90 dias
  momentum_skip           = 5 dias
  min_momentum_stocks     = 20 (minimo para rankear)

REGIMEN (continuo)
  sig_200 k               = 15.0 (sigmoid SMA200)
  sig_cross k             = 30.0 (sigmoid SMA50/200)
  sig_mom k               = 15.0 (sigmoid 20d momentum)
  trend_weight            = 0.60
  vol_weight              = 0.40

POSICIONES (COMPASS)
  num_positions           = 5 (risk-on, score >= 0.65)
  num_positions_risk_off  = 2 (score < 0.35)
  max_per_sector          = 3
  hold_days               = 5
  hold_days_max           = 10 (hard cap)
  bull_override_threshold = 0.03 (SPY > SMA200 × 1.03)
  bull_override_min_score = 0.40

ADAPTIVE STOPS
  stop_daily_vol_mult     = 2.5
  stop_floor              = -6%
  stop_ceiling            = -15%
  position_stop_loss      = -8% (fallback)
  trailing_activation     = +5%
  trailing_stop_pct       = 3% (vol-scaled)
  trailing_vol_baseline   = 0.25

EXIT RENEWAL
  renewal_profit_min      = +4%
  momentum_renewal_thresh = 85th percentile

DRAWDOWN SCALING (smooth)
  dd_scale_tier1          = -10% (start reducing)
  dd_scale_tier2          = -20% (mid reduction)
  dd_scale_tier3          = -35% (floor)
  lev_full                = 1.0
  lev_mid                 = 0.60
  lev_floor               = 0.30

CRASH BRAKE
  crash_vel_5d            = -6%
  crash_vel_10d           = -10%
  crash_leverage          = 0.15
  crash_cooldown          = 10 dias

RATTLESNAKE
  drop_threshold_5d       = -8%
  rsi_period              = 5
  rsi_threshold           = 25
  sma_filter              = 200 dias
  min_volume              = 500,000 shares
  position_size           = 20% de R_account
  max_positions           = 5 / 2 (risk-on / risk-off)
  profit_target           = +4%
  stop_loss               = -5%
  time_exit               = 8 dias
  vix_max                 = 35

CAPITAL MANAGEMENT
  base_compass_alloc      = 50%
  base_rattle_alloc       = 50%
  max_compass_alloc       = 75% (cap con recycling)

OVERLAYS
  overlay_damping         = 0.25
  overlay_floor           = 0.25

COSTOS
  initial_capital         = $100,000
  margin_rate             = 6% anual
  commission              = $0.001/accion
  leverage_max            = 1.0 (sin apalancamiento)

EJECUCION
  preclose_signal_time    = 15:30 ET
  moc_deadline            = 15:50 ET
  market_open             = 09:30 ET
  market_close            = 16:00 ET
```

---

## 8. FLUJO DIARIO DE OPERACION

```
CADA DIA DE TRADING (09:30 - 16:00 ET):

  1. DATOS
     - Fetch precios via Yahoo Finance v8 API
     - Fetch datos FRED (si stale > 24h)
     - Actualizar VIX, ^GSPC, EFA

  2. OVERLAYS
     - Calcular BSO composite scalar
     - Calcular M2 momentum scalar
     - Calcular FOMC surprise scalar (con decay)
     - Verificar Fed Emergency (WALCL jump)
     - Verificar Credit filter (HY OAS)
     - Agregar: capital_scalar = BSO × M2 × FOMC (clamp 0.25-1.0)

  3. REGIMEN
     - Calcular regime_score continuo [0.0, 1.0]
     - Determinar max_positions segun thresholds
     - Verificar bull override (+1 pos si aplica)

  4. DRAWDOWN & CRASH
     - Calcular drawdown actual vs peak
     - dd_leverage = interpolacion segun DD tiers
     - Verificar crash velocity (5d y 10d)
     - Si crash triggered: leverage = 0.15, cooldown = 10d

  5. CERRAR POSICIONES (COMPASS)
     a. Hold >= hold_days (considerar renewal si profit >= 4%)
     b. Adaptive stop triggered (vol-scaled)
     c. Trailing stop triggered (vol-scaled)
     d. Fuera del top-40 anual
     e. Exceso por cambio de regimen → cerrar peores
     f. Exceso por sector → cerrar ultimas del sector

  6. ABRIR POSICIONES (COMPASS) — 15:30 ET
     a. Calcular SCORE para elegibles (no en portfolio, quality filter OK)
     b. Aplicar sector filter (max 3 per sector)
     c. Aplicar credit filter (excluir sectores si HY alto)
     d. Rankear por score descendente
     e. Pesos por inverse volatility
     f. Capital = base × capital_scalar × dd_leverage
     g. Ejecutar MOC orders antes de 15:50 ET

  7. RATTLESNAKE
     a. Verificar regime (SPY > SMA200 AND VIX <= 35)
     b. Scan S&P 100: buscar drop >= 8%, RSI(5) < 25, precio > SMA200
     c. Entrar posiciones (20% de R_account cada una)
     d. Verificar exits: profit +4%, stop -5%, time 8d

  8. CASH RECYCLING
     a. Calcular R_idle
     b. Reciclar a COMPASS (cap 75%)
     c. Invertir sobrante en EFA (si EFA > SMA200)

  9. REGISTRAR
     - Save state JSON (positions, meta, regime, overlays)
     - Log decisions para ML learning
     - Git sync (auto-commit + push cada 15 min)
```

---

## 9. INFRAESTRUCTURA TECNICA

### Arquitectura de Deployment

```
LOCAL (Windows 11)
├── compass_dashboard.py    — Flask + live engine (port 5000)
├── omnicapital_live.py     — COMPASSLive class (2,800+ lineas)
├── compass_overlays.py     — Overlay system v3 (407 lineas)
├── rattlesnake_signals.py  — Mean-reversion signals (200 lineas)
├── hydra_capital.py        — Capital recycling manager (199 lineas)
├── compass_fred_data.py    — FRED data downloader (164 lineas)
├── compass_ml_learning.py  — ML decision logger
├── compass_watchdog.py     — Auto-restart daemon
└── git_sync.py             — Non-blocking git push (15 min)

CLOUD (Render.com)
├── compass_dashboard_cloud.py — Showcase dashboard (gunicorn)
├── render.yaml                — Deployment config
└── requirements-cloud.txt     — Minimal dependencies

SYNC: Local → GitHub → Render (auto-deploy on push)
```

### Stack Tecnologico

| Componente | Tecnologia |
|------------|------------|
| Lenguaje | Python 3.14.2 |
| Framework | Flask |
| Datos mercado | Yahoo Finance v8 Chart API |
| Datos macro | FRED API (Federal Reserve) |
| Frontend | Vanilla JS + Chart.js |
| Deployment cloud | Render.com (gunicorn) |
| Version control | Git → GitHub |
| State persistence | JSON files |
| Broker (paper) | PaperBroker (internal) |

### Archivos de Estado

| Archivo | Contenido | Update |
|---------|-----------|--------|
| `state/compass_state_latest.json` | Estado actual completo | Cada 60s |
| `state/compass_state_YYYYMMDD.json` | Snapshot diario | EOD |
| `state/cycle_log.json` | Historial de ciclos de rotacion | Por ciclo |
| `state/ml_learning/decisions.jsonl` | Decisiones de trading | Por trade |
| `state/ml_learning/daily_snapshots.jsonl` | Snapshots de mercado | Diario |
| `state/ml_learning/outcomes.jsonl` | Resultados de trades | Al cerrar |

---

## 10. EVOLUCION DEL SISTEMA

| Version | Fecha | Descripcion | CAGR | Sharpe | Max DD |
|---------|-------|-------------|------|--------|--------|
| v1 | Feb 2026 | MicroManagement intradayia | — | — | — |
| v4 | Feb 2026 | Optimized daily | — | — | — |
| v5 | Feb 2026 | 3 Day Strategy | — | — | — |
| v6 | Feb 2026 | Random selection, 2x leverage | 5.40%* | 0.22 | -59.4% |
| v8.0 | Feb 2026 | COMPASS (momentum + regime) | 16.16% | 0.73 | -34.8% |
| **v8.4** | **Mar 2026** | **HYDRA (multi-strategy + overlays)** | **14.92%** | **1.12** | **-22.25%** |

*v6 CAGR con universo corregido (sin sesgo de supervivencia).

> La evolucion muestra un trade-off deliberado: v8.4 sacrifica ~1.2% de CAGR vs v8.0 pero mejora dramaticamente la calidad de retornos (Sharpe 1.12 vs 0.73) y reduce max DD de -34.8% a -22.25%. Esto refleja la prioridad del sistema: **sobrevivir primero, crecer despues**.

---

## 11. RIESGOS Y LIMITACIONES

### Riesgos Sistemicos

1. **Overfitting**: Aunque cada parametro tiene base academica, el ensamble de componentes fue calibrado sobre datos 2000-2026. Out-of-sample performance puede diferir.

2. **Momentum crashes**: Factor momentum puede sufrir reversiones violentas en recuperaciones de mercado (ej: Mar 2009). El regime filter y overlays mitigan parcialmente.

3. **Correlacion en crisis**: En eventos de tail risk (2008, 2020), correlaciones entre acciones convergen a 1.0. La diversificacion por sector/estrategia pierde efectividad.

4. **Dependencia de datos**: Yahoo Finance y FRED son servicios gratuitos sin SLA. Una interrupcion prolongada deja al sistema ciego.

5. **Model risk**: El regime score continuo usa sigmoides calibradas subjetivamente (k=15, k=30). Cambios estructurales en el mercado podrian invalidar estos parametros.

### Limitaciones Conocidas

- **No opera intradayia** — solo Market-on-Close
- **No hace short selling** — solo long equity
- **No usa opciones ni derivados** — sin hedging explicito
- **No analiza fundamentales** — pure quant, solo datos de precio/volumen + macro
- **Sin leverage en produccion** — LEVERAGE_MAX = 1.0
- **Slippage no modelado** — mitigado por operar solo stocks liquidos (top-40 por dollar volume)
- **Sin reinversion de dividendos explicita** — asumido en precios adjusted

---

## 12. REGLAS INQUEBRANTABLES

1. **NO modificar parametros sin backtest completo** (2000-2026). 40 experimentos fallidos lo confirman.

2. **NO agregar complejidad sin justificacion** — si no mejora Sharpe o reduce DD significativamente, no se implementa.

3. **NO ignorar overlays** — estan ahi por una razon macro. Desactivarlos es volar ciego.

4. **NO aumentar LEVERAGE_MAX por encima de 1.0** — el costo de margen (6%) destruye el alpha.

5. **NO operar acciones fuera del top-40** — liquidez es proteccion.

6. **SIEMPRE respetar los stops** — adaptativos o no, sin excepciones.

7. **Paper trading primero** — minimo 3 meses antes de capital real. (En curso desde Mar 6, 2026.)

8. **NO modificar el engine durante market hours** — cambios solo despues del cierre.

9. **Git sync siempre activo** — el state file es la fuente de verdad. Perderlo es perder contexto.

10. **Overlays son multiplicativos, nunca aditivos** — previene que un solo overlay anule a los demas.

---

## 13. REFERENCIAS ACADEMICAS

- Ang, A. & Bekaert, G. (2002). "Regime Switches in Interest Rates." *Journal of Business & Economic Statistics*.
- Asness, C., Moskowitz, T. & Pedersen, L. (2013). "Value and Momentum Everywhere." *Journal of Finance*.
- Bernanke, B. & Kuttner, K. (2005). "What Explains the Stock Market's Reaction to Federal Reserve Policy?" *Journal of Finance*.
- Collin-Dufresne, P., Goldstein, R. & Martin, J.S. (2001). "The Determinants of Credit Spread Changes." *Journal of Finance*.
- De Bondt, W. & Thaler, R. (1985). "Does the Stock Market Overreact?" *Journal of Finance*.
- Faber, M. (2007). "A Quantitative Approach to Tactical Asset Allocation." *Journal of Wealth Management*.
- Friedman, M. & Schwartz, A. (1963). *A Monetary History of the United States, 1867-1960*. Princeton University Press.
- Gilchrist, S. & Zakrajsek, E. (2012). "Credit Spreads and Business Cycle Fluctuations." *American Economic Review*.
- Grossman, S. & Zhou, Z. (1993). "Optimal Investment Strategies for Controlling Drawdowns." *Mathematical Finance*.
- Hamilton, J. (1989). "A New Approach to the Economic Analysis of Nonstationary Time Series." *Econometrica*.
- Jegadeesh, N. (1990). "Evidence of Predictable Behavior of Security Returns." *Journal of Finance*.
- Jegadeesh, N. & Titman, S. (1993). "Returns to Buying Winners and Selling Losers." *Journal of Finance*.
- Johansen, A., Ledoit, O. & Sornette, D. (2000). "Crashes as Critical Points." *International Journal of Theoretical and Applied Finance*.
- Lo, A. & MacKinlay, A.C. (1990). "When Are Contrarian Profits Due to Stock Market Overreaction?" *Review of Financial Studies*.
- Maillard, S., Roncalli, T. & Teiletche, J. (2010). "The Properties of Equally Weighted Risk Contribution Portfolios." *Journal of Portfolio Management*.
- Moskowitz, T. & Grinblatt, M. (1999). "Do Industries Explain Momentum?" *Journal of Finance*.
- Novy-Marx, R. (2012). "Is Momentum Really Momentum?" *Journal of Financial Economics*.

---

*"HYDRA no predice el futuro. Reacciona al presente con disciplina academica y ejecuta con precision mecanica."*
