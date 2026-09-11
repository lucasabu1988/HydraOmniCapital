# El proveedor se degrada por la tarde-noche, y el libro vivo se pone al dia sin problema

Claude, 2026-09-10 20:15 local (21:15 ET). Notas de apoyo para **TASK-416** y para la corrida viva
del viernes 2026-09-11. Nada de esto toco `state/`: todo se midio sobre una COPIA en el scratchpad.

## 1. Tercera y cuarta reproduccion de la degradacion

| hora local | que se pidio | resultado |
|---|---|---|
| 16:55 | corrida completa (3002 + 10 ETFs) | preflight 13 filas OK salvo el WARN de procedencia |
| 19:36 | corrida completa | 10 ETFs con ultima barra 09-09, `universe print share` 7 %, **HARD** |
| **20:13** | corrida completa sobre la copia | **identico al de 19:36**: `universe print share` 7 % (umbral 90), `ETF prices observed` **HARD**, 10/10 sin print del 09-10 |
| **20:15** | solo los 10 ETFs, `period=2y` | frame con 501 barras y **ultima barra 2026-09-10** |

La cuarta fila parece contradecir a la tercera, y no: la barra del 09-10 que devuelve el proveedor es
**un relleno hacia adelante**, identica al 09-09 en los diez simbolos hasta el ultimo decimal —

```
              SPY     QQQ     IWM     EFA    EEM    TLT   IEF     GLD    DBC    VNQ
2026-09-09  762.4  716.31  290.64  106.56  68.48  81.73  91.9  403.35  32.85  94.94
2026-09-10  762.4  716.31  290.64  106.56  68.48  81.73  91.9  403.35  32.85  94.94
```

`data.fetch` rellena huecos de ETF a proposito (para que una ventana de 252 barras sobreviva a un
hueco de una barra) y `observed_mask` es justo lo que distingue el relleno del print. Por eso la fila
`ETF prices observed` dice `stale(last 2026-09-09)` mientras `last bars` dice OK: **las dos tienen
razon**, y la puerta de ASTRA-03 es la que ve la verdad. Un operador que solo mirase "ultima barra
2026-09-10" se la habria creido.

**No es tamano de lote** (la hipotesis del throttle): pedir 10 simbolos solos devuelve la misma barra
falsa que pedir 3012. Es la **hora**: a las 16:55 local (17:55 ET, ~2 h tras el cierre) los datos
estaban completos; a las 19:36 y a las 20:13-20:15 (20:36 / 21:15 ET) ya no. Yahoo recarga su EOD por
la noche y durante esa ventana sirve datos parciales.

**Regla operativa para el viernes 2026-09-11:** correr el libro **dentro de las ~2 h siguientes al
cierre** (16:00-18:30 ET). Si toca correr mas tarde y sale el HARD, **no es que falten datos de la
sesion: es la ventana de recarga**; se reintenta, nunca `--force`.

## 2. El HARD tambien aplaza el settle, no solo el plan

`portfolio_v9.py:696` (`PF.raise_if_hard`) esta **antes** del bloque de settle (~720). Con el HARD de
esta noche la corrida no planifico — correcto — pero tampoco **fichò los 30 fills pendientes del
2026-09-04**, y esos fills se valoran a los cierres del **2026-09-08**, una barra que ya esta en el
frame y que la degradacion de hoy no toca. Consecuencia real: el libro vivo lleva desde el 09-08 con
una obligacion sin anotar, y cada tarde degradada la vuelve a aplazar.

No propongo tocar la puerta (fail-closed se queda). Lo que falta es que el rechazo **diga lo que
aplaza**: "N ordenes del <planned> quedan sin fichar (barra de ejecucion <exec_date>, ya en el
frame)". Va como **TASK-420**.

## 3. La puesta al dia del libro vivo, ensayada: sale limpia

Copia de `state/` en el scratchpad, solo los 30 tickers pendientes bajados, `engine.settle` con
`_row`/`_dividend_table` de produccion (script `scratchpad/rehearse_catchup.py`):

- `exec_date` que elige el motor = **2026-09-08** (primera sesion tras el plan del 09-04; el 09-07 fue
  Labor Day). El motor **no** ficha a los cierres de hoy: `next_session_date(prices.index, planned)`.
- **30/30 fills**, ninguno `not_filled`, ningun ticker sin print en la barra de ejecucion.
- **14.439,09 USD** fichados, **10,78 USD** de costes. 22 acciones a 323,88 USD cada una y 8 ETFs
  (DBC 763,10 / EEM 567,03 / EFA 1.168,83 / GLD 616,43 / IWM 1.116,66 / QQQ 689,63 / SPY 1.286,92 /
  VNQ 1.105,17). Tramo 0.
- **0 ex-dates posteriores a la barra de ejecucion** en las 1.430 filas de dividendos del run, asi que
  la des-ajuste de ASTRA-03 no mueve ningun precio de fill en esta puesta al dia.
- Caja tras el settle: stocks 42.867,56 / etf 42.682,57. `pending` 0, ledger 30 filas.
- `pending age` es **WARN y nunca HARD** (`preflight.py`, `sessions > 1`), asi que el retraso por si
  solo no bloquea nada: hoy dice "3 sessions behind", el viernes dira 5.

Es decir: **la unica cosa que impide poner al dia el libro vivo es la ventana del proveedor.** Corrida
el viernes tras el cierre en la ventana buena, el motor ficha estos 30 fills al 09-08 y renueva la
semana 1. Los numeros de arriba son lo que hay que ver en la hoja; si aparece otra cosa, hay algo que
mirar antes de aceptarla.

Aviso de metodo: son fills **presuntos** del motor. Lucas confirmo fuera del repo que el settle del
09-08 se ejecuto; lo que aqui no consta sigue siendo la **sincronizacion del estado vivo** con los
fills reales. Si los reales difieren de estos, la diferencia se resuelve con `confirm_fills.py`, no
reescribiendo el estado a mano.
