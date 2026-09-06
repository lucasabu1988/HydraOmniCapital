# HYDRA v9 — Cartera 50/50 T20 + ETF en producción: diseño e implementación

**Autorización:** Lucas, 2026-09-06: "autorizo a llevar 50/50 t20+etf. el objetivo es retorno por unidad de
riesgo. no se ejecuta ningún tracking en la máquina." Es la instrucción explícita que exige la regla 6 para
cambiar scoring y exposición. **Producción sigue en v8.4 hasta que este diseño esté implementado, con paridad
probada contra el simulador y revisado de forma independiente.**
**Integradora:** Claude. **Implementación compartida:** Claude (motor, scoring, SPEC) / Grok (datos, estado,
CLI, hoja de instrucciones). Revisión cruzada obligatoria antes de activar `ALGO_VERSION = "v9"`.
**Evidencia de referencia:** `.comms/claude-audit-2026-09-06.md` §5 (simulador ejecutable): 50/50 = 6.91 % neto,
Sharpe 0.74, maxDD −19.5 %, vol 9.6 %, 9 episodios < −10 %; T20 solo 7.55 / 0.59 / −29.2; PROD 5.48 / 0.42 /
−37.8; SPY 10.96 / 0.68 / −54.7. Simulación sobre S&P 500 PIT, no sobre el universo Russell de producción;
no hay track record.

---

## 1. Qué es v9 (definición operativa)

Una cartera de dos mangas con capital fijo 50/50, operada **manualmente** a partir de una hoja de
instrucciones semanal. No hay bróker conectado, no hay webhooks, no hay órdenes automáticas.

| | Manga A — T20 (acciones) | Manga B — ETF trend |
|---|---|---|
| Capital | 50 % de la cartera, en 4 tramos de 12.5 % | 50 %, en 4 tramos de 12.5 % |
| Universo | el de producción (`UNIVERSE="all"`, filtros prácticos, DQ filter, sector cap 5 GICS, veto) | SPY QQQ IWM EFA EEM TLT IEF GLD DBC VNQ (fijo) |
| Señal | **momentum 12-7**: `close[t−126]/close[t−252] − 1` dividido por vol63 anualizada; boost corto, filtro estricto, `dynamic_count`, régimen y Meta-Layer **sin cambios** respecto a v8.4 | retorno 12 meses (252 barras) − T-bill acumulado > 0 → largo, si no T-bill |
| Selección del tramo | los `n` (dynamic_count) mejores del ranking; un nombre que el tramo ya tiene se conserva si sigue en el top `2n` (buffer) | todos los ETFs "encendidos" |
| Pesos dentro del tramo | iguales × exposición `e = min(1, 0.15 / vol63 de la cesta equiponderada)`; resto en T-bill | inverse-vol (vol63) normalizado sobre **todo** el universo elegible; los apagados dejan su parte en T-bill |
| Ritmo | cada **5 barras de bolsa** se renueva **un** tramo (k = semana mod 4); cada tramo vive 20 barras | igual |
| Mix | cada semana se restablecen los totales de manga a 50/50 (transferencia entre mangas = operaciones reales, con coste) | |
| Cash | T-bill / fondo monetario (decisión operativa de Lucas) | |
| Costes modelados | 10 bp/lado | 5 bp/lado |

Convención temporal (idéntica al simulador): la corrida se hace **tras el cierre del día t** con datos hasta t;
la hoja instruye ejecutar **al cierre de t+1** (MOC). La siguiente corrida asume esas ejecuciones a los cierres
de t+1 (fills presumidos, marcados como tales) salvo que el usuario corrija el estado.

## 2. Qué cambia en el código (y qué no)

**Cambia (autorizado):**
- `core/signals.py`: ventana de momentum seleccionable: `mom_12_7` (v9) además de `ret90` (v8.4). Todo lo
  demás del scoring, igual.
- `config.py`: `ALGO_VERSION = "v8.4"` hasta activar; bloque `V9 = dict(...)` con los parámetros de la tabla
  (pre-especificados en el lab; no se re-optimizan). `fetch` a 2 años cuando v9 (252+126 barras + vol).
- `HYDRA_ALGORITHM_SPEC.md`: §4.1 gana la variante 12-7; nuevo **§9 "Cartera v9"** con esta tabla, la
  convención temporal, el esquema de estado y la hoja de instrucciones. `test_spec_compliance.py` se
  extiende a §9.
- Nuevo `core/tranche_book.py` (movido desde `experiments/`, que pasa a importarlo): unidades/efectivo/valor
  por tramo, operaciones cobradas, write-offs explícitos. Producción no importa de `experiments/`.
- Nuevo `core/portfolio_engine.py` (Claude): puro y sin red. Estado → (ranking de acciones, precios ETF,
  T-bill) → tramo a renovar → pesos objetivo → **órdenes** (vender/comprar, $ y unidades) → estado nuevo;
  marcado a mercado; reset 50/50; write-offs. Debe reproducir `run_exec`/`run_sleeve`/`mix` del lab sobre
  los mismos datos (test de paridad).
- Nuevo `sleeves/etf_trend.py` (Claude): señales y pesos de la manga B a partir de precios e IRX.
- Nuevo `portfolio_v9.py` (Grok): CLI diario. Carga estado, obtiene datos (vía `data/fetch.py`), llama al
  motor, persiste `state/portfolio_v9.json` (gitignored) con respaldo previo, escribe
  `state/instructions_<fecha>.md` + `.json`. En días sin renovación imprime el estado y "sin operaciones".
- `data/fetch.py` (Grok): ETFs + `^IRX` + ventana de 2 años con el mismo `report` de fallos.
- `daily.py` (Grok): `--v9` invoca el CLI tras el screener; sin `--v9` el ritual es el de hoy.

**No cambia:** régimen rico, Meta-Layer, `dynamic_count`, sector cap, filtros, veto, universo, tracking
(no se ejecuta), Pine/TradingView (aparcado: los artefactos v8.4 siguen generándose mientras
`ALGO_VERSION="v8.4"`).

## 3. Estado persistido (`state/portfolio_v9.json`, gitignored)

```
schema_version: 1
anchor_date, last_run_date, last_renewal_date, week_index
capital_reference (USD, lo fija Lucas al arrancar; los pesos se expresan en % y en USD)
sleeves: {A: {tranches: [{k, opened, units: {ticker: n}, cash}], ...}, B: {...}}
presumed_fills: [{date, sleeve, tranche, ticker, side, units, price, cost}]   # hasta que Lucas confirme
ledger: [instrucciones emitidas por fecha]
write_offs: [...]
```
Respaldo: copia con timestamp antes de cada escritura (`state/backup/`). Sin `history/`, sin tracking.

**Parámetros operativos fijados por Lucas (2026-09-07):** `capital_reference = 100 000 USD`; **ancla = lunes**.
Mapeo a la convención temporal del motor (señal al cierre de t, ejecución al cierre de t+1, MOC): la primera
corrida se hace el **viernes tras el cierre** (o el fin de semana); ese viernes es la barra ancla y las primeras
órdenes se ejecutan el **lunes al cierre**. Lucas dijo "apertura de mercado": la ejecución al cierre es la
que está simulada y medida (TASK-328: la apertura de D+1 no es mejor y depende de la era); si Lucas prefiere
ejecutar en la apertura del lunes es una desviación de la evidencia y se anota, no se simula como si fuera
igual. Las renovaciones siguientes caen cada **5 barras de bolsa** (paridad con el simulador), así que una
semana con festivo desplaza el día de la semana; se acepta y se documenta en la hoja de instrucciones.

## 4. Criterios de aceptación (antes de poner `ALGO_VERSION = "v9"`)

1. **Paridad con el simulador:** sobre el panel in-sample 2020-2026 (`_sweep_cache/`), el motor de producción
   alimentado con los mismos precios reproduce los pesos objetivo de `run_exec(T20)` y `run_sleeve(ETF)` en
   ≥ 20 fechas de renovación (tolerancia 1e-9 en pesos) y las mismas órdenes/costes.
2. **Casos a mano:** dos tramos, 100→200→100, sin renovar → 0 %; reset 50/50 registra la transferencia; cero
   recomendados → el tramo renovado queda en T-bill (no fallback); ETF todos apagados → 100 % T-bill.
3. **Idempotencia:** correr dos veces el mismo día no duplica órdenes ni cambia el estado.
4. **Sin red en el motor:** `core/portfolio_engine.py` y `sleeves/etf_trend.py` no importan yfinance.
5. **Suite verde**, `test_spec_compliance.py` cubriendo §9, revisión cruzada aprobada en el board.
6. Documentación: README, CLAUDE.md, AGENTS.md describen v9 como producción solo cuando el flag esté activo.

## 5. Reparto y orden

| Tarea | Quién | Archivos |
|---|---|---|
| Diseño, SPEC §9/§4.1, `core/tranche_book.py` (move), `core/signals.py` (12-7), `core/portfolio_engine.py`, `sleeves/etf_trend.py`, paridad | Claude | los listados |
| TASK-339 datos: `data/fetch.py` (2y, ETFs, ^IRX, report) + tests con red parcheada | Grok | `data/fetch.py`, `test_fetch_v9.py` |
| TASK-340 estado + CLI + hoja: `portfolio_v9.py`, `state/`, `.gitignore`, `daily.py --v9`, tests de persistencia/idempotencia | Grok (empieza cuando el motor tenga interfaz estable, la publico en el board) | `portfolio_v9.py`, `daily.py`, `test_portfolio_v9_cli.py`, `.gitignore` |
| TASK-341 revisión independiente del motor y la paridad | Grok | `test_review_341.py`, nota |
| Revisión de 339/340 | Claude | — |

## 6. Límites que quedan escritos

- La evidencia es simulación sobre S&P 500 PIT; producción opera Russell. Medir Russell requiere Norgate
  (decisión separada, $630/año).
- No hay track record ni tracking: el único registro vivo será el ledger de instrucciones y fills presumidos.
- El 10 % neto no se demuestra; el objetivo acordado es retorno por unidad de riesgo (Sharpe 0.74 y DD −19.5
  simulados frente a 0.42 / −37.8 de v8.4).
