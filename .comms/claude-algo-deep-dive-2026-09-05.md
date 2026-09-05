# HYDRA v8.4 — Análisis profundo del algoritmo

**Autor:** Claude (architect) · **Fecha:** 2026-09-05
**Alcance:** `hydra_screener_local/core/` + `config.py` contra `HYDRA_ALGORITHM_SPEC.md` v1.2
**Estado del algoritmo:** LOCKED. Nada de esto se aplicó. Los cambios de scoring necesitan OK de Lucas (regla 6).

---

## 0. Resumen ejecutivo

Tres bugs de correctitud confirmados en ejecución, dos hallazgos estructurales que cambian
cómo hay que entender el sistema, y —el resultado más importante— **ninguna variante de
parámetros del algoritmo produce una mejora estadísticamente significativa** en la muestra
disponible.

| # | Hallazgo | Tipo | Evidencia |
|---|---|---|---|
| B1 | El watchdog de volumen (TASK-202) nunca dispara | Bug | lee `0.0` siempre |
| B2 | 2 ficheros de test dan verde sin ejecutar una sola aserción | Bug | `pytest` → 2 fallos reales |
| B3 | El régimen que se imprime y se guarda ≠ el que decide | Bug | 0.793 vs 0.693 |
| S1 | La Meta-Layer no altera el ranking. En absoluto. | Estructural | Spearman = 1.000 |
| S2 | El control sectorial penaliza al 87% del universo | Estructural | 435/498 nombres |
| S3 | El gate de régimen es casi inerte (91.5% expuesto) | Estructural | −7.6 bp/ciclo, p=0.275 |
| A1 | Quitar el vol-scaling "dobla" el retorno… por beta, no por alfa | Análisis | IC95% [−4.4, +33.5] bp |

La conclusión práctica: **el trabajo de mayor valor no es tocar el algoritmo, es arreglar los
bugs y decidir qué hacer con dos piezas que no hacen lo que su documentación dice que hacen.**

---

## 1. Metodología

Motor point-in-time propio (`experiments/backtest_variant_sweep.py`), validado contra el
código real antes de usarlo:

```
universo después de filtros : 500 | scoreados réplica 498 | real 498
dynamic_count               : réplica 22 | real 22
top-50 orden idéntico       : True
recommended set equal       : True (19 vs 19)
```

- **Datos:** 503 constituyentes actuales del S&P 500, 2020-01-02 → 2026-09-04 (1678 días).
- **Protocolo:** rebalanceo cada 5 días hábiles, hold 5 días, equal weight sobre el set
  `recommended`. 283 ciclos. Entrada con lag de 1 día (el cierre de la señal no es ejecutable).
- **Benchmarks:** universo equal-weight y SPY sobre las mismas fechas.

### Sesgos que hay que tener presentes al leer los números

1. **Supervivencia.** Uso los constituyentes *actuales* del S&P 500 sobre 2020-2026. Los que
   quebraron o fueron expulsados no están. Esto infla todos los resultados de momentum, y más
   cuanto más concentrada o más alta-volatilidad sea la variante.
2. **Un solo régimen macro.** 2020-2026 es mayormente un bull de tecnología. No hay evidencia
   sobre 2000-2002 ni 2008.
3. **Universo distinto al de producción.** Producción corre `UNIVERSE="all"` (~2500-3000,
   con small caps). Aquí son 500 large caps. El efecto S2 es *peor* en producción, no mejor.
4. **Los umbrales que se ven mejor se eligieron mirando estos mismos datos.** Eso no es
   validación, es selección.

---

## 2. Bugs de correctitud (no tocan el scoring)

### B1 — El watchdog de volumen de TASK-202 nunca dispara

`core/signals.py:231-232` calcula `vol_ratio_nan_share` y lo mete como columna. El contrato
de salida (`final_df = df[[...]]`, línea ~300) **no la incluye**. Entonces
`screener.py:80` hace `candidates.iloc[0].get("vol_ratio_nan_share", 0.0)` y siempre recibe
el default:

```
'vol_ratio_nan_share' en el DF que devuelve el screener: False
lo que lee screener.py:80  -> 0.0
share real de vol_ratio NaN -> 0.0000   (coincide por casualidad: hoy no faltan datos)
```

Consecuencias: el aviso de "cobertura degradada del strict filter" no puede dispararse nunca,
y `history.py` guarda `vol_ratio_nan_share=0.0` todos los días. Si Yahoo deja de devolver
volumen para media cartera, el strict filter se apaga en silencio y nada avisa.

**Fix:** añadir `vol_ratio_nan_share` al contrato de salida (SPEC §7) y a la lista de renombrado.

### B2 — Dos ficheros de test dan verde sin ejecutar nada

`run_all_tests.py` ejecuta cada test como script (`python test_x.py`). `test_volume_watchdog.py`
y `test_universe_robustness.py` están escritos en estilo pytest y **no tienen bloque
`if __name__ == "__main__"`**. Ejecutados como script no hacen nada, salen 0, y el runner los
reporta `[PASS]`.

```
$ python test_volume_watchdog.py ; echo $?     ->  0        (verde falso)
$ python -m pytest test_volume_watchdog.py -q  ->  2 failed, 1 passed
```

Los 2 fallos reales son exactamente B1. Es decir: **existía un test correcto que detectaba el
bug, y la infraestructura lo silenciaba.** Esto también explica cómo B1 pasó la revisión de
TASK-202.

**Fix:** que el runner detecte ficheros sin `__main__` y los ejecute con pytest — o falle
explícitamente en vez de asumir que "exit 0 = pasó".

### B3 — El régimen que se reporta no es el que decide

`screener.py:77` llama a `compute_regime_score(spy)` (fórmula simple: `0.7*trend + 0.3*mom20`)
y ese número es el que se imprime en el resumen y el que va a `save_daily_run(regime_score=...)`.
Pero el scoring usa `compute_rich_regime_scores` (5 sub-scores ponderados 30/25/20/15/10).

```
compute_regime_score      (se imprime y se guarda) : 0.793
compute_rich_regime_scores (realmente decide)      : 0.693
```

0.100 de diferencia, y cae a caballo de los umbrales de `regime_type` (STRONG ≥ 0.62,
MODERATE ≥ 0.50). El historial queda etiquetado con un régimen que no es el que generó las
señales, así que `analyze_history.py` y el win-rate por régimen están correlacionando
resultados contra la variable equivocada.

**Fix:** reportar y persistir `candidates['regime'].iloc[0]` (el rich, que ya viaja en el
contrato de salida) y dejar `compute_regime_score` solo como helper legacy — o borrarla.

### B4-B7 — Menores

- **B4:** `MOMENTUM_SKIP = 5` se importa en `signals.py:21` y no se usa en ningún sitio.
  No es solo un import muerto: `CLAUDE.md` documenta los parámetros de v8.4 como
  *"Momentum: 90d lookback, **5d skip**, 5d hold"*. El screener local heredó la constante
  y dejó de aplicar el skip, así que **diverge del algoritmo que dice implementar**.
  Medido: aplicar el skip da +3.8 bp/ciclo (p=0.433, no significativo) pero mejora el
  maxDD de −21.7% a −17.2%. Decisión de Lucas: o se aplica el skip (cambio de scoring,
  regla 6) o se documenta explícitamente que el screener local es 90d sin skip a propósito.
- **B5:** `prices.pct_change()` sin `fill_method` → `FutureWarning`; pandas 3.0 cambia el
  default. Medido en esta muestra: 5 tickers con huecos interiores, distorsión de volatilidad
  < 0.01%. Hoy es inocuo; es deuda de mantenimiento, no un problema de señal.
- **B6:** `dynamic_vol_threshold` se calcula dos veces, idéntico, en `generate_daily_candidates`.
- **B7:** deriva spec↔código en el breadth. SPEC §4.3 dice
  `0.4*sma50 + 0.6*sma200`; el código hace `0.3*pct_positive + 0.3*sma50 + 0.4*sma200`.
  El `pct_positive` es de 1 día e inyecta ruido diario en el régimen. **Decisión de Lucas:**
  alinear el código al spec cambia scoring (regla 6); alinear el spec al código no. El header
  del spec dice que la fuente de verdad es el código, así que por defecto: actualizar el spec.

---

## 3. Hallazgos estructurales

### S1 — La Meta-Layer no cambia el ranking. En absoluto.

Esta es la más importante del informe.

`meta_score = momentum × overall_aggression × pillar_factor`. Ambos factores son **el mismo
escalar positivo para todos los tickers** de ese día. Después,
`composite = meta_score × (1 + short_boost × 0.35)`. Ordenar por `composite` es idéntico a
ordenar por `momentum × (1 + short_boost × 0.35)`: el escalar global se cancela.

Verificado sobre los cuatro regímenes:

```
STRONG_BROAD  aggr=1.166 compass=1.357   ranking idéntico
MODERATE      aggr=1.040 compass=1.050   ranking idéntico
CAUTIOUS      aggr=0.930 compass=0.880   ranking idéntico
WEAK_CRISIS   aggr=0.612 compass=0.600   ranking idéntico
Spearman(meta_score STRONG, meta_score WEAK) = 1.000000
```

Las ~230 líneas de Meta-Layer —4 pilares, 4 special modes, biases por régimen, clamps—
afectan exactamente a **dos cosas**: el entero `dynamic_count ∈ [6,28]` y el flag booleano
`regime_score >= 0.2975`. `Rattlesnake`, `Catalyst` y `EFA` no tocan el ranking en ningún
camino de código: `bias_rattlesnake` entra en `pillar_factor`, que es global.

Dicho de otra forma: el sistema declara "en régimen WEAK favorecer mean-reversion" y a
continuación rankea por momentum puro, exactamente igual que en STRONG. La única diferencia
es que recomienda menos nombres.

Esto no es necesariamente malo — es una forma legítima de gestionar riesgo por tamaño de
cartera. Pero la documentación, el dashboard y el spec describen un mecanismo de tilt de
estilo que no existe. **Hay que elegir: o se hace transversal, o se documenta honestamente
como un controlador del número de posiciones.**

Probé la primera opción (§4.5). No mejora.

### S2 — El control sectorial penaliza al 87% del universo

`SECTOR_BUCKETS` mapea **80 tickers**. `UNIVERSE="all"` trae ~2500-3000. Todo lo no mapeado
cae en `"Other"`, y `MAX_PER_SECTOR=8` penaliza un 15% a todo lo que rankee > 8 *dentro de su
bucket*. Como `"Other"` es prácticamente el universo entero, el resultado medido sobre S&P 500:

```
[SECTOR CONTROL] Penalizados 435 nombres por sobre-concentración (>8 por bucket)
                 (435 de 498 = 87%)
```

Lo que el docstring llama "control de concentración" funciona en la práctica como **un
descuento del 15% a todo lo que no esté en una lista hardcodeada de 80 nombres**, dejando
pasar a full score solo a los 8 mejores del resto. Es casi lo contrario de diversificar: privilegia
sistemáticamente a las mega caps mapeadas.

En backtest cuesta poco (quitarlo: +1.9 bp/ciclo; exentar `"Other"`: +2.2 bp; ninguno
significativo), así que **no es un problema de rendimiento sino de que el sistema no hace lo
que dice hacer** — y en el universo de producción de 3000 nombres el efecto es más extremo
que aquí.

**Opciones:** (a) sectores reales cacheados (`yfinance` `sector`/`industry`, un fetch diario),
(b) exentar `"Other"` del cap, (c) quitarlo. (a) es la única que cumple la intención original.

### S3 — El gate de régimen es casi inerte

```
variante                       exposición  bp/ciclo   ann%   Sharpe  maxDD
sin gate (siempre invertido)      100.0%      51.3    26.30   1.17   -19.4
thr 0.2975 (PRODUCCIÓN)            91.5%      43.7    21.97   1.07   -18.8
thr 0.35                           89.4%      44.1    22.35   1.10   -18.8
thr 0.45                           85.5%      43.1    21.83   1.10   -18.8
thr 0.55                           78.4%      45.1    23.29   1.21   -15.6

gate producción vs sin gate: -7.6 bp/ciclo (t=-1.09, p=0.275)
```

Con el umbral de producción el sistema está invertido el 91.5% de los ciclos, cuesta 7.6 bp
por ciclo (no significativo) y baja el maxDD apenas 0.6 puntos. Y los ciclos en los que se
quedó fuera fueron, en promedio, **mejores** que aquellos en los que estuvo dentro:

```
SPY en los ciclos FUERA : +0.617%/ciclo  (n=24)
SPY en los ciclos DENTRO: +0.274%/ciclo  (n=259)
```

n=24 es poco para condenarlo, pero desde luego no hay evidencia de que aporte timing.

Dato colateral con más sustancia: **el régimen CAUTIOUS es donde el sistema pierde dinero**
(−77.2 bp/ciclo, n=19), mientras WEAK es levemente positivo (+12.1 bp, n=34). El gate actual
(0.2975) no excluye CAUTIOUS (0.38-0.50) en absoluto. Eso explica por qué `thr 0.55` sale
mejor en Sharpe y maxDD. Es una hipótesis con n=19 detrás: **vale la pena testearla fuera de
muestra, no aplicarla.**

---

## 4. Barrido de variantes

283 ciclos, mismas fechas, t-test pareado contra el baseline. Ordenado por delta.

| Variante | Δ bp/ciclo | t | p |
|---|---:|---:|---:|
| momentum sin vol-scaling | **+26.9** | 2.64 | **0.009** |
| solo top 5 | +21.8 | 1.68 | 0.094 |
| N fijo = 10 | +7.1 | 1.12 | 0.264 |
| sin short-term boost | +6.3 | 1.61 | 0.109 |
| score aditivo (sign-safe) | +5.2 | 2.26 | 0.024 |
| entrada con lag de 1 día | +4.5 | 0.42 | 0.675 |
| sin downtrend gate | +4.2 | 1.33 | 0.184 |
| momentum con skip de 5d | +3.8 | 0.78 | 0.433 |
| control sectorial exenta "Other" | +2.2 | 0.84 | 0.402 |
| sin control sectorial | +1.9 | 0.72 | 0.475 |
| sin strict bonus | +1.2 | 1.24 | 0.218 |
| vol ratio no solapado | +0.4 | 0.48 | 0.632 |
| N fijo = 28 | +0.1 | 0.02 | 0.985 |
| gate sin la regla "solo en negativo" | −1.0 | −0.60 | 0.548 |
| distancia al máximo de 252d (52w) | −4.4 | −1.90 | 0.058 |

Con 15 comparaciones sobre la misma muestra, un p=0.024 aislado no sobrevive a corrección por
multiplicidad. **Solo una variante merece examen serio.**

### 4.1 El vol-scaling: el titular que no resiste

`momentum = ret90 / vol63`. Quitar el divisor da +26.9 bp/ciclo, p=0.009, anualizado 38% vs 22%.
Es el número más grande del estudio. Y es engañoso.

```
k    score = ret90/vol63**k     bp/ciclo   ann%   Sharpe  maxDD   vol media de lo elegido
0.00  (raw)                       71.7    38.15   1.33   -21.0        47.3%
0.25                              64.5    33.67   1.24   -21.2        44.5%
0.50                              62.1    32.63   1.28   -22.4        41.4%
0.75                              52.9    27.16   1.18   -18.9        37.1%
1.00  (PRODUCCIÓN)                43.7    21.97   1.07   -18.8        33.0%
```

Lo que compra el `k=0` es riesgo:

```
baseline (vol-scaled)  vol63 media 33.6%   beta media 0.95
raw momentum           vol63 media 50.9%   beta media 1.51
```

Apalancando el baseline a la misma volatilidad que el raw (1.32x), la comparación honesta:

```
baseline apalancado a la vol del raw : 57.7 bp/ciclo
raw                                  : 71.7 bp/ciclo
diferencia atribuible a la señal     : 14.0 bp/ciclo
IC95% bootstrap                      : [-4.4, +33.5] bp   → incluye cero
Sharpe raw 1.33 vs baseline 1.07, dif IC95% [-0.10, +0.63] → incluye cero
```

**Traducción: no hay alfa demostrable en quitar el vol-scaling. Hay beta 1.5 en un mercado que
subió.** En una muestra con sesgo de supervivencia y sin un 2008 dentro, subir el beta del
sistema en base a esto sería exactamente el error que el sesgo está diseñado para provocar.

Matiz técnico que sí vale la pena registrar: Barroso & Santa-Clara (2015) escalan **la cartera
long-short por la volatilidad de la estrategia** (series temporales). HYDRA divide **el score de
cada acción por su propia volatilidad** (transversal). No son la misma operación: la segunda es
un tilt hacia baja volatilidad, no gestión de riesgo. Si el objetivo es el de B&S, el sitio
correcto es el tamaño de la posición, no el ranking.

### 4.2 Costes de transacción

Rotación medida del set recomendado: **39% por ciclo** (~16 nombres, rebalanceo semanal).

```
coste  0 bp/lado -> 0.437%/ciclo | ann 21.97% | Sharpe 1.07
coste  5 bp/lado -> 0.398%/ciclo | ann 19.60% | Sharpe 0.97
coste 10 bp/lado -> 0.359%/ciclo | ann 17.28% | Sharpe 0.88
coste 20 bp/lado -> 0.281%/ciclo | ann 12.76% | Sharpe 0.69
```

A 10 bp/lado el sistema entrega ~17% anual en vez de ~22%. Los costes no aparecen en ningún
sitio del pipeline ni del tracking. Para un sistema de rotación semanal, **el modelo de costes
importa más que cualquier variante de la tabla de arriba** — todas las diferencias del barrido
son menores que el coste de rotar.

### 4.3 Lo que el sistema ya hace bien

- **La regla "solo en negativo" del gate (jun-2026) está confirmada.** Quitarla cuesta
  −1.0 bp y empeora el maxDD (−22.8 vs −21.7). La decisión de aquel día era correcta.
- **El strict filter tiene respaldo académico.** Exigir retorno reciente fuerte **junto con**
  surge de volumen coincide con Medhat & Schmeling (2022): los ganadores recientes de *alto*
  turnover continúan, los de bajo turnover revierten. El filtro está, sin saberlo, del lado
  correcto de esa literatura.
- **No adoptar el máximo de 52 semanas.** Pese a George & Hwang (2004), aquí *empeora*
  (−4.4 bp, p=0.058). Coherente: el horizonte de HYDRA son 5 días, y la ventana de 20 días es
  la escala temporal adecuada.

### 4.4 Prototipo de Meta-Layer transversal (no funciona)

Antes de recomendar rehacer la Meta-Layer para que sí afecte al ranking, la probé: que el
régimen cambie el **peso** de las features en vez de una escala global.

```
variante                                              bp/ciclo   ann%   Sharpe
prod   (k = 0.35 fijo)                                  43.7    21.97   1.07
tilt   (k: STRONG .50 / MOD .35 / CAUT .15 / WEAK 0)    42.8    21.42   1.05
tilt_mr (además mean-reversion en WEAK, k = -0.30)      40.8    20.18   0.99

tilt    vs prod: -0.9 bp (p=0.593)
tilt_mr vs prod: -2.9 bp (p=0.099)
```

**No mejora.** Así que la recomendación sobre S1 no es "hazla transversal": es "documenta lo
que realmente hace, o simplifícala". Convertir 230 líneas en un tilt real no está justificado
por los datos.

---

## 5. Recomendaciones, por orden de valor

**Ahora, sin tocar scoring (territorio de Grok, cero riesgo):**

1. **B1** — meter `vol_ratio_nan_share` en el contrato de salida. Restaura una alarma de
   producción que hoy está muerta.
2. **B2** — que el runner no dé verde a ficheros sin `__main__`. Es el bug que ocultó B1.
3. **B3** — reportar y persistir el régimen rico, no el simple. Sin esto, todo el análisis
   histórico por régimen está mal etiquetado.
4. **B4/B6** — limpiar el import muerto y el cálculo duplicado.

**Decisiones que necesitan tu OK (Lucas):**

5. **S2 — control sectorial.** Recomiendo (a): sectores reales cacheados desde yfinance. Hoy
   es un impuesto del 15% a todo lo que no esté en una lista de 80 nombres.
6. **B7 — deriva spec/código en breadth.** Recomiendo actualizar el spec al código (no cambia
   scoring). Si preferís la fórmula del spec, eso sí es cambio de scoring.
7. **S1 — Meta-Layer.** Recomiendo documentarla honestamente como controlador de
   `dynamic_count`. El prototipo transversal no mejora (§4.4).

**No hacer:**

8. **No quitar el vol-scaling.** El +27 bp es beta, no alfa (§4.1).
9. **No cambiar a máximo de 52 semanas.** Empeora en este horizonte.
10. **No mover umbrales del gate por estos números.** `thr 0.55` sale mejor pero se eligió
    mirando estos mismos datos.

**Lo que de verdad falta (y no es un parámetro):**

11. **Un modelo de costes de transacción** en el backtest y en el tracking. Con 39% de rotación
    semanal, es el factor que más mueve el resultado neto y hoy es invisible.
12. **Validación fuera de muestra.** Todo lo de aquí es 2020-2026 sobre supervivientes del
    S&P 500. Antes de mover un solo parámetro del algoritmo haría falta: universo
    point-in-time (con delistados) y al menos un régimen de estrés previo a 2020.

---

## 6. Reproducibilidad

`experiments/backtest_variant_sweep.py` — motor point-in-time, validación contra
`generate_daily_candidates`, barrido de variantes, t-tests pareados, descomposición
alfa/apalancamiento y curva de costes. Descarga sus propios datos vía yfinance.

```bash
cd hydra_screener_local
python experiments/backtest_variant_sweep.py --download   # ~2 min
python experiments/backtest_variant_sweep.py --sweep
```

## 7. Referencias

- Jegadeesh (1990), *Evidence of Predictable Behavior of Security Returns* — reversión a 1 mes.
- Barroso & Santa-Clara (2015), [*Momentum Has Its Moments*](https://www.sciencedirect.com/science/article/abs/pii/S0304405X14002566), JFE 116(1) — escalado por volatilidad **de la estrategia**.
- George & Hwang (2004), [*The 52-Week High and Momentum Investing*](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2004.00695.x), JF — proximidad al máximo de 52 semanas.
- Medhat & Schmeling (2022), [*Short-Term Momentum*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3795253), RFS — momentum de corto plazo condicionado a turnover alto.
