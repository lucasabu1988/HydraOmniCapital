# OMNICAPITAL v8 COMPASS
## Manifiesto del Algoritmo

**Cross-sectional Momentum, Position-Adjusted Risk Scaling**

Fecha: 17 Febrero 2026
Version: 8.0

---

## 1. FILOSOFIA

COMPASS nace de una leccion dolorosa: el v6 original reportaba 16.92% CAGR, pero al eliminar el sesgo de supervivencia, la realidad era 5.40% con -59.4% de drawdown maximo. No habia signal. Era compra aleatoria con leverage. El "alpha" era una ilusion.

COMPASS reemplaza la aleatoriedad con un edge real basado en tres pilares academicos probados en decadas de investigacion:

1. **Los ganadores siguen ganando** (Momentum cross-seccional)
2. **Cuando el mercado cae, hay que salir** (Filtro de regimen)
3. **La volatilidad es el verdadero riesgo** (Vol targeting)

La simplicidad sigue siendo el principio rector. COMPASS usa solo datos OHLCV diarios, un indicador de mercado (SPY vs SMA200), y una formula de scoring de dos componentes. No hay machine learning, no hay optimizacion de 50 parametros, no hay caja negra.

---

## 2. RESULTADOS (Backtest 2000-2026)

| Metrica | v6 (aleatorio) | v8 COMPASS | Mejora |
|---------|---------------|------------|--------|
| **CAGR** | 5.40% | **16.16%** | +10.76% |
| **Sharpe** | 0.22 | **0.73** | 3.3x mejor |
| **Sortino** | — | **1.02** | — |
| **Max Drawdown** | -59.4% | **-34.8%** | 24.6% menos |
| **Calmar** | — | **0.46** | — |
| **Win Rate** | — | **55.25%** | — |
| **Trades (26 anos)** | — | 5,386 | ~207/ano |
| **Anos positivos** | — | **21/26** | 81% |
| **$100k se convierte en** | ~$400k | **$4.95M** | 12x mas |
| **Mejor ano** | — | +128.1% | — |
| **Peor ano** | — | -32.7% | — |

---

## 3. EL ALGORITMO

### 3.1 Universo de Inversion

**Pool amplio**: 113 acciones del S&P 500 distribuidas en 9 sectores (Technology, Financials, Healthcare, Consumer, Energy, Industrials, Utilities, Real Estate, Telecom).

**Rotacion anual**: Cada 1 de enero, las 113 acciones se rankean por volumen promedio diario en dolares (Close x Volume) del ano anterior. Solo las **top 40** son elegibles para ese ano. Esto evita sesgo de supervivencia: no se puede invertir en acciones que solo sabemos que son grandes "hoy".

**Filtro de antiguedad**: Una accion necesita al menos 63 dias de historia (3 meses) para ser elegible. Esto evita la volatilidad excesiva de IPOs recientes.

Resultado historico: 78 acciones unicas utilizadas en 26 anos, ~4-5 rotan cada ano.

### 3.2 Filtro de Regimen de Mercado

El sistema opera en dos modos:

| Condicion | Regimen | Posiciones | Leverage |
|-----------|---------|------------|----------|
| SPY > SMA(200) por 3+ dias | **RISK_ON** | 5 | Vol targeting (0.5x-2.0x) |
| SPY < SMA(200) por 3+ dias | **RISK_OFF** | 2 | 1.0x fijo |

**Por que funciona**: El filtro SMA200 es el indicador de tendencia mas simple y robusto que existe. Meb Faber (2007) demostro que estar fuera del mercado cuando SPY esta debajo de su SMA200 reduce el max drawdown a la mitad con minimo impacto en retornos.

**Confirmacion de 3 dias**: Evita whipsaw. No se cambia de regimen por un solo dia de cruce. Se requieren 3 dias consecutivos para confirmar el cambio.

Resultado historico: ~25.7% del tiempo en RISK_OFF. Evito la mayoria de 2001-2002, 2008-2009, y partes de 2022.

### 3.3 Seleccion de Acciones: El Score COMPASS

La pieza central del algoritmo. Cada dia, para cada accion elegible, se calcula:

```
momentum_90d = (Precio hace 5 dias / Precio hace 90 dias) - 1
reversal_5d  = (Precio hoy / Precio hace 5 dias) - 1

SCORE = momentum_90d - reversal_5d
```

Se seleccionan las acciones con **mayor score** (top N, donde N = posiciones disponibles).

**Que significa un score alto**:
- **momentum_90d alto**: La accion ha subido fuerte en los ultimos 3 meses (excluyendo la ultima semana). Es un ganador de mediano plazo.
- **reversal_5d bajo** (o negativo): La accion tuvo un pullback reciente en la ultima semana.
- **Combinacion**: Ganador de mediano plazo + pullback reciente = oportunidad de compra en la tendencia.

**Base academica**:
- Jegadeesh & Titman (1993): Momentum cross-seccional funciona en horizontes de 3-12 meses. Acciones ganadoras siguen ganando.
- Lo & MacKinlay (1990): Retornos de corto plazo (1-5 dias) muestran reversion a la media. Un pullback reciente es temporal.
- El "skip" de los ultimos 5 dias es critico: elimina el efecto de micro-reversion que cancela el momentum. Este es un hallazgo robusto de la literatura.

**Diferencia con v6**: v6 seleccionaba al azar. COMPASS rankea y elige los mejores. Esto es la diferencia entre tirar dados y leer el mercado.

**Diferencia con el filtro SMA20/SMA50 que fallo en v6**: Ese era un filtro de tendencia individual (trend-following por accion). COMPASS es momentum cross-seccional: compara acciones ENTRE SI y elige las mejores relativas. Son conceptos fundamentalmente diferentes.

### 3.4 Position Sizing: Inverse Volatility

No todas las posiciones son iguales. Una accion con 40% de volatilidad anual no deberia tener el mismo peso que una con 15%.

```
vol_20d(stock) = desviacion estandar de retornos diarios (20 dias) x sqrt(252)
peso_raw(stock) = 1 / vol_20d(stock)
peso(stock) = peso_raw / suma(todos los pesos_raw)
tamano_posicion = peso x capital_efectivo
```

**Efecto**: Acciones estables (JNJ, PG, KO) reciben mas capital. Acciones volatiles (TSLA, NVDA, AMD) reciben menos. Esto reduce la volatilidad total del portfolio sin sacrificar retornos.

**Limite**: Ninguna posicion puede exceder 40% del cash disponible, independientemente de los pesos.

### 3.5 Leverage Dinamico: Volatility Targeting

En lugar de leverage fijo (2x siempre o 1x siempre), COMPASS ajusta el leverage automaticamente:

```
realized_vol = volatilidad realizada de SPY (20 dias) anualizada
leverage = 15% / realized_vol
leverage = max(0.5, min(2.0, leverage))
```

| Volatilidad del mercado | Leverage resultante | Interpretacion |
|------------------------|--------------------|-|
| 8% (calma extrema) | 1.88x | Mercado tranquilo, apalancar |
| 12% (normal bajo) | 1.25x | Condiciones favorables |
| 15% (normal) | 1.00x | Neutro |
| 20% (elevada) | 0.75x | Cautela |
| 30% (crisis) | 0.50x | Minima exposicion |

**Por que funciona**: La volatilidad se agrupa (volatility clustering). Dias de alta vol son seguidos por mas dias de alta vol. Reducir exposicion cuando la vol sube evita las peores perdidas. Aumentarla cuando baja captura los mejores rallies.

**Solo en RISK_ON**: En RISK_OFF, el leverage es siempre 1.0x. En protection mode, es 0.5x (stage 1) o 1.0x (stage 2).

### 3.6 Reglas de Salida

Tres mecanismos de exit, el primero que se active:

| Mecanismo | Condicion | Proposito |
|-----------|-----------|-----------|
| **Hold time** | >= 5 dias de trading | Capturar el momentum de corto plazo, luego rotar |
| **Position stop** | Retorno <= -8% | Limitar perdida individual |
| **Trailing stop** | Subio >5%, luego cae 3% desde maximo | Proteger ganancias |

Adicionalmente:
- **Rotacion de universo**: Si una accion sale del top-40 anual, se cierra.
- **Reduccion por regimen**: Si el regimen cambia a RISK_OFF, se cierran las posiciones con peor rendimiento hasta tener max 2.

**Distribucion historica de exits**:
- Hold expirado: 87% (la mayoria de trades cumplen su ciclo normal)
- Position stop: 6.5% (corta perdedores rapido)
- Trailing stop: 5.0% (protege ganadores)
- Portfolio stop: 0.9% (eventos raros pero importantes)

### 3.7 Portfolio Stop Loss y Recovery

**Trigger**: Drawdown del portfolio >= -15% desde el peak.

**Accion inmediata**: Cerrar TODAS las posiciones. Entrar en modo proteccion.

**Recovery gradual en 2 etapas**:

| Etapa | Condicion | Max Posiciones | Leverage |
|-------|-----------|----------------|----------|
| Stage 1 | Primeros 63 dias post-stop | 2 | 0.5x |
| Stage 2 | Despues de 63 dias + regimen RISK_ON | 3 | 1.0x |
| Normal | Despues de 126 dias + regimen RISK_ON | 5 | Vol targeting |

**Requisito critico**: Cada etapa de recovery requiere que el mercado este en RISK_ON (SPY > SMA200). Si el mercado sigue en bear, el sistema NO restaura leverage aunque haya pasado el tiempo. Esto previene re-entry prematuro.

**Leccion del v6**: El v6 original requeria superar el peak historico para recuperarse, lo que era practicamente imposible despues de un crash severo (+59% necesario tras -59% DD). COMPASS usa tiempo + regimen, no niveles absolutos.

---

## 4. COSTOS Y FRICCION

| Concepto | Costo | Notas |
|----------|-------|-------|
| Margin | 6% anual sobre borrowed | Solo cuando leverage > 1.0x |
| Commission | $0.001 por accion | Realista para brokers como IBKR |
| Hedge cost | ELIMINADO | Vol targeting actua como hedge natural |
| Slippage | No modelado explicitamente | Mitigado por operar solo stocks liquidos (top-40 por dollar volume) |

**Mejora vs v6**: El v6 cargaba 2.5% anual de "hedge cost" (simulated puts). COMPASS lo elimina porque el vol targeting y el regime filter cumplen la misma funcion de proteccion, sin costo explicito.

---

## 5. PARAMETROS COMPLETOS

```
UNIVERSO
  broad_pool          = 113 stocks (S&P 500 multi-sector)
  top_n               = 40 (rotacion anual por dollar volume)
  min_age_days        = 63 (3 meses minimo de historia)

SIGNAL
  momentum_lookback   = 90 dias
  momentum_skip       = 5 dias (excluir del calculo de momentum)

REGIMEN
  regime_sma_period   = 200 dias (SPY)
  regime_confirm_days = 3 (dias consecutivos para confirmar)

POSICIONES
  num_positions       = 5 (RISK_ON)
  num_positions_off   = 2 (RISK_OFF)
  hold_days           = 5 (dias de trading)

RIESGO POR POSICION
  position_stop_loss  = -8%
  trailing_activation = +5%
  trailing_stop_pct   = -3% (desde el maximo)

RIESGO DE PORTFOLIO
  portfolio_stop_loss = -15%
  recovery_stage_1    = 63 dias + RISK_ON
  recovery_stage_2    = 126 dias + RISK_ON

LEVERAGE
  target_vol          = 15% anualizado
  leverage_min        = 0.5x
  leverage_max        = 2.0x
  vol_lookback        = 20 dias

COSTOS
  initial_capital     = $100,000
  margin_rate         = 6% anual
  commission          = $0.001/accion
```

---

## 6. FLUJO DIARIO DE OPERACION

```
CADA DIA DE TRADING:

  1. VALORAR
     - Calcular valor del portfolio (cash + posiciones a mercado)
     - Actualizar peak si hay nuevo maximo

  2. PROTECCION
     - Si en recovery: verificar si se cumplen condiciones de siguiente etapa
     - Calcular drawdown actual
     - Si drawdown <= -15%: STOP LOSS → cerrar todo, entrar Stage 1

  3. REGIMEN
     - Leer precio de SPY
     - Comparar con SMA(200)
     - Si 3+ dias consecutivos en nuevo lado: cambiar regimen

  4. CERRAR POSICIONES (en orden de prioridad)
     a. Posiciones con hold >= 5 dias → cerrar
     b. Posiciones con retorno <= -8% → cerrar (position stop)
     c. Posiciones con trailing activado y caida >= 3% → cerrar
     d. Posiciones fuera del top-40 anual → cerrar
     e. Si hay exceso de posiciones (cambio de regimen) → cerrar peores

  5. ABRIR POSICIONES (si hay slots disponibles)
     a. Calcular SCORE para cada accion elegible no en portfolio
     b. Rankear por score descendente
     c. Seleccionar top N disponibles
     d. Calcular pesos por inverse volatility
     e. Calcular leverage por vol targeting
     f. Abrir posiciones: tamano = peso x capital x leverage

  6. COSTOS
     - Deducir margin cost diario si leverage > 1.0x

  7. REGISTRAR
     - Snapshot diario: valor, cash, posiciones, drawdown, leverage, regimen
```

---

## 7. COMPORTAMIENTO EN ESCENARIOS HISTORICOS

### Dot-com crash (2000-2002)
- Stop loss activado Sep 2000 (DD -15.5%)
- Recovery en Ene 2002 (tras 63d cooldown + RISK_ON)
- Segundo stop en Abr 2002 (DD -15.2%)
- Recovery en Abr 2003
- Proteccion evito lo peor del crash, pero la recovery temprana en 2002 causo un segundo stop

### Bull market 2003-2007
- Crecimiento sostenido con leverage 1.5x-2.0x
- Un stop en Jul 2004, recovery rapida en 6 meses
- Otro stop en Jun 2006, recovery en 6 meses

### Crisis financiera 2008-2009
- Stop loss en Feb 2008 (antes del crash principal)
- RISK_OFF activo la mayor parte de 2008
- Recovery en Jun 2009 (mercado ya en modo RISK_ON)
- Evito la caida de -50%+ del mercado general

### Bull market 2010-2019
- 10 anos de crecimiento con stops menores en 2011 y 2012
- Recovery rapida en ambos casos (~6 meses)
- Leverage entre 1.5x-2.0x la mayoria del tiempo
- Portfolio crece de ~$220k a $1M+

### COVID crash Mar 2020
- Stop loss 9 Mar 2020 (DD -17.7%)
- Recovery Stage 1 en Jun 2020
- Recovery Stage 2 en Sep 2020
- El rally post-COVID con vol targeting captura retornos excepcionales
- Mejor ano: +128% en 2020-2021

### Bear market 2022
- Stop loss Ene 2022 (DD -15%)
- RISK_OFF activo gran parte del ano
- Recovery completa en May 2023

### 2024-2026
- Stop en Jul 2024, recovery en Ene 2025
- Stop en Mar 2025, recovery en Ene 2026
- Valor final: ~$4.95M

---

## 8. RIESGOS Y LIMITACIONES

### Riesgos conocidos
1. **Overfitting**: Los parametros fueron elegidos con base academica, no optimizados sobre este dataset especifico. Sin embargo, cualquier backtest tiene riesgo de overfitting. Se necesita out-of-sample testing.

2. **Momentum crash**: El momentum como factor puede sufrir "crashes" rapidos (tipicamente en recuperaciones de mercado como Mar 2009). El regime filter mitiga esto parcialmente.

3. **Costos reales**: El slippage no esta modelado explicitamente. En acciones liquidas del top-40 deberia ser minimo, pero en dias de alta volatilidad podria ser significativo.

4. **Dependencia de un indicador**: El filtro de regimen depende de SPY vs SMA200. Si el mercado cambia de estructura (por ejemplo, un bear market que nunca cruza debajo de SMA200), el filtro no protege.

5. **Max drawdown de -34.8%**: Aunque es sustancialmente mejor que v6 (-59.4%), sigue siendo significativo. Un inversor conservador podria no tolerar una caida de un tercio.

### Lo que NO hace COMPASS
- No predice el futuro
- No usa machine learning ni AI
- No opera intradayia
- No hace short selling
- No usa opciones ni derivados
- No analiza fundamentales ni noticias
- No promete retornos garantizados

---

## 9. IMPLEMENTACION TECNICA

### Archivo principal
`omnicapital_v8_compass.py` — ~875 lineas de Python

### Dependencias
- pandas, numpy (calculo)
- yfinance (datos)
- pickle (cache)

### Datos necesarios
- OHLCV diario para 113 stocks (2000-presente)
- OHLCV diario para SPY (2000-presente)
- Cache en `data_cache/`

### Outputs
- `backtests/v8_compass_daily.csv` — snapshot diario del portfolio
- `backtests/v8_compass_trades.csv` — historial de trades
- `results_v8_compass.pkl` — resultados completos serializados

### Para ejecutar
```bash
python omnicapital_v8_compass.py
```

---

## 10. REGLAS INQUEBRANTABLES

1. **NO modificar los parametros sin backtest completo**. Cada cambio debe probarse en todo el periodo 2000-2026.

2. **NO agregar complejidad**. Si una mejora no aporta al menos +1% CAGR o -5% max DD, no vale la pena.

3. **NO ignorar el regime filter**. La tentacion de operar en RISK_OFF "porque esta vez es diferente" es la causa #1 de perdidas catastroficas.

4. **NO aumentar leverage max por encima de 2.0x**. El vol targeting ya optimiza el leverage. Forzar mas es jugar con fuego.

5. **NO operar acciones fuera del top-40**. El universo esta definido por liquidez. Stocks iliquidos tienen slippage impredecible.

6. **SIEMPRE respetar los stops**. Position stop (-8%), trailing stop (-3% desde max), portfolio stop (-15%). Sin excepciones.

7. **Paper trading primero**. Minimo 3 meses de paper trading antes de capital real.

---

## 11. EVOLUCION DESDE v1

| Version | Fecha | Descripcion | CAGR | Sharpe |
|---------|-------|-------------|------|--------|
| v1 | Feb 2026 | MicroManagement intradayia | — | — |
| v4 | Feb 2026 | Optimized daily | — | — |
| v5 | Feb 2026 | 3 Day Strategy | — | — |
| v6 | Feb 2026 | Random selection, 2x leverage, -20% stop | 5.40%* | 0.22 |
| **v8 COMPASS** | **Feb 2026** | **Momentum + Regime + Vol targeting** | **16.16%** | **0.73** |

*v6 CAGR con universo corregido (sin sesgo de supervivencia). El valor original de 16.92% incluia sesgo.

---

## 12. CONCLUSION

COMPASS demuestra que reemplazar la aleatoriedad con un signal academicamente fundamentado, combinado con gestion de riesgo adaptativa, puede triplicar los retornos ajustados por riesgo.

El algoritmo no es perfecto. Tiene 11 stop loss events en 26 anos y un max drawdown de -34.8%. Pero a diferencia del v6, cada componente tiene una razon de ser:

- **Momentum**: Compra ganadores → edge positivo
- **Regime filter**: Sale en bear markets → protege capital
- **Vol targeting**: Adapta exposicion → suaviza la curva
- **Position stops**: Corta perdedores rapido → limita dano
- **Inverse vol sizing**: Equilibra riesgo → reduce volatilidad

Cinco mecanismos simples, cada uno con decadas de evidencia academica. Juntos, transforman $100k en $4.95M en 26 anos.

---

*"Don't confuse randomness with edge. COMPASS knows the difference."*
