# OMNICAPITAL v8.0 - PROPUESTAS DE MEJORA
## Análisis y Roadmap de Optimización

**Fecha:** Febrero 2026  
**Basado en:** Resultados v6.0 y v7.0 (2000-2026)

---

## 📊 DIAGNÓSTICO DEL SISTEMA ACTUAL

### Hallazgos Clave del Análisis

| Métrica | v6 Random 666 | v7 Hybrid 666 | Observación |
|---------|--------------|---------------|-------------|
| **CAGR** | 17.55% | 17.20% | v6 gana ligeramente |
| **Volatilidad** | 22.53% | 21.41% | v7 más estable |
| **Max DD** | -49.45% | -55.54% | v6 mejor en drawdown |
| **Sharpe** | 0.74 | 0.76 | v7 ligeramente mejor |
| **Win Rate** | 52.9% | 47.6% | **v6 significativamente mejor** |
| **Operaciones** | 31,599 | 500 | v6 mucho más activo |
| **Ops/Año** | 1,215 | 19 | Diferencia masiva |

### 🔍 Problemas Identificados

1. **El filtro fundamental está eliminando alpha**
   - v6 (random): 52.9% win rate
   - v7 (filtrado): 47.6% win rate
   - La selección "inteligente" está perdiendo contra la aleatoria

2. **Frecuencia de trading muy baja en v7**
   - Solo 19 operaciones/año vs 1,215 del v6
   - Menos exposición al overnight premium

3. **Drawdown severo en crisis**
   - 2008-2009: -55.54% máximo
   - 2020: -30.56%
   - 2022: -30.98%

4. **Asimetría negativa en v7**
   - Ganancia promedio: +3.20%
   - Pérdida promedio: -2.94%
   - Pero win rate < 50% = expectativa negativa por trade

---

## 🚀 PROPUESTAS DE MEJORA v8.0

### 1. SELECCIÓN DE ACTIVOS: "Smart Random"

**Problema:** La selección puramente aleatoria (v6) funciona mejor que la fundamental (v7).

**Solución:** Híbrido inteligente que combine lo mejor de ambos:

```python
# NUEVO: Smart Random Selection

def smart_random_selection(universe, data, n_positions=10):
    """
    1. Filtrar solo lo peor (evitar basura)
    2. Seleccionar aleatoriamente del resto
    """
    
    # PASO 1: Filtrado de exclusión (evitar lo peor)
    candidates = []
    for symbol in universe:
        # Excluir si:
        # - Volatilidad > 60% (demasiado riesgoso)
        # - Momentum < -30% (tendencia fuertemente bajista)
        # - Precio < $10 (problemas de liquidez)
        
        vol = calculate_volatility(symbol)
        mom = calculate_momentum(symbol)
        price = get_current_price(symbol)
        
        if vol < 0.60 and mom > -0.30 and price > 10:
            candidates.append(symbol)
    
    # PASO 2: Selección aleatoria de candidatos
    if len(candidates) >= n_positions:
        return random.sample(candidates, n_positions)
    else:
        return candidates
```

**Beneficio:** Elimina los peores activos sin sobre-optimizar la selección.

---

### 2. FRECUENCIA DE TRADING: "Continuous Entry"

**Problema:** v7 solo hace 19 ops/año vs 1,215 de v6.

**Solución:** Entrada continua diaria en lugar de mensual:

```python
# NUEVO: Continuous Entry System

# En v7 actual:
# - Rebalanceo mensual (21 días)
# - Solo 10 posiciones simultáneas
# - Resultado: ~19 trades/año

# En v8 propuesto:
# - Entrada diaria de 5 posiciones
# - Hold 666 minutos
# - Resultado esperado: ~600+ trades/año

DAILY_POSITIONS = 5      # Nuevas posiciones cada día
MAX_POSITIONS = 50       # Máximo simultáneas (diversificación)
HOLD_MINUTES = 666       # Igual
```

**Beneficio:** Mayor exposición al overnight premium sin concentración excesiva.

---

### 3. GESTIÓN DE RIESGO DINÁMICA: "Volatility Regime"

**Problema:** Drawdowns severos en 2008 (-55%), 2020 (-30%), 2022 (-31%).

**Solución:** Ajustar exposición según régimen de volatilidad:

```python
# NUEVO: Regime-Based Risk Management

def get_position_size_regime(portfolio_volatility_20d):
    """
    Ajustar sizing según volatilidad del portafolio
    """
    if portfolio_volatility_20d < 0.15:
        # Régimen tranquilo: sizing normal
        return 1.0  # 100% de sizing base
    
    elif portfolio_volatility_20d < 0.25:
        # Régimen moderado: reducir 25%
        return 0.75
    
    elif portfolio_volatility_20d < 0.35:
        # Régimen elevado: reducir 50%
        return 0.50
    
    else:
        # Régimen extremo: pausa
        return 0.0  # No nuevas posiciones

# Aplicar al sizing
base_position_size = capital * 0.20 / 10  # 2% por posición
regime_multiplier = get_position_size_regime(portfolio_vol_20d)
actual_position_size = base_position_size * regime_multiplier
```

**Beneficio:** Reducir drawdown en períodos de crisis.

---

### 4. TIMING ÓPTIMO: "Intraday Seasonality"

**Problema:** El minuto de entrada es aleatorio.

**Solución:** Usar patrones de seasonality intradía documentados:

```python
# NUEVO: Seasonality-Based Entry Timing

def get_optimal_entry_minute():
    """
    Basado en estudios de seasonality:
    - 9:30-10:00: Reversión de apertura (evitar)
    - 10:00-11:00: Momentum estable (bueno)
    - 11:00-14:00: Rango medio (neutral)
    - 14:00-15:30: Momentum afternoon (bueno)
    - 15:30-16:00: Reversión de cierre (evitar)
    """
    
    # Distribución óptima
    hour = random.choices(
        population=[0, 1, 2, 3, 4, 5, 6],  # Horas desde apertura
        weights=[5, 15, 20, 15, 20, 20, 5],  # Probabilidades
        k=1
    )[0]
    
    minute = random.randint(0, 59)
    return hour * 60 + minute  # Convertir a minutos desde apertura
```

**Distribución propuesta:**
| Horario | Peso | Razón |
|---------|------|-------|
| 9:30-10:00 | 5% | Evitar volatilidad de apertura |
| 10:00-11:00 | 15% | Buen momentum |
| 11:00-14:00 | 50% | Distribuido en rango medio |
| 14:00-15:30 | 25% | Momentum afternoon |
| 15:30-16:00 | 5% | Evitar reversión de cierre |

---

### 5. DIVERSIFICACIÓN TEMPORAL: "Multi-Horizon"

**Problema:** Solo un horizonte de hold (666 minutos).

**Solución:** Múltiples horizontes para capturar diferentes anomalías:

```python
# NUEVO: Multi-Horizon Hold System

HOLD_PERIODS = {
    'overnight': 390,      # 1 día (cierre a apertura)
    'short': 666,          # 11.1 horas (actual)
    'medium': 1332,        # 22.2 horas (~3 días)
    'long': 1998,          # 33.3 horas (~1 semana)
}

# Asignar horizonte según volatilidad del activo
def select_hold_period(symbol_volatility):
    if symbol_volatility < 0.20:
        return HOLD_PERIODS['long']     # Activos estables: hold largo
    elif symbol_volatility < 0.30:
        return HOLD_PERIODS['medium']   # Moderados: hold medio
    elif symbol_volatility < 0.40:
        return HOLD_PERIODS['short']    # Volátiles: hold corto
    else:
        return HOLD_PERIODS['overnight'] # Muy volátiles: overnight only
```

**Beneficio:** Adaptar el hold a las características del activo.

---

### 6. PROTECCIÓN DE TAIL RISK: "Correlation Hedge"

**Problema:** Correlaciones aumentan en crisis (diversificación falla).

**Solución:** Hedge automático cuando correlación del portafolio > umbral:

```python
# NUEVO: Dynamic Correlation Hedge

def calculate_portfolio_correlation(positions, data):
    """Calcular correlación promedio entre posiciones"""
    correlations = []
    for i, pos1 in enumerate(positions):
        for pos2 in positions[i+1:]:
            corr = calculate_correlation(pos1.symbol, pos2.symbol, data)
            correlations.append(corr)
    return np.mean(correlations)

def should_hedge(positions, data):
    """Determinar si se necesita hedge"""
    avg_correlation = calculate_portfolio_correlation(positions, data)
    
    if avg_correlation > 0.70:
        # Alta correlación: activar hedge
        return True
    return False

# Hedge: Comprar VIX calls o SPY puts cuando correlación > 0.70
if should_hedge(positions, data):
    hedge_size = portfolio_value * 0.02  # 2% en protección
    buy_vix_calls_or_spy_puts(hedge_size)
```

---

### 7. OPTIMIZACIÓN DE PARÁMETROS: "Walk-Forward"

**Problema:** Parámetros fijos pueden volverse obsoletos.

**Solución:** Optimización walk-forward periódica:

```python
# NUEVO: Walk-Forward Optimization

def walk_forward_optimization(data, train_window=252*3, test_window=63):
    """
    1. Entrenar en 3 años de datos
    2. Probar en siguiente trimestre
    3. Deslizar ventana y repetir
    4. Seleccionar parámetros robustos
    """
    
    parameters_to_optimize = {
        'hold_minutes': [333, 666, 999, 1332],
        'n_positions': [5, 10, 15, 20],
        'position_size': [0.02, 0.05, 0.10, 0.20],
    }
    
    results = []
    for train_start in range(0, len(data) - train_window - test_window, test_window):
        train_end = train_start + train_window
        test_end = train_end + test_window
        
        # Probar combinaciones
        best_params = grid_search(
            data[train_start:train_end],
            parameters_to_optimize
        )
        
        # Validar
        test_performance = backtest(
            data[train_end:test_end],
            best_params
        )
        
        results.append({
            'params': best_params,
            'performance': test_performance
        })
    
    # Seleccionar parámetros más consistentes
    return select_robust_parameters(results)
```

---

### 8. MACHINE LEARNING: "Ensemble Predictor"

**Problema:** Reglas fijas no capturan patrones complejos.

**Solución:** Modelo ensemble para predecir probabilidad de éxito:

```python
# NUEVO: ML-Enhanced Selection

from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier

def train_success_predictor(historical_trades):
    """
    Entrenar modelo para predecir probabilidad de trade exitoso
    """
    
    features = [
        'value_score',
        'quality_score', 
        'momentum_score',
        'volatility_20d',
        'volume_ratio',
        'sector_momentum',
        'market_regime',
        'vix_level',
        'entry_hour',
        'day_of_week',
    ]
    
    target = 'trade_profitable'  # 1 si ganó, 0 si perdió
    
    # Ensemble de modelos
    models = [
        RandomForestClassifier(n_estimators=100),
        GradientBoostingClassifier(n_estimators=100),
    ]
    
    # Entrenar
    for model in models:
        model.fit(historical_trades[features], historical_trades[target])
    
    return models

def predict_trade_success(symbol, features, models):
    """Predecir probabilidad de éxito"""
    predictions = [model.predict_proba([features])[0][1] for model in models]
    return np.mean(predictions)  # Promedio de ensemble

# Usar en selección
if predict_trade_success(symbol, features, models) > 0.55:
    # Solo operar si probabilidad > 55%
    enter_position(symbol)
```

---

## 📈 PROYECCIONES DE IMPACTO

### Escenarios de Mejora

| Mejora | Impacto Esperado | Complejidad |
|--------|-----------------|-------------|
| Smart Random | +1-2% CAGR | Baja |
| Continuous Entry | +2-3% CAGR | Media |
| Volatility Regime | -10% Max DD | Media |
| Intraday Seasonality | +0.5-1% CAGR | Baja |
| Multi-Horizon | +1-2% CAGR | Alta |
| Correlation Hedge | -15% Max DD en crisis | Alta |
| Walk-Forward | +1% CAGR, más robusto | Media |
| ML Ensemble | +2-4% CAGR | Muy Alta |

### Proyección v8.0 Consolidado

| Métrica | v7 Actual | v8 Proyectado | Mejora |
|---------|-----------|---------------|--------|
| **CAGR** | 17.20% | 22-25% | +5-8% |
| **Max DD** | -55.54% | -35-40% | +15-20% |
| **Sharpe** | 0.76 | 1.0-1.2 | +0.3-0.5 |
| **Win Rate** | 47.6% | 52-55% | +5-7% |

---

## 🎯 IMPLEMENTACIÓN RECOMENDADA

### Fase 1: Quick Wins (Inmediato)
1. ✅ Smart Random Selection
2. ✅ Continuous Entry (aumentar frecuencia)
3. ✅ Intraday Seasonality

**Tiempo:** 1 semana  
**Impacto esperado:** +3-5% CAGR

### Fase 2: Risk Management (1 mes)
4. ✅ Volatility Regime
5. ✅ Multi-Horizon Hold

**Tiempo:** 2-4 semanas  
**Impacto esperado:** -10-15% Max DD

### Fase 3: Advanced (2-3 meses)
6. ✅ Correlation Hedge
7. ✅ Walk-Forward Optimization
8. ✅ ML Ensemble

**Tiempo:** 2-3 meses  
**Impacto esperado:** +2-4% CAGR adicional

---

## 📝 CONCLUSIÓN

El sistema v7.0 tiene una base sólida (17% CAGR), pero presenta oportunidades claras de mejora:

1. **La selección fundamental está filtrando alpha** → Smart Random
2. **Frecuencia de trading muy baja** → Continuous Entry  
3. **Drawdown severo en crisis** → Volatility Regime + Correlation Hedge
4. **Parámetros fijos** → Walk-Forward Optimization

**La combinación de estas mejoras podría llevar el sistema a 22-25% CAGR con Max DD de 35-40%, resultando en un Sharpe ratio de 1.0+.**

---

*Documento preparado para discusión y priorización.*
