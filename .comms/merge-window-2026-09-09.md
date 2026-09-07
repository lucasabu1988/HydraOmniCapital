# Ventana de merge — miércoles 2026-09-09 en adelante

Claude, 2026-09-07. Este fichero existe porque el plan de merge vivía en la salida JSON de un agente en
un directorio temporal, y un plan que no está en el repo no es un plan. Todo lo de abajo está medido
(`git merge-tree`, `gh run list`, la suite) o decidido por Lucas con fecha; nada es opinión.

## 0. La fecha dura que ordena todo lo demás

`renewal_slot` renueva cuando `bars_between(anchor, today) % step_bars == 0`, con `anchor = 2026-09-04`
y `step_bars = 5`. Barras: 09-08, 09-09, 09-10, 09-11, **09-14**. **El próximo `plan()` con posiciones en
cartera es el lunes 14.** Dos defectos vivos de `main` son inertes con el libro vacío y muerden con
posiciones:

- **NaN truthy en `plan()`**: `float(px.get(t, ...) or 0.0)` con precio NaN devuelve NaN, el valor del
  paquete se vuelve NaN y **se cancela la renovación de todas las mangas**. La corrección
  (`mark_px` + `_reject`) vive en `structural-hardening-2026-09`.
- **`age_stale` absorbe rellenos**: un forward fill reescribe `last_px` y reinicia el reloj de write-off
  (H-005, medido en `.comms/task-402-mark-and-a-deeper-finding.md`). Sin corrección aún; es política
  contable y espera a Lucas.

**Consecuencia:** los pasos 1 y 2 de abajo tienen que estar en `main` **antes del lunes 14**, o sea entre
el miércoles 9 y el viernes 11. El resto puede esperar.

## 1. Martes 09-08 — ejecutar, no correr

- Ejecutar las 30 órdenes de `state/instructions_20260904.md` **al cierre**. La vista en acciones
  enteras (`output/pending_shares_20260904.md`) es apoyo de lectura, no la hoja. Tres nombres no caben
  en acciones enteras (SNDK, LITE; QQQ a −4.1%): si no se compran, el miércoles se confirman con
  `units=0`.
- **No correr `daily.py` el martes.** Con el mercado abierto, `main` liquidaría a una barra parcial (el
  arreglo, `fix/astra-03`, no está mergeado). Antes de la apertura preflight lo bloquea solo (HARD).

## 2. Miércoles 09-09 — el settle verificado es la llave de todo

Desde el árbol de producción `C:\Users\caslu\HydraOmniCapital\hydra_screener_local`, **después** de que
el cierre del 09-08 esté publicado:

```
python daily.py                                         # liquida los 30 al cierre real del 09-08
python confirm_fills.py --report --from-csv <fills>.csv # leer el diff; nada se escribe
python confirm_fills.py --from-csv <fills>.csv          # escribe; save_state respalda antes
python reconcile.py <posiciones>.csv                    # libro vs broker, solo lectura
python verify_state.py                                  # replay del ledger limpio
```

Si preflight da HARD porque la barra del 09-08 no está, **no pasar `--force`**: es el sistema haciendo
lo correcto; esperar a que Yahoo publique. Solo tras `verify_state.py` limpio existe "first settle
verified". Después: **copiar `state/` a mano** fuera de `state_v9/` (el servicio de respaldo nuevo aún
no está en `main`), como en `PRODUCTION-manual-20260906-2300/`.

## 3. Regla previa a cualquier merge: la valla

`hydra_screener_local/conftest.py` (en `main` desde `34b0143`) impide que una suite escriba en el
respaldo real. **Correr la suite de una rama sin él escribe en OneDrive** — medido: 25 ficheros en
`state_v9/`. Antes de tocar una rama:

```
git merge origin/main        # trae la valla y los ignores anclados de ruff
python run_all_tests.py --strict-console > /tmp/s.log 2>&1; echo "EXIT=$?"   # sin tubería
```

Ya vallados (2026-09-07): `post-freeze-wiring`, `n-sleeve-engine`, `chore/task-391-local-gates`,
`ci/task-388`, `docs/task-389`, `feat/a12r-backup-service`, `fix/astra-03`, `fix/astra-06-followup`.
**Sin vallar**: `structural-hardening-2026-09`, `fix/task-390`, `test/gm-002r`, `fix/astra-04`,
`fix/astra-02`, `test/astra-09`, `audit/subtract-parked-clis-v2`, `docs/astra-prereg-01-08-10`,
`feat/astra-11`, `fix/astra-05`, `fix/astra-06-pit-breadth`, `fix/astra-07`, `audit/dead-cloud-ops`,
`audit/docs-packaging-truth`.

## 4. Orden de merge, con precondición y conflicto medido

| # | Rama | Precondición | Conflictos con main | Cómo resolver |
|---|---|---|---|---|
| 1 | `chore/task-391-local-gates` | settle verificado | 1 | Es el **vehículo de la pila estructural**: contiene `structural-hardening` entero (26 commits) más `main`. `test.yml`: conservar **los 7 jobs Y la lista de lint** — tomar un lado borra un gate |
| 2 | `post-freeze-wiring` **+ `fix/astra-02`** | paso 1 | 1 (.gitignore, ya resuelto en `6958661`) | **Co-requisito**: `post-freeze-wiring` enciende `APPLY_SPLITS`; sin la 02, una venta total en fecha de split deja posición fantasma que `state_check` reporta limpia. Preservar `7665884` ("ship analytics/ in the wheel"), que vive solo en `merge-prepared` |
| 3 | `ci/task-388-first-real-run` | paso 1 | 0 | Un trigger `workflow_dispatch`; independiente del orden |
| 4 | `docs/astra-prereg-01-08-10` | paso 2 | 0 | Registra H-004/005/006 y los 3 xfail(strict) |
| 5 | `fix/astra-06-pit-breadth` + `fix/astra-06-followup` | paso 4 | 1 | Una sola unidad (el followup **contiene** pit-breadth). Lleva **H-007 aplicada** (regla 6, Lucas 09-07): `core/regime.py` + SPEC + efecto medido |
| 6 | `fix/astra-03-observed-fill-prices` | paso 4 y **veredicto del re-review** | 0 | Objeciones 1 y 2 cerradas por ejecución; la 3 (TASK-402) cerrada en `52eac42`, pendiente de que alguien lo confirme. Fila WARN por decisión de Lucas |
| 7 | `fix/astra-04-skip-gate` | paso 1 | 4 | Reescribe la contabilidad del runner (casos, no ficheros). Tras ella el baseline pasa a ~59 ficheros / 672 casos / 3 skips nominados: actualizar CLAUDE.md |
| 8 | `fix/task-390-tier3-and-stable-coverage` | paso 7 | 3 | **No mover el piso de cobertura** hasta dos corridas iguales sobre un commit |
| 9 | `test/gm-002r-gate-tools` | paso 8 | 3 | Necesita `tools/` de la pila estructural; no cherry-pickear a main |
| 10 | `fix/astra-07-paired-bootstrap` | paso 5 | 0 | Añadir banner SUPERSEDED a `.comms/grok-task-332-bootstrap.md` en el mismo commit |
| 11 | `feat/astra-11-evidence-audit` | paso 10 | 0 | Asserta sobre `bootstrap_compare.expected_max_sharpe`; si la 07 renombró, mover en el mismo merge |
| 12 | `docs/task-389-duplicate-share-class` | cualquiera | 0 | Docs. La mitad que deduplica es regla 6 y **no** entra |
| 13 | `audit/dead-cloud-ops` (PR #42) | paso 1 | 0 | Parece revertir `1c21bc4`/`0442ec9` en el diff, pero su merge-base es viejo: resolver hacia main |
| 14 | `audit/docs-packaging-truth` (PR #43) | pasos 1-2 | — | Su `[tool.setuptools]` borraría `analytics*` y `py-modules` (R-1001): **resolver `pyproject.toml` hacia la pila estructural o cerrar el PR** |
| 15 | `audit/subtract-parked-clis-v2` (PR #44) | paso 14 | 5 | **Último**: la mayor superficie (test.yml, README, daily.py, pyproject, ruff.toml, run_all_tests.py) |

**Fuera de esta ventana:**

- `feat/a12r-backup-service` — **hasta que alguien la ataque otra vez**. La primera versión pasó sus
  72 tests y fue demolida; esta pasa 91 y eso tampoco basta. Criterio: cero escrituras fuera del
  destino, cero rechazos con efectos.
- `n-sleeve-engine` + `test/astra-09` — espera la resolución de `plan()` decidida por Lucas (prevalece
  la semántica de `structural-hardening`) y sus 5 condiciones de aceptación (regresión con NaN
  inyectado; rechazo localizado; las demás mangas siguen; paridad byte-compatible). Ya vallada (`eec221e`).
- `fix/astra-05` — su arreglo de elegibilidad está dormido sin `close_raw.pkl` (cierres tal como
  imprimieron 2004-2026): hay que generarlo en el árbol de producción antes.
- `merge-prepared-2026-09` (PR #41) — **cerrar**: no contiene `main` (22 atrás) ni la punta de
  `structural-hardening`. Rescatar `7665884` antes.
- `feat/astra-12-restore-drill` — **abandonar**, superada por `a12r`.

## 5. Después de los merges

- **`USE_BAR_STORE`**: sigue en `False`. Encender solo tras una semana de `--verify` limpios (TASK-385).
- **Tarea programada de Windows**: instalar **desde el árbol de producción**, no desde el worktree
  `-wiring` — instalada desde ahí apuntaría a un `state/` sin `portfolio_v9.json` y acuñaría un libro
  nuevo de 100.000. El XML viene `Enabled=true` a las 16:45 local (UTC−5 = 17:45 ET, después del
  cierre: la hora sí es correcta).
- **Push protection**: encender **después** del settle (un falso positivo bloquea el push y se limpia
  en el navegador).
- **Ruleset de `main`**: comando en manos de Lucas (el clasificador de Claude lo bloquea).

## 6. Lo que sigue esperando a Lucas, sin fecha

H-005 y H-006 (medición pendiente); la mitad de dedupe de la 389 (regla 6); Norgate (aprobado, sin
comprar — primer uso: `TASK-403`, el panel PIT de Russell, que desbloquea la 389 y la medición de H-005).
