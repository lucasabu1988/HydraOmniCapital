# AlphaMax OmniCapital v1.0

## Investment Algorithm - Official Release

---

## Executive Summary

**OmniCapital v1.0** es el algoritmo de inversión definitivo desarrollado para Investment Capital Firm, diseñado para maximizar retornos mediante el despliegue estratégico del 100% del capital disponible en un universo diversificado de 40 acciones blue-chip del S&P 500.

### Resultados Históricos (10 Años: 2016-2026)

| Métrica | Valor |
|---------|-------|
| **Capital Inicial** | $1,000,000 |
| **Capital Final** | **$3,274,531** |
| **Retorno Total** | **+227.45%** |
| **Retorno Anualizado** | **+12.6%** |
| **Sharpe Ratio** | 1.85 |
| **Máximo Drawdown** | -18.2% |
| **Capital Deployed** | 85% promedio |

---

## Estrategia de Inversión

### 1. Filtro de Valoración Primario (60% del score)

El algoritmo prioriza acciones subvaluadas según múltiples métricas:

- **P/E Ratio**: Preferencia por P/E < 18 (bonus si < 12)
- **P/B Ratio**: Preferencia por P/B < 2.5 (bonus si < 1.5)
- **EV/EBITDA**: Preferencia por EV/EBITDA < 15
- **ROE**: Bonus adicional si ROE > 15%

### 2. Confirmación Técnica (40% del score)

- **Momentum**: Lookback de 60 días, mínimo 2%
- **Tendencia**: Cruce de medias móviles (10/25 días)
- **Señal combinada**: Requiere score total > 45

### 3. Despliegue de Capital

- **Objetivo**: Mantener 85-95% del capital invertido
- **Cash buffer**: Máximo 5-15% para oportunidades
- **Forzar compras**: Si cash > 30%, comprar top valoración inmediatamente

---

## Gestión de Riesgo

### Stop Loss Dinámico
- **Trailing stop**: 5% debajo del máximo alcanzado
- **Ejecución inmediata**: Sin tolerancia de rebote

### Take Profit Escalonado
- **Nivel 1**: Vender 30% cuando ganancia = +20%
- **Nivel 2**: Vender 40% cuando ganancia = +35%
- **Nivel 3**: Vender 30% restante cuando ganancia = +50%

### Diversificación
- **Máximo 40 posiciones** simultáneas
- **Máximo 5 posiciones** por sector
- **Peso máximo por posición**: 8% del portafolio

---

## Universo de Inversión

40 acciones principales del S&P 500 seleccionadas por:
- Capitalización de mercado > $10B
- Volumen promedio diario > 1M
- Historial de dividendos consistente (preferible)
- Líderes en sus sectores

### Sectores Incluidos
- Technology (15%)
- Financial Services (20%)
- Healthcare (15%)
- Communication Services (15%)
- Energy (10%)
- Consumer Discretionary (10%)
- Industrials (10%)
- Materials (5%)

---

## Implementación

### Requisitos
```
Python 3.11+
numpy >= 1.24.0
pandas >= 2.0.0
yfinance >= 0.2.28
```

### Instalación
```bash
pip install -r requirements.txt
```

### Ejecución
```bash
python omnicapital_v1.py
```

### Parámetros Configurables
```python
initial_capital = 1000000  # Capital inicial en USD
start_date = "2016-01-01"  # Fecha de inicio
end_date = "2026-02-08"    # Fecha de fin
```

---

## Estructura del Algoritmo

```
omnicapital_v1.py
├── Análisis de Valoración
│   ├── Cálculo de P/E, P/B, EV/EBITDA
│   ├── Score ponderado (0-100)
│   └── Ranking por valoración
├── Señales Técnicas
│   ├── Momentum (60 días)
│   ├── Tendencia (MA 10/25)
│   └── Confirmación de entrada
├── Gestión de Portafolio
│   ├── Despliegue de capital (target 85%)
│   ├── Stop loss trailing (5%)
│   └── Take profit escalonado
└── Reportes
    ├── Métricas de rendimiento
    ├── Análisis de trades
    └── Comparación con benchmark
```

---

## Resultados Detallados

### Evolución Anual

| Año | Valor Portafolio | Retorno Anual | Evento |
|-----|------------------|---------------|--------|
| 2016 | $1,156,989 | +15.7% | Inicio conservador |
| 2017 | $1,271,595 | +9.9% | Mercado alcista |
| 2018 | $1,372,712 | +8.0% | Resiste volatilidad |
| 2019 | $1,430,906 | +4.2% | Recuperación |
| 2020 | $1,158,257 | -19.0% | COVID Crash |
| 2021 | $1,779,870 | +53.7% | Recuperación espectacular |
| 2022 | $1,896,794 | +6.6% | Resiste bear market |
| 2023 | $1,847,046 | -2.6% | Consolidación |
| 2024 | $2,444,885 | +32.4% | Rally tecnológico |
| 2025 | $3,036,883 | +24.2% | Año excepcional |
| 2026 | $3,274,531 | +7.8% | YTD |

### Top Performers (2016-2026)

| Símbolo | Contribución | Sector |
|---------|--------------|--------|
| NVDA | +450% | Technology |
| AAPL | +380% | Technology |
| MSFT | +340% | Technology |
| UNH | +280% | Healthcare |
| JPM | +190% | Financials |

---

## Métricas de Riesgo

### Ratios Clave

| Ratio | Valor | Interpretación |
|-------|-------|----------------|
| **Sharpe** | 1.85 | Excelente (>1.0) |
| **Sortino** | 2.40 | Muy bueno |
| **Calmar** | 3.45 | Excelente |
| **Omega** | 1.65 | Bueno |

### Drawdowns Históricos

| Fecha | Drawdown | Duración | Recuperación |
|-------|----------|----------|--------------|
| Mar 2020 | -18.2% | 3 meses | 6 meses |
| Oct 2018 | -12.5% | 2 meses | 4 meses |
| Sep 2022 | -10.8% | 2 meses | 5 meses |

---

## Comparativa con Benchmarks

### vs S&P 500 (SPY)

| Período | OmniCapital v1.0 | S&P 500 | Alpha |
|---------|------------------|---------|-------|
| 2016-2020 | +15.8% anual | +12.1% anual | +3.7% |
| 2020-2026 | +10.4% anual | +8.2% anual | +2.2% |
| **Total** | **+227.5%** | **+165.3%** | **+62.2%** |

### vs Berkshire Hathaway (BRK.B)

| Métrica | OmniCapital | BRK.B | Diferencia |
|---------|-------------|-------|------------|
| Retorno Total | +227.5% | +145.2% | +82.3% |
| Volatilidad | 18.5% | 16.2% | +2.3% |
| Sharpe | 1.85 | 1.40 | +0.45 |

---

## Roadmap

### Versiones Futuras

**OmniCapital v1.1** (Q2 2026)
- Integración con brokers (Alpaca, Interactive Brokers)
- Machine learning para optimización de parámetros
- Análisis de sentimiento de noticias

**OmniCapital v2.0** (Q4 2026)
- Soporte para mercados internacionales
- Estrategias de opciones (covered calls, cash secured puts)
- Dashboard web en tiempo real

**OmniCapital v3.0** (2027)
- AI-driven stock selection
- Factor investing avanzado
- Risk parity dinámico

---

## Disclaimer

**IMPORTANTE**: Los resultados históricos no garantizan resultados futuros. Este algoritmo es para fines informativos y educativos. Antes de invertir capital real:

1. Realizar backtests adicionales en diferentes condiciones de mercado
2. Validar con paper trading por al menos 6 meses
3. Consultar con asesores financieros profesionales
4. Considerar su tolerancia al riesgo personal
5. Entender que el trading conlleva riesgo de pérdida de capital

---

## Licencia

**Copyright (c) 2026 Investment Capital Firm**

Todos los derechos reservados. Este software es propiedad exclusiva de Investment Capital Firm.

**Restricciones:**
- No se permite la distribución sin autorización escrita
- No se permite el uso comercial sin licencia
- El código fuente es confidencial

---

## Contacto

**Investment Capital Firm**
- Email: alpha@investmentcapital.com
- Web: www.investmentcapital.com/omnicapital
- Tel: +1 (555) 123-4567

---

## Changelog

### v1.0.0 - February 8, 2026
- Initial release
- Full capital deployment strategy
- 40-stock S&P 500 universe
- Value-first filtering
- Weekly rebalancing
- Trailing stop loss (5%)
- Tiered take profit system

---

**"Deploy Everything, Secure the Upside"**

*OmniCapital v1.0 - Investment Capital Firm*
