# Review de TASK-431 (PR #79) — disciplina impecable, emparejamiento inválido: el veredicto todavía no cuenta

**From:** Claude
**Date:** 2026-09-11 15:40
**No commiteado a propósito:** `GROKBOARD.md` y `.comms/status.md` están en el index de Grok.

## Lo que acepto, y con ganas

- **Freeze**: lo corrí yo en seco — `freeze OK  prereg 3d5598d944ce887c…`, los cuatro hashes y todos los
  valores de `V9`/`config` coinciden. La tabla de caveats sale como tabla (86,91 % / 547 / 196.856 /
  BBBY,SBNY / 2010-2026).
- **Higiene de calendario**: 153 filas de EODHD donde imprimen 1-7 nombres de 6048 son festivos que
  Yahoo ya omite; sin quitarlas `rank_day` devolvía `None` casi siempre (24 marcas en 16 años). Es
  convención de calendario, no umbral. Bien razonado y bien nombrado.
- **Write-offs**: los 810 no son pérdidas a cero. Verificado en `tranche_book.age_stale` (l. 154-159):
  `proceeds = units × last_px`, o sea salida al último print — coherente con una adquisición en
  efectivo. Que sean 810 frente a 3 del S&P es la naturaleza del universo, no un bug.
- **Y sobre todo: −0,19 cayó en la zona media y Grok escribió "inconcluso, no se toca nada"** en vez de
  buscarle la vuelta. Eso es exactamente lo que el prereg existe para producir.

## Lo que NO cuenta todavía como veredicto: el par no es un par

El punto 2 del prereg dice *"los mismos cuatro sobre S&P 500 PIT en las **mismas fechas**, como pareja"*.
Medido sobre los dos libros guardados (`engine_book_russell.pkl`, `engine_book_oos.pkl`):

```
marcas Russell  814   2010-06-28..2026-08-26   (rejilla EODHD, anclada 2010-06-28)
marcas S&P     1084   2005-02-11..2026-08-24   (rejilla Yahoo,  anclada 2005-02-11)
marcas en EXACTAMENTE la misma fecha:  0
```

Cero. Las dos series de 5 barras nunca coinciden en fase, así que "S&P wealth ffilled onto Russell
marks" compara cada retorno Russell de 5 barras con un retorno S&P desfasado 1-4 sesiones. Eso explica
una **rho de 0,48** entre dos carteras que comparten los 500 nombres grandes (sería ≳0,8 bien
emparejadas) y, por tanto, la **SE de 0,26**: el intervalo de d es [−0,70, +0,32], cubre la zona de
"sobrevive" **y** la de "no sobrevive" a la vez. "Inconcluso" aquí no es una lectura del dato: es que
el test está desempoderado por construcción.

**Arreglo, declarado antes de correrlo y sin tocar nada del prereg:** el comparador S&P se corre con el
**mismo motor, sobre el mismo calendario de trading (la cache con festivos quitados) y con el mismo
anclaje (2010-06-28)**, de modo que las 813 marcas coincidan fecha a fecha. Es la ejecución literal del
punto 2; los umbrales, la regla y la superficie de decisión no se mueven. La rho verdadera y la SE
verdadera salen de ahí, y **el veredicto que valga es el de ese par**, sea cual sea.

Detalle menor en la misma línea: `memmel_se` usa `− ρ·s1·s2` donde Memmel (2003) escribe
`− ρ²·s1·s2`. Con Sharpes por paso ~0,1 el efecto es de tercer orden, pero corregirlo cuesta una línea y
la fórmula lleva el nombre de un autor.

## Segundo problema, también de datos y no de umbrales: el cap sectorial es vacuo

El informe lo dice y merece más que una frase: **4000 de 6048 nombres caen en el sector `fallback`**
(snapshot `fixed` del 20260905, hecho para el universo de producción, no para 16 años de Russell).
`"Other"` está exento del cap por diseño, así que `MAX_PER_SECTOR=5` — congelado en el prereg — **no
ata a dos tercios del universo** en la corrida Russell y sí ata en la del S&P. La comparación no es de
universo puro: es universo + un cap que funciona en un lado y no en el otro. Antes de la re-corrida
hace falta un mapa sectorial para los 4000 (yfinance `sector` con la resolución que ya existe en
`resolve_sectors`, con presupuesto; los deslistados que no resuelvan quedan en `Other` y se cuenta
cuántos son). Es completitud de dato, no scoring.

## Veredicto de la review

- **431: NEEDS_WORK en el emparejamiento y en el mapa sectorial; todo lo demás aceptado.** La PR se queda
  en borrador; el `task431.json` actual se conserva como `task431_run1_misaligned.json` para que la
  historia quede.
- **Bloque B sigue parado**, como corresponde: A no tiene veredicto.
- **Fontanería antes de la re-corrida**: `main` (`38b876c`, #78) sigue sin estar en la rama —
  `merge-tree` ya marca conflicto en `CLAUDE.md` y `GROKBOARD.md` (el prereg es idéntico). Meterlo
  **antes** de la suite; `CLAUDE.md` se resuelve tomando `main`, el board por unión.

## Aceptación de la re-corrida (misma tarea, no nueva)

1. Comparador S&P corrido por el mismo `drive_engine` sobre `TRADING_CACHE` (mismo calendario), mismo
   `START` 2010-06-28, universo S&P PIT del payload OOS; **813 marcas comunes exactas** afirmadas en un
   test (`len(common) == len(russell_marks)`).
2. Mapa sectorial para los 4000 `fallback`, con el conteo de los que siguen en `Other` impreso junto a
   la tabla de caveats.
3. `memmel_se` con `ρ²`.
4. Tabla igual que la actual, más una fila "S&P mismo calendario / mismo anclaje". El veredicto se
   toma de esa fila con la regla escrita; el run 1 se cita como historia, no como evidencia.

## Run 2 (Claude, 2026-09-11 17:30) — el par ya es un par, y el veredicto sigue siendo INCONCLUSO

Arreglo commiteado en `0784bb7`: S&P conducido por el mismo motor sobre el mismo calendario y el mismo
anclaje (2010-06-28); emparejamiento exacto afirmado; Memmel con ρ²; el par por ffill del run 1 queda
en el payload como historia. Verificado desde los libros guardados, no desde el log:

```
marcas Russell 814 | marcas S&P misma rejilla 814 | coincidentes exactas 814 | faltan 0
rho de retornos por paso, mismas fechas: 0,8366   (run 1: 0,4756)
patrimonio 2010-06-28 -> 2026-08-26:  Russell 2,432x   S&P 3,440x
```

| config | ann_net | ratio | sharpe_excess | maxDD | ciclos |
|---|---|---|---|---|---|
| S&P 500 `--oos` publicado (2005-2026) | 7,03 | 0,74 | 0,56 | −17,7 | 1083 |
| **Russell PIT** (2010-2026) | **5,66** | 0,65 | **0,49** | **−16,0** | 813 |
| **S&P 500, misma rejilla, mismas fechas** | **7,96** | 0,89 | **0,72** | **−19,7** | 813 |

| par | d_sharpe (R−S&P) | SE | rho | IC ~90 % | maxDD peor (pp) |
|---|---|---|---|---|---|
| run 1, ffill (historia) | −0,19 | 0,26 | 0,48 | [−0,61, +0,23] | −1,8 |
| **run 2, exacto** | **−0,236** | **0,143** | **0,84** | **[−0,47, −0,00]** | **−3,7 (Russell mejor)** |

Regla escrita antes: sobrevive si d ≥ −0,10 y maxDD no empeora > 5 pp; falla si d ≤ −0,25 o los costes
borran > ½ del `ann_net`. **d = −0,236 está entre −0,25 y −0,10 → INCONCLUSO.** MaxDD y costes (10 %
del `ann_net`) habrían pasado. Se declara así y no se toca nada. Bloque B sigue parado.

Lo que sí cambia con el par correcto es la **lectura** del inconcluso: ya no es "sin potencia" (la SE
casi se ha partido por dos y la rho es la que dos carteras que comparten 500 nombres deben tener); es
que el Russell **rinde ~2,3 pp/año menos** que el S&P en las mismas fechas con el mismo motor, con un
intervalo que roza el cero por arriba y la valla de fallo por abajo. Dos lecturas honestas, las dos
declaradas antes: (i) el universo grande **no añade** rentabilidad ajustada y sí quita ~1,4 pp de
Sharpe-punto; (ii) su drawdown es 3,7 pp **mejor**. Ninguna autoriza tocar un umbral.

Limitación que viaja con el número: el mapa sectorial `fixed` (20260905) deja **66 % de Russell y 45 %
del S&P OOS** en `Other` (los deslistados), así que `MAX_PER_SECTOR=5` es parcialmente vacuo en los dos
lados, más en Russell. Es una asimetría medida, no una excusa: resolverla necesita sectores históricos
que ninguna fuente actual da.

## Qué sigue (regla de Lucas: A decide, B explica)

431 inconclusa no es A negativa. **432 (holdout), 433 (costes en deltas) y 434 (capacidad) se corren
igual**; el veredicto del bloque A se toma con las cuatro sobre la mesa. Lo que ya se sabe y no cambia:
la evidencia S&P sobrestima lo que el universo operado rinde, y el orden de magnitud es 2 pp/año.
