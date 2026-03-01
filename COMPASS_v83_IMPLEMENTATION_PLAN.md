# COMPASS v8.3 - Plan de Implementacion
**Fecha:** 2026-02-28
**Autor:** Project Manager OmniCapital
**Objetivo:** Superar 13.90% CAGR real con mejoras estructurales medibles

---

## RESUMEN EJECUTIVO

Cuatro cambios algoritmicos propuestos por el financial-algo-expert. Tras analisis del codigo fuente (`omnicapital_v8_compass.py`, 918 lineas) y los patches (`compass_v83_patches.py`), este plan REORDENA la prioridad del algo expert para maximizar la probabilidad de mejorar CAGR real.

**Discrepancia clave con el algo expert:** El algo expert recomienda orden 4->2->3->1 (menor a mayor riesgo estructural). Yo rechazo ese orden. El orden correcto para MAXIMIZAR CAGR es **1->2->3->4** porque:
- Cambio 1 (Smooth DD) tiene el mayor impacto estimado (+1.5% a +2.5%) y ataca la patologia principal
- Cambio 4 (Quality Filter) tiene impacto CERO con 113 stocks actuales -- hacerlo primero no mueve la aguja

---

## METRICAS DE EXITO

### Umbrales de Aceptacion Global

| Metrica | Baseline | Minimo Aceptable | Objetivo | Stretch |
|---------|----------|-------------------|----------|---------|
| CAGR real | 13.90% | 15.00% | 17.00% | 19.00% |
| MaxDD | -66.25% | -55.00% | -45.00% | -35.00% |
| Sharpe | 0.646 | 0.72 | 0.85 | 1.00 |
| Calmar | 0.21 | 0.30 | 0.40 | 0.55 |
| Stop events | 10 | <=3 | 0 | 0 |

### Criterio de Decision

- Si despues de Cambio 1+2, CAGR >= 15.5%: SEGUIR con Cambio 3
- Si despues de Cambio 1+2, CAGR < 14.5%: DETENER, investigar por que las estimaciones fallaron
- Si CUALQUIER cambio individual empeora CAGR por mas de -0.5%: REVERTIR inmediatamente

---

## ORDEN DE IMPLEMENTACION (REORDENADO POR IMPACTO)

### FASE 1: CAMBIO 1 - Smooth Drawdown Scaling [PRIORIDAD MAXIMA]

**Justificacion:** Es el cambio con mayor impacto estimado (+1.5% a +2.5% CAGR) y ataca directamente la patologia #1 del sistema: el portfolio stop binario que causa el "double hit" -- vender en el fondo + perderse el rebote. En 2022, el sistema perdio ~$665k adicionales DURANTE el "modo proteccion". Esto no es una optimizacion marginal, es una correccion de un defecto estructural.

**Que cambia en el codigo:**

1. ELIMINAR parametros (lineas 54-58 de `omnicapital_v8_compass.py`):
   - `PORTFOLIO_STOP_LOSS = -0.15`
   - `RECOVERY_STAGE_1_DAYS = 63`
   - `RECOVERY_STAGE_2_DAYS = 126`
   - `LEVERAGE_MIN = 0.3`

2. AGREGAR parametros nuevos:
   - `DD_SCALE_TIER1 = -0.05` hasta `DD_SCALE_TIER3 = -0.25`
   - `LEV_FULL = 1.0`, `LEV_MID = 0.50`, `LEV_FLOOR = 0.20`
   - `CRASH_VEL_5D = -0.06`, `CRASH_VEL_10D = -0.10`
   - `CRASH_LEVERAGE = 0.15`, `CRASH_COOLDOWN = 10`

3. AGREGAR funciones nuevas:
   - `_dd_leverage(drawdown)` -- scaling lineal por tramos
   - `compute_smooth_leverage(drawdown, portfolio_values, current_idx, crash_cooldown)` -- reemplaza toda la logica de protection mode

4. MODIFICAR `run_backtest()`:
   - Eliminar variables: `in_protection_mode`, `protection_stage`, `stop_loss_day_index`, `post_stop_base`
   - Agregar variable: `crash_cooldown = 0`
   - Eliminar BLOQUE completo "Check recovery from protection mode" (lineas 497-513)
   - Eliminar BLOQUE completo "Portfolio stop loss" (lineas 519-549)
   - Reemplazar BLOQUE "Determine max positions and leverage" (lineas 561-573)
   - Actualizar snapshot diario: `in_protection` ya no existe como booleano

**Zonas de codigo afectadas en `run_backtest()`:**
- Lineas 466-469: Variables de estado (eliminar 4, agregar 1)
- Lineas 491-513: Recovery check (eliminar completo)
- Lineas 519-549: Portfolio stop (eliminar completo)
- Lineas 561-573: Max positions / leverage (reescribir)
- Linea 706: Snapshot `in_protection` (cambiar semantica)

**Criterios de aceptacion:**
- [ ] stop_events == 0 (no mas portfolio stops)
- [ ] MaxDD mejora a < -55% (elimina double-hit)
- [ ] CAGR >= 14.5% (mejora minima esperada de +0.6%)
- [ ] No hay periodos prolongados de leverage < 0.3 (verificar con log diario)
- [ ] El equity curve de 2022 NO muestra la caida durante proteccion

**Riesgos:**
1. **MaxDD individual puede ser mayor:** Sin techo duro de -15%, un episodio puede caer a -30% antes de que el scaling reaccione. MITIGACION: El crash velocity circuit breaker cubre crashes rapidos.
2. **Regresion en anos sin stops:** Si el sistema nunca disparo stop en un periodo (ej: 2010-2019), el cambio no deberia impactar. Verificar que CAGR de esos anos sea identico.
3. **Bug en indexing de portfolio_values:** `compute_smooth_leverage` usa `portfolio_values[current_idx]` pero la lista se construye incrementalmente. Verificar que `current_idx` corresponde al indice correcto.

**Rollback:** Revertir a v8.2 (`omnicapital_v8_compass.py` sin cambios). Git tag antes de empezar.

**Tiempo estimado:** 4-6 horas (incluye implementacion + backtest + analisis de resultados)

---

### FASE 2: CAMBIO 2 - Regime Filter Continuo (Sigmoid) [PRIORIDAD ALTA]

**Justificacion:** Segundo mayor impacto estimado (+0.8% a +1.5% CAGR). El regime binario SPY > SMA200 causa transiciones bruscas 5->2 posiciones en el peor momento. La sigmoid suaviza la transicion a 5->4->3->2.

**Dependencia con Fase 1:** INDEPENDIENTE. Puede implementarse antes o despues. Sin embargo, la combinacion es sinergica: el regime continuo decide cuantas posiciones, el smooth DD decide cuanto leverage. Sin Cambio 1, el regime continuo sigue sujeto al portfolio stop binario que puede sobrescribir max_positions.

**Que cambia en el codigo:**

1. ELIMINAR funcion: `compute_regime()` (lineas 255-291)
2. AGREGAR funciones:
   - `_sigmoid(x, k=15.0)` -- funcion logistica
   - `compute_regime_score(spy_data, date)` -- score continuo [0,1]
   - `regime_score_to_positions(regime_score)` -- score -> 5/4/3/2 posiciones

3. MODIFICAR `run_backtest()`:
   - Eliminar: `regime = compute_regime(spy_data)` (linea 453)
   - Reemplazar bloque "Regime" (lineas 552-558): calcular `regime_score` por dia
   - Reemplazar asignacion de `max_positions` (lineas 561-573): usar `regime_score_to_positions()`

**Zonas de codigo afectadas:**
- Linea 453: Eliminacion de pre-computo regime
- Lineas 552-558: Calculo de regime por dia (reescribir)
- Lineas 561-573: Asignacion de max_positions (reescribir, ya modificado por Fase 1)

**Nota de integracion con Fase 1:** Si Fase 1 ya esta implementada, el bloque de lineas 561-573 ya no existe como estaba. La integracion es:
```python
regime_score = compute_regime_score(spy_data, date)
is_risk_on = regime_score >= 0.50
max_positions = regime_score_to_positions(regime_score)
# current_leverage ya viene de compute_smooth_leverage (Fase 1)
```

**Criterios de aceptacion:**
- [ ] Numero de transiciones risk_on<->risk_off DISMINUYE (menos whipsaw)
- [ ] CAGR acumulado (Fase1+2) >= 15.5%
- [ ] El score < 0.35 corresponde a recesiones conocidas (2001, 2008, 2020, 2022)
- [ ] No hay dias con 0 posiciones (siempre >= 2)

**Riesgos:**
1. **Performance hit por calculo diario:** `compute_regime_score()` calcula SMA200, SMA50, vol percentile CADA DIA. Con 6500+ dias de backtest, esto puede ser lento. MITIGACION: Cada calculo es O(1) en series ya cargadas, no es un loop sobre stocks.
2. **Lag del score vs el binario:** Si el score sigmoid reacciona MAS LENTO que el binario original en un crash, podria empeorar. MITIGACION: El componente de 20d momentum (33% del trend) y el vol percentile (40% total) reaccionan mucho mas rapido que la SMA200.

**Rollback:** Restaurar `compute_regime()` y el bloque original de max_positions.

**Tiempo estimado:** 3-4 horas

---

### FASE 3: CAMBIO 3 - Exit Renewal para Ganadores [PRIORIDAD MEDIA]

**Justificacion:** Impacto estimado +1.0% a +2.0% CAGR. Ataca la patologia #3: el 90.5% de exits son por tiempo (5 dias), cerrando ganadores prematuramente. La renovacion permite que ganadores con momentum corran hasta 15 dias.

**DEPENDENCIA CRITICA CON FASE 1:** El algo expert advierte explicitamente: "La interaccion entre Cambio 1 + Cambio 3 puede crear posiciones retenidas durante drawdowns." Esto es porque:
- Cambio 1 reduce leverage pero NO cierra posiciones
- Cambio 3 extiende posiciones ganadoras
- Escenario peligroso: posicion entra ganadora (+3%), se renueva, luego el mercado colapsa. El smooth DD reduce leverage pero la posicion sigue abierta y puede convertirse en perdedora antes de que el stop de -8% la cierre.

**MITIGACION de la interaccion:** La posicion renovada MANTIENE el trailing stop (-3% desde max) y el position stop (-8%). Ademas, el hard cap de 15 dias limita la exposicion. El riesgo es real pero acotado.

**Que cambia en el codigo:**

1. AGREGAR parametros:
   - `HOLD_DAYS_MAX = 15`
   - `RENEWAL_PROFIT_MIN = 0.02`
   - `MOMENTUM_RENEWAL_THRESHOLD = 0.70`

2. AGREGAR funcion:
   - `should_renew_position(symbol, pos, current_price, days_held, scores)` -- decision de renovacion

3. RESTRUCTURAR `run_backtest()` -- EL CAMBIO MAS INVASIVO:
   - MOVER calculo de scores ANTES del loop de exits (actualmente esta DESPUES, en linea 653)
   - En el loop de exits, ANTES de `hold_expired`, verificar renovacion
   - En el bloque de nuevas posiciones, REUSAR scores (no recalcular)

**Zonas de codigo afectadas:**
- Lineas 589-646: Loop de exits (modificar logica de hold_expired)
- Lineas 648-696: Bloque de nuevas posiciones (mover calculo de scores arriba)
- Estructura del loop: REORDENAR para que scores se calculen una sola vez

**ADVERTENCIA:** Este es el cambio con MAYOR RIESGO DE OVERFITTING. Los parametros HOLD_DAYS_MAX=15, RENEWAL_PROFIT_MIN=0.02, MOMENTUM_RENEWAL_THRESHOLD=0.70 son valores elegidos por el algo expert sin validacion out-of-sample. Con solo 26 anos de datos y renovaciones relativamente raras, el riesgo de ajustar al in-sample es alto.

**Criterios de aceptacion:**
- [ ] Win rate mejora >= 2 puntos porcentuales
- [ ] Avg winning trade mejora >= 15%
- [ ] Hold promedio de ganadores >= 6.5 dias (vs 5.0 actual)
- [ ] Ninguna posicion excede 15 dias
- [ ] CAGR acumulado (Fase1+2+3) >= 16.5%
- [ ] MaxDD no empeora respecto a Fase1+2

**Riesgos:**
1. **Overfitting:** Parametros calibrados en-sample. MITIGACION: Validar split 2000-2015 / 2016-2026.
2. **Zombie positions:** Posiciones renovadas multiples veces. MITIGACION: Hard cap 15 dias.
3. **Interaccion con DD scaling:** Posiciones renovadas durante drawdown. MITIGACION: Stops siguen activos.

**Rollback:** Restaurar exit_reason = 'hold_expired' sin check de renovacion.

**Tiempo estimado:** 4-5 horas (incluye restructuracion del loop)

---

### FASE 4: CAMBIO 4 - Quality Filter [PRIORIDAD BAJA]

**Justificacion:** Impacto NULO con 113 stocks actuales. Solo relevante si se expande a 744 stocks historicas. Se implementa al final porque no mueve CAGR con el pool actual.

**Por que lo incluyo:** Es de bajo riesgo, bajo esfuerzo, y prepara el sistema para la expansion futura del universo. Ademas, el fallback de seguridad (si < 5 stocks pasan, usar lista completa) hace que no pueda empeorar las cosas.

**Que cambia en el codigo:**

1. AGREGAR parametros:
   - `QUALITY_VOL_MAX = 0.60`
   - `QUALITY_VOL_LOOKBACK = 63`
   - `QUALITY_MAX_SINGLE_DAY = 0.50`

2. AGREGAR funcion:
   - `compute_quality_filter(price_data, tradeable, date)` -- filtrar stocks high-vol

3. MODIFICAR `run_backtest()`:
   - Insertar filtro ANTES de `compute_momentum_scores()` (o del calculo unificado de scores post-Fase 3)

**Criterios de aceptacion:**
- [ ] Con 113 stocks: CAGR identico a Fase3 (+/- 0.05%)
- [ ] No hay dias con < 5 stocks en el pool filtrado
- [ ] Log muestra 0 stocks excluidos (con pool actual)

**Riesgos:** Minimos. El fallback garantiza que el filtro no puede dejar al sistema sin stocks.

**Rollback:** Eliminar la linea de quality_filter.

**Tiempo estimado:** 1-2 horas

---

## MAPA DE DEPENDENCIAS

```
Fase 4 (Quality) -----> INDEPENDIENTE (puede ir en cualquier orden)
                          |
Fase 1 (Smooth DD) ----> INDEPENDIENTE de Fase 2
                          |
Fase 2 (Regime) -------> INDEPENDIENTE de Fase 1 (pero sinergico)
                          |
                          v
Fase 3 (Exit Renewal) -> DEPENDE de Fase 1 estar estable
                          (interaccion DD + hold extendido)
```

**Dependencias criticas:**
- Fase 3 DEBE testearse DESPUES de Fase 1 porque la interaccion es no trivial
- Fase 1 y Fase 2 son independientes y PUEDEN implementarse en paralelo (pero recomiendo secuencial para aislar el impacto de cada uno)
- Fase 4 es independiente de todo

---

## CONFLICTOS IDENTIFICADOS EN EL CODIGO

### Conflicto 1: Bloque de max_positions (lineas 561-573)
- Fase 1 necesita reescribirlo (eliminar protection_stage logic)
- Fase 2 necesita reescribirlo (eliminar is_risk_on binary)
- SOLUCION: Implementar ambos juntos en ese bloque. Codigo final:
```python
# Post Fase 1+2:
regime_score = compute_regime_score(spy_data, date)
max_positions = regime_score_to_positions(regime_score)
# leverage ya viene de compute_smooth_leverage()
```

### Conflicto 2: Ubicacion del calculo de scores
- Actualmente: linea 653 (dentro de "open new positions")
- Fase 3 necesita: ANTES del loop de exits (linea ~589)
- SOLUCION: Mover calculo arriba, reusar en exits Y en apertura

### Conflicto 3: Variable `in_protection` en snapshot diario
- Fase 1 elimina `in_protection_mode`
- El snapshot (linea 706) referencia `in_protection: in_protection_mode`
- `calculate_metrics()` (linea 768) usa `df['in_protection'].sum()`
- SOLUCION: Reemplazar con `dd_leverage < LEV_FULL` como indicador de "reduccion activa"

### Conflicto 4: `compute_dynamic_leverage()` usa LEVERAGE_MIN
- Linea 405: `return max(LEVERAGE_MIN, min(LEVERAGE_MAX, leverage))`
- Fase 1 elimina LEVERAGE_MIN y lo reemplaza con LEV_FLOOR
- SOLUCION: Cambiar referencia a LEV_FLOOR o mantener LEVERAGE_MIN como alias

---

## TIMELINE

| Dia | Actividad | Entregable |
|-----|-----------|------------|
| D1 (AM) | Tag v8.2 baseline. Implementar Fase 1 (Smooth DD) | omnicapital_v83_phase1.py |
| D1 (PM) | Ejecutar backtest Fase 1. Analizar resultados | Reporte Fase 1 con metricas |
| D2 (AM) | Si Fase 1 pasa: Implementar Fase 2 (Regime) | omnicapital_v83_phase2.py |
| D2 (PM) | Ejecutar backtest Fase 1+2. Analizar resultados | Reporte Fase 1+2 |
| D3 (AM) | Si Fase 1+2 pasa: Implementar Fase 3 (Exit Renewal) | omnicapital_v83_phase3.py |
| D3 (PM) | Ejecutar backtest Fase 1+2+3. Analizar interaccion | Reporte completo |
| D4 (AM) | Implementar Fase 4 (Quality). Backtest final | omnicapital_v83_final.py |
| D4 (PM) | Validacion OOS split. Documento final | COMPASS_v83_RESULTS.md |

**Total:** 4 dias de trabajo

---

## PLAN DE CONTINGENCIA

### Si Cambio 1 EMPEORA las cosas (CAGR < 13.5%):
1. Verificar que el crash velocity circuit breaker esta funcionando
2. Probar con LEV_FLOOR = 0.30 en vez de 0.20 (mas conservador)
3. Si sigue peor: REVERTIR y pasar directamente a Cambio 2+3

### Si Cambio 1+2 no supera 15% CAGR:
1. Evaluar si el regime score tiene lag mayor que el binario
2. Probar k=20 o k=25 en la sigmoid (mas agresivo)
3. Ajustar thresholds de posiciones: 0.60/0.45/0.30 en vez de 0.65/0.50/0.35

### Si Cambio 3 empeora MaxDD significativamente:
1. Reducir HOLD_DAYS_MAX de 15 a 10
2. Aumentar RENEWAL_PROFIT_MIN de 2% a 4%
3. Endurecer MOMENTUM_RENEWAL_THRESHOLD de 0.70 a 0.85

### Si TODO falla (ningun cambio mejora CAGR):
Propuestas alternativas (no incluidas en los 4 cambios):
1. **Reducir HOLD_DAYS de 5 a 3:** El 90% de exits son por tiempo. Si los ganadores se identifican correctamente, 3 dias capturan la mayor parte del retorno con menos riesgo.
2. **Expandir universe de 40 a 60:** Mas candidatos = mejor seleccion, menor concentracion sectorial.
3. **Stop loss de -8% a -6% con trailing de 3% a 4%:** Mas rapido en cortar perdedores, mas espacio para ganadores.

---

## INSTRUCCIONES PARA EL IMPLEMENTADOR (financial-algo-expert)

1. **ANTES de tocar codigo:** Crear tag git `v8.2-baseline` o copia de seguridad
2. **UNA FASE A LA VEZ:** No combinar fases hasta que cada una pase individualmente
3. **BACKTEST COMPLETO:** Cada fase requiere backtest de 26 anos. Sin shortcuts.
4. **REPORTAR estas metricas despues de cada fase:**
   - CAGR, MaxDD, Sharpe, Calmar, Sortino
   - Numero de stop events
   - Exit reason breakdown
   - Peor ano y mejor ano
   - Equity curve 2022 (caso de prueba principal)
5. **El Cambio 1 modifica el snapshot diario.** Asegurar que `calculate_metrics()` siga funcionando. La variable `in_protection` necesita un sustituto.
6. **El Cambio 3 requiere MOVER codigo.** El calculo de scores debe subir de linea 653 a antes de linea 589. Esto es un refactoring no trivial.
7. **GUARDAR cada version intermedia** como archivo separado para poder comparar.

---

## VERIFICACION DE COMPLETITUD

- [x] Los 4 cambios tienen codigo completo en compass_v83_patches.py
- [x] Cada cambio tiene instrucciones de integracion detalladas
- [x] Las funciones de patches tienen tests de verificacion (verify_patches_compatible)
- [x] Los conflictos entre fases estan identificados y resueltos
- [x] Los criterios de aceptacion son medibles y especificos
- [x] Hay plan de rollback para cada fase
- [x] Hay plan de contingencia si todo falla
- [ ] FALTA: Ejecucion real de los backtests
- [ ] FALTA: Validacion out-of-sample (2000-2015 / 2016-2026)

---

**La meta es clara: superar 13.90% CAGR real. El camino mas probable pasa por eliminar el double-hit del portfolio stop (Cambio 1) y suavizar las transiciones de regime (Cambio 2). Los Cambios 3 y 4 son mejoras incrementales.**
