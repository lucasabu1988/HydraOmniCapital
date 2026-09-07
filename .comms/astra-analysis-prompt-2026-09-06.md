# Prompt para ChatGPT Astra — auditoría analítica de HydraOmniCapital

> Copiar y pegar completo. Modo análisis: Astra **no** commitea, no abre PRs, no toca ficheros.
> Generado por Claude 2026-09-06 sobre el estado real del repo (main + 5 ramas por mergear).

---

## 0. Quién eres en este trabajo

Eres un **auditor adversarial** de un sistema de trading cuantitativo con dinero real en
producción desde el 2026-09-05. Tu cliente (Lucas) no necesita que le expliques su código:
necesita que encuentres lo que está **mal, no medido o auto-engañoso**. Un informe que diga
"el código está bien estructurado" es un informe fallido.

Reglas de conducta del informe:

- **Cero adulación, cero resumen descriptivo.** No escribas "este repo implementa un screener
  de momentum". Ya lo sabemos.
- **Cada afirmación va con `ruta/fichero.py:línea`.** Sin cita = no existe.
- **Clasifica cada hallazgo** como `CONFIRMADO` (leí el código/dato y esto es así),
  `PROBABLE` (la lectura lo sugiere, falta un dato) o `HIPÓTESIS` (hay que medirlo).
  No mezcles los tres tonos en la misma frase.
- **Nada de consejos genéricos.** Prohibido: "añade type hints", "usa CI", "considera usar una
  librería de X", "añade docstrings", "refactoriza a clases", "usa pydantic", "métele Docker".
  Si el hallazgo cabría igual en cualquier repo de Python, no lo escribas.
- **Prohibido proponer reescrituras.** El sistema está vivo y las órdenes se ejecutan los lunes.
  Propón cambios acotados, medibles y reversibles.
- Si no puedes verificar algo (fichero ausente, dato gitignored), **dilo explícitamente** en vez
  de asumir. Inventar un número es el único error imperdonable aquí.

---

## 1. Cómo orientarte (orden de lectura obligatorio)

El repo es `lucasabu1988/HydraOmniCapital`. El código activo es **solo** `hydra_screener_local/`
(138 ficheros .py, ~26.800 líneas). Todo lo demás es legacy o archivo.

Lee en este orden antes de opinar de nada:

1. `AGENTS.md` — contrato corto para agentes.
2. `CLAUDE.md` — guía larga: reglas críticas, arquitectura, parámetros, "facts agents keep
   getting wrong". **Trátalo como una afirmación a verificar, no como verdad.**
3. `hydra_screener_local/HYDRA_ALGORITHM_SPEC.md` — fuente de verdad del algoritmo
   (secciones 1-8 = screener v8.4; **sección 9 = HYDRA v9, lo que está en producción**;
   sección 10 = protocolo de evolución).
4. `hydra_screener_local/config.py` — todos los parámetros reales. Si un número del doc no
   coincide con este fichero, el fichero gana y eso ya es un hallazgo.
5. `.comms/claude-audit-2026-09-06.md`, `.comms/claude-project-audit-2026-09-06.md`,
   `.comms/claude-algo-deep-dive-2026-09-05.md`, `.comms/claude-redesign-verdict-2026-09-06.md`,
   `.comms/claude-v9-production-design-2026-09-06.md`, `.comms/claude-sleeves-design-2026-09-06.md`
   — auditorías previas. **Léelas para no repetirlas**, y para atacarlas: si una conclusión de
   esas está mal argumentada, ese es un hallazgo de primer nivel.
6. `GROKBOARD.md` (207 KB, mensajes más recientes arriba) — historial de tareas TASK-3xx con
   evidencia y notas de review. Es el registro de qué se midió y qué no.

### Estado del árbol que vas a leer

- `main` es el ancestro común; hay **5 ramas sin mergear** por delante de él
  (`merge-prepared-2026-09` +36 commits, `audit/subtract-parked-clis-v2` +37,
  `structural-hardening-2026-09`, `post-freeze-wiring`, `n-sleeve-engine`).
  Si tu herramienta solo ve `main`, dilo y trabaja sobre `main`; si puedes elegir rama, usa
  `merge-prepared-2026-09` y trata la divergencia como objeto de análisis.
- **No existen en el repo** (gitignored, viven en un solo disco local): `history/` (el único
  registro de qué se recomendó cada día), `state/portfolio_v9.json` (el estado real de la
  cartera), `.env`, `data_cache/`, el bar store SQLite. **No inventes su contenido.**
  Cuando un análisis dependa de ellos, escribe exactamente el comando que Lucas debería
  ejecutar en local para producir el dato que te falta.

---

## 2. Restricciones duras del proyecto (violarlas invalida tu informe)

1. **El scoring está congelado.** Fórmulas en `core/signals.py`, multiplicadores en
   `core/meta_layer.py`, umbrales de gate en `config.py` y el SPEC solo cambian con aprobación
   explícita de Lucas (regla 6 del GROKBOARD). *Puedes proponer* un cambio de scoring, pero
   etiquétalo `REQUIERE APROBACIÓN` y adjunta el experimento que lo decidiría.
2. **Filtros y reglas de selección no son scoring** (liquidez, precio mínimo, cap sectorial,
   zombie removal). Se pueden cambiar sin aprobación, pero cambian la lista recomendada: toda
   propuesta ahí viene con cómo medir el impacto.
3. **Nunca ancles parámetros en el legacy.** El motor COMPASS y la lista v8.4 ("5 posiciones,
   máx 3 por sector, momentum 90d con skip de 5 días") están archivados en
   `archive/root-legacy-2026-09/` y usaban otra taxonomía sectorial. Ya causaron un cambio
   equivocado (TASK-318). Lee `config.py`.
4. **Todo número del harness de medición es solo S&P 500, 2020-2026, constituyentes actuales**
   (`experiments/backtest_variant_sweep.py`). Sesgo de supervivencia a favor del momentum.
   El panel OOS (2004-26, membership PIT real) tiene **53% de cobertura de precios en 2005**.
   Si citas un nivel absoluto sin ese caveat, el hallazgo se descarta.
5. **Un skip no es un pass.** El runner es `hydra_screener_local/run_all_tests.py`; CI corre un
   único job. Verde en CI prueba ausencia de regresión de código, **no** validez financiera ni
   track record.
6. **Los horizontes son días de trading**, nunca calendario. La entrada es el primer precio
   ejecutable (la barra siguiente a la señal), nunca el cierre que generó la señal.
7. **El Meta-Layer no cambia el ranking**: `aggression` y `pillar_factor` son un escalar
   positivo igual para todos los tickers del día; solo mueven `dynamic_count`. No lo describas
   como un tilt de estilo.

---

## 3. Qué quiero que analices (por prioridad)

Trabaja los bloques en este orden. Si te quedas sin presupuesto, es mejor A y B hechos a fondo
que las ocho superficialmente. **Di dónde paraste.**

### A. Integridad point-in-time y look-ahead (máxima prioridad)

Dinero real depende de que no haya futuro filtrado en las decisiones. Audita el camino completo
dato → decisión buscando fugas:

- `data/pit.py`, `data/universe.py` (membership histórica), `data/sectors.py` +
  `sector_overrides.json` (¿el sector usado en el backtest es el de la fecha o el de hoy? ver
  `test_lab_sector_pin.py` y TASK-387), `data/adjust.py` y `data/store.py` (ajuste de
  splits/dividendos: `adjust='local'`, `APPLY_SPLITS`; ¿el factor de ajuste conocido hoy se
  aplica a barras del pasado en una simulación?), `data/dividends.py`, `data/fetch.py`.
- `core/portfolio_engine.py`, `core/tranche_book.py`, `core/fills.py`, `core/tracking.py`,
  `core/history.py`: ¿qué información de t+1 es visible en t?
- Los filtros: `min_avg_volume`, `min_price`, zombie removal, `MAX_PER_SECTOR` — ¿se aplican con
  datos disponibles en la fecha de decisión, o con la serie completa?
- El régimen (`core/regime.py`) y sus SMA/lookbacks: ventanas, `fill_method`, reindexado.
- Convención de `pct_change(fill_method=None)`: ¿hay algún sitio donde se rellenen huecos y eso
  invente retornos?

Entrega: tabla de cada fuga candidata con severidad, el fichero:línea, y **el test que la
demostraría** (ideal: un test que falle hoy).

### B. Validez estadística de la evidencia acumulada

El proyecto ha tomado decisiones (no-skip, `k=1` de vol-scaling, 50/50, T20, tranches, cap
sectorial 5) apoyadas en medidas del harness. Audita el razonamiento, no solo el código:

- `experiments/backtest_variant_sweep.py`, `bootstrap_compare.py`, `panel_methodology.py`,
  `build_cone.py` / `oos_cone_5050.json`, `t20_sensitivity.py`, `engine_backtest.py`,
  `engine_diff.py`, `redesign_lab.py`, `lab_costs.py`, `cost_model.py`.
- **Multiple testing**: ¿cuántas variantes se han probado sobre el mismo panel? ¿Cuál es el
  p-valor efectivo de la variante elegida? ¿Hay corrección, o hay overfitting de selección?
- **Tamaño de muestra real**: ciclos de 5 días entre 2020-2026 → ¿cuántas observaciones
  *independientes*? ¿Qué potencia estadística tiene una diferencia de X% anual con ese N?
- **Bootstrap**: ¿block bootstrap o iid? Si es iid sobre retornos autocorrelacionados, los
  intervalos son demasiado estrechos: dilo con el número.
- **Costes**: `COST_BP_PER_SIDE = 10`. ¿Es defendible con un universo Russell-heavy (~2/3
  mid/small)? Estima slippage e impacto por capacidad y di a partir de qué AUM el edge medido
  se muere.
- **Coherencia in-sample vs OOS**: ¿qué decisiones se sostienen solo in-sample? Nómbralas.

### C. Corrección del motor de cartera (invariantes)

`core/portfolio_engine.py` es puro y decide las órdenes reales. Busca:

- Invariantes que deberían existir y no están testeadas: conservación de cash, suma de pesos,
  no-negatividad de shares, idempotencia de un ciclo repetido, reinicio de estado (hubo un
  "reset leak" en TASK-347), hurdle de T-bill, devengo de `^IRX` sobre cash idle, dividendos,
  splits, fills parciales, `reconcile.py`, `preflight.py`, `state_check.py`,
  `state_migrations.py`.
- El vol-target 15% y las 4 tranches de 20 barras: ¿qué pasa en un gap, en un halt, con un
  ticker deslistado a mitad de tranche, con un ticker que sale del universo?
- Rutas de error: `daily.py`, `live_watcher.py`, `confirm_fills.py`. ¿Qué falla *en silencio*?
  El patrón `try/except` que degrada a no-op ya apareció una vez en `screener.py`.
- El comportamiento fail-closed de VIX (indisponible = pánico = bloquear entradas): ¿está
  implementado así en todas las rutas o solo en una?

### D. Qué NO prueba la suite verde

63 ficheros de test / 0 skips en la rama v2, 22 pass / 2 skip en main. Quiero un análisis de
**fuerza de aserción**, no de cobertura de líneas:

- Tests que pasarían igual si la lógica estuviera invertida o vacía (aserciones tautológicas,
  mocks que se auto-confirman, `assert result is not None`).
- Rutas críticas sin ningún test que pueda fallar por la razón correcta.
- Dónde los tests usan sintéticos sin huecos y por eso no ven el bug real (gaps, NaN,
  deslistados, festivos — `utils/trading_calendar.py`).
- `test_spec_compliance.py`: ¿enforcea de verdad las fórmulas del SPEC o solo los valores?
- Propón, para los 5 huecos peores, el test concreto (nombre, fichero, qué debe fallar hoy).

### E. Riesgo operacional (lo que rompe un lunes)

- `history/` y `state/` en un solo disco, gitignored; `daily.py` zipea a `HYDRA_BACKUP_DIR`.
  ¿Qué se pierde irrecuperablemente si ese disco muere? ¿Qué es reconstruible desde git?
- El flujo es semi-manual (hoja de instrucciones ejecutada a mano el lunes al cierre): enumera
  los modos de fallo humano y qué control automático los detectaría (`reconcile.py`,
  `confirm_fills.py`, `verify_state.py`).
- Windows/cp1252, Python 3.14 local vs 3.12/3.13 en CI: ¿hay divergencias que solo aparecen en
  una de las dos?
- Dependencias externas (yfinance como única fuente): ¿qué pasa el día que cambie el schema o
  devuelva datos silenciosamente malos? ¿Hay detección o solo confianza? Mira
  `test_volume_watchdog.py`, `data/providers/`.

### F. Complejidad y deuda estructural

- 138 ficheros .py / 26.8k líneas para un sistema de 2 sleeves. Identifica lo que está **muerto
  o duplicado**: `experiments/` (40+ scripts), `tranche_book.py` duplicado en `core/` y
  `experiments/`, `hydra_backtest/` (import-dead), `backtest/`, `dashboard/`, `tools/` vacío,
  docs legacy en la raíz (`SECURITY.md`, `BUGS_FIXED.md`, `REGIME_AWARE_CHANGES.md`,
  `IMPLEMENTATION_GUIDE.md`).
- Las 5 ramas sin mergear: ¿hay conflicto semántico entre ellas (dos ramas cambiando el mismo
  invariante de forma incompatible)? Ese es el riesgo real, no el textual.
- Acoplamientos que impiden medir: dónde `core/` depende de I/O, dónde el scoring depende de
  config global, dónde no se puede correr una variante sin tocar producción.

### G. Drift documento ↔ código

`CLAUDE.md`, `AGENTS.md`, `README.md`, el SPEC y `GROKBOARD.md` afirman decenas de hechos
concretos (parámetros, rutas, qué corre CI, qué está borrado). **Verifica una muestra amplia
contra el código y lista cada discrepancia** con las dos citas (doc y código). Este bloque es
mecánico y de alto valor: cada drift es un agente futuro tomando una decisión con datos falsos.

### H. Crítica de la estrategia (nivel diseño)

Aquí quiero pensamiento, no lectura de código. Sé duro:

- 50/50 T20-stocks + ETF-trend: ¿es una elección medida o un compromiso? ¿Qué correlación real
  hay entre sleeves y qué diversificación aporta de verdad el 50%?
- **Régimen calculado sobre SPY con universo Russell-heavy** (debilidad conocida, audit R1,
  espera TASK-324): cuantifica el coste esperado de ese mismatch y diseña el experimento que lo
  resolvería con el panel PIT.
- Momentum 12-7 en sleeve A vs momentum 90d del screener v8.4 que sigue produciéndose: ¿dos
  algoritmos coexistiendo es intencional o es deuda?
- `MAX_PER_SECTOR = 5` sobre T20 = hasta 25% en un sector. ¿Es un control de riesgo o una
  restricción cosmética? ¿Qué concentración real ha habido?
- La decisión de **no usar skip** (TASK-319) y `k=1` de vol-scaling: reargumenta ambas desde la
  literatura y desde los datos del repo. Si crees que están mal, dilo con el experimento.
- Objetivo declarado: 10% neto — no alcanzado (ver `.comms/claude-redesign-verdict-2026-09-06.md`).
  ¿Es alcanzable con este diseño, o el diseño necesita otra fuente de retorno? Sé concreto:
  ¿qué añadirías y qué evidencia lo justificaría?
- Lo que **no** está modelado: impuestos, dividendos en el sleeve ETF, borrow, tamaño mínimo de
  orden, tracking error de ejecución manual con un día de retraso.

---

## 4. Formato de salida obligatorio

Un solo informe markdown, con esta estructura exacta:

```
# Auditoría Astra — HydraOmniCapital — <fecha> — rama <rama leída>

## 0. Alcance real
Qué leí (lista de ficheros), qué NO pude verificar y por qué, dónde paré.

## 1. Los 10 hallazgos que importan
Tabla ordenada por (impacto en dinero × probabilidad):
| # | Hallazgo (1 frase) | Sev | Estado | Fichero:línea | Cómo se demuestra |
Sev = CRÍTICO (puede costar dinero / decisión inválida) | ALTO | MEDIO | BAJO.
Estado = CONFIRMADO | PROBABLE | HIPÓTESIS.

## 2. Detalle por hallazgo
Para cada uno de los 10, en <=250 palabras:
- Qué hace el código hoy (con la cita).
- Por qué está mal / por qué el argumento que lo sostiene no se sostiene.
- El escenario concreto de fallo: entradas/estado -> resultado incorrecto.
- La corrección mínima (no una reescritura), y si toca scoring: REQUIERE APROBACIÓN.
- El check que lo verifica: comando exacto o test con nombre y aserción.

## 3. Drift documento <-> código
Tabla: afirmación | dónde se afirma | qué dice el código | veredicto.

## 4. Lo que la evidencia NO permite afirmar
Lista de conclusiones que el repo trata como establecidas y que estadísticamente no lo están,
cada una con el número que falta para establecerlas.

## 5. Cola de tareas propuesta (formato GROKBOARD)
De 6 a 12 tareas, listas para pegar en el board. Cada una:
### TASK-XXX — <título imperativo>
Objetivo: <una frase, con el propósito concreto — no "mejorar X">
Files: <rutas exactas que se tocan>
Criterio de aceptación: <qué comando exacto debe pasar / qué número debe aparecer>
Medición: <cómo se prueba que sirvió; si no se puede medir, dilo>
Riesgo: <qué puede romper en producción>
Aprobación: <no requiere | REQUIERE APROBACIÓN DE LUCAS (scoring)>
Ordénalas por ratio valor/riesgo y marca cuáles son paralelizables.

## 6. Lo que revisé y está bien
Máximo 10 líneas. Solo lo que verificaste explícitamente y aguantó el ataque — sirve para
saber dónde no hace falta volver a mirar. Nada de elogios.

## 7. Preguntas para Lucas
Solo las que bloquean análisis (no las que puedes resolver leyendo). Máximo 5.
```

---

## 5. Chuleta de hechos verificados (2026-09-06) — punto de partida, verifícala

- Producción = HYDRA v9 (`ALGO_VERSION="v9"`) desde 2026-09-05; primeras órdenes 2026-09-07.
  50/50: sleeve A = T20 stocks (momentum 12-7, 4 tranches de 20 barras, vol-target 15%),
  sleeve B = ETF trend (10 ETFs, excess return 12m, inverse-vol).
- Universo producción: `UNIVERSE="all"` (S&P500 ∪ NDX ∪ Dow ∪ R1000 ∪ R2000, ~3000 nombres).
- Ciclos de 5 días de trading. Entrada al primer precio ejecutable.
- Parámetros clave: `MOMENTUM_LOOKBACK=90` (ret90/vol63) sin skip, `SHORT_TERM_BOOST=0.35`,
  `VOL_SURGE_THRESHOLD=1.50`, `REGIME_SMA=200`, `MIN_REGIME_SCORE=0.35` (flag a 0.35×0.85),
  gate de downtrend (-8.0 / -5.0, regla "only-negative"), `MAX_PER_SECTOR=5` (GICS, hard cap en
  selección, `"Other"` exento), dynamic count `clamp(round(14×aggression×compass), 6, 28)`,
  `COST_BP_PER_SIDE=10`, filtros min_avg_volume 100k / min_price 5.0.
- Decidido 2026-09-06: sin momentum skip (el skip v8.4 era una apuesta de reversión y medía peor
  in- y out-of-sample); vol-scaling `k=1` se queda (`k=0` es beta y pierde OOS); régimen sigue en
  SPY, IWM persistido como régimen secundario para evidencia.
- VIX indisponible = pánico = bloquear entradas (fail-closed).
- Cash idle devenga `^IRX` en los libros (Lucas 2026-09-05).
- Objetivo de 10% neto: **no alcanzado** todavía.
- `hydra_backtest/` es import-dead desde 2026-06-05 (importa 9 funciones de un
  `omnicapital_live.py` borrado); borrar-o-restaurar es decisión pendiente de Lucas.
- Protocolo de evolución (SPEC §10): journal semanal / evidencia trimestral / registro de
  hipótesis; **nunca ajustar a la última semana**.

---

## 6. Anti-objetivos

No quiero: un tutorial, un plan de refactor a microservicios, "añade logging estructurado", una
propuesta de migrar a otro broker o a la nube (Render se eliminó a propósito, no vuelve),
sugerencias de ML/LLM dentro del scoring sin un experimento diseñado, ni un informe que mezcle
40 hallazgos triviales con los 3 que importan. **Prioriza brutalmente.**

Si al terminar crees que el hallazgo más grave es algo que este prompt no te pidió mirar, ponlo
primero y dilo.
