# COMPASS Russell 2000 Expansion Plan
## De 113 S&P 500 a ~2000 Russell 2000 stocks

**Fecha**: 2026-02-28
**Estado**: PLANIFICACION
**Baseline**: COMPASS v8.2 = 13.90% CAGR (bias-corrected), -66.25% MaxDD, 0.646 Sharpe

---

## 1. DIAGNOSTICO: POR QUE ESTO ES DIFICIL

### 1.1 Escalado de datos (el problema dominante)

| Dimension | S&P 500 actual | Russell 2000 objetivo | Factor |
|-----------|---------------|----------------------|--------|
| Pool bruto | 113 stocks | ~2000 stocks | 18x |
| Pool historico (survivorship) | 797 stocks | ~5000-6000 stocks | 7x |
| Cache actual (.pkl) | 34 MB (broad_pool) | ~600 MB estimado | 18x |
| Cache survivorship | 276 MB | ~4-5 GB estimado | 18x |
| Backtest runtime | ~15 seg | ~4-5 min estimado | 18x |

**Calculo de runtime**: El bucle principal en `run_backtest()` (lineas 434-728 de `omnicapital_v8_compass.py`) itera sobre `all_dates` (~6500 dias). Dentro, para cada dia:
- `compute_momentum_scores()` recorre todos los stocks tradeables (~40 hoy, seguira siendo ~40-100)
- `compute_volatility_weights()` recorre los seleccionados (5-10)
- `get_tradeable_symbols()` recorre el universo anual

El cuello de botella REAL no es el loop diario sino `compute_annual_top40()`: con 5000+ stocks calculando dollar volume medio del anio anterior. Esto pasa de O(113) a O(5000+) pero solo se ejecuta 26 veces (una por anio), asi que el impacto real sera moderado (~2-5 min total).

### 1.2 Survivorship bias en small caps

Este es el riesgo EXISTENCIAL del proyecto. En S&P 500:
- Survivorship bias delta medido: +4.56% (exp40)
- Pool historico: 797 stocks (2.7x el pool actual de 113)

En Russell 2000:
- Tasa de delisting MUCHO mayor (bancarrotas, adquisiciones, penny stocks)
- Estimacion: 3000-4000 stocks delistados en 26 anios
- Survivorship bias delta potencial: +8-12%
- Si el CAGR bruto es 18% pero el bias es 10%, el CAGR real seria 8% -- PEOR que S&P 500

### 1.3 Costes de ejecucion

En `omnicapital_v8_compass.py` linea 71:
```python
COMMISSION_PER_SHARE = 0.001
```

Esto es realista para large caps ($0.001/share). Para small caps:
- Spread bid-ask: 0.3-1.5% (vs 0.01-0.05% en large caps)
- Market impact: significativo si position > 1% del volumen diario
- El modelo actual NO modela spread, solo comision fija

### 1.4 Parametros optimizados para large caps

Parametros que probablemente necesiten re-calibracion:
- `MOMENTUM_LOOKBACK = 90` -- puede ser diferente para small caps (mas ruido)
- `POSITION_STOP_LOSS = -0.08` -- small caps son mas volatiles, -8% se triggea constantemente
- `TRAILING_ACTIVATION = 0.05` / `TRAILING_STOP_PCT = 0.03` -- idem
- `TOP_N = 40` -- con 2000 stocks, podria ser TOP_100 o TOP_200
- `NUM_POSITIONS = 5` -- con mayor universo, diversificacion deberia aumentar
- `MIN_MOMENTUM_STOCKS = 20` -- escala con el universo

---

## 2. AGENTES: SET MINIMO VIABLE

### Agentes existentes que SE REUTILIZAN:

1. **project-manager** (este agente) -- coordinacion y decisiones go/no-go
2. **financial-algo-expert** (Sonnet) -- adaptacion de parametros COMPASS y analisis de resultados

### Agentes NUEVOS necesarios (solo 1):

3. **russell-data-engineer**

**Justificacion**: El 80% del trabajo es conseguir datos historicos limpios del Russell 2000 con survivorship bias corregido. Esto es un problema de ingenieria de datos, no de algoritmica. El `financial-algo-expert` no deberia perder ciclos en esto.

**Responsabilidades**:
- Obtener composicion historica del Russell 2000 (point-in-time, anio por anio)
- Descargar precio historico de ~5000-6000 tickers (actuales + delistados)
- Manejar fuentes de datos: yfinance (primaria), Stooq (fallback para delistados), posiblemente Tiingo
- Producir un `.pkl` equivalente a `survivorship_bias_pool.pkl` pero para Russell 2000
- Validar calidad de datos: splits, dividendos, gaps, tickers reutilizados
- Optimizar formato de almacenamiento (posiblemente parquet en vez de pickle para >4GB)

**Modelo**: Sonnet (tareas procedimentales, no requiere razonamiento profundo)

### Agentes que NO necesitamos (y por que):

- **execution-specialist**: NO. Primero hay que saber si la estrategia funciona en backtest. Los costes de ejecucion se modelan como parametro en el backtest, no como sistema separado.
- **validation-statistician**: NO. El `financial-algo-expert` puede hacer bootstrap/Monte Carlo. No justifica un agente dedicado para una sola estrategia.
- **systems-architect**: NO. No estamos refactorizando la arquitectura. Es un archivo monolitico y funciona. La modularizacion es un lujo, no un requisito.

---

## 3. RUTA CRITICA Y SECUENCIA DE ENTREGABLES

```
FASE 0: FEASIBILITY GATE (Semana 1)
  |
  v
FASE 1: DATA PIPELINE (Semanas 2-4)
  |
  v
FASE 2: BACKTEST NAIVE (Semana 5)
  |
  v
  [GO/NO-GO #1: Es el CAGR raw > 10%?]
  |
  v
FASE 3: SURVIVORSHIP BIAS (Semanas 6-8)
  |
  v
  [GO/NO-GO #2: Es el CAGR bias-corrected > 12%?]
  |
  v
FASE 4: PARAMETROS + COSTES (Semanas 9-11)
  |
  v
  [GO/NO-GO #3: CAGR neto > 14% con costes realistas?]
  |
  v
FASE 5: VALIDACION FINAL (Semana 12)
```

---

### FASE 0: FEASIBILITY GATE (antes de escribir codigo)
**Owner**: project-manager + financial-algo-expert
**Duracion**: 3-5 dias
**Objetivo**: Verificar que los datos existen y son accesibles

| # | Tarea | Entregable | Complejidad |
|---|-------|-----------|-------------|
| 0.1 | Investigar fuentes de composicion historica Russell 2000 | Lista de fuentes con cobertura temporal y coste | S |
| 0.2 | Test de descarga: 50 tickers Russell 2000 actuales via yfinance | Script + reporte de exito/fallo | S |
| 0.3 | Test de descarga: 10 tickers delistados del Russell via Stooq | Script + reporte de cobertura | S |
| 0.4 | Estimar tamano total de datos y tiempo de descarga | Documento con numeros | S |
| 0.5 | Decision: continuar o abortar | GO/NO-GO gate 0 | - |

**GO/NO-GO #0**: Si no podemos obtener composicion historica point-in-time del Russell 2000, el proyecto SE CANCELA. Sin esto, cualquier backtest tiene survivorship bias fatal.

**Fuentes candidatas para composicion historica**:
- FTSE Russell (propietario, caro)
- Sharadar/Quandl (historico de indices, ~$500/anio)
- Compustat (academico)
- Scraping de SEC filings (13F de ETFs como IWM)
- Reconstruccion via market cap (todas las stocks con market cap entre $300M-$2B en cada momento)

---

### FASE 1: DATA PIPELINE
**Owner**: russell-data-engineer
**Duracion**: 2-3 semanas
**Dependencia**: FASE 0 completada con GO

| # | Tarea | Entregable | Complejidad |
|---|-------|-----------|-------------|
| 1.1 | Obtener composicion historica Russell 2000 (2000-2026) | `data_cache/russell2000_constituents_history.pkl` | L |
| 1.2 | Construir lista maestra de tickers (actuales + historicos) | `data_cache/russell2000_master_tickers.csv` con ~5000-6000 tickers | M |
| 1.3 | Descargar precios: tickers actuales (~2000) | `data_cache/russell2000_current_pool.pkl` | M |
| 1.4 | Descargar precios: tickers delistados (~3000-4000) | `data_cache/russell2000_delisted_pool.pkl` | XL |
| 1.5 | Validacion de datos: splits, gaps, outliers | Reporte de calidad + datos limpios | M |
| 1.6 | Merge y producir dataset final | `data_cache/russell2000_full_pool.pkl` (o .parquet si >4GB) | M |

**Riesgo clave**: La tarea 1.4 puede tardar DIAS en descargas. Plan de mitigacion:
- Descargas en batches de 100 tickers con reintentos
- Cache incremental (no re-descargar si ya existe)
- Fallback multi-fuente: yfinance -> Stooq -> Tiingo

---

### FASE 2: BACKTEST NAIVE
**Owner**: financial-algo-expert
**Duracion**: 1 semana
**Dependencia**: FASE 1 completada (al menos tickers actuales)

| # | Tarea | Entregable | Complejidad |
|---|-------|-----------|-------------|
| 2.1 | Crear `compass_russell2000_v1.py` copiando v8.2 con nuevo pool | Archivo ejecutable | M |
| 2.2 | Ajustar TOP_N (40 -> 100?) y NUM_POSITIONS (5 -> 10-15?) | Parametros justificados | S |
| 2.3 | Ejecutar backtest con datos de tickers actuales (sin survivorship correction) | Metricas: CAGR, MaxDD, Sharpe, Calmar | M |
| 2.4 | Comparar equity curve con S&P 500 baseline | Grafico + tabla comparativa | S |

**GO/NO-GO #1**:
- Si CAGR raw (con survivorship bias) < 10%: ABORTAR. Si ni siquiera con bias favorable supera 10%, no hay premio de momentum en small caps.
- Si CAGR raw > 10%: CONTINUAR a Fase 3.
- Nota: esperamos que el raw sea alto (~18-25%) porque tiene survivorship bias severo.

---

### FASE 3: SURVIVORSHIP BIAS CORRECTION
**Owner**: russell-data-engineer (datos) + financial-algo-expert (backtest)
**Duracion**: 2-3 semanas
**Dependencia**: FASE 1 completa (incluyendo delistados) + FASE 2 completada

| # | Tarea | Entregable | Complejidad |
|---|-------|-----------|-------------|
| 3.1 | Adaptar logica de `exp40_survivorship_bias.py` para Russell 2000 | `exp50_russell2000_survivorship.py` | L |
| 3.2 | Construir universo point-in-time por anio | `annual_universe` dict con ~2000 tickers por anio | M |
| 3.3 | Ejecutar backtest con universo corregido | Metricas bias-corrected | M |
| 3.4 | Cuantificar survivorship bias delta (raw - corrected) | Numero: delta en puntos de CAGR | S |

**GO/NO-GO #2**:
- Si CAGR bias-corrected < 12%: ABORTAR. No justifica la complejidad vs S&P 500 (13.9%).
- Si survivorship bias delta > 8%: BANDERA ROJA. Significa que la senial de momentum en small caps esta dominada por selection bias.
- Si CAGR bias-corrected > 12%: CONTINUAR.

---

### FASE 4: CALIBRACION DE PARAMETROS + COSTES DE EJECUCION
**Owner**: financial-algo-expert
**Duracion**: 2-3 semanas
**Dependencia**: FASE 3 completada con GO

| # | Tarea | Entregable | Complejidad |
|---|-------|-----------|-------------|
| 4.1 | Modelar spread bid-ask como funcion de market cap y volumen | Modelo de costes parametrico | M |
| 4.2 | Re-ejecutar backtest con costes realistas de small cap | Metricas con costes | M |
| 4.3 | Sensitivity analysis de parametros clave | Grid search: MOMENTUM_LOOKBACK, STOP_LOSS, TOP_N, NUM_POSITIONS | L |
| 4.4 | Filtro de liquidez minima para evitar microcaps iliquidos | Parametro MIN_DOLLAR_VOLUME | S |
| 4.5 | Backtest final con parametros optimizados + costes | Metricas definitivas | M |

**GO/NO-GO #3**:
- Si CAGR neto (bias-corrected + costes realistas) < 14%: DECISION AMBIGUA. Podria no justificar la complejidad operativa.
- Si CAGR neto > 14%: EXITO. Superamos S&P 500 baseline.
- Tambien evaluar: Sharpe > 0.65? MaxDD < -70%? Calmar > 0.20?

---

### FASE 5: VALIDACION Y DOCUMENTACION
**Owner**: financial-algo-expert + project-manager
**Duracion**: 1 semana
**Dependencia**: FASE 4 completada

| # | Tarea | Entregable | Complejidad |
|---|-------|-----------|-------------|
| 5.1 | Out-of-sample walk-forward test (si hay datos suficientes) | Metricas OOS | M |
| 5.2 | Analisis de regimen: comportamiento en bear markets (2000-02, 2008, 2020, 2022) | Tabla por periodo | M |
| 5.3 | Comparar con benchmarks: IWM (Russell 2000 ETF), SPY | Tabla comparativa | S |
| 5.4 | Documentar COMPASS Russell 2000 v1.0 final | Documento tecnico | M |

---

## 4. REGISTRO DE RIESGOS

| ID | Riesgo | Probabilidad | Impacto | Mitigacion | Gate |
|----|--------|-------------|---------|------------|------|
| R1 | No existe fuente gratuita de composicion historica R2000 | ALTA | FATAL | Considerar reconstruccion via market cap; presupuesto para datos pagos | Gate 0 |
| R2 | Survivorship bias > 10% | ALTA | ALTO | Gate 2 explicito; si bias > 8% evaluar filtros de calidad | Gate 2 |
| R3 | Spreads eliminan alfa | MEDIA | ALTO | Filtro de liquidez minima; aumentar holding period | Gate 3 |
| R4 | Backtest runtime > 30 min | MEDIA | MEDIO | Vectorizar `compute_momentum_scores()`; paralelizar anios; usar parquet | Fase 2 |
| R5 | Datos de precio incorrectos (splits, ticker reuse) | ALTA | MEDIO | Validacion cruzada multi-fuente; flags de outliers | Fase 1 |
| R6 | Parametros S&P 500 no transfieren a small caps | MEDIA | MEDIO | Grid search sistematico en Fase 4 | Gate 3 |

---

## 5. LO QUE ESTA FUERA DE ALCANCE

- Multi-asset (bonos, commodities, FX) -- NO
- Mercados internacionales (STOXX 600, Nikkei) -- NO
- Live trading / execution system -- NO
- Refactorizacion de arquitectura monolitica -- NO
- Machine learning / deep learning -- NO
- Optimizacion de latencia -- NO

---

## 6. METRICAS DE EXITO

| Metrica | Baseline (S&P 500 v8.2) | Objetivo Russell 2000 | Minimo aceptable |
|---------|------------------------|----------------------|-------------------|
| CAGR (bias-corrected) | 13.90% | > 16% | > 14% |
| MaxDD | -66.25% | < -60% | < -70% |
| Sharpe | 0.646 | > 0.70 | > 0.60 |
| Calmar | 0.21 | > 0.25 | > 0.20 |
| Backtest runtime | 15 seg | < 5 min | < 10 min |

---

## 7. DEFINICION DEL AGENTE NUEVO

### russell-data-engineer

**Archivo**: `.claude/agents/russell-data-engineer.md`
**Modelo**: Sonnet
**Scope**: Exclusivamente obtener, limpiar, y validar datos de precio historicos del Russell 2000 con correccion de survivorship bias.

**NO hace**: analisis de estrategia, optimizacion de parametros, evaluacion de rendimiento.
**SI hace**: descargas, parsing, limpieza, validacion, cache, formato de almacenamiento.

Patron de trabajo equivalente a `exp40_survivorship_bias.py` pero para Russell 2000.
