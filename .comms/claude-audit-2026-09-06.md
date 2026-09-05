# HYDRA — Auditoría técnica (mandato de Lucas, 2026-09-06)

**Responsable técnico / integradora:** Claude · **Revisor independiente:** Grok (TASK-336, 337, 338)
**Objetivo del mandato:** recomendaciones, seguimiento y backtests correctos, trazables y reproducibles;
primero medición fiable, después evaluar si existe mejora de estrategia. El 10 % neto es una hipótesis a
evaluar, no una cifra a fabricar.

---

## 1. Estado de partida

| | |
|---|---|
| Rama / commit de partida | `main` @ **2bfa5da** (`docs: pre-register sleeve 3…`) |
| Cambios locales ajenos al empezar | Grok con TASK-335 sin commitear en `core/filters.py`, `screener.py`, `test_data_quality_filter.py` → no toqué esos archivos hasta su commit `b6d6eaf` / `385c217` |
| Producto activo | `hydra_screener_local/` (screener Python + TradingView, universo `"all"` ~3000, ciclos de 5 sesiones). COMPASS/Render/IBKR archivados. **T20, manga ETF y manga MR son experimentos**; producción sigue en v8.4 sin cambio de scoring. Verificado en `CLAUDE.md`, `AGENTS.md`, `config.py`, `screener.py`. |
| Spec vs código | `test_spec_compliance.py` (10 tests) pasa: fórmulas y parámetros de `config.py` coinciden con SPEC §6. |
| Comunicaciones leídas | `GROKBOARD.md`, `.comms/*` (todas), notas de Grok 326-335 |
| Versión final evaluada | números de §5 producidos con **`0d4f2e5`**; correcciones de la revisión independiente en el commit final (ver §2.1). La revisión no cambió ninguna cifra de §5 salvo la exposición en pasos con nombres en carry (T20, 3 episodios) |

## 2. Revalidación de los cinco antecedentes

| # | Antecedente | Estado al empezar (inspección sobre 2bfa5da) | Estado ahora | Evidencia |
|---|---|---|---|---|
| A | Cero recomendaciones → fallback publicaba rechazados | **Vigente**: `send_hydra_summary.py:78-79` (`recommended = top_candidates[:top_n]`), `generate_pine_watchlist.py:44-49` y `run_feeder` (fallback top N), `screener.py:236-238` (`exec_pool = candidates` → Top5 con rechazados), `validate_pine_contract.py:66-69` (lista vacía = error) | **Corregido** `839e375` | `test_output_integrity.py::test_zero_recommended_never_falls_back`, `test_generate_pine_watchlist.py::test_zero_recommended_stays_zero`; ambos fallaban antes del arreglo (el fallback devolvía 15/20 nombres) |
| B | La lista completa no sobrevivía a las exportaciones | **Vigente**: `screener.py:210` `head(20)`, `:279` `head(15)`, `run_feeder(top_n=15)`, `run_sender(top_n=15)`, `DEFAULT_TOP=10` | **Corregido** `839e375`: `history_records()` (todos los recomendados + top-20 de contexto), `top_n=None` por defecto, `display_limit` explícito solo cuando se recorta `top_details`, validador exige `top_details == recommended_tickers` salvo `display_limit`. Pine: `i_max_watchlist` es el tope de visualización del lado TV (ya existía, explícito) | `test_output_integrity.py` (0/1/22/28, con ranks > 20) |
| C | Tracking saltaba v2 con retornos nulos | **Vigente**: `core/tracking.py:221-225` saltaba cualquier v2 con candidatos | **Corregido** `839e375`: `needs_update()`; `status` por horizonte {measured, pending, unmeasurable+motivo}; `recommended_snapshot`, `run_schema_version`, `price_source`; idempotente | `test_tracking_pending.py` (4; parcial → completo → idéntico; hueco vs delistado; history editado / fecha de señal / esquema viejo) |
| D | Tramos con pesos nominales; rotación solo al tramo renovado | **Vigente** en `run_tranched()` y `run_sleeve()` (mi código): caso 100→200→100 daba +12.5 % con rotación 0 | **Corregido** `0d4f2e5`: `experiments/tranche_book.py` (unidades, efectivo, valor y operaciones por tramo; write-offs explícitos), `run_exec`, `run_sleeve`; los runners nominales se conservan solo para la tabla comparativa (`nominal=True`) | `experiments/test_tranche_book.py` (6): el caso de referencia da 0 % y documenta el +12.5 % antiguo; conservación de valor − costes; drift no rebalanceado gratis; reset registra y cobra; renovación con valor propio; cash remunerado; write-off registrado |
| E | `combine(mode='rp')` usaba la vol del propio paso | **Vigente** en `sleeve_lab.py` | **Corregido** `0d4f2e5`: `mix()` con `shift(1)` + costes de reasignación y de reset del mix drifteado | `experiments/test_mix_causality.py` (3): un shock en el paso *i* no cambia pesos ≤ *i* y sí el *i+1*; coste de reset calculado a mano |

### 2.1 Revisión independiente (Grok, TASK-336/337/338) y cierre

| Revisión | Resultado | Cierre (Claude) |
|---|---|---|
| 336 — A/B/C (`test_review_336.py`, 13 tests: 7 sostienen, 6 rompen) | A resiste todos los ataques. B: CLI `--top` seguía en 15; el validador no exigía que `top_details` fuera el prefijo bajo `display_limit`; un ticker duplicado se publicaba dos veces. C: un v2 completo sin `recommended_snapshot` ignoraba un history con más recomendados; `no_entry_price` no se reintentaba; ticker duplicado medido dos veces | Los 6 corregidos con cambios acotados (CLI default `None`; validador exige prefijo; dedupe en summary/watchlist/`history_records`; ficheros sin procedencia se comparan con su propio conjunto candidatos+omitidos; `no_entry_price` reintentable; medición única). 13/13 verdes |
| 337 — simulador (`experiments/test_review_337.py`, 12: 11 sostienen, 1 rompe) | D y E reproducidos sobre el código viejo (+12.5 % / peso con look-ahead). Hallazgo: `exposure()` ignoraba nombres en carry (valorados a último precio en P&L) → expo 0 en esos pasos. 10 supuestos no documentados | `exposure()` valora igual que el P&L; supuestos añadidos a la cabecera de `tranche_book.py`. 12/12 verdes. Efecto sobre §5: solo la columna exposición de T20 en 3 pasos |
| 338 — datos/metodología (`experiments/panel_methodology.py`) | Precios `auto_adjust` = retorno total aproximado; cobertura 52.7 → 99.4 %; 0 operaciones en tickers reutilizados; T20 expuesto a delisting-en-cartera (ESRX ×2, SCG, 2019); **write-offs a 0 → T20 7.36 → 6.90 (−0.46 pp)**; PROD sin write-offs | Aprobada; sensibilidad incorporada en §5.1 |

Revisión de fechas señal/ejecución (E, inspección): `run_exec` — señal con datos hasta el cierre *t* (ranking, vol63, ADV, JUMP252, régimen, vol de la cesta), ejecución al cierre *t+1*, medición *t+1 → t+1+paso*; ETF — mom12/SMA200/tb12 en *t*, ejecución *t+1*; T-bill del paso tomado en *t*. Manga MR: señal al cierre *t*, entrada al cierre *t+1*; **salidas evaluadas y ejecutadas al mismo cierre** (supuesto MOC sobre el precio observado; declarado, no probado con lag 1 — la manga está muerta por pre-registro y no se usa).

## 3. Archivos modificados y efecto

| Archivo | Efecto |
|---|---|
| `send_hydra_summary.py` | sin fallback; lista completa; `top_n` = tope de `top_details` con `display_limit` |
| `generate_pine_watchlist.py` | sin fallback; `top_n=None` → lista completa; lista vacía se escribe vacía |
| `screener.py` | `history_records()`, `executable_top5()`; llamadas `top_n=None`; sin `head(15)` |
| `core/tracking.py` | `status` por horizonte, procedencia, `needs_update()`, resumen con pendientes |
| `validate_pine_contract.py` | vacío ≠ ausente; exige count/lista/top_details coherentes; `[SKIP]` sin artefactos (exit 0) |
| `run_all_tests.py` | descubre `ADDITIONAL_TESTS` aunque no casen con el glob (el validador Pine nunca corría) |
| `experiments/tranche_book.py` (nuevo) | contabilidad ejecutable |
| `experiments/redesign_lab.py` | `run_exec`, `run_any(nominal=False)`, CLI `--nominal` |
| `experiments/sleeve_lab.py` | `run_sleeve` ejecutable (+`run_sleeve_nominal`), `mix()` causal con costes |
| Tests nuevos | `test_output_integrity.py`, `test_tracking_pending.py`, `experiments/test_tranche_book.py`, `experiments/test_mix_causality.py`; `test_tracking_horizons.py` y `test_generate_pine_watchlist.py` ajustados |

## 4. Comandos y resultados

- `cd hydra_screener_local && python run_all_tests.py` (versión final, con los 25 tests de revisión de Grok): **22 archivos PASS, 2 SKIP, 0 FAIL** (44.6 s). Tras `839e375` eran 18/2/0.
  Skips: `test_hybrid_integration.py` (necesita `history/`), `validate_pine_contract.py` (necesita
  `pine/hydra_last_summary.json`) — ambos ahora **descubiertos y ejecutados**, y omitidos con motivo.
- `python -m pytest experiments/test_tranche_book.py experiments/test_mix_causality.py -q`: 9 passed.
- Indicador real de TradingView: no se compila ni se ejecuta aquí (`validate_pine_contract.py` simula el
  parser en Python). **Aparcado por decisión de Lucas (2026-09-06)**; no bloquea nada.
- Revisión independiente completada: TASK-336/337/338 (Grok), ver §2.1.

## 5. Métricas recalculadas (simulador corregido, commit `0d4f2e5`)

**Datos y supuestos (fijos antes de correr; ninguna variante nueva):** panel S&P 500 PIT 2004-01-02 →
2026-09-04, 1209 tickers con precio en Yahoo (membresía real; cobertura de precios 53 % en 2005 → 95 %
en 2023; TASK-325 bloquea reutilización de tickers). Precios `auto_adjust` (retorno total aproximado).
Rejilla de 5 barras; señal al cierre *t*, ejecución al cierre *t+1*, medición *t+1 → t+6*. Costes 10
bp/lado acciones, 5 bp/lado ETFs, sobre dólares operados. Cash: 0 % o T-bill 13 semanas (^IRX), ambos
mostrados. Precio ausente: se mantiene al último precio hasta 10 barras y se da de baja a ese precio
(registrado). DEV 2004-2015 / TEST 2016-2026: el TEST ya se usó una vez para elegir T20 (veredicto
06-09) — **no es una prueba intacta**; aquí solo se recalcula. Sharpe = media/desv. de retornos netos por
paso × √(252/5), sin restar la tasa libre de riesgo.

### 5.1 Nominal (pre-auditoría) vs ejecutable — mismas señales, otra contabilidad

| Config | Período | bruto | neto | Sharpe | maxDD | rotación/sem | exposición | nombres |
|---|---|---|---|---|---|---|---|---|
| PROD nominal | ALL | 9.60 | 5.38 | 0.41 | −38.2 | 39.0 | 91 | 16 |
| **PROD exec** | ALL | 9.59 | **5.36** | 0.41 | −38.1 | 39.1 | 91 | 16 |
| PROD exec + T-bill | ALL | 9.72 | 5.48 | 0.42 | −37.8 | | | |
| T20 nominal | ALL | 8.87 | 7.61 | 0.60 | −28.6 | 11.6 | 86 | 31 |
| **T20 exec** | ALL | 8.61 | **7.36** | 0.58 | −29.7 | 11.5 | 86 | 31 |
| T20 exec + T-bill | ALL | 8.80 | 7.55 | 0.59 | −29.2 | | | |
| ETF nominal | ALL | 6.17 | 6.07 | 0.91 | −12.4 | 2.0 | 66 | 7 |
| **ETF exec** (T-bill) | ALL | 6.15 | **6.05** | 0.91 | −11.9 | 1.9 | 66 | 7 |

Por período (ejecutable, cash 0 %): PROD DEV 3.32 / TEST 7.50; T20 DEV 7.03 / TEST 7.69; ETF (T-bill)
DEV 6.53 / TEST 5.56.

Lectura: la contabilidad nominal **no cambiaba PROD** (un solo tramo, rebalanceo total cada 5 barras: el
único error era la rotación medida contra pesos objetivo en vez de drifteados, 39.0 → 39.1) y **favorecía
a T20 en +0.25 pp de neto y ~1 pp de DD** (el rebalanceo implícito gratuito entre tramos). En el ETF el
efecto es nulo (2 % de rotación). Operaciones registradas 2004-2026: PROD 24 286, T20 26 557, ETF 7 681.
Write-offs: PROD 0, T20 **3** (ESRX ×2 y SCG, 2019: adquiridas; dadas de baja al último precio, 0.22 en
unidades de libro inicial). **Sensibilidad (TASK-338): marcadas a 0, T20 pasa de 7.36 a 6.90 % neto (−0.46 pp)**;
es el precio de mantener 20 barras con 4 tramos frente al rebalanceo total cada 5 de PROD. ETF 0.

### 5.2 Carteras de mangas (mangas ejecutables, pesos causales, costes de reasignación cobrados)

| Cartera | Período | neto | Sharpe | maxDD | vol anual | episodios DD < −10 % | coste reasignación |
|---|---|---|---|---|---|---|---|
| PROD (T-bill) | ALL | 5.48 | 0.42 | −37.8 | 15.7 % | 34 | — |
| T20 (T-bill) | ALL | 7.55 | 0.59 | −29.2 | 13.9 % | 33 | — |
| ETF | ALL | 6.05 | 0.91 | −11.9 | 6.7 % | 1 | — |
| **50/50 T20+ETF** | DEV / TEST / ALL | 6.96 / 6.87 / **6.91** | 0.75 / 0.73 / **0.74** | −13.8 / −19.5 / **−19.5** | 9.6 % | 9 | 2.7 bp/año |
| **Paridad de riesgo** (peso T20 medio 0.33) | DEV / TEST / ALL | 6.78 / 6.31 / **6.55** | 0.81 / 0.79 / **0.80** | −10.1 / −16.5 / **−16.5** | 8.4 % | 2 | 3.6 bp/año |
| **SPY buy-and-hold** (misma rejilla, sin costes) | DEV / TEST / ALL | 6.52 / 15.70 / **10.96** | 0.43 / 0.98 / **0.68** | −54.7 / −31.7 / **−54.7** | | | — |

Correlación semanal T20–ETF: 0.70 (DEV 0.66, TEST 0.76). El arreglo de causalidad en la paridad de riesgo
movió el resultado −0.16 pp de neto y +0.2 pp de DD frente al cálculo con look-ahead (6.71 / −16.7 →
6.55 / −16.5); el coste de reasignación es despreciable (3-4 bp/año).

### 5.3 Qué dicen los números (evidencia ejecutada, no hipótesis)

1. **Nadie llega al 10 % neto.** El mejor neto ejecutable es T20 con T-bill: **7.55 %** (7.36 a cash 0).
   Ni las carteras (6.5-6.9 %) ni PROD (5.4-5.5 %). El objetivo histórico **no se demuestra** con esta
   familia sobre este panel y estos costes; nada se ajustó para acercarse.
2. **El benchmark pasivo gana en retorno**: SPY 10.96 % en 2004-2026 (15.7 % en 2016-2026) frente a 7.5 %
   del mejor activo. Lo que las estrategias ofrecen es **riesgo**: DD −12/−17/−20 % frente a −55 %, y
   Sharpe 0.74-0.91 frente a 0.68. En DEV (2004-2015, con 2008) T20 (7.0) y ETF (6.5) sí superan a SPY (6.5)
   con un tercio/octavo del drawdown; en TEST SPY gana por 8 pp.
3. La ventaja de T20 sobre PROD (+2.1 pp neto, exec+T-bill) sigue **sin ser estadísticamente distinguible
   de cero** (TASK-332, IC 95 % [−3.6, +5.2] medido sobre la serie nominal; la serie ejecutable difiere en
   0.25 pp, dentro del intervalo). Su caso es rotación (11.5 % vs 39 %) y drawdown, no alpha.
4. Sensibilidad ya medida y no repetida aquí: fase de arranque (T20 invariante, F1 no — TASK-330),
   parámetros vecinos de T20 (spreads 0.3-0.9 pp — TASK-331), costes por tamaño (T20 6.9 % a +10 bp,
   PROD 3.2 % — TASK-333). Todo sobre la contabilidad nominal; la diferencia exec/nominal (≤ 0.25 pp) no
   cambia ninguna de esas conclusiones.
5. **Simulación, no operación real.** No existe track record medido con el tracking v2 corregido; el
   `history/` vive en un disco y `tracking/` se recalcula desde hoy con estados pendiente/medido.

## 6. Trabajo restante y decisiones para Lucas

**Restante (técnico, sin decisión):**
- (Revisión independiente completada; nada abierto de 336-338.)
- Pine / TradingView: **aparcado por decisión de Lucas (2026-09-06)**. El contrato JSON queda
  protegido por `validate_pine_contract.py` (simulación Python); compilar el indicador real no se hará
  por ahora. Nadie trabaja en `pine/` hasta nueva instrucción.
- Correr `python core/tracking.py`/`track_performance.py` donde vive `history/` para regenerar los tracking
  con `status` (idempotente; recalcula solo lo pendiente).
- Actualizar `CLAUDE.md` (sección Testing: 20 archivos, 2 skips con motivo) — pendiente de la revisión 336.

**Decisiones que requieren a Lucas (ninguna tomada por mí):**
1. **Producción sigue en v8.4.** Llevar T20, la manga ETF o una cartera a producción es un cambio de
   scoring/exposición y requiere tu instrucción explícita, con la evidencia de §5: mejor Sharpe y DD que
   PROD, no más retorno que SPY, sin 10 % neto.
2. **Cash en T-bill / fondo monetario** en la cuenta real: decisión operativa; vale +0.1-0.2 pp/año medido
   y ~+0.5 pp a los tipos actuales.
3. **Comprar Norgate ($630/año)** para medir el universo de producción (Russell): sin eso, todo lo anterior
   es S&P 500 y no se extrapola.
4. **Objetivo:** si el 10 % neto sin apalancamiento sigue siendo el requisito, esta familia de estrategias
   no lo cumple sobre datos honestos; la alternativa pasiva (SPY) rinde más con el doble de drawdown. La
   decisión de qué se quiere optimizar — retorno o retorno por unidad de riesgo — es tuya.
