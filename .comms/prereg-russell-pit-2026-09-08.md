# Pre-registro — HYDRA v9 sobre Russell PIT (TASK-403)

Escrito el **2026-09-08**, con `main` en `5a01856`, **antes de comprar los datos**. Ese es el punto:
cuando llegue Norgate, el experimento ya está declarado y no se puede mover la portería después de ver
el resultado. Todavía no es H-008 en `.comms/hypotheses.md` porque H-004/005/006 viven en
`docs/astra-prereg-01-08-10` y el registro se funde en el paso 2 de la ventana de merge; se traslada
allí con su número después.

## La pregunta

**¿El v9 que ya decidimos operar — sin retocar nada — funciona sobre el universo PIT que de verdad
representa producción?**

La evidencia fuerte de HYDRA es S&P 500 point-in-time. Producción es S&P 500 + Nasdaq-100 + Dow +
Russell 1000 + Russell 2000 (~3.000 nombres), dos tercios mid/small. Todo lo que hoy afirmamos sobre
rentabilidad, costes y drawdown está medido en el tercio equivocado del universo.

## Lo que se congela hoy

La superficie de decisión, por hash, para que la congelación sea verificable después:

| fichero | sha256 (12) |
|---|---|
| `core/signals.py` | `f9806b77bd61` |
| `core/regime.py` | `656ff8135814` |
| `core/filters.py` | `95c78d2591c6` |
| `core/meta_layer.py` | `5e81ff429455` (la pila de merge le quita un import sin usar; el cuerpo no cambia) |

Y los valores, porque `config.py` **sí** cambia en la ventana de merge (constantes nuevas de
contabilidad y observabilidad, no de scoring), así que el hash del fichero no sirve de ancla:

`V9`: `step_bars 5`, `hold_bars 20`, `tranches 4`, `stock_momentum_window "mom12_7"`,
`stock_buffer 2.0`, `stock_target_vol 0.15`, `stock_cost_bp 10.0`, `etf_lookback_bars 252`,
`etf_vol_bars 63`, `etf_cost_bp 5.0`, `mix 50/50`, `max_stale_bars 10`, `etf_universe` los 10 de
siempre. Fuera de `V9`: `MAX_PER_SECTOR 5`, `MIN_REGIME_SCORE 0.35`, `SHORT_TERM_LOOKBACK 10`,
`PROXIMITY_HIGH_DAYS 20`, `MAX_DIST_TO_HIGH_PCT 3.0`, `SHORT_TERM_BOOST 0.35`,
`VOL_SURGE_THRESHOLD 1.50`, `ALGO_VERSION "v9"`.

**Cualquier cambio de esos valores o de esos cuerpos antes de la corrida invalida este pre-registro**
y obliga a escribirlo de nuevo con la fecha nueva. Los arreglos de contabilidad de la ventana de merge
(NaN, fill/split, precios observados) **no** lo invalidan: no tocan la decisión, y de hecho la corrida
tiene que hacerse **con** ellos.

## Lo que se mide, declarado antes de mirar

Sobre el panel Russell PIT (membresía real por fecha, delistados con sus precios, sufijos estilo
`AABA-201910`), con el motor end-to-end (`experiments/engine_backtest.py`, plan/settle/mark, estado
round-tripped por JSON) y costes incluidos:

1. `ann_net`, `ratio_net_vol` **y** `sharpe_excess` (TASK-404: neto − ^IRX alineado), `maxDD`.
2. Los mismos cuatro sobre S&P 500 PIT en las **mismas fechas**, como pareja. Lo que decide no es el
   nivel Russell: es la **diferencia pareada** Russell − S&P con su error estándar.
3. Cobertura impresa junto a cada número: celdas con precio, nombres sin historia as-printed, y el
   arranque real de la serie. Sin eso, ningún nivel absoluto se cita (regla que ya cuesta caro una vez:
   `close_raw` cubre 83.6% de las celdas y los 538 que faltan son los delistados).
4. Turnover y `order$ / ADV` por decil de capitalización — el canal por el que el universo pequeño se
   come el edge, y la única forma de saber si los 10/5 bp modelados son fantasía en la mitad Russell.

## La regla de decisión, también antes

- **Sobrevive** si la diferencia pareada de `sharpe_excess` Russell − S&P es `>= -0.10` con su SE, y el
  `maxDD` Russell no empeora más de 5 pp. Entonces v9 se declara medido en su propio universo.
- **No sobrevive** si la diferencia pareada es `<= -0.25`, o si el turnover implica un coste que borra
  más de la mitad del `ann_net`. Entonces el hallazgo es que **producción opera un universo donde la
  evidencia no se sostiene**, y la respuesta correcta no es tunear: es reducir el universo a lo medido.
- Zona intermedia (`-0.25 < d < -0.10`): resultado **inconcluso**, se declara así y no se toca nada.

## Lo que explícitamente NO se hace

No se mueven umbrales, ni el número de nombres, ni el buffer, ni el cap sectorial, ni la ventana de
momentum después de ver la tabla. Si alguien quiere cambiar algo, eso es una hipótesis nueva, con su
entrada en el registro, su métrica y su falsificador — y se mide en DEV (< 2016) antes de tocar TEST.
El valor de este experimento está entero en que la decisión se tomó antes de tener los datos.

## Lo único que lo bloquea

**Norgate Data US Stocks Platinum, 630 USD/año** (aprobado por Lucas 2026-09-06, sin comprar). Silver
y Gold no traen delistados ni constituyentes históricos: esa es la trampa (TASK-334).
