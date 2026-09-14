# Status Board

Each agent updates ONLY their own section. Read the other's section before starting work to avoid conflicts.

## Codex
**Updated:** 2026-09-13 16:13 UTC
**Working on:** revision de #85 para integracion. Los recuentos globales 23 agentes / 156 hallazgos /
118 supervivientes de la seccion de Claude son una declaracion del autor; esta revision no dispone de
un inventario trazable para acreditarlos de forma independiente. Los tres defectos concretos y los
merges de #82/#83 si tienen evidencia individual.
**Operational evidence:** 30 pending, ledger 0 y last_run_date 2026-09-04 describen el estado local
observado, no prueban ausencia de ejecuciones reales. Falta evidencia de broker para reconciliar.
**Backup scope:** copia local en carpeta OneDrive y restauracion de ensayo verificadas; las tres
generaciones examinadas eran sinteticas. No se afirma que no existiera otra copia en ninguna fecha.
La comprobacion web de OneDrive llega a inicio de sesion; sincronizacion remota pendiente de acceso.
**Files I'm touching:** `GROKBOARD.md` y esta seccion, sin modificar la seccion de Claude.

## Claude
**Updated:** 2026-09-14
**Working on:** **HYDRA-CI-01**, rama `fix/ci-01-portable-vs-external`, PR exclusiva (sin 433 ni 434).
Los **once** skips por caso que CI-02 destapo, clasificados uno a uno leyendo cada `skipif` y cada
artefacto que exige: **siete PORTABLES** y **seis AUDITORIAS EXTERNAS** (dos casos se parten en las
dos mitades). Los portables corren ya en clone limpio sobre fixtures sinteticos deterministas, sin
un solo byte de fixture commiteado: paridad motor/lab en `test_parity_portable.py` (generador con
semilla; **5 mutaciones del motor, 5 rojos**) y las cuatro invariantes de acreditacion en
`experiments/test_accredit_433.py` sobre inputs sinteticos - `cost_stress.data_inputs` ya estaba
hecho inyectable justamente para eso (**8 mutaciones, 8 rojos**). Las externas salen de la suite
requerida a `audits/`, que `run_all_tests.py` NO descubre, y las corre `tools/external_audit.py`
con tres estados y ningun cuarto: `RAN - PASS`, `RAN - FAIL`, `DID NOT RUN - <ruta exacta>`.
**Un skip dentro de una auditoria se reporta como FALLO**, no como pass ni como did-not-run.
`EXPECTED_CASE_SKIPS` queda **vacio** y hay un test que lo exige.
**Hallazgo por mutacion:** ninguna prueba portable llegaba nunca a un libro que SI acredita, asi
que vaciar `compared`/`uncompared` de una respuesta ACCREDITED dejaba las 18 en verde. Anadido el
camino positivo: un libro sobre la rejilla derivada acredita con los nueve bloques de identidad
comparados, y su control (una etiqueta de escenario cambiada) lo rechaza.
**Anomalia de write isolation, punto 6: REPRODUCIDA y es A con un MENSAJE FALSO.** El hijo imprimia
"The real backup root was NOT captured and is NOT protected" mientras ESE MISMO hijo tenia armado
el OneDrive\HydraBackups real (medido). La barrera nunca llego tarde: `repo_evidence_roots` leia el
redirect y no podia saber que `sitecustomize` recibe la raiz real por
`HYDRA_WRITE_BARRIER_BACKUP_ROOT` y la anade despues. Ahora se le pasa (`backup_root=`) y el aviso
solo sale en el unico caso genuinamente desprotegido. Cuatro tests nuevos lo fijan.
**Gate de 3.13:** el skip gate llevaba `if: matrix.python-version == '3.12'` heredado del paso de
coverage. Un skip NO pone roja la suite, asi que un caso omitido solo en 3.13 era invisible - el
agujero exacto que CI-02 existia para cerrar. Quitado: la verdad por caso se exige en 3.12 **y**
3.13. El **coverage floor sigue en 3.12 y sigue en 81.25**: es un numero unico y dos plataformas
dan dos numeros. No lo he tocado.
**Lo que NO cierro aqui:** `ledger_evidence()` / `KeyError: n_ledger` - `experiments/capacity_434.py`
y su test **no existen en `main`** (verificado con `git ls-tree origin/main`), viven en la rama de
#84, asi que van a **PR 3**. Registrado en el board antes de implementar.
**Files I'm touching:** `audits/` (4 nuevos), `tools/external_audit.py`, `tools/test_external_audit.py`,
`test_parity_portable.py`, los siete ficheros de test de los once casos, `test_skip_gate.py`,
`tools/check_skips.py`, `tools/write_isolation.py`, `tools/test_write_isolation.py`, `conftest.py`,
`tools/_bootstrap/sitecustomize.py`, `mypy.ini`, `.github/workflows/test.yml`, `CLAUDE.md`,
`GROKBOARD.md` y esta seccion.
**Blockers:** ninguno propio. Dos ficheros **sin trackear y ajenos** en el arbol compartido -
`tools/expire_pending.py` y `tools/test_expire_pending.py` - los dejo intactos; el segundo tiene un
error de ruff (B905) que **no arreglo** porque no es mio y no esta commiteado. Uso siempre
`git commit -- <paths>`. Sigue pendiente de Lucas el **CSV de fills reales del 2026-09-08**
(`exec_date,sleeve,tranche,ticker,side,units,price,fee`) o la confirmacion de que no hubo
ejecuciones: no se infiere del ledger local, y ninguna auditoria de este PR lo infiere.
**Medido en clone limpio** (worktree de `9129db9`, solo trackeados), **dos interpretes**:
3.14.3 y 3.13.15 dan **lo mismo** — 114 ficheros PASS / 0 skip / 0 fail, **1346 casos passed,
0 skipped, 0 failed, 0 error**, suite exit 0 y `check_skips ok` exit 0 en ambos, con tokens
distintos. Coverage **82,33 %** (floor 81.25, intacto). ruff y mypy limpios. Auditorias externas:
**11 DID NOT RUN** con la ruta exacta en clone limpio (exit 0; `--require-all` exit 1) y
**11 RAN - PASS** en la maquina lab (exit 0) — incluido un `reconcile()` REAL que deja los ocho
libros publicados byte-identicos, sin manifiesto y con `fully_accredited` en False.
**13 mutaciones, 13 rojos** contra el codigo commiteado, mas 3 reversiones del arreglo de
write-isolation, tambien rojas.
**TASK-431 sigue INCONCLUSIVE; 433 y 434 abiertas; Bloque B parado.**

---

### Historico (2026-09-10 20:20)
**Working on:** nada abierto en codigo. Esta tarde: ensayo de la puesta al dia del libro vivo sobre una
COPIA en el scratchpad (`state/` intacto, `HYDRA_BACKUP_DIR` desviado) y dos reproducciones mas de la
degradacion del proveedor. Resultado en `.comms/provider-evening-window-2026-09-10.md`: la degradacion es
la HORA (ventana de recarga EOD de Yahoo), no el tamano del lote — la barra "del 09-10" de los ETFs es un
relleno identico al 09-09; y la puesta al dia ficha 30/30 al 2026-09-08 por 14.439,09 USD sin un solo hueco.
**Proximo paso (viernes 2026-09-11, tras el cierre, dentro de las ~2 h): correr el libro vivo** — ese run
ficha esos 30 fills y renueva la semana 1. El libro de papel renueva el mismo dia por su propio ancla.
Revisadas y aceptadas TASK-416/417/418 (suite 93 PASS, ruff limpio); arreglo mio encima en `681e9bd`
(el diagnostico de 416 no puede abortar una corrida). Cola de Grok: 419 (en curso), **420**, **421**.
**Files I'm touching:** ninguno del arbol de codigo (solo `.comms/` y `GROKBOARD.md`).
**Blockers:** ninguno. Pendiente de Lucas: sincronizar el estado vivo con los fills reales del 09-08
(si difieren de los presuntos, via `confirm_fills.py`), y branch protection.

## Grok
**Updated:** 2026-09-11 14:20
**Working on:** TASK-431 done, INCONCLUSIVE. Waiting Claude review. Block B does not start.
**Files I'm touching:** none.
**Blockers:** none. Next in Block A is 432 after review; 430 still after verified settle.
