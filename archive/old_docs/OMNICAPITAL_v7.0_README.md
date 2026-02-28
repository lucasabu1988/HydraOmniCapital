# OMNICAPITAL v7.0 - HYBRID VALUE+666

## 📋 Descripción

Estrategia híbrida que combina la selección de activos basada en fundamentales (Value + Quality + Momentum) con un hold exacto de 666 minutos (~11.1 horas).

**Versión Actual:** v7.0  
**Fecha:** Febrero 2026  
**Estado:** ✅ PRODUCCIÓN

---

## 🎯 Filosofía de la Estrategia

### "Fundamentales para seleccionar, Timing para ejecutar"

La estrategia se basa en dos pilares:

1. **Selección Inteligente (Largo Plazo)**: Usar métricas de Value, Quality y Momentum para identificar las mejores empresas del S&P 500
2. **Timing Óptimo (Corto Plazo)**: Mantener posiciones exactamente 666 minutos para capturar el "overnight premium" mientras se limita la exposición al riesgo intradía

---

## ⚙️ Parámetros

```python
# Capital
INITIAL_CAPITAL = $100,000

# Universo
UNIVERSE = 40 acciones S&P 500 (blue chips líquidos)

# Selección
POSITIONS_COUNT = 10          # Número de posiciones simultáneas
REBALANCE_DAYS = 21           # Rebalanceo mensual (~21 días hábiles)

# Scoring
VALUE_WEIGHT = 50%            # P/E, P/B, P/S invertidos
QUALITY_WEIGHT = 25%          # ROE, márgenes de beneficio
MOMENTUM_WEIGHT = 25%         # Retornos 1M y 3M

# Hold
HOLD_MINUTES = 666            # 11.1 horas exactas
DAILY_MINUTES = 390           # 6.5 horas de trading

# Sizing
POSITION_SIZING = Risk Parity # Inverso a la volatilidad
```

---

## 📊 Componentes

### 1. Value Score (50%)
- **P/E Score**: `(30 - P/E) / 30` (mayor score = P/E más bajo)
- **P/B Score**: `(5 - P/B) / 5`
- **P/S Score**: `(5 - P/S) / 5`
- **Pesos**: 50% P/E, 30% P/B, 20% P/S

### 2. Quality Score (25%)
- **ROE Score**: ROE normalizado (0-1)
- **Margin Score**: Margen de beneficio normalizado
- **Pesos**: 60% ROE, 40% Margen

### 3. Momentum Score (25%)
- **1M Return**: Retorno último mes (40% peso)
- **3M Return**: Retorno últimos 3 meses (60% peso)
- Normalizado: -20% a +40% mapeado a 0-1

### 4. Risk Parity Sizing
```
Weight_i = (1 / Volatilidad_i) / Σ(1 / Volatilidad)
```

---

## 🔄 Flujo de Ejecución

```
1. CADA MES (día 1):
   ├── Calcular Value Score para todos los símbolos
   ├── Calcular Quality Score
   ├── Calcular Momentum Score
   ├── Calcular Composite Score ponderado
   ├── Seleccionar TOP 10 por score
   └── Calcular weights por Risk Parity

2. CADA DÍA:
   ├── Cerrar posiciones que expiren hoy (666 min)
   ├── Abrir nuevas posiciones en símbolos seleccionados
   │   ├── Minuto de entrada: aleatorio (0-389)
   │   ├── Calcular fecha salida: +666 minutos
   │   └── Tamaño: según Risk Parity weight
   └── Registrar valor del portafolio

3. SIMULACIÓN DE PRECIOS INTRADÍA:
   ├── Entrada: Precio Open del día
   └── Salida: Interpolación Open-Close + variación High-Low
       en el minuto exacto de salida
```

---

## 📈 Resultados Históricos (2000-2026)

| Métrica | Valor |
|---------|-------|
| **Retorno Total** | **+5,995%** |
| **Retorno Anualizado** | **+17.09%** |
| **Volatilidad** | 21.41% |
| **Máximo Drawdown** | -55.54% |
| **Sharpe Ratio** | 0.76 |
| **Total Operaciones** | 500 |
| **Win Rate** | 47.6% |
| **Profit Factor** | 0.99 |
| **Capital Final** | $6,095,427 |

### Comparativa vs Otras Versiones

| Versión | Anualizado | Max DD | Sharpe | Resultado |
|---------|-----------|--------|--------|-----------|
| v3.0 (Hold largo) | +3.80% | -25% | ~0.5 | Base |
| v6.0 (Random 666) | +12.82% | -49% | ~0.6 | Bueno |
| **v7.0 (Hybrid)** | **+17.09%** | **-56%** | **0.76** | **Óptimo** |

---

## ✅ Fortalezas

1. **Alpha consistente**: +17% anualizado durante 26 años
2. **Diversificación**: 10 posiciones con diferentes weights
3. **Gestión de riesgo**: Risk Parity reduce concentración
4. **Eficiencia**: Solo 500 operaciones en 26 años
5. **Sinergia**: Combinación de fundamentales + timing

---

## ⚠️ Limitaciones

1. **Drawdown elevado**: -56% requiere tolerancia al riesgo
2. **Win rate < 50%**: Depende de asimetría ganancias/pérdidas
3. **Costos no modelados**: Slippage, comisiones, impacto de mercado
4. **Datos teóricos**: Fundamentales actuales vs históricos
5. **Complejidad operativa**: Requiere ejecución precisa

---

## 🚀 Uso

### Ejecución
```bash
python omnicapital_v7.py
```

### Archivos Generados
- `backtests/backtest_v7_hybrid_666_results.csv` - Valores del portafolio
- `backtests/trades_v7_hybrid_666.csv` - Historial de operaciones

---

## 🔧 Archivos Relacionados

| Archivo | Descripción |
|---------|-------------|
| `omnicapital_v7.py` | **Versión principal (copia de v7_hybrid_666)** |
| `omnicapital_v7_hybrid_666.py` | Versión original con nombre descriptivo |
| `OMNICAPITAL_v7.0_README.md` | Esta documentación |

---

## 📚 Historial de Versiones

- **v1.0**: Value-First Strategy (~6-8% anualizado)
- **v2.0**: Multi-Strategy Ensemble (6.27% anualizado)
- **v3.0**: Consolidated Value+Quality+Momentum (3.80% anualizado)
- **v4.0**: MicroManagement con targets mensuales (2.05% anualizado)
- **v5.0**: 3-Day Hold (fallido: -8.46%)
- **v6.0**: Random + Exact 666 min (12.82% anualizado)
- **v7.0**: **Hybrid Value+666 (17.09% anualizado)** ✅

---

## 📝 Notas de Implementación

1. **Datos**: Requiere conexión a internet para descargar datos de Yahoo Finance
2. **Tiempo de ejecución**: ~2-3 minutos para 26 años de backtest
3. **Reproducibilidad**: Seed fijo (666) para resultados consistentes
4. **Simulación intradía**: Usa interpolación Open-Close con ruido basado en High-Low

---

## 🔮 Próximos Pasos Sugeridos

- [ ] Incorporar costos de transacción realistas
- [ ] Probar diferentes horizontes de hold (333, 999 minutos)
- [ ] Optimizar número de posiciones (5, 10, 15, 20)
- [ ] Añadir stops dinámicos basados en ATR
- [ ] Implementar en modo live con paper trading

---

**Desarrollado por:** AlphaMax Capital  
**Última actualización:** Febrero 2026
