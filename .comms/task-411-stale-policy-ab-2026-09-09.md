# TASK-411 (a) — H-005 medida sobre el panel PIT: lo que cuesta que el reloj de write-off cuente rellenos

Claude, 2026-09-09. **Solo medir** (regla 6). Nada de política cambia aquí.

## Por qué se puede medir hoy, sin `fix/astra-03`

El panel del laboratorio **no pasa por `data/fetch.py`**: lo escribe un `yf.download` directo y
`Panels.__init__` rellena **solo `spy`**, nunca `close`. Así que en el panel `close.notna()` **es**
la máscara de observados, bit a bit lo que `attach_observed(prices, prices.notna())` guardaría.
Verificado hoy: `grep -c observed hydra_screener_local/data/fetch.py` en `main` = **0**, y aun así
la mitad (a) sale.

## El A/B

Dos brazos, **rankings idénticos** (los dos se calculan del panel crudo), que difieren en una sola
cosa: la serie de precios que ve el LIBRO.

| brazo | precios que ve el libro |
|---|---|
| `observed` | panel crudo; el que no imprime es NaN y el reloj corre |
| `filled` | `close.ffill(limit=3)`, el relleno de producción (`data/fetch.py:291`, `FFILL_LIMIT_BARS`) |

Entrega: `experiments/stale_policy_ab.py` + `experiments/test_stale_policy_ab.py` (6 tests sobre
series sintéticas: el relleno es el de producción, el write-off cae en la barra del límite, y un
relleno dentro de la ventana retrasa el write-off exactamente `FFILL_LIMIT_BARS`).

**Validación del arnés:** el brazo `observed` reproduce **exactamente** la cifra publicada de `main`
— **7.10 / 0.75 / −17.8** (TASK-350), mismo panel PIT y mismos sectores. Si no coincidiera, ningún
número de abajo valdría (regla de TASK-387).

## Los números (panel OOS PIT 2004-26, 5705 × 1209, capital = 1.0)

| | observed | filled | diferencia |
|---|---|---|---|
| `ann_net` | **7.10** | **7.05** | **−0.05 pp** |
| `ratio_net_vol` | 0.75 | 0.74 | −0.01 |
| `sharpe_excess` | 0.57 | 0.56 | −0.01 |
| `maxdd_net` | −17.8 | −17.8 | **0.0** |
| write-offs | 2 | 2 | 0 |
| dólares de write-off | 0.076411 | 0.083684 | **+0.007273 desplazados** |

- **Celdas que el relleno de producción inventaría en el panel: 656** de 6.897.345 (**0,0095 %**).
- **Marks con `last_px` puesto desde un relleno: 3**, sobre dos nombres (**ESRX**, **SCG**).
- **Relojes ya acumulados que un relleno borró: 0.** El mark del laboratorio ocurre una vez cada
  5 barras, así que un relleno de 3 barras casi nunca cae sobre una fila de mark con el contador
  ya corriendo.
- **Retraso del write-off:** un nombre comparable, **ESRX**, 7 días de calendario (= un paso de 5
  barras): 2019-03-01 → 2019-03-08. **SCG** aparece escrito solo en el brazo `filled` (2019-03-15):
  en cuanto los libros divergen, las carteras dejan de ser las mismas y la comparación por nombre
  es aproximada — dicho aquí para que nadie la lea como exacta.

## Control in-sample (2020-26, 1678 × 503)

**1 sola celda** rellenable en todo el panel, **0 write-offs**, cero diferencia entre brazos. El
efecto solo existe donde hay deslistados; el panel de supervivientes no puede verlo.

## Las tres preguntas que dejó escrita la nota de TASK-402

1. **¿Cuántos nombres tuvieron `last_px` puesto desde un relleno?** Tres marks, dos nombres
   (ESRX, SCG) en 22 años de panel PIT. En el panel es marginal.
2. **¿Cuántas sesiones se carga de verdad un nombre antes del write-off, contando solo prints,
   frente a las diez que promete `max_stale_bars`?** **46 barras** (ESRX, brazo observed) y
   **51 barras** (ESRX y SCG, brazo filled). No son diez: `max_stale_bars = 10` cuenta **marks**,
   y aquí se marca una vez cada 5 barras, así que "diez sesiones" son ~50 días de mercado. **Este
   es el hallazgo grande de la mitad (a), y no depende del relleno**: es la unidad del contador.
   En el camino vivo, que marca a diario, diez marks sí son diez sesiones — o sea que la misma
   constante significa dos cosas distintas según quién la corra.
3. **¿Qué le hace al recuento de write-offs tomar la máscara de observación?** En el panel, nada:
   2 y 2. Mueve un write-off 7 días antes, devuelve 0.007273 de libro y **+0.05 pp de `ann_net`**.

## Lectura, y lo que esto NO dice

Sobre el panel PIT el defecto es real pero **pequeño**: el relleno de 3 barras casi nunca alcanza
una fila de mark, porque el laboratorio marca cada 5. **El camino vivo es el caso distinto** y sigue
sin medir: marca a diario (un relleno de 3 barras tapa 3 marks seguidos) y el universo es
Russell-pesado, con nombres mucho más finos que los 1209 del panel. Esa es la mitad (b) de
TASK-411, y sigue bloqueada por `OBSERVED_ATTR`/`attach_observed()` de
`fix/astra-03-observed-fill-prices` (paso 6 de la ventana de merge).

**Nada de esto propone cambiar la política.** Cambiar qué cuenta como "llegó un precio" mueve
write-offs, P/L histórico y caja: es regla 6 y espera a Lucas, ahora con números.

## Reproducir

```
cd hydra_screener_local
python experiments/stale_policy_ab.py                 # OOS PIT, escribe el JSON con --json
python experiments/stale_policy_ab.py --in-sample     # el control
python -m pytest experiments/test_stale_policy_ab.py -q
```

Artefactos: `experiments/_lab_scratch/stale_policy_ab_oos.json`,
`experiments/_lab_scratch/stale_policy_ab_insample.json` (gitignored, se regeneran).
