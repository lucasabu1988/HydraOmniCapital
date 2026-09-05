# Plan: Cuantificar Survivorship Bias en COMPASS v8.2

## ✅ COMPLETADO - 27 Feb 2026

**Resultado**: Survivorship bias cuantificado en **+4.56% CAGR**
- CAGR Original (sesgado): 18.46%
- CAGR Corregido (realista): **13.90%**
- Ver: `backtests/exp40_comparison.txt` para detalles completos

---

## Objetivo
Crear un script informativo (`exp40_survivorship_bias.py`) que corra el EXACT backtest de COMPASS v8.2 pero con el universo historico REAL del S&P 500 (incluyendo stocks que quebraron/salieron). Comparar contra el backtest actual para cuantificar el sesgo.

## No se modifica
- `omnicapital_v8_compass.py` (LOCKED)
- Ningun parametro del algoritmo

## Fuente de datos
- **Constituyentes historicos**: GitHub `fja05680/sp500` — CSV con membership diaria del S&P 500 desde 1996
- **Precios de stocks delistadas**: Stooq (ya tenemos experiencia en `cross_validation_stooq.py`)
- **Precios de stocks actuales**: yfinance (como siempre)

## Pasos del script

### 1. Descargar constituyentes historicos S&P 500
- Descargar el CSV de `fja05680/sp500` con membership diaria
- Parsear para obtener lista de tickers por año (2000-2026)
- Identificar tickers que estuvieron en el S&P 500 pero NO estan en nuestro BROAD_POOL actual

### 2. Descargar precios de stocks faltantes
- Para cada ticker historico que no esta en BROAD_POOL: intentar Stooq primero, yfinance como fallback
- Mapping de tickers problematicos (LEH, ENE, BSC, WM old, CFC, WCOM, GM old)
- Cache en `data_cache/survivorship_bias_pool.pkl`
- Reportar cuantas stocks se pudieron descargar vs cuantas no

### 3. Reconstruir universo anual point-in-time
- Para cada año, el universo elegible es: stocks que estaban en el S&P 500 EN ESE MOMENTO + tienen datos de precio
- Ya no usar BROAD_POOL fijo — usar constituyentes historicos reales
- `compute_annual_top40()` opera sobre este universo expandido

### 4. Correr backtest COMPASS v8.2 identico
- Copiar EXACTA logica de `omnicapital_v8_compass.py` (parametros, signals, stops, regime, recovery)
- Unica diferencia: universo de entrada = constituyentes historicos reales
- SPY data: misma fuente (yfinance)
- Cash yield: mismo (Moody's Aaa)

### 5. Comparar resultados
- Tabla lado a lado: CAGR, Sharpe, MaxDD, final value, # trades, # stops
- Delta de survivorship bias = CAGR_actual - CAGR_corregido
- Analizar: cuantas veces el backtest corregido selecciono una stock que luego quebro
- Listar las stocks problematicas que entraron al portfolio y su impacto

### 6. Output
- Console: resumen comparativo
- `backtests/exp40_survivorship_daily.csv` — equity curve
- `backtests/exp40_survivorship_trades.csv` — trades
- `backtests/exp40_survivorship_analysis.csv` — stocks problematicas y su impacto

## Riesgos y mitigaciones
- **Stooq no tiene datos de algunas delistadas**: reportar coverage gap, no inventar datos
- **Ticker reuse** (WM = Washington Mutual hasta 2008, luego Waste Management): usar fecha de remocion del S&P 500 para cortar datos
- **Adjusted close de delistadas**: Stooq provee split+dividend adjusted, consistente con yfinance
- **Tickers con formato distinto**: mapping manual para los ~15 casos criticos (LEH, ENE, BSC, etc.)

## Resultado esperado
Un numero concreto: "el survivorship bias de COMPASS v8.2 es X.XX% CAGR"
