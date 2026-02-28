# OmniCapital v7 - Ideas de Mejora
## Conversacion Interna: El Futuro del Sistema

> *"El mejor momento para plantar un arbol fue hace 20 anos. El segundo mejor momento es ahora."*
> — Proverbio chino

---

## I. EL PARADOJA DE LA MEJORA

**Kimi-A:** v6 funciona. Pero "funciona" no es "optimo". Hay alpha dejado sobre la mesa.

**Kimi-B:** Cada optimizacion que probamos en v6 fallo. Momentum, sectores, tenure, fixed stocks. Todo degrado performance.

**Kimi-A:** Porque optimizamos dentro del paradigma. Nunca cuestionamos el paradigma.

**Kimi-B:** El paradigma es: aleatorio, 5 posiciones, 1200 min, 2:1 leverage, -20% stop.

**Kimi-A:** Exacto. ¿Y si el paradigma mismo tiene limites estructurales?

---

## II. CINCO FRONTERAS SIN EXPLORAR

### 2.1 Regimenes de Mercado Adaptativos

**Problema:** Leverage 2:1 es binario. O esta ON o OFF (durante proteccion).

**Idea:** Leverage graduado segun regimen de volatilidad:
- VIX < 15: 2.5:1 (calma, mas riesgo justificado)
- VIX 15-25: 2:1 (normal)
- VIX 25-35: 1.5:1 (turbulencia)
- VIX > 35: 1:1 (crisis) o cash

**Riesgo:** Overfitting a VIX. El regimen puede cambiar estructuralmente.

**Test:** Backtest 1990-2026 (necesitamos VIX historico desde 1990).

---

### 2.2 Microestructura: El Intradia Oculto

**Problema:** 1200 minutos es "set and forget". No sabemos QUE pasa durante esas 20 horas.

**Idea:** Micro-management no discrecional:
- Si una posicion sube >5% en las primeras 4 horas: take partial profit (25%)
- Si una posicion baja >3% en las primeras 2 horas: early exit
- Reinvertir proceeds inmediatamente en nueva posicion aleatoria

**Hipotesis:** Asimetria positiva. Ganancias rapidas = momentum continuo. Perdidas rapidas = reversión.

**Riesgo:** Aumento masivo de transacciones. Costos pueden anular beneficio.

---

### 2.3 Aleatoriedad Condicionada por Correlacion

**Problema:** 5 stocks aleatorios pueden ser 5 tech stocks altamente correlacionados.

**Idea:** Seleccion aleatoria con restriccion de correlacion:
1. Calcular matriz de correlacion 63-dias del universo
2. Seleccionar primer stock aleatorio
3. Segundo stock: aleatorio entre los que tengan correlacion < 0.7 con el primero
4. Tercer stock: correlacion < 0.7 con promedio de los dos primeros
5. Etc.

**Beneficio:** Diversificacion verdadera, no solo aparente.

**Riesgo:** Look-ahead bias si usamos correlacion futura. Complejidad operativa.

---

### 2.4 Timing del Leverage

**Problema:** Asumimos costo de margin constante. En realidad, los costos varian.

**Idea:** Optimizacion del "cuando" del leverage:
- Solo usar leverage en los primeros 15 dias del mes (efecto "turn of the month")
- Reducir leverage en dias de FOMC, NFP, earnings season
- Aumentar leverage en dias post-crash (recuperacion)

**Hipotesis:** Hay asimetrias temporales predecibles en el costo del riesgo.

**Riesgo:** Data mining. Muchos "dias especiales" son spurious.

---

### 2.5 Hold Time Variable Dinamico

**Problema:** 1200 minutos es fijo. ¿Y si el "tiempo optimo" varia?

**Idea:** Hold time adaptativo basado en momentum intradia:
- Si portfolio sube >2% antes de las 12pm: extender hold time a 1800 min (3 overnights)
- Si portfolio baja >2% antes de las 12pm: reducir hold time a 600 min (1 overnight)
- Si volatilidad intradia > 2%: reducir hold time (evitar reversión)

**Hipotesis:** Ganancias tempranas predicen momentum continuo. Perdidas tempranas predicen reversión.

**Riesgo:** Overfitting al horario de 12pm. El mercado no respeta nuestros cortes temporales.

---

## III. LA ARQUITECTURA v7: ADAPTIVE

### 3.1 Principio Central

v7 no reemplaza v6. **v7 es un meta-sistema que elige entre estrategias.**

```
OmniCapital v7 Adaptive
|
+-- Modo Conservador (v6 puro)
|   Hold: 1200min, Lev: 2:1, Stop: -20%
|
+-- Modo Agresivo (v7 experimental)
|   Hold: variable, Lev: 2.5:1, Micro-management ON
|
+-- Modo Defensivo (proteccion extendida)
|   Hold: 600min, Lev: 1:1, Cash elevado
|
+-- Selector de Modo
    Basado en: VIX, tendencia 20-dias, drawdown actual
```

### 3.2 Reglas de Transicion

| Desde | Hacia | Condicion |
|-------|-------|-----------|
| Conservador | Agresivo | VIX < 15 Y drawdown < 5% Y tendencia > 0 |
| Conservador | Defensivo | VIX > 30 O drawdown > 15% |
| Agresivo | Conservador | VIX > 20 O perdida diaria > 3% |
| Defensivo | Conservador | VIX < 20 Y recuperacion > 95% del peak |

**Frecuencia maxima de cambio:** 1 vez por semana (evitar whipsaw).

---

## IV. EXPERIMENTOS PROPUESTOS

### 4.1 Test 1: Regimen de Volatilidad

```python
# Pseudo-codigo
if vix < 15:
    leverage = 2.5
elif vix < 25:
    leverage = 2.0
elif vix < 35:
    leverage = 1.5
else:
    leverage = 1.0
```

**Periodo:** 1990-2026 (necesita VIX historico)
**Benchmark:** v6 puro
**Success criteria:** CAGR > 17% con Max DD < 40%

### 4.2 Test 2: Micro-management

```python
# Pseudo-codigo
check_interval = 60  # minutos

if position_return > 0.05 and hours_held < 4:
    sell_25_percent(position)
    
if position_return < -0.03 and hours_held < 2:
    close_position(position)
    open_new_random()
```

**Periodo:** 2000-2026
**Benchmark:** v6 puro
**Success criteria:** CAGR > 18% con turnover < 3x

### 4.3 Test 3: Correlacion Condicionada

```python
# Pseudo-codigo
def select_uncorrelated(symbols, n=5, max_corr=0.7):
    selected = [random.choice(symbols)]
    
    while len(selected) < n:
        candidates = [s for s in symbols if s not in selected]
        candidates = [s for s in candidates 
                     if all(corr(s, existing) < max_corr 
                           for existing in selected)]
        
        if not candidates:
            break
            
        selected.append(random.choice(candidates))
    
    return selected
```

**Periodo:** 2000-2026
**Benchmark:** v6 puro (aleatorio simple)
**Success criteria:** Sharpe > 0.85 con mismo CAGR

---

## V. OBJECIONES Y RESPUESTAS

### "Esto es overfitting"

**Respuesta:** Posible. Por eso cada test debe:
1. Tener justificacion teorica (no solo estadistica)
2. Usar out-of-sample testing
3. Ser validado en multiples regimenes (2000-2026 incluye 4 crisis)
4. Fallar gracefully (si no funciona, volver a v6)

### "Demasiada complejidad"

**Respuesta:** v7 es opcional. v6 sigue siendo el sistema base. v7 es un experimento controlado.

### "Los costos de transaccion"

**Respuesta:** Cada test debe incluir:
- Comisiones realistas ($0.001/share)
- Slippage (0.1% para entradas/salidas)
- Borrow cost dinamico (basado en fed funds + spread)

---

## VI. ROADMAP v7

### Fase 1: Data Engineering (2 semanas)
- [ ] Obtener VIX historico 1990-2026
- [ ] Construir matriz de correlacion rolling 63-dias
- [ ] Calcular costos de margin historicos

### Fase 2: Backtest Engine (2 semanas)
- [ ] Implementar framework de regimenes
- [ ] Implementar micro-management
- [ ] Implementar correlacion condicionada

### Fase 3: Testing (4 semanas)
- [ ] Test 1: Regimen de volatilidad
- [ ] Test 2: Micro-management
- [ ] Test 3: Correlacion condicionada
- [ ] Test 4: Combinaciones

### Fase 4: Validacion (2 semanas)
- [ ] Walk-forward analysis
- [ ] Paper trading 1 mes
- [ ] Documentacion

---

## VII. LA ULTIMA PREGUNTA

**Kimi-A:** ¿Vale la pena?

**Kimi-B:** v6 da 16.92% CAGR. Eso es excelente. Pero...

**Kimi-A:** ¿Pero?

**Kimi-B:** Pero si no exploramos, nunca sabremos si hay un v7 mejor. Y si exploramos y fallamos, confirmamos que v6 es optimo.

**Kimi-A:** Entonces exploramos.

**Kimi-B:** Entonces exploramos. Pero con disciplina. Con rigor. Con la humildad de saber que probablemente volvamos a v6.

**Kimi-A:** Esa es la actitud.

---

**Estado:** Ideas documentadas  
**Proximo paso:** Fase 1 - Data Engineering  
**Decision:** Implementar tests, pero v6 sigue siendo el sistema de produccion

*"In Simplicity We Trust... But We Verify"*
