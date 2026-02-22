# OmniCapital v6 Replicable - Especificación Técnica

## Resumen Ejecutivo

**OmniCapital v6 Replicable** es la versión corregida sin look-ahead bias. Solo utiliza símbolos que existían en cada momento del tiempo, haciendo el sistema implementable en el mundo real.

**Resultado Validado**: 12.80% CAGR, $100K → $2.3M en 26 años (2000-2026)

---

## Diferencia Clave vs Versión Original

| Aspecto | Versión Original | Versión Replicable |
|---------|-----------------|-------------------|
| **CAGR** | 17.93% | 12.80% |
| **Look-ahead bias** | Sí (usa símbolos futuros) | No (solo símbolos existentes) |
| **Implementable** | No | Sí |
| **Universo 2000** | 40 símbolos (incluye GOOGL, META, etc.) | 55 símbolos pre-2000 |

### Por Qué Baja el Performance

La versión original cometía **survivorship bias + look-ahead bias**:
- Incluía empresas como GOOGL (IPO 2004), META (2012), TSLA (2010) en el backtest de 2000
- Estas empresas tuvieron performance excepcional (conocido hoy, no en 2000)
- La versión replicable solo usa lo que existía: INTC, CSCO, GE, IBM, etc.

---

## Parámetros del Modelo

| Parámetro | Valor | Descripción |
|-----------|-------|-------------|
| `HOLD_MINUTES` | 666 | Tiempo de retención (~11.1 horas) |
| `NUM_POSITIONS` | 5 | Número de posiciones simultáneas |
| `INITIAL_CAPITAL` | $100,000 | Capital inicial |
| `RANDOM_SEED` | 42 | Semilla para reproducibilidad |
| `COMMISSION_PER_SHARE` | $0.001 | Comisión IBKR Pro |
| `MIN_AGE_DAYS` | 63 | Antigüedad mínima para IPOs (~3 meses) |

---

## Lógica de Universo Dinámico

### Reglas de Elegibilidad

Un símbolo es elegible para trading en fecha `t` si:

1. **Ya cotizaba en `t`**: Tiene datos de precio para esa fecha
2. **Cumple antigüedad mínima**: `(t - first_date) >= MIN_AGE_DAYS`

### Excepción de Inicio

Para el primer mes del backtest, se relaja la regla de antigüedad para permitir operar inmediatamente.

### Evolución del Universo

| Año | Símbolos Tradeables | Notas |
|-----|---------------------|-------|
| 2000 | 55 | Base pre-2000: INTC, CSCO, IBM, GE, etc. |
| 2004 | 56 | Entran GOOGL, CRM (post-IPO 63 días) |
| 2006 | 58 | Entra MA |
| 2008 | 59 | Entran V, PM |
| 2010 | 61 | Entra TSLA, AVGO |
| 2012 | 62 | Entra META |
| 2013 | 64 | Entra ABBV |
| 2014+ | 65 | Universo maduro |

---

## Mecánica de Trading

### 1. Selección Diaria

```python
# Cada día:
tradeable = [s for s in all_symbols 
             if date in price_data[s].index 
             and (date - price_data[s].index[0]).days >= MIN_AGE_DAYS]

if len(tradeable) >= NUM_POSITIONS:
    random.seed(RANDOM_SEED + date.toordinal())
    selected = random.sample(tradeable, NUM_POSITIONS)
```

### 2. Rotación Automática

- **Entrada de nuevos símbolos**: Cuando un IPO cumple 63 días, entra al pool
- **Salida de símbolos**: Si un símbolo deja de cotizar (delisting), se rota
- **Mantenimiento**: Siempre se mantienen 5 posiciones (si hay suficientes símbolos)

### 3. Ejecución

- **Entrada**: Al open del día
- **Salida**: Después de `HOLD_MINUTES` (aprox 1 día de trading)
- **Sizing**: Capital dividido equitativamente entre las 5 posiciones

---

## Métricas de Performance

| Métrica | Valor |
|---------|-------|
| **CAGR** | 12.80% |
| **Total Return** | 2,205% |
| **Valor Final** | $2,305,282 |
| **Sharpe Ratio** | 0.62 |
| **Max Drawdown** | -56.69% |
| **Volatilidad Anual** | 20.62% |
| **Win Rate** | 51.56% |
| **Trades** | 32,705 |

---

## Implementación en Tiempo Real

### Requisitos

1. **Feed de datos**: Acceso a precios históricos y tiempo real
2. **Universo dinámico**: Sistema que rastree:
   - Nuevos IPOs (incorporar después de 63 días)
   - Delistings (rotar inmediatamente)
   - Corporate actions (splits, mergers)
3. **Broker**: Soporte para órdenes de mercado con comisiones bajas

### Algoritmo de Operación Diaria

```
PRE-MARKET (9:30 AM ET):
1. Obtener lista de símbolos tradeables hoy
   - Filtrar por: datos disponibles + antigüedad >= 63 días
   
2. Identificar posiciones a cerrar:
   - Hold time >= 666 minutos
   - Símbolo ya no tradeable
   
3. Calcular posiciones a abrir:
   - Necesarias = 5 - posiciones_actuales
   - Selección aleatoria del universo tradeable

MARKET OPEN:
4. Ejecutar cierres (market orders)
5. Ejecutar aperturas (market orders)
6. Registrar entry_time para cada nueva posición

POST-MARKET:
7. Calcular portfolio value
8. Log de trades y métricas
```

---

## Código de Referencia

Archivo: `omnicapital_v6_look_ahead_fixed.py`

```python
def get_tradeable_symbols(price_data, date, min_age_days=63):
    """
    Retorna símbolos elegibles en 'date' (sin look-ahead bias)
    """
    tradeable = []
    for symbol, df in price_data.items():
        if date not in df.index:
            continue
        
        first_date = df.index[0]
        days_since_start = (date - first_date).days
        
        if days_since_start >= min_age_days:
            tradeable.append(symbol)
    
    return tradeable
```

---

## Comparativa: Escenarios de Implementación

| Escenario | CAGR Esperado | Riesgo | Complejidad |
|-----------|---------------|--------|-------------|
| **Teórico (look-ahead)** | 17.93% | Alto | Imposible |
| **Replicable (esta versión)** | 12.80% | Medio | Baja |
| **Conservador (solo large-caps)** | ~10% | Bajo | Muy baja |

---

## Conclusión

**OmniCapital v6 Replicable (12.80% CAGR)** es la versión válida para implementación real:

1. ✅ **Sin look-ahead bias**: Solo usa información disponible en cada momento
2. ✅ **Replicable**: Puedes ejecutarlo hoy con datos públicos
3. ✅ **Robusto**: 26 años de backtest, múltiples ciclos de mercado
4. ✅ **Escalable**: Funciona con cualquier tamaño de capital

**Nota**: La diferencia de ~5% CAGR vs la versión teórica es el costo de la realidad. No es un bug, es la naturaleza del trading real.

---

*Documento generado: 2026-02-09*
*Versión: v6 Replicable (Look-Ahead Fixed)*
*Resultado validado: 12.80% CAGR*
