"""TASK-433: the deliverable table, rendered from an accredited run's own report.

    python experiments/report_433.py --run-id <id> [--md out.md]

Reads `_lab_scratch/task433_accredited_<run_id>.json` - the file `accredit_433.reconcile()`
wrote - and renders what the task asks for and nothing it does not: per universe and scenario
`ann_net`, `sharpe_excess`, `maxDD`, and the three deltas against that universe's own base, plus
the T-bill comparison, the period, the mark count, the calendar, the effective costs and the
identity blocks each book actually compared.

It computes no statistic of its own. Every number here is read from the payload, which was
produced from books that `provenance.accredit()` had already validated against their scenario's
effective request; recomputing them somewhere else would only create a second number to
reconcile. The one thing it does add is the reading of the deltas - which scenario, if any, is
the first to put `ann_net` under the risk-free rate - because that is the question the table
exists to answer and leaving it to the reader is how a sensitivity gets quoted as a level.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import provenance as PV  # noqa: E402

SCENARIOS = ("base", "conservative", "stress", "smallcap_crisis")
BP = {"base": "10/5", "conservative": "20/8", "stress": "35/10", "smallcap_crisis": "50/15"}
PANELS = ("russell", "sp500")
PANEL_NAME = {"russell": "Russell PIT", "sp500": "S&P 500 OOS"}


def load(run_id: str) -> dict:
    path = os.path.join(HERE, "_lab_scratch", f"task433_accredited_{run_id}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"no report for run {run_id!r} at {path}. TASK-433 publishes one file per run; an "
            "absent report is not an empty one.")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class OneGridViolated(Exception):
    """The eight books are not on one calendar, so the deltas are not deltas."""


def assert_one_comparison_grid(payload: dict) -> dict:
    """HARD GATE, before a single number is rendered. Eight books, one calendar, verified here.

    THE TRAP THIS CLOSES. `cost_stress.derived_grid("sp500")` is the S&P panel's NATIVE grid -
    1084 marks from 2005-02-11 - and it is NOT what TASK-433 measures. Every one of the eight
    books lands on the ANCHOR's grid, 814 marks from 2010-06-28, because the S&P scenarios are
    driven by `drive_sp_same_grid` with `start_date=russell_start_date()`. A delta is a
    subtraction between two books; two calendars would make the whole table meaningless while
    looking exactly as plausible. The semantic trap is easy to repeat, so this is an assertion
    rather than a note.

    It checks the per-book `calendar` block `reconcile` recorded - digest, count and endpoints -
    not the aggregate boolean beside it. A boolean computed by the same pass that produced the
    rows is not independent of them.
    """
    recs = [r for r in payload["reconciliation"] if r.get("accredited_calendar")]
    if len(recs) != 8:
        raise OneGridViolated(
            f"{len(recs)} of 8 scenarios carry an accredited calendar block. An incomplete run "
            "has no table: a missing book is not a zero.")
    digests = {r["accredited_calendar"]["sha256"] for r in recs}
    counts = {r["accredited_calendar"]["n_marks"] for r in recs}
    firsts = {r["accredited_calendar"]["first"] for r in recs}
    lasts = {r["accredited_calendar"]["last"] for r in recs}
    if len(digests) != 1 or len(counts) != 1 or len(firsts) != 1 or len(lasts) != 1:
        detail = {f"{r['panel']}/{r['scenario']}":
                  (r["accredited_calendar"]["n_marks"], r["accredited_calendar"]["first"],
                   r["accredited_calendar"]["last"], r["accredited_calendar"]["sha256"][:12])
                  for r in recs}
        raise OneGridViolated(
            "the eight books are NOT on one comparison grid, so every delta below would be a "
            f"subtraction across calendars: {detail}")
    marks = payload.get("marks_accredited") or {}
    if marks.get("identical") is not True or marks.get("n_books") != 8:
        raise OneGridViolated(
            f"the per-book calendars agree but the aggregate disagrees: {marks}. Two answers to "
            "one question is a defect, not a rounding difference.")
    return dict(n_marks=counts.pop(), first=firsts.pop(), last=lasts.pop(),
                calendar_sha256=digests.pop())


#: A scenario is not required to degrade monotonically - a cost change moves the NAV and therefore
#: the whole later trajectory, so Sharpe and maxDD can legitimately move either way. But a
#: MATERIAL improvement in `ann_net` when costs RISE is not a trajectory effect to wave through:
#: it is the shape a mislabelled book, a swapped cost pair or a broken cost application would take,
#: and it is worth investigating before publication even when everything accredits.
IMPROVEMENT_TOLERANCE_PP = 0.05


def degradation_anomalies(payload: dict, tol_pp: float = IMPROVEMENT_TOLERANCE_PP) -> list:
    """Scenarios whose `ann_net` IMPROVES materially as costs rise. Reported, never auto-fixed."""
    rows = _rows(payload)
    out = []
    for panel in PANELS:
        for cheaper, dearer in zip(SCENARIOS, SCENARIOS[1:]):
            a, b = rows.get((panel, cheaper)), rows.get((panel, dearer))
            if a is None or b is None:
                continue
            gain = float(b["ann_net"]) - float(a["ann_net"])
            if gain > tol_pp:
                out.append(dict(panel=panel, cheaper=cheaper, dearer=dearer,
                                gain_pp=round(gain, 4),
                                detail=f"{PANEL_NAME[panel]}: ann_net RISES {gain:+.4f} pp going "
                                       f"from {BP[cheaper]} to {BP[dearer]} bp/side"))
    return out


def _rows(payload: dict) -> dict:
    out = {}
    for row in payload["rows_accredited"]:
        out[(row["panel"], row["scenario"])] = row
    return out


def _f(v, dp=4):
    return "n/a" if v is None else f"{float(v):.{dp}f}"


def table_md(payload: dict) -> str:
    rows = _rows(payload)
    lines = []
    for panel in PANELS:
        base = rows.get((panel, "base"))
        lines.append(f"\n### {PANEL_NAME[panel]}\n")
        lines.append("| escenario | bp/lado | ann_net % | sharpe_excess | maxDD % | "
                     "ΔCAGR pp | ΔSharpe | ΔmaxDD pp | T-bill % | ann_net < T-bill |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|:--:|")
        for sc in SCENARIOS:
            r = rows.get((panel, sc))
            if r is None:
                lines.append(f"| {sc} | {BP[sc]} | — | — | — | — | — | — | — | NOT ACCREDITED |")
                continue
            lines.append(
                f"| {sc} | {BP[sc]} | {_f(r['ann_net'])} | {_f(r['sharpe_excess'])} | "
                f"{_f(r['maxdd_net'], 2)} | {_f(r.get('d_ann_net'))} | "
                f"{_f(r.get('d_sharpe_excess'))} | {_f(r.get('d_maxdd'))} | "
                f"{_f(r['rf_ann_pct'])} | {'**YES**' if r.get('below_tbill') else 'no'} |")
        if base is None:
            lines.append("\n*(no accredited base: the deltas have no reference)*")
    return "\n".join(lines)


def crossing(payload: dict) -> list:
    """The first scenario, per universe, whose net return falls under the risk-free rate."""
    rows = _rows(payload)
    out = []
    for panel in PANELS:
        first = None
        for sc in SCENARIOS:
            r = rows.get((panel, sc))
            if r is not None and r.get("below_tbill"):
                first = sc
                break
        out.append((panel, first))
    return out


def identity_md(payload: dict) -> str:
    prov = payload["provenance"]
    lines = ["\n### Acreditacion por escenario\n",
             "| escenario | estado | bloques comparados | no comparados (y por que) |",
             "|---|---|---|---|"]
    for key in payload["order"]:
        state = "ACCREDITED" if key in prov["accredited"] else "NOT ACCREDITED"
        compared = prov["compared_by_book"].get(key) or []
        why = prov["uncompared_by_book"].get(key) or {}
        lines.append(f"| {key} | {state} | {len(compared)}: {', '.join(sorted(compared))} | "
                     f"{'; '.join(f'{k}: {v}' for k, v in sorted(why.items())) or '—'} |")
    lines.append(f"\n`fully_accredited = {str(prov['fully_accredited']).lower()}`")
    return "\n".join(lines)


def provenance_md(payload: dict) -> str:
    recs = {f"{r['panel']}/{r['scenario']}": r for r in payload["reconciliation"]}
    first = payload["rows_accredited"][0] if payload["rows_accredited"] else {}
    marks = payload.get("marks_accredited") or {}
    lines = ["\n### Identidad de la corrida\n"]
    lines.append(f"- **run_id**: `{payload.get('run_id')}`")
    lines.append(f"- **directorio**: `{payload.get('accredited_dir')}`")
    lines.append(f"- **libros**: {marks.get('n_books')} , misma rejilla: "
                 f"`{marks.get('identical')}`")
    if first:
        lines.append(f"- **periodo**: {first.get('first')} .. {first.get('last')} "
                     f"({first.get('n')} marcas, paso 5 barras)")
    lines.append(f"- **escenarios (bp/lado, congelados antes de mirar nada)**: "
                 + ", ".join(f"{s} {BP[s]}" for s in SCENARIOS))
    for key, rec in recs.items():
        sha = rec.get("accredited_sha256")
        if sha:
            lines.append(f"  - `{key}` book sha256 `{sha[:16]}` "
                         f"costes {rec['stock_bp']}/{rec['etf_bp']} bp")
    lines.append("\n**Limitacion que viaja con el resultado:** `self_sha256` es un digest SIN "
                 "CLAVE producido por el mismo `seal()` publico que llama un escritor. Prueba "
                 "integridad del fichero frente a corrupcion; **no** prueba independencia frente "
                 "a un autor que modifica el artefacto y lo vuelve a sellar. Integridad del "
                 "fichero, compatibilidad con una solicitud e independencia estadistica son tres "
                 "afirmaciones distintas, y este camino habla de las dos primeras.")
    return "\n".join(lines)


SECTOR_CAVEAT = """
### Alcance de esta evidencia — leer antes de citar cualquier numero

El panel se carga con `sectors mode=fixed_map snapshot=20260905 mapped=2048 fallback=4000
pit_valid=False`, y el propio lab avisa: *"FIXED-MAP SCENARIO: one map for every date,
reproducible but NOT point-in-time -> excluded from PIT conclusions"* y *"the sector map is mostly
fallback -> the sector cap will not bind the same way; headline not comparable with other runs"*.

Consecuencia, dicha con precision:

- El mapa sectorial decide que nombres sobreviven al cap `MAX_PER_SECTOR`, y por tanto la
  **seleccion y la concentracion**; seleccion y concentracion deciden el **turnover**; y el
  turnover es exactamente la palanca por la que un coste por lado se convierte en rentabilidad
  perdida. La sensibilidad a costes **no es independiente** de la construccion sectorial.
- Estos ocho libros comparten esa construccion con los libros historicos de TASK-431, asi que las
  **deltas** son evidencia **condicional sobre la misma trayectoria experimental**: dicen cuanto se
  degrada ESTA configuracion al subir los supuestos de coste.
- **No son una estimacion universal de la sensibilidad de HYDRA a costes.** Otra construccion
  sectorial point-in-time podria producir otro turnover y, por tanto, otra sensibilidad. Nada aqui
  mide eso, y presentarlo como si lo midiera seria pasar de "medido bajo estas condiciones" a
  "propiedad del sistema" sin un solo dato nuevo.
- Los **niveles absolutos** (`ann_net`, `sharpe_excess`, `maxdd_net`) arrastran ademas el caveat de
  PIT sectorial y no deben citarse como resultado PIT.
"""


def render(payload: dict) -> str:
    grid = assert_one_comparison_grid(payload)        # HARD: no table without one calendar
    parts = [f"## TASK-433 — sensibilidad a costes, corrida `{payload.get('run_id')}`",
             f"\nRejilla de comparacion verificada: **{grid['n_marks']} marcas** "
             f"{grid['first']} .. {grid['last']}, digest `{grid['calendar_sha256'][:16]}`, "
             f"identica en los ocho libros.",
             table_md(payload), identity_md(payload), provenance_md(payload),
             SECTOR_CAVEAT,
             "\n### Lectura\n"]
    for panel, first in crossing(payload):
        if first is None:
            parts.append(f"- **{PANEL_NAME[panel]}**: **ningun escenario** pone `ann_net` por "
                         f"debajo de la T-bill, ni siquiera 50/15 bp/lado. Dicho expresamente, "
                         f"como pide la tarea.")
        else:
            parts.append(f"- **{PANEL_NAME[panel]}**: el primer escenario con "
                         f"`ann_net < T-bill` es **{first}** ({BP[first]} bp/lado).")

    anomalies = degradation_anomalies(payload)
    if anomalies:
        parts.append("\n**ANOMALIA DE DEGRADACION — investigar antes de publicar.** Subir el "
                     "coste no obliga a que Sharpe o maxDD empeoren de forma monotona (el coste "
                     "mueve el NAV y con el toda la trayectoria posterior), pero una MEJORA "
                     "material de `ann_net` al encarecer la ejecucion tiene la forma de un libro "
                     "mal etiquetado o de un par de costes intercambiado, y merece revision "
                     "aunque todo acredite:")
        for a in anomalies:
            parts.append(f"  - {a['detail']}")
    else:
        parts.append(f"\n- **Degradacion**: ningun escenario mejora `ann_net` en mas de "
                     f"{IMPROVEMENT_TOLERANCE_PP} pp al subir los costes. No se exige "
                     f"monotonicidad de Sharpe ni de maxDD: el coste altera la trayectoria, no "
                     f"solo el nivel.")
    return "\n".join(parts)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--md", type=str, default=None, help="write the rendered markdown here")
    args = ap.parse_args(argv)
    payload = load(args.run_id)
    text = render(payload)
    print(text)
    if args.md:
        os.makedirs(os.path.dirname(os.path.abspath(args.md)), exist_ok=True)
        with open(args.md, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"\nwrote {PV._rel(args.md)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
