# TASK-430 — diseño: EODHD como segunda fuente del camino vivo (para DESPUÉS del settle verificado)

**From:** Claude
**Date:** 2026-09-11
**Estado:** diseño solamente. No se toca `data/fetch.py` ni `portfolio_v9.py` hasta que `verify_state.py`
salga limpio tras el primer settle vivo (hoy el libro sigue con las 30 órdenes del 09-04 pendientes y
0 filas de ledger). Escrito ahora para que la tarea entre limpia en cuanto se abra la ventana.

## Dónde está la costura

`portfolio_v9.fetch_v9_market(universe)` (línea ~173) hace cuatro llamadas a `data.fetch`:

```
prices, volumes = fetch_prices_and_volume(tickers, period, report=stock_report)   # grupo "stocks"
spy             = fetch_spy(period)
etf             = fetch_etf_closes(V9["etf_universe"], period, report=etf_report)   # grupo "etf"
irx             = fetch_tbill(period, report=irx_report)                             # grupo "^IRX"
```

y devuelve un dict que el preflight y el diagnóstico de 416/421 ya leen **por grupo** (`stocks`, `etf`,
`^IRX`), con la máscara `attrs["observed"]` de `data.fetch` y `print_share` + `last_bar` por grupo. Esa
es exactamente la granularidad a la que hay que hacer el fallback: **por grupo, no por barra ni por
nombre**, para no mezclar dos proveedores dentro de un mismo frame.

## Regla

1. `config.py`: `PROVIDER_ORDER = ("yfinance", "eodhd")` (constante nueva, observabilidad/plumbing:
   regla 6 no aplica). `("yfinance",)` reproduce el comportamiento de hoy byte a byte — ese es el
   valor con el que se hace la primera corrida tras el settle, y solo después se añade `"eodhd"`.
2. `fetch_v9_market` pide cada grupo al primer proveedor. Si el frame del grupo tiene `print_share <
   PRINT_SHARE_WARN` (la **misma** constante de `config.py` que usa el preflight — TASK-421 ya la
   unificó), pide **ese grupo entero** al siguiente proveedor y se queda con el que tenga mayor
   `print_share`; en empate, el primero.
3. El frame ganador lleva `attrs["provider"] = "eodhd"|"yfinance"` y el `*_report` del grupo dice
   `provider`, `print_share` de cada intento y por qué se cayó al segundo. El diagnóstico
   `provider refresh degraded` (416/421) imprime el proveedor que ganó y el que perdió.
4. **La puerta no se toca.** Si los dos proveedores están por debajo, el preflight sale HARD como hoy;
   `--force` sigue siendo del operador; nada de auto-force. El fallback es una segunda oportunidad de
   tener datos buenos, no una forma de bajar el listón.
5. **Nunca se mezcla dentro de un grupo.** Ni una barra de EODHD en un frame de Yahoo ni al revés,
   porque `close` ajustado de dos proveedores no es la misma serie (dividendos/splits distintos) y un
   fill se ficharía a un precio de una fuente y se marcaría con otra. Si alguien quiere mezclar por
   nombre, es otra tarea con su medición.
6. EODHD entra por el `BarProvider` que ya existe (`data/providers/eodhd_provider.py`), no por una
   segunda ruta de descarga: `fetch` devuelve el frame largo `ticker, date, close_adj, close_raw,
   volume`, y `data.fetch` ya sabe convertirlo a los frames anchos (`_close_frame_from_yf` tiene su
   gemelo para el proveedor de TASK-361). `^IRX`: EODHD lo sirve como `IRX.INDX`; comprobar en la sonda
   antes de escribir código, igual que se hizo con `eod/` y la lista de deslistados.
7. Un grupo pedido a EODHD **también** pasa por `attach_observed`: la máscara de impresión no puede
   perderse en el fallback, porque el preflight y el corte de antigüedad (`age_stale`, H-005) la leen.

## Coste y cuota

Universo `all` ≈ 3000 nombres = 3000 llamadas por fallback de `stocks` (una por nombre en `eod/`). El plan
da 100.000/día; una corrida diaria con fallback completo gasta el 3 %. Para ETFs y `^IRX` es despreciable.
Si algún día el fallback de `stocks` se dispara todos los días, eso es una señal de Yahoo, no un problema
de cuota — y se verá en el `provider` del journal.

## Tests (con dos proveedores falsos, sin red)

- Yahoo sano → EODHD **no se llama** (contador de llamadas = 0) y el frame dice `yfinance`.
- Yahoo degradado en `etf` (share 7 %, la huella del 09-10), EODHD sano → el grupo `etf` viene de EODHD,
  `stocks` sigue de Yahoo, el preflight pasa, la salida nombra el cambio.
- Los dos degradados → HARD, mensaje de 416/421 con los dos shares, nada escrito.
- `PROVIDER_ORDER = ("yfinance",)` → idéntico a hoy: mismo frame, mismos reports (test de paridad).
- Máscara `observed` presente en el frame de EODHD.

## Medición antes de encender

Sobre la corrida de preflight de un día real, con `fetch_fn` real: los dos frames (`yfinance` solo y
`yfinance→eodhd`) pegados con `print_share`, `last_bar` y las diferencias de `close` en los nombres
comunes (deben ser ≈0 en `close_raw`; en `close` ajustado pueden no serlo, y eso se documenta). Solo
entonces `PROVIDER_ORDER` pasa a incluir `"eodhd"`, en un commit propio con esos números.

## Lo que esta tarea NO es

No es "EODHD como proveedor primario". Eso cambia la fuente de todos los fills y merece su propia
medición de paridad histórica (mismos cierres, mismos ajustes) antes de plantearse. Y no es el bar store
de TASK-361: el store sigue apagado hasta su propia comparación cacheado-vs-directo.
