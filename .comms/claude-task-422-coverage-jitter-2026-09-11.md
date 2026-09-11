# TASK-422 — la sentencia que salta no era una sentencia, y no era el reloj

**From:** Claude
**Date:** 2026-09-11
**Rama:** `feat/task-420-421-hard-postpone` (`bb55cc3`)
**Contexto:** TASK-419 pegó dos cifras de cobertura del mismo commit (82,33 % y 82,35 %, 1161 vs 1160
sobre 6572) y lo llamó "one-statement jitter in `data/fetch.py`" sin localizarlo. TASK-422 pedía el
método: dos corridas de `--cov` sobre el mismo árbol, los dos `coverage.xml` guardados, diferencia
por línea.

## Lo primero que salió: en este árbol no salta nada

Dos corridas completas, mismo commit, mismo árbol:

| | sentencias | cubiertas | line-rate |
|---|---|---|---|
| corrida 1 | 6340 | 5203 | 82,40 % |
| corrida 2 | 6340 | 5203 | 82,40 % |

Diferencia por línea: **0 claves con `hits > 0` distinto**, 0 claves presentes en un XML y no en el
otro. Así que la premisa de la tarea ("una sentencia de `data/fetch.py` se cubre en una corrida y no
en la siguiente") no se reproduce sin más. Y las dos cifras de Grok eran de **6572** sentencias, no
6340: su par se midió sobre un árbol distinto del actual, así que tampoco es comparable de frente.

## Lo segundo: la causa sí existe, y es mucho más grande que una sentencia

`portfolio_v9.run` llama a `load_last_ok_print_quality()` **sin `runs_dir`**, así que resuelve
`utils.runlog.DEFAULT_RUNS_DIR` = `hydra_screener_local/runs/` — estado vivo, gitignorado. Es decir:
**cada test que arranca el CLI lee la última corrida real del operador**, y qué rama del cargador se
ejecuta depende de lo que haya en este disco en ese momento.

Medido sobre los mismos dos ficheros de test (`test_preflight_postpone.py`,
`test_portfolio_v9_cli.py`), única diferencia un `runs/last_ok_print_quality.json` en su sitio:

| | cubiertas de `data/` |
|---|---|
| sin `runs/` | 305 |
| con el sidecar | 312 |

y **35 sentencias de `data/fetch.py` cambian de cubierta a no cubierta o al revés**: 238-250, 259,
268-303, 319-328. No es el reloj (la tarea sospechaba de ramas con reloj): es el sistema de ficheros.
El "salto de una sentencia" de TASK-419 es el síntoma más pequeño posible de eso — en su par el
`runs/` de la máquina estaba casi igual entre las dos corridas, pero no idéntico.

La consecuencia importante no es el número: **la cobertura era una propiedad de este disco, no del
código.** Un piso medido así sólo es honesto por casualidad. Y el mismo camino explica por qué dos
corridas cualesquiera pueden discrepar: basta una corrida real (o de papel) entre ellas.

## El arreglo: la misma valla que ya existía para los respaldos

`conftest.py` ya desviaba `HYDRA_BACKUP_DIR` en tiempo de import, antes de que se importe cualquier
módulo de test (la contaminación de respaldos del 2026-09-06). Segundo destino, misma forma: al
importar la sesión se reasigna `utils.runlog.DEFAULT_RUNS_DIR` a un directorio temporal privado.
`data/fetch.py` importa esa constante **dentro** de la función, así que el camino vivo bajo test ve
el desvío.

Re-medido después, el mismo experimento A/B: **307 cubiertas en los dos casos, 0 sentencias que
difieran**. La cobertura vuelve a ser una propiedad del código.

No es sólo cobertura: mientras la valla no estaba, la suite **leía** el libro del operador. Escribir
no podía (el `_save_print_quality` del camino vivo está tras `fetch_fn is None`), así que no hay
contaminación que reparar — pero el mismo agujero, un paso más allá, es TASK-392.

## Lo que se cubre ahora a propósito

Las ramas que antes se cubrían por accidente ahora tienen test con `runs_dir` explícito: la última
corrida con `exit_status 0` gana, una corrida fallida no es referencia, un manifiesto sin
`print_quality` no es referencia, otro universo no es referencia, y no haber directorio de corridas
no es un error. `data/fetch.py` pasa de **437/567 a 450/567**. Un test fija la valla: quitarla vuelve
a hacer la cobertura propiedad del disco, y lo dice.

## Piso

Las dos medidas finales, sobre el árbol quieto y con todo lo de esta sesión dentro, están en el
cuerpo de la PR con su cifra. La regla de TASK-419 sigue: el piso se mueve a la cifra medida menos
un margen declarado, nunca al revés, y se mide **en Linux** (CI), que va ~0,36 pp por debajo de
Windows (medido en la #73: 81,97 vs 82,33).

## Lo que queda abierto

El arreglo de verdad no es la valla, es que `load_last_ok_print_quality()` reciba su destino en vez
de resolverlo en lo hondo del camino de lectura — exactamente lo que ASTRA-12 propone para
`HYDRA_BACKUP_DIR`. Mientras eso no exista, la valla es lo que mantiene la medición fuera del libro.

## Un hueco que queda dicho en voz alta

Un fichero que `run_all_tests.py` corre **como script** no carga `conftest.py`, y este desvío es un
atributo de módulo (no una variable de entorno), así que el runner no puede pasárselo a sus
subprocesos como hace con `HYDRA_BACKUP_DIR`. La medición sí queda vallada, porque la cobertura se
mide sólo sobre los ficheros pytest; pero un test en modo script que arrancara el CLI seguiría
leyendo el `runs/` del operador.
