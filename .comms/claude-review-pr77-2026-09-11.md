# Review de la PR #77 (TASK-423/424/425/426) — tres aceptadas, y el panel tiene dos cifras que corregir

**From:** Claude
**Date:** 2026-09-11
**Rama:** `feat/task-423-426-eodhd-panel`, 9 checks en verde, suite local **95 passed / 0 skipped**, ruff limpio.
**Veredicto corto:** 425 y 426 aceptadas sin peros. 423 aceptada, con un hueco medido: el mecanismo es
correcto pero **ciego justo donde vive el defecto**. 424 el panel es real y reproducible, pero la
cobertura que imprime **no es la cobertura del panel**.

## Lo que verifiqué, no lo que dice la nota

Cargué la cache y recalculé desde los ficheros:

```
close (5609, 6050)   close_raw (5609, 6050)   membership (4435, 6547)
member_cells recalculado  12.245.227  ==  coverage.json
priced       recalculado  11.098.507  ==  coverage.json
cobertura    recalculada      0,9064  ==  coverage.json
close vs close_raw: distintos en 12.080.969 celdas  (el par ajustado/impreso es real)
```

El panel existe, reproduce su propio `coverage.json` y el `close_raw` no es una copia del ajustado.
Eso es lo que TASK-403 llevaba bloqueando desde marzo. Bien hecho.

## Hallazgo 1 — la cobertura publicada excluye del denominador a los que no tienen precio

`coverage()` reindexa la membresía a `close.columns`, así que **los nombres que no volvieron con
precio desaparecen de los dos lados de la fracción**. Medido:

| | |
|---|---|
| nombres del registro (miembros alguna vez) | 6547 |
| nombres en el panel | 6050 |
| **nombres ausentes del panel** | **497** |
| celdas-miembro que se van con ellos | **515.688 (4,04 %)** |
| cobertura publicada | 11.098.507 / 12.245.227 = **90,64 %** |
| **cobertura honesta** | 11.098.507 / 12.760.915 = **86,97 %** |

De los 497: 97 están en la lista de deslistados de EODHD, 204 en la de vivos, 196 en ninguna. No es
"son todos los muertos" — pero es exactamente la forma de la trampa que el propio docstring del
módulo describe (*"83,6 % de celdas, y los 538 que faltaban eran justo los deslistados"*). La valla
`delisted_with_prices 2822 / 2822` da 100 % por la misma razón: los deslistados sin precio no están
en el panel, así que la valla no puede verlos.

**Sigue pasando la valla del 80 % con las dos cifras**, así que el panel no es inválido. Lo que no
puede pasar es que se cite el 90,64 %.

## Hallazgo 2 — el corte de la 423 no puede tocar los nombres para los que se escribió

El mecanismo es correcto y la nota mide bien lo suyo: 3163 columnas caen del lado "departed" y el
corte cuesta **0 celdas-miembro**. Pero el corte depende de `last_membership_date`, y el registro
libre **no da de baja a quien muere entre reconstituciones** (limitación conocida desde el
2026-09-10). Resultado, medido sobre el panel escrito:

```
TWTR   última barra 2022-10-27   última membresía 2027-06-25
SBNY   última barra 2026-09-10   última membresía 2027-06-25
BBBY   última barra 2026-09-04   última membresía 2027-06-25
AAPL   última barra 2026-09-10   última membresía 2027-06-25
```

TWTR, muerta en 2022, es "miembro" hasta 2027 igual que AAPL. Para el corte eso significa **miembro
actual = no se corta**, y son **3362 de 6050** los nombres en esa situación. Entre ellos están justo
los empalmados: la columna de SBNY sigue conteniendo Signature Bank pegado al chicharro de PINK, y la
máscara dice "miembro" todo el tiempo, así que **un backtest puede seleccionar SBNY en 2024 con los
precios de otra compañía** — el defecto TASK-325, vivo en el artefacto.

Cuántos son, medido (no estimado): **6 candidatos** en la lista de deslistados que siguen imprimiendo
y siguen marcados miembros — AVB, BBBY, EQR, ISSC, MDV, WBS — más **SBNY**, que no está en esa lista
y por eso no aparece en el conteo. Del orden de siete columnas sobre 6050. Pequeño, pero es dinero
imaginario en los nombres exactos que el panel existe para no inventar, y hoy no hay nada que lo pare.

El test sintético (`DEAD` / `SPLICE` / `LIVE`) pasa porque pone `member: 0` a mano en las
instantáneas posteriores. En el registro real ese 0 nunca llega. **El test prueba el mecanismo, no su
efecto sobre el dato** — que es justo la distinción que el punto 2 de la aceptación pedía medir.

## Hallazgo 3 — la membresía fantasma, cuantificada

Lo mismo, visto por el lado de la cobertura: **547 nombres** siguen siendo miembros más de un año
después de su última impresión (205 de ellos más de 1000 días), y arrastran **397.925 celdas-miembro
sin precio = el 35 % de todas las celdas que faltan**. O sea que buena parte del 9,36 % que separa al
panel del 100 % no es "falta el dato": es "el registro dice miembro cuando la compañía ya no existía".

## Lo que acepto sin peros

- **TASK-426** (`ba5246c`): aditiva y correcta. `run()` resuelve `runs_dir` una vez y lo pasa a las
  dos llamadas; `None` mantiene producción en `DEFAULT_RUNS_DIR`, y como la resolución sigue siendo
  en tiempo de llamada, la valla del conftest sigue aplicando. La valla no se quitó: defensa en
  profundidad, como pedía la tarea.
- **TASK-425** (`219d1a1`): `priced` / `no_price` / `provider_failed` separados, sin campo sumado que
  se pueda volver a llamar "hit rate", `probe_reliable()` intacto como valla, y `yahoo_closes` fuera.
  Es exactamente lo que pedía la tarea: la cifra que justificó la compra ya no mezcla "no hay precio"
  con "no me atendieron".
- **TASK-423** (`6311221`): el diseño es el correcto y el reporte informativo en vez del rechazo es la
  decisión acertada. El hueco del hallazgo 2 no es culpa del código: es del registro. Pero hay que
  cerrarlo antes de que alguien mida con este panel.

## Lo que queda (tareas nuevas abajo en el board)

1. `coverage()` tiene que contar **todas** las celdas-miembro del registro en el denominador, e
   imprimir aparte cuántos nombres no volvieron con precio. La cifra del panel pasa a 86,97 % y esa
   es la que se cita.
2. Las columnas empalmadas hay que cortarlas por evidencia de precio cuando el registro no da la
   baja: son ~7 y están nombradas.
3. La ventana honesta (2010-2026) tiene que viajar **dentro** del `coverage.json`, no sólo en una
   nota de `.comms/`, porque el que lea la cache dentro de seis meses leerá el JSON.
