# HYDRA — Auditoría general del proyecto

**Autor:** Claude (architect) · **Fecha:** 2026-09-06
**Alcance:** todo lo que el deep-dive del 05-09 no cubrió: capa de datos (`data/`), el bucle de
medición (`core/tracking.py`, `core/history.py`, Excel), orquestación (`daily.py`,
`live_watcher.py`), la capa Pine, y el proyecto raíz (CI, docs de agentes, dependencias).
**Método:** lectura completa de los módulos + comprobación empírica de cada afirmación cuantitativa
sobre el panel cacheado (503 S&P 500, 2020-2026) o sobre descargas puntuales.
**Estado:** solo análisis. No se tocó código salvo declarar `scipy` en `requirements.txt` (deuda mía).
Grok tiene activas TASK-321/322/323/324; ningún hallazgo de aquí se ha convertido en tarea todavía.

---

## 0. Lo que importa, en una tabla

| # | Hallazgo | Área | Severidad | Evidencia |
|---|---|---|---|---|
| T1 | `tracking.py` mide "5d" como **3 días de bolsa** en el 65% de los casos | Medición | **Crítica** | −18.1 bp/ciclo de sesgo |
| T2 | Nombres delistados/adquiridos desaparecen del win-rate en silencio | Medición | **Crítica** | `continue` sin contar |
| T3 | Todo `history/*.json` anterior a TASK-315 lleva el régimen equivocado, sin re-etiquetar | Medición | Alta | 0.793 vs 0.693 |
| R1 | El gate de régimen mira SPY para un universo mitad Russell | Algorítmica | **Alta** | 12.5% de días en desacuerdo; IWM −15.8 bp en ellos |
| D1 | Un lote de descarga que falla encoge el universo sin avisar | Datos | Alta | `except: continue`, 40 lotes/día |
| D2 | No hay comprobación de que los datos sean de hoy | Datos | Alta | ningún guard de fecha |
| D3 | El filtro de liquidez es en acciones, no en dólares | Algorítmica | Alta | 100k acc. × $5 = $500k/día |
| P1 | Pine y Python discrepan en el strict filter sin volumen | Contrato | Alta | Python `False`, Pine `True` |
| S1 | CI no ejecuta **ni un** test del screener | Proceso | Alta | workflow: solo `tests/` legacy |
| S2 | 5 docs de agentes describen un sistema borrado como si fuera el actual | Proceso | Alta | ya causó un error (MAX_PER_SECTOR=3) |
| S3 | `history/` vive solo en un disco, sin versión de esquema | Estructural | Media | gitignored, no existe en este clone |
| S4 | Dos sistemas de P&L (JSON y Excel) sin reconciliación | Estructural | Media | lógicas de entrada distintas |
| A1 | El contrato de salida no tiene tamaño de posición | Algorítmica | Media | equal-weight implícito en todo |
| A2 | El timing de entrada no está estudiado y hay señal de que importa | Algorítmica | Media | lag 1 > lag 0 en +4.5 bp |
| A3 | Todo se midió en S&P 500; producción corre ~3000 con Russell 2000 | Algorítmica | Media | sin datos small-cap |

La conclusión de fondo, igual que en el deep-dive pero un nivel más arriba: **el sistema tiene más
problemas en cómo se mide a sí mismo que en cómo elige acciones.** El scoring está razonablemente
auditado ya. El bucle que dice "esto funciona" — tracking, historial, régimen etiquetado, costes —
es donde hoy no se puede confiar en ningún número.

---

## 1. El bucle de medición (`core/tracking.py`, `core/history.py`)

### T1 — "5d" no son 5 días de bolsa. Son 3, casi siempre.

`compute_forward_returns_for_run` hace `target_date = run_date + timedelta(days=h)` con
`h = 5`: **días de calendario**. Luego `_nearest_price` avanza hasta el primer día con precio. El
sistema está diseñado explícitamente para ciclos de **5 días de bolsa** (SPEC §1). Medido sobre las
258 fechas de rebalanceo del panel:

```
HORIZONTE REAL que mide tracking.py cuando dice "5d":
   2 días de bolsa:  17 ciclos ( 7%)
   3 días de bolsa: 168 ciclos (65%)
   4 días de bolsa:  54 ciclos (21%)
   5 días de bolsa:  19 ciclos ( 7%)
```

Un lunes mide 5 días de bolsa; un miércoles, jueves o viernes mide 3. El horizonte depende del
día de la semana en que corrió el screener. Y el efecto sobre el número que se reporta:

```
tracking.py (entrada = cierre observado, salida = +5 días CALENDARIO) :  26.6 bp/ciclo
misma entrada, salida correcta a +5 días de BOLSA                     :  43.9 bp/ciclo
ejecutable (entrada siguiente cierre, +5 días de BOLSA)               :  44.7 bp/ciclo

sesgo total de tracking.py vs lo ejecutable : −18.1 bp/ciclo
   por horizonte (calendario vs bolsa)      : −17.4 bp
   por entrada (cierre observado vs sig.)   :  −0.8 bp
```

**El win-rate report subestima la estrategia en ~40% de su retorno**, y lo hace con un horizonte
que cambia según el calendario. "10d" tiene el mismo problema (≈6-8 días de bolsa). Cualquier
comparación entre fechas, regímenes o special modes construida sobre esto compara horizontes
distintos sin saberlo.

El segundo componente — entrar al cierre que ya se observó — es una entrada inalcanzable. En
esta muestra cuesta poco (−0.8 bp) pero el signo no está garantizado; lo correcto es medir desde
el primer precio ejecutable.

### T2 — Los nombres que desaparecen, desaparecen del win-rate

```python
if ticker not in prices_df.columns:
    continue
```

`_fetch_prices` baja los tickers recomendados históricamente con yfinance. Un nombre adquirido o
delistado desde entonces no vuelve → la operación se **omite sin contarse**. Las adquisiciones
suelen ser ganadores grandes; los delistados, perdedores grandes. Es sesgo de supervivencia, pero
en el tracking **en vivo**, que es justamente lo que debería ser la medida honesta. No se reporta
cuántos se omitieron.

### T3 — El historial ya guardado tiene el régimen equivocado

TASK-315 corrigió que `screener.py` persistiera el régimen rico en vez del simple (0.793 vs 0.693
el mismo día). Pero **todos los `history/*.json` anteriores conservan la etiqueta vieja**, y
`aggregate_winrate` agrupa por `regime.type` leído de ahí. No hay re-etiquetado ni marca de qué
versión del régimen lleva cada fichero. Cualquier "win-rate por régimen" sobre datos anteriores al
05-09 está agrupando por una variable que no fue la que decidió.

### Menores en este módulo

- `_nearest_price(..., max_offset=7)` en la salida: si falta el día objetivo, toma uno **posterior**.
  Extiende el holding en silencio, siempre hacia adelante.
- `HISTORY_DIR = "history"` (relativo). `tracking.py`, `history.py`, `live_watcher.py`
  (`Path("history")`) y `log_cycle_positions.py` (`'backtest/portfolio_cycles.xlsx'`) dependen
  del CWD. `daily.py` fija `cwd=ROOT`; una invocación directa desde otro directorio escribe el
  historial donde caiga.
- El JSON de historial no lleva versión de esquema. `regime_gate_blocked` se añadió ayer; los
  ficheros viejos no lo tienen y todo consumidor tiene que adivinar. El resumen Pine sí tiene
  `contract_version` — el historial, que es más importante, no.

---

## 2. Régimen: el índice equivocado para el universo (R1)

`compute_rich_regime_scores(spy, ...)`: todo el régimen — y por tanto el gate de exposición y
`dynamic_count` — se calcula sobre **SPY**. El universo de producción es `"all"`: S&P 500 ∪
Nasdaq-100 ∪ Dow ∪ Russell 1000 ∪ **Russell 2000**. Alrededor de dos tercios de los nombres son
mid/small caps cuyo régimen no es el de SPY.

Medido 2020-2026, SPY vs IWM (Russell 2000), criterio SMA200:

```
SPY > SMA200 pero IWM < SMA200 : 210 días (12.5%)
SPY < SMA200 pero IWM > SMA200 :  22 días ( 1.3%)
racha más larga "SPY dice risk-on, small caps bajo tendencia": 54 días de bolsa

IWM retorno 5d medio cuando SPY>SMA y IWM<SMA : −15.8 bp
IWM retorno 5d medio cuando ambos > SMA         : +31.6 bp
```

Uno de cada ocho días el gate dice "adelante" mirando large caps mientras el segmento que domina
el universo está bajo su tendencia y rinde negativo. La asimetría (12.5% vs 1.3%) no es ruido:
small caps se quedan atrás de SPY durante meses (2023-2024 entero). **El gate es ciego al segmento
del universo con más probabilidad de estar en problemas.**

No es un ajuste de parámetro: es que la variable de estado se mide en un activo distinto del que
se opera. Opciones: régimen sobre un proxy del universo real (equal-weight del propio universo, o
IWM/RSP), o régimen por segmento con el gate aplicado por nombre según su segmento. Cualquiera es
cambio de scoring (regla 6) y necesita TASK-324 para validarse.

---

## 3. Capa de datos (`data/fetch.py`, `data/universe.py`)

### D1 — Un lote que falla no existe

```python
except Exception as e:
    print(f"✗ Error: {e}")
    continue
```

`fetch_prices_and_volume` descarga en lotes de 75. Con `UNIVERSE="all"` son ~40 lotes. Si Yahoo
devuelve error en uno — rate limit, timeout, un ticker roto que tumba el lote — **75 nombres
desaparecen del universo ese día**, con un `print` y nada más. No hay recuento al final, no hay
umbral de aviso, no hay reintento del lote. Compárese con el watchdog de volumen (TASK-202/314),
que avisa cuando falta el 20% del volumen: para los precios, que son el input primario, no existe
el equivalente. La lista recomendada puede cambiar de un día a otro por una razón que no es de
mercado y que nadie ve.

### D2 — Nadie comprueba que los datos sean de hoy

No hay ninguna verificación de que la última barra del panel sea la sesión esperada. Si yfinance
devuelve datos que terminan hace tres días (pasa: caché de Yahoo, feriado mal manejado, fallo
parcial), el screener puntúa precios viejos como si fueran de hoy, `ret_short` y `dist_to_high`
salen de una fecha distinta a la que el usuario cree, y el historial se guarda con la fecha de
ejecución. El zombie filter detecta series *planas*, no un panel *atrasado*. Comprobado en el
panel cacheado: hoy 0 tickers atrasados — pero eso es suerte, no un guard.

### D3 — Liquidez medida en acciones, no en dólares

`FILTERS["min_avg_volume"] = 100_000` **acciones**. Con `min_price = 5`, una acción de $5 con
100k de volumen medio pasa el filtro con **$500k/día** de negociación. En el S&P 500 esto no
muerde (todos pasan; mi barrido con `min $vol 20M` no cambió nada por eso). En Russell 2000,
sí: entran nombres donde una posición modesta es un porcentaje relevante del volumen diario, en
una estrategia que rota el 39% de la cartera cada semana. El filtro correcto para este universo es
en dólares (ADV$), y la propia SPEC §1 dice que las reglas de selección son "implementation-specific"
— no es cambio de scoring.

### D4 — Sin capa de normalización de tickers

Cada fuente hace su `.strip().upper()` y nada más. La conversión `BRK.B → BRK-B` (formato Yahoo)
aparece solo en un docstring. Los dos tickers con punto del caché S&P (`BF.B`, `BRK.B`) se
manejan **individualmente en la blacklist** — o sea, la normalización se hace por excepción, no
por regla. Las fuentes Russell (slickcharts, barchart, nasdaq) traen su propio formato; cualquier
clase-A/B con punto (`PBR.A`, `LEN.B`, `UHAL.B`, `HEI.A`…) llega a yfinance en formato incorrecto,
falla, y se pierde vía `dropna(how='all')` — alimentando D1 en silencio.

### D5 — Duplicación y código muerto

- `fetch_prices` y `fetch_prices_and_volume`: ~80 líneas casi idénticas. La primera devuelve
  `pd.DataFrame()` en el early-exit y una tupla en el camino normal (tipo de retorno inconsistente:
  el caller que desempaque una tupla revienta). Solo la usa `experiments/run_real_headless.py`.
- `data/universe.py`: 1425 líneas, 14 fetchers con la misma estructura copiada (TASK-316 arregló
  una de las cinco copias de una sola cosa), y **~375 líneas de tickers hardcodeados** como fallback
  (líneas 339-714). Un fallback hardcodeado envejece sin avisar; es el "SNDK delisted 2016" pero a
  escala.

---

## 4. Capa Pine (`pine/HYDRA_Screener.pine`)

Pine es una **segunda implementación** del scoring, por símbolo. `validate_pine_contract.py` valida
que el JSON se parsea — no que las fórmulas coincidan. Y no coinciden:

### P1 — Strict filter sin volumen: Python dice no, Pine dice sí

```pine
strict = ret_s > i_strict_ret and dist_h >= i_strict_dist and (vrat > dth or na(vrat))
```

Sin volumen (`na(vrat)`), **Pine aprueba**. Python: `vol_ratio.fillna(0.0) > 1.5` → `False`. Y la
SPEC §5 es explícita: *"Volume missing: vol_ratio treated as 0 (fails strict filter)"*. Verificado
con un nombre sintético que cumple ret y dist sin volumen: Python `passes_strict=False`, Pine `True`.
El usuario ve en TradingView un `strict` verde que Python negó, sobre el mismo nombre, el mismo día.

### P2 — Fórmula de volatilidad distinta

`v = ta.stdev(ta.change(c)/c, i_vol_len)` es `(c − c[1]) / c` — retorno dividido por el precio
**actual**. Python usa `pct_change` = `(c − c[1]) / c[1]`. Diferencia pequeña por barra, pero es una
fórmula distinta, y con `math.max(v, 0.0001)` Pine devuelve un momentum enorme donde Python devuelve
`NaN`. Los composites que muestra la tabla de TV no son los de Python; son parecidos.

### P3 — Lo que Pine no puede hacer, y lo que eso implica

Pine no puede hacer nada transversal: ni sector cap, ni ranking, ni `dynamic_count`. Por diseño el
flag "Rec?" viene del JSON pegado — bien. Pero cada cambio de scoring en Python (hoy: el skip de
momentum si se aprueba, la fórmula de breadth si se toca) exige un cambio manual en Pine, y no hay
ningún test que detecte que se olvidó. P1 y P2 son la prueba de que ya pasó.

---

## 5. Proceso y estructura del repositorio

### S1 — CI no ejecuta ni un test del screener

`.github/workflows/test.yml` corre `pytest tests/` (raíz, motor legacy congelado) y los cinco
`hydra_backtest/*/tests/`. **`hydra_screener_local/run_all_tests.py` no aparece.** El proyecto
activo desde junio tiene cero cobertura de CI; el proyecto congelado tiene 481 tests corriendo en
cada push. Todo lo que rompimos y arreglamos esta semana — el runner en falso verde, el watchdog
muerto, el test roto de TASK-201 — habría sido invisible para CI aunque CI estuviera perfecto.
(Bloqueo conocido: el push del workflow requiere `gh auth refresh -s workflow`, que es de Lucas.)

### S2 — Cinco documentos de agente describen un sistema borrado

`CLAUDE.md`, `AGENTS.md`, `CODEX.md`, `GEMINI.md`, `PROJECT_STATE.md` presentan
`omnicapital_live.py` (borrado en la limpieza del 05-09) como el motor actual, con "live paper
trading since Mar 16, 2026". Cuatro de los cinco no se tocan desde marzo-junio. Solo `GROKBOARD.md`
dice que el foco es el screener.

Esto ya costó dinero de atención: Grok ancló `MAX_PER_SECTOR=3` en el "Sector limit: max 3 per
sector" de `CLAUDE.md` — un parámetro del motor legacy, bajo una taxonomía de sectores distinta
(TASK-318 → 320). Un agente nuevo que lea CLAUDE.md hoy trabajará sobre un sistema que no existe.
Un solo documento vivo por agente; los demás, a `archive/` con fecha.

### S3 — La memoria del sistema vive en un disco

`hydra_screener_local/history/` está en `.gitignore` y no existe en este clone. Es el **único
registro** de qué recomendó el sistema cada día. De él dependen `tracking.py`, `analyze_history.py`,
`live_watcher.py`, `generate_pine_watchlist.py` y `test_hybrid_integration.py`. Sin copia, sin
versión de esquema, sin forma de reconstruirlo. Un disco que falla borra el track record. (Los
precios se pueden volver a bajar; *qué se recomendó* no.)

### S4 — Dos P&L para la misma operación

`core/tracking.py` (JSON) y `log_cycle_positions.py` + `refresh_current_prices.py` (Excel,
`portfolio_cycles.xlsx`) miden lo mismo con lógicas distintas: el Excel usa `_get_next_trading_day`
con calendario Lun-Vie sin feriados y "entry price auto-fetched via yf as of signal"; el JSON usa
`_nearest_price` con `max_offset`. No hay reconciliación. Dos números para la misma operación es
peor que uno malo: no se sabe cuál mirar.

### S5 — Dependencias: dos manifiestos, uno sin pinear

Raíz: `requirements.txt` pineado (`pandas==2.3.3`, `numpy==2.4.2`, `yfinance==1.1.0`). Screener:
`requirements.txt` con `>=` y `pyproject.toml` sin versiones. `yfinance` cambia de API entre
versiones menores (el `fill_method` de pandas ya mordió una vez esta semana); `>=0.2.40` acepta
cualquier cosa. `scipy` lo usaba el harness sin declararlo — mío, corregido en este commit.

---

## 6. Algorítmico: lo que está por encima de los parámetros

### A1 — El sistema no dice cuánto comprar

El contrato de salida (SPEC §7) es una lista con flags. El tamaño de posición no existe en ningún
sitio: el backtest, el tracking y el Excel asumen equal-weight, y en TradingView el usuario decide
a mano. Esto importa porque la única idea de gestión de riesgo que el sistema toma de la literatura
(escalar por volatilidad, Barroso & Santa-Clara) **se aplica en el sitio equivocado** — divide el
score de cada acción por su vol, lo que es un tilt hacia baja volatilidad, en vez de dimensionar la
posición, que es lo que el paper hace. Sin nivel de posición no hay dónde ponerla.

### A2 — El timing de entrada tiene señal y nadie lo ha mirado

En el barrido del deep-dive, entrar al **cierre siguiente** (lag 1) rindió +4.5 bp/ciclo más que
entrar al cierre de la señal (lag 0). No es significativo (p=0.675), pero la dirección es la que
predice la literatura de reversión a una semana (Jegadeesh 1990): el día después de un cierre
fuerte tiende a ser levemente negativo. Para una estrategia que paga 39% de rotación semanal, si la
apertura de D+1 es sistemáticamente mejor que el cierre de D+1 (o al revés), eso es dinero real y
hoy no hay ni un dato de apertura en el proyecto.

### A3 — Se midió en el S&P 500, se opera en Russell

Todo el deep-dive, el harness, la calibración del sector cap y esta auditoría usan 503 large caps.
Producción corre ~3000 nombres, mayoría mid/small. El momentum small-cap tiene más reversión, más
coste, menos liquidez, y — por R1 — un régimen medido en otro índice. El comportamiento del
sistema donde realmente corre no se ha medido nunca. TASK-324 (universo point-in-time) es el
prerrequisito; sin ella, cualquier número de este proyecto es sobre un sistema distinto del que
opera.

### A4 — El suelo de `dynamic_count` deshace la Meta-Layer donde más importa

`dynamic_count = clamp(round(14 × aggression × compass), 6, 28)`. En CRISIS_ACUTE +
ELEVATED_VOL: `14 × 0.612 × 0.60 = 5.1 → 6`. La única palanca real de la Meta-Layer (documentado en
TASK-313) es `dynamic_count`, y justo en su estado más defensivo el suelo de 6 la neutraliza. El
gate de régimen a 0.2975 tampoco entra hasta más abajo. Entre los dos, la respuesta del sistema a
una crisis es "recomienda 6 en vez de 14".

---

## 7. Lo que está bien

Para que el informe no lea como si nada funcionara:

- La **SPEC es fuente de verdad y se está haciendo cumplir**: dos derivas cerradas esta semana, y
  TASK-321 (en curso) convierte eso en un test que falla solo.
- El **runner de tests ya es honesto** (TASK-311), y TASK-323 está eliminando el último rojo
  permanente.
- El **sector control vincula** y el scoring quedó separado de la construcción de cartera (TASK-320).
- El **harness existe y está validado** contra producción. Es la herramienta que hace posible que
  cada afirmación de esta auditoría lleve un número.
- El **protocolo Claude/Grok** ha detectado y corregido problemas reales en cada ciclo. Falla en
  verificación, no en honestidad — y la verificación se está endureciendo.

---

## 8. Qué haría, en orden

Sin tocar lo que Grok tiene abierto (321-324). Propuesta, no cola: Lucas decide qué entra.

**Primero — que los números vuelvan a significar algo:**
1. **T1+T2**: horizontes en días de bolsa; entrada en el primer precio ejecutable; contar y
   reportar los nombres omitidos por falta de datos. Pequeño, y sin él el win-rate miente.
2. **T3**: script de re-etiquetado de `history/` con el régimen rico (recalculable desde SPY) +
   campo `schema_version` en el JSON.
3. **S3**: `history/` a un almacenamiento versionado (repo privado aparte, o al menos un backup
   automático en `daily.py`).

**Segundo — que producción no se degrade en silencio:**
4. **D1+D2**: recuento de lotes fallidos con umbral de aviso (mismo patrón que el watchdog de
   volumen) y guard de fecha de la última barra.
5. **D3**: filtro de liquidez en dólares. No es scoring.
6. **P1**: Pine alineado con la SPEC §5 (sin volumen → strict falla). Es un `or na(vrat)` de menos.

**Tercero — proceso:**
7. **S1**: `run_all_tests.py` en CI. Necesita el `gh auth refresh -s workflow` de Lucas.
8. **S2**: un `CLAUDE.md` que describa el screener; los otros cuatro docs a `archive/`.
9. **S4**: elegir un P&L (el JSON) y retirar el Excel, o reconciliarlos en un test.

**Cuarto — algorítmico, todo detrás de TASK-324:**
10. **R1**: régimen sobre un proxy del universo que se opera. Cambio de scoring; medir en la
    muestra sin supervivencia antes de tocar.
11. **A2**: bajar datos de apertura y medir open-vs-close de D+1. Puro estudio.
12. **A1**: decidir si el sistema emite pesos. Es una decisión de producto, no de código.

Lo que **no** haría: tocar ningún parámetro del scoring por ninguno de estos hallazgos. El deep-dive
ya mostró que no hay señal estadística para eso en la muestra actual, y esta auditoría añade que la
muestra actual ni siquiera es el universo que se opera.
