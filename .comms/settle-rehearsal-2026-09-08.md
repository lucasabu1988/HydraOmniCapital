# Ensayo del settle, 2026-09-08

## USA ESTO (2026-09-08, tras ensayar la secuencia entera contra una copia)

```
python daily.py                      # tu, primero: necesita el cierre real
python settle.py --fills fills.csv   # snapshot + diff, y PARA. Lee el diff.
python settle.py --fills fills.csv --write \
                 --positions posiciones.csv --cash-total <caja del broker>
```

`settle.py` no toca ninguno de los CLI congelados: los **invoca**. Hace por ti las dos cosas que
esta nota te dejaba recordar a las nueve de la mañana, y ademas se niega a dejarte cometer el error
que encontre ensayandolo. Las tres cosas, en orden de gravedad:

**1. Confirmar antes de `daily.py` duplica el libro, sin un solo mensaje de error.**
`confirm_fills` empareja contra el **ledger**, y el ledger esta vacio hasta que `settle()` corre
dentro de `daily.py`. Ensayado sobre una copia: los 26 fills entraron como
`confirmed_unplanned  matched False`, y la rama `else` de `core/fills.apply_confirmations`
**los aplica igualmente** a unidades y caja del tramo — mientras los 30 pending siguen pendientes y
`daily.py` los liquida otra vez al dia siguiente. Posicion doble y caja descuadrada.
`settle.py` lo detecta y **se niega** (`order guard`), diciendo que falta `daily.py`.

**2. Los nombres que no compraste necesitan una fila con `units=0`.** Cuatro de las 30 ordenes no
caben ni a una accion (**SLAB, SNDK, LITE, QQQ** — medido sobre las ordenes reales). Sin fila en el
CSV, su fill *presumido* se queda en el libro como real, al precio estimado del plan.
`settle.py` avisa nombrandolos.

**3. `verify_state` va a dar `ERROR replay_cash`, y NO es un problema.** `accrue_interest` acredita
a cada tramo su `cash * factor` con la caja **anterior** a la confirmacion; luego `confirm_fills`
mueve esa caja, y `core/state_check.replay` reparte el interes del sleeve por **pesos posteriores**
(`_apply_interest`). Resultado: hasta 8 `ERROR replay_cash` con diferencias de centimos.
Medido en el ensayo: **totales por manga identicos (0.00e+00), unidades identicas, diferencia
maxima por tramo 0.2293 USD**. `settle.py` lo comprueba cada vez y lo explica con los numeros
delante, en vez de dejarte una pantalla roja. Si aparece **cualquier** otro codigo, o si el total de
una manga no cuadra, lo reporta como fallo real. El arreglo de fondo es registrar el interes **por
tramo** para que el replay no tenga que repartirlo: `TASK-415`, despues del settle.

**Y el residual no va a ser cero: va a ser ~-12,75.** El interes esta en el libro y no en el broker,
y `reconcile` calcula `broker - state` sin restar nada a proposito. `settle.py` lo netea y te dice
lo que queda **sin explicar** (en el ensayo: `-0.00`, 0.000% del equity). El interes real devengado
por una barra al ultimo ^IRX medido (3,757%) sobre 85.550,13 de caja post-settle:
**12,7544 USD**, calculado con la funcion de verdad.

---

## 0. Lo que NO se pudo ensayar, y por que

`python daily.py` **no se corrio**. Dos razones, ambas verificadas leyendo el codigo:

1. El mercado estaba abierto: `daily.py` valoriza contra barras de yfinance y habria settleado
   contra una barra parcial.
2. `daily.py` **no acepta `--state-dir` ni `--state`**. Sus flags son `--universe`,
   `--refresh-pnl/--pnl`, `--no-instructions`, `--skip-screener`, `--v9`, `--v9-capital`,
   `--force`, `--note`. Llama `run_v9(capital=..., force=...)` sin `state_dir`, asi que
   `portfolio_v9.run` usa siempre `DEFAULT_STATE_DIR = hydra_screener_local/state`.
   **CORRECCION (revision adversarial de esta nota, 2026-09-08):** `daily.py` no acepta la bandera,
   pero **`portfolio_v9.py` si** — `--state-dir` (linea 441), y `main()` lo pasa al **mismo** `run()`
   que invoca `daily.py`. El paso 1 **si se puede ensayar** contra una copia:
   `python portfolio_v9.py --state-dir <copia> ...`, y de hecho el verificador lo corrio completo
   (7 filas de preflight, `settled 30 fill(s) at 2026-09-08`, `plan 2026-09-08`,
   `instructions_20260908.md` dentro de la copia, respaldo en `<copia>/backup/`).
   **Con una condicion que no es opcional:** `run()` llama `copy_state_off_disk`
   **incondicionalmente** (`portfolio_v9.py:413`), asi que hay que apuntar `HYDRA_BACKUP_DIR` a un
   directorio temporal antes de correrlo — si no, el ensayo escribe en la copia OneDrive del libro
   vivo, que es exactamente la contaminacion de respaldo que ya nos paso una vez.
   Lo unico que queda sin ensayar de verdad es el **fetch de yfinance** (necesita el cierre real).

Para poder ensayar la mitad de la confirmacion hacia falta un ledger no vacio, asi que se llamo
`core.portfolio_engine.settle()` directamente sobre la copia, con cierres sinteticos
(script: `Temp\hydra_settle_rehearsal_20260908\simulate_settle.py`). Es exactamente la funcion que
`daily.py` invoca, pero sin red, sin preflight, sin `plan()` y sin escribir en `state/`.

**Queda sin ensayar:** el fetch de yfinance, el preflight, la eleccion de `exec_date`, `plan()`
(la hoja nueva), el journal y el backup off-disk. Es decir: el paso 1 completo.

---

## 1. El hallazgo grande: el ORDEN es obligatorio, y equivocarlo cuesta dinero

`confirm_fills.py` **no mira `state["pending"]`**. Empareja las filas del CSV contra
`state["ledger"]`, y el ledger **esta vacio hoy** (0 entradas, 30 ordenes en `pending`).
Solo `settle()` — o sea `daily.py` — convierte `pending` en entradas `filled` del ledger.

Consecuencia medida sobre la copia:

| escenario | resultado observado |
|---|---|
| `daily.py` primero, luego `confirm_fills` (orden correcto) | 29/30 filas `confirmed  True`, 1 `confirmed_unplanned` (la fila inventada de VOO). Libro correcto. |
| `confirm_fills` **antes** de `daily.py` | **las 30 filas** salen `confirmed_unplanned  False`. Se aplican al libro **y las 30 ordenes siguen en `pending`**. Cuando despues corre `daily.py`, `settle()` las vuelve a bookear: ledger 60 entradas, SLAB con 2,4693 unidades en vez de 1, cash de `stocks[0]` y `etf[0]` en **0,00** exactos (el motor clampea la compra al cash disponible). Posiciones dobles y el tranche descapitalizado. |

Peor aun: si en ese estado doble `last_run_date` ya vale `2026-09-08`,
`python verify_state.py` dice **"state check: clean (0 findings)"** sobre un libro con posiciones
dobles y cash cero. Verificado. `verify_state.py` reconstruye el libro *desde el ledger*, asi que
un ledger duplicado es internamente consistente y no lo detecta.

**El unico que detecta la duplicacion es `reconcile.py`**: contra el CSV del broker dio
`quantity-diff 22`, `missing 2`, residual **10.082,29 USD (10,084% del equity)**.

> Regla: `daily.py` **siempre** antes de `confirm_fills.py`. Y `reconcile.py` no es opcional.

---

## 2. Secuencia que funciona (flags reales, verificados)

Desde `C:\Users\caslu\HydraOmniCapital\hydra_screener_local`:

```
REM 1) settle de las 30 al cierre real del 08-09  (NO se pudo ensayar; ver seccion 0)
python daily.py

REM 2) leer el diff, no escribe nada
python confirm_fills.py --report --from-csv fills_20260908.csv

REM 3) escribir  (save_state hace backup antes)
python confirm_fills.py --from-csv fills_20260908.csv

REM 4) libro vs broker, read-only  (--cash-* es OBLIGATORIO, ver abajo)
python reconcile.py positions_20260908.csv --cash-total 85082.29

REM 5) replay del ledger
python verify_state.py
```

Ojo con los flags, **son distintos en cada script**:

| script | flag de estado | apunta a | default |
|---|---|---|---|
| `daily.py` | **ninguno** | siempre `state/` | — |
| `confirm_fills.py` | `--state-dir <dir>` | el **directorio** | `state/` |
| `reconcile.py` | `--state <fichero.json>` | el **fichero** | `state/portfolio_v9.json` |
| `verify_state.py` | `--state <fichero.json>` | el **fichero** | `state/portfolio_v9.json` |

`verify_state.py --state-dir ...` es un error de argparse. `reconcile.py` tambien.
El fichero de estado se llama `portfolio_v9.json`, no `state_v9.json`
(`state_v9` es solo el nombre del subdirectorio dentro de `HYDRA_BACKUP_DIR`; ya no queda
ninguna referencia a `state_v9.json` en el repo).

Codigos de salida medidos: `confirm_fills` 0 ok / 1 sin estado o sin `--from-csv`;
`reconcile` **siempre 0** (incluso con residual de 10k — hay que LEER la salida);
`verify_state` 0 limpio / 1 si hay algun `ERROR` / 2 si se pide `--restore` sin `--yes`.

---

## 3. Formato del CSV de fills

Cabecera exacta (de la docstring de `confirm_fills.py` y de `core/fills.py`):

```
exec_date,sleeve,tranche,ticker,side,units,price,fee
```

| columna | valor | notas duras |
|---|---|---|
| `exec_date` | `2026-09-08` | **la fecha del CIERRE en que se ejecuto**, no el dia en que se corre el script. Alias aceptado: `date`. |
| `sleeve` | `stocks` o `etf` | minusculas exactas |
| `tranche` | `0` | hoy las 30 ordenes son tranche 0 |
| `ticker` | `SLAB` | **MAYUSCULAS** |
| `side` | `buy` o `sell` | **minusculas** |
| `units` | `20` | acciones enteras; `0` = no se ejecuto (ver 4.2) |
| `price` | `15.9412` | precio de fill, punto decimal |
| `fee` | `0.35` | comision de esa linea; alias aceptado: `cost` |

La clave de emparejamiento es la tupla **(`exec_date`, `sleeve`, `tranche`, `ticker`, `side`)**.
Si cualquiera de los cinco no coincide con la entrada del ledger, la fila no empareja y se
registra como `confirmed_unplanned` — que es la ruta de la doble contabilizacion.

## 3b. Formato del CSV de posiciones del broker (`reconcile.py`)

```
ticker,units
AES,22
AG,15
```

Solo dos columnas y es tolerante: acepta `ticker`/`symbol` y `units`/`qty`/`quantity`/`shares`,
en cualquier capitalizacion (probado con `Symbol,Qty`: informe identico). Si no encuentra la
columna de cantidad usa la segunda columna. Suma duplicados por ticker.

**El cash NO va en el CSV**, va por flag y sin flag el script no hace nada:

```
python reconcile.py positions.csv --cash-total 85082.29
python reconcile.py positions.csv --cash-stocks 43383.29 --cash-etf 41699.00
```

Sin ninguno de los tres imprime `[v9] reconcile: pass --cash-total or --cash-stocks/--cash-etf`
y sale 0. En modo `split` el cash del libro por sleeve incluye **los 4 tranches**
(p.ej. `stocks 43.383,29` = 5.883,29 del tranche 0 + 3 x 12.500 sin invertir), asi que hay que
inventarse un reparto; con una sola cuenta en el broker, **usar `--cash-total`**.

---

## 4. Defectos y trampas encontradas (nada se arreglo; solo se documenta)

### 4.1 CSV desde Excel: dos formas de romperlo, una silenciosa
`read_csv` abre con `encoding="utf-8"` y `csv.DictReader` por defecto (coma).

- **"CSV UTF-8" de Excel mete BOM** entonces la primera cabecera pasa a ser `\ufeffexec_date`,
  `exec_date` queda vacio y **las 30 filas salen `confirmed_unplanned`, sin ningun error**.
  Es la peor trampa del dia: `--report` no falla, solo se ve un hueco al principio de cada linea
  (` stocks 0 buy SLAB ...` en vez de `2026-09-08 stocks 0 buy SLAB ...`).
- **Excel en español guarda con `;`** entonces `KeyError: ''` con traceback en `core/fills.py:21`.
  Feo pero seguro: revienta en `--report`, antes de escribir.

> Guardar el CSV como **UTF-8 sin BOM, separado por comas**. El Notepad de Windows en "UTF-8"
> mete BOM; Notepad++ / VSCode permiten "UTF-8 sin BOM".

### 4.2 No hay forma de decir "esta orden no se ejecuto"
El CSV no tiene columna de estado y el ledger tiene un `not_filled` que el CSV no puede producir.
Dos comportamientos medidos:

- **Omitir la fila**: la entrada presumida se queda en `status: "filled"` con las unidades y el
  precio presumidos, **sin ningun aviso**. En el ensayo, LITE quedo con 0,3681 unidades fantasma
  en `stocks[0]` a 879,9331. `confirm_fills` **nunca avisa de un fill planificado que falta en el
  CSV**. Lo cazo `reconcile.py`: `LITE missing 0.3681` y residual **324,201931**, que es
  exactamente `dollars 323,878053 + cost 0,323878` de esa entrada fantasma, al centimo.
- **Poner `units=0, price=0, fee=0`**: funciona. Revierte el fill presumido, la posicion
  desaparece del tranche y el cash vuelve. Queda una entrada `status: "confirmed"` con
  `price 0.0`. Cosmeticamente raro, contablemente correcto y `verify_state` lo aprueba.
  **Esta es la forma de registrar un no-fill.** (Verificado con SNDK.)

### 4.3 `--report` no muestra el diff
Imprime la misma tabla que el modo escritura: solo los numeros **nuevos**. `core/fills.py` calcula
`old_units` / `old_price` pero `report_lines()` no los imprime. No hay columna "antes vs despues".
Lo que si es cierto: `--report` **no escribe nada** (comprobado: sha256 del JSON de la copia
intacto, `backup/` no se creo) y sirve para detectar el CSV mal formado antes de tocar el libro.
El WARN de fill no planificado sale **duplicado** (una vez desde `report_lines`, otra desde `main`).

### 4.4 El precio presumido se pierde (la afirmacion del orquestador: **confirmada, con matiz**)
`apply_confirmations` hace `fill.update(units=..., price=..., cost=fee, dollars=units*price,
status="confirmed")`, es decir **sobrescribe `price` en sitio**. Medido en SLAB:

| campo | antes (presumido por `settle`) | despues de confirmar |
|---|---|---|
| `units` | 1,4693304794 | 1,0 |
| `price` | 220,4256 | 220,2272 |
| `dollars` | 323,878053 | 220,2272 |
| `cost` | 0,323878 | 0,35 |
| `status` | `filled` | `confirmed` |
| `est_units` | 1,4683019758 | **1,4683019758 (sobrevive)** |
| `est_price` | 220,5800018311 | **220,5800018311 (sobrevive)** |

Matiz importante: lo que sobrevive es la **estimacion de la hoja** (`est_price`, `est_units`,
`planned`, `week`, `cost_bp`). El **precio presumido del fill** (el cierre con que `settle`
bookeo) desaparece del estado; solo queda en `state/backup/<ts>.json`. Si se quiere comparar
"presumido vs real", hay que hacerlo **antes** de confirmar, o desde el backup.

### 4.5 Las filas `confirmed_unplanned` entran con tipos de CSV
La entrada creada para una fila sin fill previo es `dict(row, cost=fee, dollars=..., status=...)`,
o sea **strings crudos del CSV**: `"tranche": "0"`, `"units": "1"`, `"price": "705.12"`, mas una
clave `fee` que ninguna otra entrada tiene, y **sin `planned` / `week` / `cost_bp` / `est_*`**.
`_f()` las coacciona al leer, asi que el replay cuadra, pero el ledger queda con esquema mixto.

Efecto colateral medido: al no tener `planned`, esa fila rompe la excepcion de `state_check`
para `ledger_future` y `verify_state` reporta
`ERROR ledger_future  ledger 2026-09-08 > last_run_date 2026-09-04`.
**Esto solo pasa si `last_run_date` es anterior al `exec_date`.** Con `last_run_date = 2026-09-08`
(lo que `plan()` estampa manana) el mismo estado sale **limpio**. Verificado en las dos direcciones.

### 4.6 `side` en mayusculas: confirmacion muda que no hace nada
Muchos exports de broker escriben `BUY`. Medido con `side=BUY` en las 30 filas:
las 30 salen `confirmed_unplanned`, el ledger pasa de 30 a **60** entradas, y
**el cash y las unidades del libro no se mueven** (`stocks[0]` sigue en 5.367,56 y SLAB sigue con
las 1,4693 unidades presumidas), porque `_apply_side` solo actua con `"buy"`/`"sell"` en
minusculas. La confirmacion no hace nada y deja 30 entradas basura. Igual con el ticker en
minusculas (`slab` sale `confirmed_unplanned`).

### 4.7 El typo mas probable: `exec_date` = el dia en que se corre
Con `exec_date=2026-09-09` (dia de la corrida) en vez de `2026-09-08` (dia del cierre):
30 filas `confirmed_unplanned`, ledger 60, posiciones dobles y **cash negativo**
(`stocks[0] -924,95`, `etf[0] -3.442,63`). Este si lo caza `verify_state`:
`ERROR cash_negative`. Recuperable con el backup (seccion 5).

### 4.8 Las ordenes de la hoja son FRACCIONARIAS
La hoja del 04-09 pide 0,1861 acciones de SNDK y 0,3675 de LITE, entre otras. El redondeo a
acciones enteras **no esta en el camino live**: `floor_orders_to_whole_shares` vive en
`experiments/engine_backtest.py` (TASK-407), no en `core/`. O sea: **el redondeo lo decide Lucas
en el broker**, y por eso *todas* las 30 filas van a diferir en cantidad respecto al plan.
Es normal y `confirm_fills` lo absorbe bien. Dos nombres no son ejecutables en enteros
(SNDK 0,19 y LITE 0,37 acciones): esos son los candidatos naturales al `units=0` de 4.2.
Aparte: `SNDK` figura con `est_price 1740,00`. Conviene mirar ese precio antes de mandar la orden.

### 4.9 Idempotencia: si, funciona
Correr el mismo CSV dos veces sobre el mismo estado: ledger sigue en 31 entradas, cash identico
(`stocks[0] 5.883,29`, `etf[0] 3.874,80`), unidades identicas. Se crea un backup nuevo en cada
corrida. Seguro reintentar.

### 4.10 Consola cp1252
Los tres scripts hacen `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`, asi que
**no hay crash de encoding**. Se probo con codepage 850 y `stdout.encoding=cp1252`. El unico
efecto es cosmetico: `reconcile.py` imprime un guion largo cuando `last_run_date` es nulo y lo
escribe como bytes UTF-8 (`\xe2\x80\x94`), que en `cmd.exe` con codepage 850 se ve como basura.
Sin consecuencias.

---

## 5. Backups y recuperacion (verificado)

`confirm_fills.py` en modo escritura llama `save_state`, que **copia el estado anterior a
`<state-dir>/backup/<AAAAMMDD_HHMMSS>.json` antes de escribir**. Confirmado: aparecio
`copyB\backup\20260908_092414.json` (17.526 bytes) y un segundo fichero en la segunda corrida.
`save_state` **no** toca `HYDRA_BACKUP_DIR` (eso solo lo hace `copy_state_off_disk`, dentro de
`portfolio_v9.run`, o sea solo `daily.py`). `HYDRA_BACKUP_DIR` esta puesto a
`C:\Users\caslu\OneDrive\HydraBackups` y ninguna corrida de este ensayo lo modifico.

Si la confirmacion sale mal:

```
python verify_state.py --state state\portfolio_v9.json --restore state\backup\<AAAAMMDD_HHMMSS>.json
        (sin --yes: imprime el chequeo del backup y se niega, exit 2)
python verify_state.py --state state\portfolio_v9.json --restore state\backup\<AAAAMMDD_HHMMSS>.json --yes
```

Probado sobre la copia rota de 4.7: restauro el estado, dejo el roto en
`backup\<ts>_replaced.json` y `verify_state` volvio a `clean (0 findings)`.

---

## 6. Riesgo de timing en el paso 1 (leido, no ensayado)

`daily.py` corre v9 con `ALGO_VERSION == "v9"` (confirmado en `config.py`), asi que
`python daily.py` si dispara el CLI v9 y el flag `--v9` es redundante. Pero antes corre el
screener completo con `--universe all` (minutos y red). `--skip-screener` salta esa parte y
**el bloque v9 sigue corriendo** (esta fuera del `if`), aunque eso no se pudo probar.

El preflight tiene un check **HARD**: las ultimas barras de `stocks`, `etf` y `^IRX` deben ser
las tres iguales **y** iguales a la ultima sesion NYSE anterior o igual a ahora. Si se corre el
09-09 antes de que yfinance haya impreso la barra del 09-09 (o si `^IRX` va con retraso), da
`last bar 2026-09-08 != last NYSE session 2026-09-09` y luego
`SystemExit: preflight hard fail`, y **no settlea**. Hay `--force`, pero deja pasar tambien el
`plan()` con datos rancios.

> Correr `daily.py` **despues del cierre del 09-09**, con las tres series ya impresas, y sin
> `--force`. Si el preflight falla, leer que check es antes de forzar.

---

## 7. Checklist para manana

1. Tener el CSV de fills **UTF-8 sin BOM, comas**, cabecera
   `exec_date,sleeve,tranche,ticker,side,units,price,fee`, con
   `exec_date=2026-09-08`, `side` en minusculas, tickers en MAYUSCULAS.
2. Las ordenes no ejecutadas: fila con `units=0,price=0,fee=0` (no omitirla).
3. Tener el CSV de posiciones del broker (`ticker,units`) y **el cash total** del broker.
4. Correr `daily.py` **primero**, despues del cierre del 09-09. Nunca `confirm_fills` antes.
5. `confirm_fills --report` y contar: deben salir **30 lineas `confirmed  True`**.
   Cualquier `False` o cualquier `[WARN] unplanned` significa que el CSV esta mal.
   **Parar y arreglar el CSV**; no pasar al modo escritura hasta que no haya ni un `False`.
6. Antes de escribir, si se quiere comparar presumido vs real: guardar copia de
   `state\portfolio_v9.json` (el modo escritura pisa `price` en sitio).
7. `confirm_fills` sin `--report`. Apuntar la ruta del backup que imprime.
8. `reconcile.py` con `--cash-total`. Objetivo: `missing 0`, `unknown 0`, `quantity-diff 0` y
   residual **≈ el interes devengado**, NO 0 — y esto lo corrige la revision adversarial de la nota:
   `accrue_interest` se llama desde **`plan()`** (`core/portfolio_engine.py:229`), no desde
   `settle()`, asi que el ensayo con `settle()` a secas no lo vio. Compone la caja de cada tramo
   por cada barra del calendario en `(last_run_date, hoy]` y **la escribe dentro del libro**
   (`tr["cash"] = cash * factor`, linea 208). Ese dinero esta en el libro y no en el broker, asi
   que el residual no puede ser cero: con 85.560,91 USD de caja despues del settle (100.000 menos
   los 14.439,09 de las ordenes) y el ultimo print de ^IRX medido, 3,757% del 2026-09-04, **una
   sola barra son ~12,76 USD**; el run de mañana cubre al menos una (09-05 y 09-06 fin de semana,
   09-07 Labor Day). `reconcile.py:194` ya imprime una linea `interest recorded`: el objetivo
   correcto es **residual ≈ interest recorded**, netearlo, y solo entonces leer lo que sobre como
   un fill sin confirmar.
9. `verify_state.py`. Debe decir `clean (0 findings)` y salir 0. **Y aun asi, si el paso 8 dio
   residual, el libro esta mal: `verify_state` no ve duplicados ni fills olvidados.**

---

## 8. Comandos exactos del ensayo (reproducibles)

```
SCR=C:/Users/caslu/AppData/Local/Temp/hydra_settle_rehearsal_20260908
python %SCR%/simulate_settle.py %SCR%/copyB 2026-09-08
python confirm_fills.py --report --from-csv %SCR%/fills_20260908.csv --state-dir %SCR%/copyB
python confirm_fills.py          --from-csv %SCR%/fills_20260908.csv --state-dir %SCR%/copyB
python reconcile.py %SCR%/positions_20260908.csv --state %SCR%/copyB/portfolio_v9.json --cash-total 85082.29
python verify_state.py --state %SCR%/copyB/portfolio_v9.json
```

Suites relevantes, sin tocar codigo:
`python -m pytest test_confirm_fills.py test_reconcile.py test_state_check.py test_portfolio_state.py -q`
da **22 passed in 1.01s**.
