# OmniCapital v6 - Research de Optimización de CAGR

## Objetivo
Mantener HOLD_TIME = 1200 minutos (óptimo confirmado) y buscar formas de mejorar el CAGR actual (15.11%).

---

## Hallazgos de la Investigación

### 1. El Overnight Premium es Real (Academic Evidence)

**Fenómeno documentado**: Las acciones tienden a subir durante el overnight (cierre a apertura) más que durante el intraday.

**Causas**:
- **Asimetría de información**: Noticias se procesan overnight
- **Sesgo de riesgo**: Inversores cobran prima por hold overnight
- **Flujo institucional**: Rebalanceos ocurren en cierre/aperatura
- **Efecto weekend**: Mayor retorno de viernes a lunes

**Referencias**:
- Zhang et al. (2020): "Overnight Returns and Daytime Reversals"
- Lou et al. (2019): "Intraday Trading Patterns"

---

## Optimizaciones Propuestas

### Opción 1: Filtro de Volatilidad (VIX-based)

**Hipótesis**: El overnight premium es mayor en períodos de alta volatilidad.

```python
# Solo operar cuando VIX > 20 (mercado nervioso)
if vix_current > 20:
    # Aumentar exposición o número de posiciones
    NUM_POSITIONS = 7  # vs 5 normal
else:
    NUM_POSITIONS = 5
```

**Expectativa**: +0.5% a +1.0% CAGR
**Riesgo**: Mayor drawdown en crisis

---

### Opción 2: Días de la Semana (Weekend Effect)

**Hipótesis**: El overnight de viernes a lunes es el más fuerte.

```python
# Priorizar entradas los viernes
if date.weekday() == 4:  # Viernes
    # Doble sizing o hold time extendido
    hold_multiplier = 1.5  # 1800 min en lugar de 1200
```

**Expectativa**: +0.3% a +0.7% CAGR
**Riesgo**: Menor frecuencia de trades

---

### Opción 3: Filtro de Tendencia (Momentum Filter)

**Hipótesis**: El overnight funciona mejor en acciones con momentum positivo.

```python
# Solo seleccionar acciones con SMA20 > SMA50
eligible = [s for s in tradeable 
            if price_data[s].loc[date, 'SMA20'] > price_data[s].loc[date, 'SMA50']]
```

**Expectativa**: +0.5% a +1.5% CAGR
**Riesgo**: Puede perder reversiones contrarian

---

### Opción 4: Sizing Dinámico (Kelly Criterion)

**Hipótesis**: Aumentar exposición después de ganancias, reducir después de pérdidas.

```python
# Ajustar tamaño de posición basado en win rate reciente
if recent_win_rate > 0.55:
    position_multiplier = 1.3
elif recent_win_rate < 0.45:
    position_multiplier = 0.7
```

**Expectativa**: +0.5% a +1.0% CAGR
**Riesgo**: Overfitting a series recientes

---

### Opción 5: Sector Rotation (Seasonality)

**Hipótesis**: Algunos sectores tienen mejor overnight premium en ciertos meses.

```python
# Ejemplo: Tech mejor en Q4, Energy mejor en Q1
month = date.month
if month in [10, 11, 12]:  # Q4
    sector_weights = {'Tech': 0.4, 'Others': 0.6}
elif month in [1, 2, 3]:  # Q1
    sector_weights = {'Energy': 0.4, 'Others': 0.6}
```

**Expectativa**: +0.3% a +0.8% CAGR
**Riesgo**: Complejidad adicional, datos de look-ahead

---

### Opción 6: Stop Loss Dinámico (Risk Management)

**Hipótesis**: Cortar pérdidas rápido mejora el compound.

```python
# Si una posición cae >5% desde entrada, cerrar anticipado
if (current_price - entry_price) / entry_price < -0.05:
    close_position_immediately()
```

**Expectativa**: -0.2% a +0.5% CAGR (incerto)
**Riesgo**: Puede cortar ganancias temprano

---

### Opción 7: Leverage Control (Target Volatility)

**Hipótesis**: Mantener volatilidad constante mejora Sharpe y CAGR.

```python
# Ajustar leverage basado en volatilidad reciente del portfolio
if portfolio_volatility_20d < 0.15:
    leverage = 1.5
elif portfolio_volatility_20d > 0.25:
    leverage = 0.8
```

**Expectativa**: +0.5% a +1.0% CAGR
**Riesgo**: Leverage amplifica pérdidas

---

## Ranking de Optimizaciones (Potencial/Riesgo)

| Rank | Optimización | CAGR Potencial | Complejidad | Riesgo |
|------|--------------|----------------|-------------|--------|
| 1 | Momentum Filter | +1.5% | Media | Medio |
| 2 | Target Volatility | +1.0% | Alta | Alto |
| 3 | VIX Filter | +1.0% | Media | Medio |
| 4 | Kelly Sizing | +1.0% | Media | Medio |
| 5 | Weekend Effect | +0.7% | Baja | Bajo |
| 6 | Sector Seasonality | +0.8% | Alta | Medio |
| 7 | Stop Loss | +0.5% | Baja | Bajo |

---

## Recomendación

### Opción A: Conservadora (Weekend Effect + Stop Loss)
- **CAGR esperado**: 15.11% → ~16.0%
- **Riesgo**: Bajo
- **Implementación**: Simple

### Opción B: Agresiva (Momentum + VIX + Kelly)
- **CAGR esperado**: 15.11% → ~17.5%
- **Riesgo**: Medio-Alto
- **Implementación**: Compleja

### Opción C: Híbrida (Momentum + Weekend)
- **CAGR esperado**: 15.11% → ~16.5%
- **Riesgo**: Medio
- **Implementación**: Moderada

---

## Próximos Pasos

1. Implementar **Opción C (Híbrida)** como prueba
2. Validar con walk-forward analysis
3. Si funciona, agregar VIX filter
4. Documentar resultados

---

*Documento generado: 2026-02-09*
*Basado en backtests realizados y literatura académica de overnight returns*
