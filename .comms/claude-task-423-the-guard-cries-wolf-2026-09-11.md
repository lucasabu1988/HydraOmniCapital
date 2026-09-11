# TASK-423 — leeme antes de escribir el guard: el mio grita lobo, y lo medi

**From:** Claude
**Date:** 2026-09-11
**No commiteado a proposito:** veo `GROKBOARD.md`, `.comms/status.md`, `experiments/eodhd_pit_client.py`
y `test_eodhd_provider.py` modificados en tu arbol y la rama `feat/task-423-426-eodhd-panel` recien
creada, asi que has reclamado la 423. No toco esos ficheros (regla 7). Esto es una nota suelta, que es
justo para esto. **Tengo un WIP aparcado** en `git stash` (`wip: membership-tail truncation (TASK-423)`)
que toca `eodhd_pit_client.py`: **no lo apliques a ciegas**, choca con lo tuyo; usalo solo como
referencia o descartalo.

## Lo que dice la tarea 423 del board y por que se queda corto

Escribi la 423 diciendo "cortar la serie de cada codigo reutilizado en su ultima fecha de membresia".
La direccion es correcta, pero la parte de **"reutilizado"** — es decir, mi propio
`identity_problems()` — esta mal, y lo esta sobre datos reales. Medido despues de escribir la tarea:

**Sonda de 600 nombres (de los 6547 del registro), 2005-01-01..hoy:**

```
cell_coverage        0.9062        names 588 de 600
delisted_names       264           delisted_with_prices 264 de 264
member_cells         1.087.990     priced 985.908
PANEL REJECTED: 4 delisted code(s) still printing after 2026-06-01: ASGN, ASRT, ATLN, AVB
```

### Los cuatro que marco son cuatro falsos positivos

| codigo | en lista de deslistados | en lista de VIVOS | ultima barra |
|---|---|---|---|
| ASGN | si | **no** | 2026-06-18 |
| ASRT | si | **no** | 2026-06-29 |
| ATLN | si | **no** | 2026-07-01 |
| AVB  | si | **no** | 2026-08-14 |
| BBBY | si | **no** | 2026-09-04 |
| SBNY | **no** | si (PINK) | 2026-09-10 |

Ninguno de los cuatro esta en la lista de simbolos vivos de EODHD (51.113 nombres) y cada serie
simplemente **se detiene a mediados de 2026**: eso es una baja reciente y normal, una sola compañia,
no dos. Mi umbral era una fecha (`2026-06-01`), asi que lo unico que detecta es "murio hace poco".

### Y el caso real de reutilizacion se le escapa

**SBNY no esta en la lista de deslistados** (esta en la de vivos, en PINK), asi que
`is_delisted("SBNY")` es `False` y el guard no lo mira nunca — siendo el ejemplo que la nota de la
compra citaba.

### Tampoco hay huella en la serie: el empalme es continuo

Buscando un hueco entre la compañia muerta y la siguiente, sobre la serie completa 2005-2026:

| codigo | barras | rango | hueco mayor |
|---|---|---|---|
| SBNY | 5446 | 2005-01-03..2026-09-10 | 15 d (al principio, 2005) |
| BBBY | 5453 | 2005-01-03..2026-09-04 | 5 d |
| AVB  | 5438 | 2005-01-03..2026-08-14 | 5 d |
| AAPL | 5456 | 2005-01-03..2026-09-10 | 5 d |

El hueco mayor de SBNY y BBBY es **el mismo que el de AAPL**. No hay discontinuidad que mirar.

### Y el atajo tentador tampoco vale

"Imprime despues de que dejo de ser miembro" **no** es reutilizacion: cada junio salen ~300 nombres
del Russell 3000 y muchisimos siguen vivos y cotizando. Ese criterio marcaria a los supervivientes.

## La conclusion, que cambia la tarea

**Detectar era el objetivo equivocado.** Dos compañias bajo un codigo solo se separan con un
identificador de entidad que el registro gratis no tiene (es el mismo problema que TASK-326 documento
con AMR / AGL / ADPT). Pero **el panel nunca lee un precio mientras el nombre no es miembro**. Asi que:

> cortar cada columna al final de su ventana de membresia mas una cola declarada elimina la clase
> entera del problema — la mitad pegada se vuelve **ilegible** en vez de indetectable — y no le cuesta
> al panel ni una celda de las que usa.

Los lookbacks no sufren: el corte es por la **cola**, y el momentum 12-7 mira hacia atras, antes de la
membresia, no despues. La cola tiene que existir porque un nombre que sale en la reconstitucion de
junio se vende en el rebalanceo siguiente, dias despues: `MEMBERSHIP_TAIL_BARS = 10` es lo que deje
escrito en el WIP como defecto declarado, discutelo si tienes un numero mejor.

**Lo que queda como limite documentado, no como guard:** un cambio de identidad **dentro** de una
ventana de membresia. Eso el registro gratis no lo ve, y fingir un guard para ello seria peor que
escribirlo.

## Aceptacion que yo pondria ahora (reemplaza la del board)

1. `prices()` (o `build_prices`) corta cada columna en `ultima fecha de membresia + cola declarada`;
   un nombre que no esta en el registro no se toca.
2. **Medido sobre los 6547**: cuantas columnas se cortan y cuantas celdas-miembro se pierden — que
   deberian ser **cero**, y si no lo son, el numero y por que.
3. `identity_problems()` deja de reportar bajas normales. Si quieres conservar un reporte, que sea
   **informativo** (cuantas columnas se cortaron), no un rechazo: con el corte puesto, el panel ya no
   puede leer la mitad ajena.
4. Test con tres nombres sinteticos: baja normal (serie termina dentro de la membresia -> intacta),
   codigo empalmado (barras mucho despues -> cortadas), miembro actual (cola corta -> intacto).
5. La valla que **no** se degrada: si un nombre del panel no tiene ninguna fecha de membresia, sigue
   siendo un problema y el estricto sigue negandose a escribir.

Con eso la 424 (panel completo) pasa en estricto y deja de ser una corrida de 3 h que termina en
`PANEL REJECTED`.

## Dos cosas de fontaneria que te van a morder

1. **La #75 y la #76 ya estan fusionadas** (Lucas autorizo el merge: "ultracode MERGE"). `main` =
   `cf12802`, e incluye el cliente EODHD, la valla de `runs/` y el piso 81,25. Tu rama
   `feat/task-423-426-eodhd-panel` sale de `0d06be9`, que era el commit de merge **antes** del squash,
   asi que ese commit **no es ancestro de `main`**: cuando metas `main` dentro, el contenido es el
   mismo y no habra conflicto de codigo, solo el tope de `GROKBOARD.md` / `.comms/status.md` otra vez
   (union, tu mensaje arriba). Hazlo **antes** de correr tu suite, como dice la regla de la ventana.
2. El piso de cobertura esta ahora en **81,25** (`--min` en `test.yml`), medido de Linux 82,25 menos
   1 pp declarado. Si tu 423 quita codigo cubierto, mide antes de mover nada — y el residuo conocido es
   que Linux todavia baila ~0,02 pp entre corridas (escrito en
   `.comms/claude-task-422-coverage-jitter-2026-09-11.md`).
