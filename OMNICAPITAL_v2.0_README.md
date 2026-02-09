# AlphaMax OmniCapital v2.0 - Multi-Strategy Investment Algorithm

## Overview

OmniCapital v2.0 es una evolución significativa del algoritmo original, incorporando múltiples estrategias cuantitativas basadas en investigación académica y práctica profesional.

### Nuevas Características v2.0

- **Multi-Strategy Engine**: Ensemble de 8+ estrategias cuantitativas
- **Regime Detection**: Detección automática de régimen de mercado (bull/bear/range/volatile)
- **Factor Investing**: Exposición sistemática a factores Value, Quality, Momentum, Low Volatility, Size
- **Risk Parity**: Allocación basada en contribución al riesgo
- **Trend Following**: Sistemas Turtle Trading y Donchian Channels
- **Mean Reversion**: Pairs Trading y Bollinger Bands + RSI

---

## Arquitectura del Sistema

```
omnicapital_v2_multi_strategy.py
├── MultiStrategyEngine
│   ├── Dual Momentum Strategy (Gary Antonacci)
│   ├── Relative Strength Strategy
│   ├── Factor Investing Strategy (Fama-French + Quality)
│   ├── Risk Parity Strategy
│   ├── Minimum Variance Strategy
│   ├── Turtle Trading System
│   ├── Donchian Channels
│   └── Mean Reversion (Bollinger + RSI)
├── Regime Detection
│   ├── Bull Market Detection
│   ├── Bear Market Detection
│   ├── Range-Bound Detection
│   └── Volatile Market Detection
└── Risk Management
    ├── Trailing Stop Loss (5%)
    ├── Escalonated Take Profit
    ├── Sector Exposure Limits
    └── Position Sizing
```

---

## Estrategias Implementadas

### 1. Momentum Strategies

#### Dual Momentum (Gary Antonacci)
- **Referencia**: Antonacci, G. (2014). Dual Momentum Investing
- **Lógica**: Combina momentum relativo (ranking de activos) con momentum absoluto (vs risk-free rate)
- **Señal**: BUY si momentum relativo top N Y momentum absoluto positivo
- **Parámetros**: 12M lookback, top 10 activos

#### Relative Strength
- **Referencia**: Basado en ETFs de momentum como MTUM
- **Lógica**: Ranking por relative strength vs benchmark (SPY)
- **Ponderación**: 40% 3M + 30% 6M + 30% 12M

#### Time Series Momentum (TSMOM)
- **Referencia**: Moskowitz, Grinblatt & Pedersen (2012)
- **Lógica**: Long en momentum positivo, short en momentum negativo
- **Sizing**: Volatility scaling para target de riesgo constante

### 2. Factor Investing Strategies

#### Multi-Factor Strategy
- **Referencia**: Fama-French 5-Factor + Quality
- **Factores**:
  - **Value** (25%): P/E, P/B, EV/EBITDA invertidos
  - **Quality** (25%): ROE, ROA, margen de ganancia
  - **Momentum** (25%): 12M - 1M (excluye último mes)
  - **Low Volatility** (15%): -volatilidad histórica
  - **Size** (10%): Small cap premium (negativo de log market cap)
- **Selección**: Top 20 por composite z-score

#### Quality Factor
- **Referencia**: Novy-Marx (2013)
- **Métricas**: ROE > 15%, ROA, margen > 20%, bajo D/E

### 3. Risk Parity Strategies

#### Risk Parity
- **Referencia**: Qian (2005), Maillard et al. (2010)
- **Optimización**: Igualar risk contribution de cada activo
- **Fórmula**: min Σ(RC_i - RC_target)² donde RC = w_i * (Cw)_i / σ_p

#### Minimum Variance
- **Optimización**: min w'Cw sujeto a Σw = 1, w ≥ 0
- **Resultado**: Portafolio de mínima varianza global

#### Inverse Volatility
- **Simplificación**: Asume correlaciones cero
- **Pesos**: w_i ∝ 1/σ_i

### 4. Mean Reversion Strategies

#### Pairs Trading
- **Referencia**: Gatev, Goetzmann & Rouwenhorst (2006)
- **Método**: Cointegración + z-score del spread
- **Entrada**: |z-score| > 2
- **Salida**: |z-score| < 0.5

#### Mean Reversion (Bollinger + RSI)
- **Entrada**: Precio < Lower Band AND RSI < 30
- **Salida**: Precio > Upper Band OR RSI > 70
- **Stop**: Mínimo 5 días de holding

### 5. Trend Following Strategies

#### Turtle Trading System
- **Referencia**: Dennis & Eckhardt (1983)
- **Entrada**: Breakout de 20 días
- **Salida**: Breakout de 10 días
- **Position Sizing**: 1% risk por trade, basado en ATR(20)
- **Pyramiding**: Hasta 4 unidades, +0.5N por adición

#### Donchian Channels
- **Entrada**: Breakout de máximo de 20 días
- **Filtro**: Confirmación con SMA50

#### Moving Average Trend
- **Sistema**: Triple MA (10/30/50)
- **Señal**: Cruzamiento alcista con alineación completa

---

## Regime Detection

El sistema detecta automáticamente el régimen de mercado:

| Regime | Condiciones | Estrategias Prioritarias |
|--------|-------------|-------------------------|
| **Bull** | Momentum > 5%, SMA50 > SMA200, Vol < 20% | Dual Momentum, Factor, Turtle |
| **Bear** | Momentum < -5%, SMA50 < SMA200 | Min Variance, Risk Parity, Mean Reversion |
| **Range** | Vol < 25%, sin tendencia clara | Mean Reversion, Pairs Trading |
| **Volatile** | Vol > 25% | Risk Parity, Min Variance, Inv Vol |

---

## Ensemble Methods

### 1. Voting Ensemble
- Señal generada si mayoría de estrategias concuerdan
- Mínimo 1/3 de estrategias para validar

### 2. Weighted Ensemble
- Score compuesto = Σ(direction × strength × weight)
- Umbral mínimo de |score| > 0.3

### 3. Regime-Based Ensemble (Default)
- Ajusta pesos según régimen detectado
- Ejemplo en Bull: Momentum 1.5x, Mean Reversion 0.5x

---

## Risk Management

### Position Level
- **Trailing Stop**: 5% desde máximo
- **Take Profit Escalonado**:
  - +20%: Vender 30%
  - +35%: Vender 40%
  - +50%: Vender 100%

### Portfolio Level
- **Max Positions**: 40
- **Max Sector Exposure**: 25%
- **Max Position Size**: 10%
- **Min Position Size**: 1%
- **Cash Buffer**: 5% objetivo

### Dynamic Sizing
- Tamaño proporcional a confidence de la señal
- Ajuste por volatilidad (risk parity simplificado)

---

## Uso

### Ejecución Básica
```bash
python omnicapital_v2_multi_strategy.py
```

### Configuración Avanzada
Editar `config/strategies.yaml` para ajustar:
- Pesos de estrategias
- Parámetros individuales
- Límites de riesgo
- Métodos de ensemble

### Integración con v1.0
El sistema es retrocompatible con `omnicapital_v1.py`. Las estrategias nuevas se activan automáticamente si las dependencias están disponibles.

---

## Referencias Académicas

### Momentum
1. Antonacci, G. (2014). *Dual Momentum Investing*. McGraw-Hill.
2. Moskowitz, T.J. & Grinblatt, M. (1999). "Do Industries Explain Momentum?" *JFE*.
3. Asness, C.S. (1997). "The Interaction of Value and Momentum." *JPM*.

### Factor Investing
4. Fama, E.F. & French, K.R. (1993). "Common Risk Factors in Stock Returns." *JFE*.
5. Fama, E.F. & French, K.R. (2015). "A Five-Factor Asset Pricing Model." *JFE*.
6. Novy-Marx, R. (2013). "The Other Side of Value." *JFE*.

### Risk Parity
7. Qian, E. (2005). "Risk Parity Portfolios." *Research Paper*.
8. Maillard, S., Roncalli, T., & Teïletche, J. (2010). "The Properties of Equally Weighted Risk Contribution Portfolios." *JPM*.

### Trend Following
9. Covel, M.W. (2009). *Trend Following*. FT Press.
10. Lemperiere, Y. et al. (2014). "Two Centuries of Trend Following." *JIM*.

### Mean Reversion
11. Gatev, E., Goetzmann, W.N., & Rouwenhorst, K.G. (2006). "Pairs Trading." *RFS*.
12. Poterba, J.M. & Summers, L.H. (1988). "Mean Reversion in Stock Prices." *JFE*.

---

## Changelog

### v2.0 (Feb 2026)
- ✨ Multi-Strategy Engine con 8 estrategias
- ✨ Regime Detection automático
- ✨ Factor Investing (5 factores)
- ✨ Risk Parity y Minimum Variance
- ✨ Turtle Trading System completo
- ✨ Pairs Trading con cointegración
- ✨ Ensemble methods (voting, weighted, regime-based)
- ✨ Dynamic strategy allocation

### v1.0 (Feb 2026)
- 🚀 Lanzamiento inicial
- Value-First con 100% capital deployment
- 40 posiciones max
- Trailing stops y take profit escalonado

---

## Licencia

Copyright (c) 2026 Investment Capital Firm. All Rights Reserved.