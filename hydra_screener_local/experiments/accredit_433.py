"""TASK-433: drive ACCREDITED cost-stress books, preserving every pre-manifest one.

The eight books published on 2026-09-11 predate `provenance.py` and cannot be accredited
retroactively; `cost_stress.classify_existing_books` has already stamped each of them
`historical_incomplete`. This script produces a SECOND, parallel set under
`_lab_scratch/accredited/` with a full sealed manifest beside every book. Nothing under
`_lab_scratch/engine_book_*.pkl` or `_lab_scratch/cost_stress/` is written, renamed, moved or
deleted: the historical books keep their paths and their classification, and the two sets are
compared against each other in `--reconcile`.

One book per invocation (`--only panel:label`) is the intended use: each engine drive is minutes
long, and the book plus its manifest hit the disk the moment that drive returns, so a run that
dies at book six leaves five accredited books behind rather than nothing.

Order matters twice. `russell:base` is the anchor - its calendar becomes the REQUESTED calendar
of every later manifest, which is what turns the 814-mark identity into a refusal instead of a
footnote - and `sp500:base` needs the Russell start date to land on the same grid.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # TASK-380: cp1252 consoles

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import cost_stress as CS  # noqa: E402
import holdout as HO  # noqa: E402
import provenance as PV  # noqa: E402
import run_russell_prereg as R  # noqa: E402

#: New location. The historical books are NEVER written to; see the module docstring.
#:
#: TASK-433 regeneration, 2026-09-14. `ACC_DIR` itself still points where the 2026-09-12 run
#: published, and that directory is LEFT EXACTLY AS IT IS: eight books whose seals verify but
#: which `accredit()` refuses on `[code]` - config.py, cost_stress.py and provenance.py have all
#: moved since, so they were produced by different code and cannot answer today's request. That
#: refusal is correct and it is the reason a regeneration exists at all. `produce()` never
#: overwrites, so a new run does not go there: it goes to `accredited/runs/<run_id>/`, which
#: gives every new book a new identity and leaves the old evidence untouched and readable.
ACC_ROOT = os.path.join(HERE, "_lab_scratch", "accredited")
ACC_DIR = ACC_ROOT
#: Set by `use_run()`. None means "the legacy location", which is the withdrawn run's.
RUN_ID: str | None = None
#: The 2026-09-12 artifact at this path was WITHDRAWN as a current result: it recorded
#: `fully_accredited = true` under an accreditation contract that no longer holds (the anchor's
#: calendar was compared against nothing, and no positive evidence was recorded per mandatory
#: contract). It is preserved as historical evidence; the withdrawal, with the superseded hash
#: and the reason, is beside it in `task433_accredited_WITHDRAWN.json`. Writing here again
#: publishes a NEW result and does not revive the old claim.
#: WITHDRAWN. The 2026-09-12 artifact at the old path recorded `fully_accredited = true` under a
#: contract that no longer holds. A comment in the writer does not change what a reader loads, so
#: the withdrawal is enforced two ways: new runs publish to an UNAMBIGUOUS new path, leaving the
#: preserved artifacts untouched, and `current_result()` below refuses to hand a caller the
#: withdrawn file.
WITHDRAWN_JSON = os.path.join(HERE, "_lab_scratch", "task433_accredited.json")
WITHDRAWAL_NOTE = os.path.join(HERE, "_lab_scratch", "task433_accredited_WITHDRAWN.json")
OUT_JSON = os.path.join(HERE, "_lab_scratch", "task433_accredited_v2.json")


def mint_run_id(now=None) -> str:
    """A new run's identifier: the date plus the digest of the code that will produce it.

    Two runs of the same code on the same day collide ON PURPOSE - the identifier is meant to
    say WHICH code produced the books, not to be unique for its own sake. If the code moves, the
    id moves, and the books land somewhere else rather than beside evidence they cannot answer
    for. `produce()` still refuses to overwrite whatever is already at the path.
    """
    from datetime import datetime, timezone
    now = now or datetime.now(timezone.utc)
    code = PV.code_identity()
    digest = (code.get("modules_combined") or PV.sha256_json(code))[:12]
    return f"{now:%Y%m%d}-{digest}"


def use_run(run_id: str) -> dict:
    """Point this module's OUTPUTS at a run of its own. Inputs and the historical set are untouched.

    Returns the paths it bound, so a caller records them rather than reconstructing them.
    """
    global ACC_DIR, OUT_JSON, RUN_ID
    RUN_ID = run_id
    ACC_DIR = os.path.join(ACC_ROOT, "runs", run_id)
    OUT_JSON = os.path.join(HERE, "_lab_scratch", f"task433_accredited_{run_id}.json")
    _ANCHOR_CAL_CACHE.clear()
    return dict(run_id=run_id, acc_dir=ACC_DIR, out_json=OUT_JSON)


def current_result(path: str = None):
    """The result a consumer should read, or a refusal naming the withdrawal.

    Readers identified the current result BY PATH, and the withdrawn artifact still sits at the
    path they knew. Anything asking this module what the standing result is gets the new one or
    an explicit refusal - never the retired claim by default.
    """
    import json as _json
    target = path or OUT_JSON
    if os.path.abspath(target) == os.path.abspath(WITHDRAWN_JSON):
        raise ValueError(
            "task433_accredited.json was WITHDRAWN on 2026-09-12: it recorded "
            "fully_accredited=true under an accreditation contract that no longer holds. It is "
            f"preserved as historical evidence and the withdrawal is recorded in "
            f"{os.path.basename(WITHDRAWAL_NOTE)}. It is not the current result and must not be "
            "read as one.")
    if not os.path.exists(target):
        raise FileNotFoundError(
            f"no current accredited result at {target}. TASK-433 is OPEN: the withdrawn artifact "
            "was not replaced, and an absent result is not a passing one.")
    with open(target, encoding="utf-8") as fh:
        return _json.load(fh)

#: (a)..(h) exactly as the task ordered them: the anchor first, then the grid partner, then the
#: Russell scenarios, then the S&P scenarios.
ORDER = (
    ("russell", "base"),
    ("sp500", "base"),
    ("russell", "conservative"),
    ("russell", "stress"),
    ("russell", "smallcap_crisis"),
    ("sp500", "conservative"),
    ("sp500", "stress"),
    ("sp500", "smallcap_crisis"),
)

#: TASK-431's published rows, as they stand on the board. Reconciliation targets, not inputs.
PUBLISHED_431 = {
    "russell": dict(ann_net=5.6638, rf_ann_pct=1.5090, sharpe_excess=0.4878, maxdd_net=-16.01),
    "sp500": dict(ann_net=7.9594, rf_ann_pct=1.5090, sharpe_excess=0.7238, maxdd_net=-19.67),
}

#: The previous cycle's ALGEBRAIC back-solve, kept only so the direct measurement can be put
#: beside it. It is a restatement of the cost deltas of the historical books; see
#: `cost_stress.INFERENCE_RULE` before quoting the two together.
INFERRED_TURNOVER_PCT = {
    "russell": dict(stocks=10.87, etf=1.22, total=12.09,
                    source="back-solved from the historical books' cost deltas, 50/50 blend"),
    "sp500": dict(stocks=None, etf=None, total=13.21,
                  source="back-solved from the historical books' cost deltas"),
}


def scenario_bp(label: str) -> tuple[float, float]:
    for name, s_bp, e_bp in CS.SCENARIOS:
        if name == label:
            return float(s_bp), float(e_bp)
    raise ValueError(f"unknown scenario {label!r}")


def _historical_paths() -> set:
    return {os.path.normcase(os.path.abspath(p)) for p in CS.historical_books()}


def not_historical(path: str) -> str:
    """Refuse, at the last moment before a write, to stand on a pre-manifest book.

    This is here because the invariant failed in practice on 2026-09-12: a mutation run pointed
    `acc_path` at `cost_stress.book_path` and a test that writes a fixture into "the accredited
    slot" then overwrote `_lab_scratch/cost_stress/russell_stress.pkl` with an 8-mark synthetic
    book. A test asserting the two sets are disjoint does not protect the write - the guard has to
    sit on the write itself, in the production path, where no monkeypatch of a module constant can
    move it.
    """
    full = os.path.normcase(os.path.abspath(path))
    if full in _historical_paths():
        raise SystemExit(
            f"REFUSING TO WRITE OVER A HISTORICAL BOOK: {PV._rel(path)}. The pre-manifest books "
            "are preserved by construction; an accredited book goes to a new path. Nothing was "
            "written.")
    return path


def acc_path(panel: str, label: str) -> str:
    return os.path.join(ACC_DIR, f"{panel}_{label}.pkl")


def engine_path(panel: str, label: str) -> str:
    return os.path.join(ACC_DIR, f"{panel}_{label}.engine.json")


def anchor_calendar() -> dict | None:
    """The requested calendar for every book after the first: the accredited Russell base's.

    PROV-08, SECOND HALF. Found by `preflight_433.py` on 2026-09-14, before any book was driven.
    PROV-08 changed `effective_request` so the ANCHOR answers to a grid derived from the rules,
    and it did fix the anchor's own accreditation. It did not touch this function, which kept
    building the pre-PROV-08 request by hand with `calendar=None` - and `provenance` now refuses
    a request that declares neither a mark grid nor `calendar_anchor`. So the validation here
    could never pass again:

        anchor_calendar() -> CACHE REJECTED [calendar] -> returns None
                          -> every non-anchor scenario is requested with calendar=None
                          -> all seven are rejected on [calendar]
                          -> fully_accredited can never be true for the set

    which is the exact condition PROV-08 was written to remove, moved one function along. The
    anchor must be validated with the SAME effective request everything else judges it by; a
    second, hand-built request here is how the two halves drifted apart in the first place.

    The stale comment this replaces said "russell/base declares itself the anchor, so its own
    request carries calendar=None". That stopped being true when PROV-08 landed.
    """
    path = acc_path("russell", "base")
    # The anchor is the grid every other book is compared to, so a seal-only check here
    # would let an unvalidated book define the calendar the rest are measured against.
    if not os.path.exists(path):
        return None
    try:
        PV.accredit(path, effective_request("russell", "base"), echo=False)
    except (PV.CacheRejected, PanelMismatch):
        return None
    return PV.calendar_block(pd.read_pickle(path))


def russell_start_date() -> str:
    path = acc_path("russell", "base")
    if not os.path.exists(path):
        raise SystemExit("russell:base must be driven first - sp500 has no grid to land on")
    return str(pd.Timestamp(pd.read_pickle(path).index[0]).date())


#: An `uncompared` block is only acceptable when the reason is one the contract already
#: names: a value derived from a field that IS compared, or the calendar of the anchor book
#: itself, which defines the grid every other book is measured against. Anything else means a
#: block went uncompared for a reason nobody wrote down, and that cannot add up to "fully
#: accredited" (HYDRA-PROV-01).
def _permitted_uncompared(field: str, why: str) -> bool:
    if field in PV.DERIVED_BLOCKS:
        return why == PV.DERIVED_BLOCKS[field]
    return field == "calendar" and why.startswith("declared anchor")


#: The derived grid is a function of the rules and the identified inputs, so it is constant
#: within a process - and deriving it loads the panel. `reconcile` asks eight times.
_ANCHOR_CAL_CACHE: dict = {}


def derived_anchor_calendar(panel: str = "russell") -> dict | None:
    """The anchor's calendar from the RULES, never from another book.

    PROV-08. `cost_stress.request(calendar=None)` stopped declaring `calendar_anchor` on
    purpose: the grid is derivable without any book, so "there is no earlier book" was never a
    reason to skip the window check. The consequence was that the anchor could not be
    accredited from cache at all, so `fully_accredited` could never be true - a correct
    refusal standing in for the missing half of the fix.

    `cost_stress.derived_grid` is that missing half, and it already existed:
    `calendar_spec.expected_grid` rebuilds the grid from the identified inputs and the
    engine's rules, takes no book and no book index, and refuses an empty or too-short
    calendar. So the anchor is now asked to match a grid nothing about the anchor produced.

    None when the inputs are not on this machine - a clean clone cannot derive it, and the
    refusal that follows says so rather than pretending the window was checked.
    """
    if panel in _ANCHOR_CAL_CACHE:
        return _ANCHOR_CAL_CACHE[panel]
    try:
        grid = CS.derived_grid(panel)
    # SystemExit is caught ON PURPOSE and is not redundant with Exception. `derived_grid` loads a
    # panel, and `backtest_variant_sweep.Panels.__init__` answers a missing cache with
    # `sys.exit('No cached data. Run with --download first.')` - a BaseException, which
    # `except Exception` does not see. So on a machine without the inputs this function did not
    # return None with a reason, it TORE DOWN the interpreter mid-reconcile (HYDRA-CI-01,
    # measured 2026-09-14). KeyboardInterrupt is deliberately NOT in this tuple.
    except (Exception, SystemExit) as exc:       # noqa: BLE001 - reported, never silent
        print(f"[accredit] cannot derive the anchor grid for {panel}: {exc!r}", flush=True)
        _ANCHOR_CAL_CACHE[panel] = None
        return None
    if not grid or grid.get("unavailable") or grid.get("n_marks", 0) <= 0:
        print(f"[accredit] no derivable anchor grid for {panel}: "
              f"{(grid or {}).get('unavailable')}", flush=True)
        _ANCHOR_CAL_CACHE[panel] = None
        return None
    block = PV.calendar_block_from_marks(grid["marks"])
    _ANCHOR_CAL_CACHE[panel] = block
    return block


def effective_request(panel: str, label: str) -> dict:
    """The request this scenario IS, built from the scenario, not from the file being judged.

    Copying the stored manifest into the request would only compare the artifact with itself.
    The cost pair comes from the scenario table and the calendar from the anchor book, exactly
    as `produce()` builds it when it drives the scenario.
    """
    s_bp, e_bp = scenario_bp(label)
    if (panel, label) == ("russell", "base"):
        # The anchor answers to the derived grid, not to another book (PROV-08).
        anchor = derived_anchor_calendar(panel)
    else:
        anchor = anchor_calendar()
    return CS.request(panel, label, s_bp, e_bp, calendar=anchor)


def accredit_answer(panel: str, label: str, *, echo: bool = False) -> dict:
    """Does the book in the accredited slot ANSWER for this scenario? Ask `accredit`, not the seal.

    HYDRA-PROV-01: this used to be `PV.classify(path)`, which checks only that a manifest is
    present and that its own seal verifies. Measured on 27afcf8, with nothing but synthetic
    data: eight books whose manifests held `{fixture_only: true, self_sha256: ...}` and nothing
    else were all reported `accredited`, the aggregate said `fully_accredited: true`, and
    `PV.accredit` was never called once. No identity block was ever compared.

    So the consumer now builds the effective request and runs the real validator, and carries
    what was compared - and what was not, and why - into every row that quotes the result.
    """
    path = acc_path(panel, label)
    if not os.path.exists(path):
        return dict(state="absent", path=PV._rel(path), book=None,
                    accreditation=None, rejected=None, seal_class="absent")
    seal_class = PV.classify(path)
    try:
        book, man = PV.accredit(path, effective_request(panel, label), echo=echo)
        data_answers(panel, path)       # the panel substitution `accredit` does not catch
    except PV.CacheRejected as exc:
        return dict(state="rejected", path=PV._rel(path), book=None, accreditation=None,
                    seal_class=seal_class,
                    rejected=dict(tag=exc.tag, field=exc.field, message=str(exc)))
    except PanelMismatch as exc:
        return dict(state="rejected", path=PV._rel(path), book=None, accreditation=None,
                    seal_class=seal_class,
                    rejected=dict(tag="PANEL MISMATCH", field="data", message=str(exc)))
    acc = man["_accreditation"]
    unexplained = [f for f in acc["uncompared"]
                   if not _permitted_uncompared(f, acc["uncompared_why"].get(f, ""))]
    if unexplained:
        return dict(state="rejected", path=PV._rel(path), book=None,
                    accreditation=acc, seal_class=seal_class,
                    rejected=dict(tag="IDENTITY INCOMPLETE", field=",".join(unexplained),
                                  message=("blocks left uncompared for a reason the contract "
                                           f"does not name: {unexplained}")))
    return dict(state=PV.ACCREDITED, path=PV._rel(path), book=book, accreditation=acc,
                seal_class=seal_class, rejected=None)


def accredited_state(panel: str, label: str) -> str:
    """ACCREDITED only when the book answers the scenario's own request."""
    return accredit_answer(panel, label)["state"]


class PanelMismatch(Exception):
    """The accredited book answers for a different PANEL than the one being asked about."""


def data_answers(panel: str, book_path: str) -> dict:
    """Compare the manifest's `data` block against the inputs `panel` actually reads.

    `provenance._check_data` compares the stored block against the CURRENT BYTES ON DISK - it
    answers "have this book's inputs moved since", which is not the same question as "are this
    book's inputs the ones I am asking about". The request's own `data` block is never read by any
    check, so a panel swap is invisible to it: asked the S&P question, `accredit()` hands back the
    RUSSELL book (measured 2026-09-12; `config.start_bar` catches the swap in one direction only,
    because the S&P request never declares one). That is a defect in `provenance.py`, which is not
    this task's file to rewrite; this is the additive guard for the books produced here.

    Raises `PanelMismatch` naming the first logical input that disagrees.
    """
    stored = (PV.read_manifest(book_path) or {}).get("data") or {}
    wanted = PV.data_identity(CS.data_inputs(panel))
    for name in sorted(set(stored) | set(wanted)):
        s, w = stored.get(name), wanted.get(name)
        s_sha = (s or {}).get("sha256") if isinstance(s, dict) else None
        w_sha = (w or {}).get("sha256") if isinstance(w, dict) else None
        if s_sha != w_sha:
            raise PanelMismatch(
                f"PANEL MISMATCH [data:{name}] {PV._rel(book_path)}: the manifest records "
                f"{'null' if s_sha is None else s_sha[:12]} for this input; the {panel!r} panel "
                f"reads {'null' if w_sha is None else w_sha[:12]}. This book was driven on a "
                "different panel and must not answer for it.")
    return dict(panel=panel, inputs_compared=len(wanted), agrees=True)


def produce(panel: str, label: str, *, progress_every: int = 100, drive_fn=None) -> dict:
    """Drive one scenario and put the book AND its sealed manifest on disk before returning."""
    os.makedirs(ACC_DIR, exist_ok=True)
    path = not_historical(acc_path(panel, label))     # before anything can touch the disk
    s_bp, e_bp = scenario_bp(label)
    anchor = anchor_calendar() if (panel, label) != ("russell", "base") else None

    if os.path.exists(path):
        req = CS.request(panel, label, s_bp, e_bp, calendar=anchor)
        try:
            book, _man = PV.accredit(path, req)
            data_answers(panel, path)          # the panel check `accredit` does not make
            print(f"[{panel}/{label}] already accredited, {len(book)} marks - left alone",
                  flush=True)
            return dict(panel=panel, label=label, action="kept", path=PV._rel(path))
        except PV.CacheRejected as exc:
            raise SystemExit(
                f"{exc}\nAn accredited-slot file is there and does not answer. Nothing was "
                "written. Move it aside by hand and re-run; this script never overwrites a book."
            ) from exc

    t0 = time.time()
    print(f"[{panel}/{label}] driving stock {s_bp} bp / etf {e_bp} bp ...", flush=True)
    start_date = russell_start_date() if panel == "sp500" else None
    book, measured = CS.drive(panel, s_bp, e_bp, start_date=start_date,
                              progress_every=progress_every, drive_fn=drive_fn)
    not_historical(path)                                        # re-checked at the write itself
    pd.to_pickle(book, path)                                    # the book first, then its seal

    req = CS.request(panel, label, s_bp, e_bp, calendar=anchor)
    for key in ("universe", "sectors"):
        if measured.get(key):
            req[key] = {**(req.get(key) or {}), **measured[key]}
    if measured.get("start_bar") is not None:
        req["config"]["start_bar"] = int(measured["start_bar"])
    man = PV.write_manifest(book, path, req, engine=measured)
    with open(engine_path(panel, label), "w", encoding="utf-8") as fh:
        json.dump(measured, fh, indent=2, default=str)

    secs = time.time() - t0
    ledger = measured.get("ledger") or {}
    print(f"[{panel}/{label}] wrote {os.path.basename(path)} + "
          f"{os.path.basename(PV.manifest_path(path))} in {secs:.0f}s: "
          f"{man['result']['n']} marks {man['result']['first']}..{man['result']['last']} "
          f"sha {man['result']['sha256'][:12]} wealth {man['result']['wealth']}", flush=True)
    print(f"[{panel}/{label}] measured turnover (filled dollars): "
          f"{json.dumps(ledger.get('turnover_filled_pct_by_sleeve'), default=str)} "
          f"total {ledger.get('turnover_filled_pct_total')}", flush=True)
    print(f"[{panel}/{label}] effective cost bp by sleeve: "
          f"{json.dumps(ledger.get('cost_bp_effective_by_sleeve'), default=str)}", flush=True)
    return dict(panel=panel, label=label, action="driven", path=PV._rel(path),
                seconds=round(secs, 1), result=man["result"])


def _irx() -> pd.Series:
    """The annualised DECIMAL risk-free, on its native ^IRX calendar - the published convention."""
    return CS.load_annual_rate(os.path.join(R.OOS_CACHE, "irx.pkl"), unit="percent")


def reconcile(irx: pd.Series | None = None) -> dict:
    """Accredited vs historical vs TASK-431, plus the accredited table. Writes a NEW json.

    Never touches `task433.json` or `task433_superseded_irx_percent.json`; the historical table is
    recomputed here from the historical books and reported beside the accredited one.
    """
    irx = _irx() if irx is None else irx
    acc_books, hist_books, rows, hist_rows, recs = {}, {}, [], [], []
    answers: dict[str, dict] = {}
    base_acc, base_hist = {}, {}
    for panel, label in ORDER:
        a_path = acc_path(panel, label)
        s_bp, e_bp = scenario_bp(label)
        h_path = CS.BASE_BOOKS[panel] if label == "base" else CS.book_path(panel, label)
        answer = accredit_answer(panel, label)
        a_cls = answer["state"]
        answers[f"{panel}/{label}"] = answer
        if a_cls == PV.ACCREDITED:
            # The book `accredit` validated, not a second read of the same path.
            acc_books[f"{panel}/{label}"] = answer["book"]
        if os.path.exists(h_path):
            hist_books[f"{panel}/{label}"] = pd.read_pickle(h_path)

        rec = dict(panel=panel, scenario=label, stock_bp=s_bp, etf_bp=e_bp,
                   accredited_class=a_cls,
                   accreditation=answer["accreditation"],
                   rejected=answer["rejected"],
                   seal_class=answer["seal_class"],
                   historical_class=(PV.classify(h_path) if os.path.exists(h_path) else "absent"))
        a_book = acc_books.get(f"{panel}/{label}")
        h_book = hist_books.get(f"{panel}/{label}")
        keys = ("ann_net", "sharpe_excess", "maxdd_net", "rf_ann_pct", "wealth")
        if a_book is not None:
            row = CS.stats_row(a_book, irx, f"{panel}/{label}")
            row.update(panel=panel, scenario=label, stock_bp=s_bp, etf_bp=e_bp,
                       provenance=PV.ACCREDITED,
                       # The evidence travels WITH the number it justifies.
                       compared=answer["accreditation"]["compared"],
                       uncompared=answer["accreditation"]["uncompared"],
                       uncompared_why=answer["accreditation"]["uncompared_why"],
                       uncompared_keys=answer["accreditation"]["uncompared_keys"],
                       degraded=answer["accreditation"]["degraded"])
            if label == "base":
                base_acc[panel] = row
            row.update(CS.deltas(row, base_acc.get(panel, row)))
            row["below_tbill"] = bool(float(row["ann_net"]) < float(row["rf_ann_pct"]))
            rows.append(row)
            rec["accredited"] = {k: row[k] for k in keys}
            rec["accredited_sha256"] = PV.book_sha256(a_book)
        if h_book is not None:
            hrow = CS.stats_row(h_book, irx, f"{panel}/{label}")
            hrow.update(panel=panel, scenario=label, stock_bp=s_bp, etf_bp=e_bp,
                        provenance=PV.HISTORICAL)
            if label == "base":
                base_hist[panel] = hrow
            hrow.update(CS.deltas(hrow, base_hist.get(panel, hrow)))
            hrow["below_tbill"] = bool(float(hrow["ann_net"]) < float(hrow["rf_ann_pct"]))
            hist_rows.append(hrow)
            rec["historical"] = {k: hrow[k] for k in keys}
            rec["historical_sha256"] = PV.book_sha256(h_book)
        if a_book is not None and h_book is not None:
            same_idx = (len(a_book) == len(h_book)
                        and bool((pd.DatetimeIndex(a_book.index)
                                  == pd.DatetimeIndex(h_book.index)).all()))
            rec["book_sha256_equal"] = rec["accredited_sha256"] == rec["historical_sha256"]
            rec["calendar_equal"] = same_idx
            rec["diff"] = {k: float(rec["accredited"][k]) - float(rec["historical"][k])
                           for k in ("ann_net", "sharpe_excess", "maxdd_net", "rf_ann_pct")}
            if same_idx:
                d = (pd.Series(a_book).astype(float) - pd.Series(h_book).astype(float)).abs()
                rec["max_abs_mark_diff"] = float(d.max())
        if label == "base" and a_book is not None:
            pub = PUBLISHED_431[panel]
            rec["published_431"] = pub
            rec["vs_published_431"] = {k: float(rec["accredited"][k]) - float(v)
                                       for k, v in pub.items()}
        recs.append(rec)

    marks_acc = CS.same_marks(acc_books) if acc_books else dict(n_books=0, identical=None)
    turnover = {}
    for panel, label in ORDER:
        p = engine_path(panel, label)
        if not os.path.exists(p):
            continue
        with open(p, "r", encoding="utf-8") as fh:
            measured = json.load(fh)
        led = measured.get("ledger") or {}
        counts = measured.get("engine_counts") or {}
        turnover[f"{panel}/{label}"] = dict(
            measured_filled_pct_by_sleeve=led.get("turnover_filled_pct_by_sleeve"),
            measured_filled_pct_total=led.get("turnover_filled_pct_total"),
            cost_bp_effective_by_sleeve=led.get("cost_bp_effective_by_sleeve"),
            settles=led.get("settles"),
            engine_planned_turnover_pct=(counts or {}).get("turnover"),
            engine_counts=counts,
            inferred_back_solve=INFERRED_TURNOVER_PCT.get(panel) if label == "base" else None)

    still = [k for k in (f"{p}/{lab}" for p, lab in ORDER)
             if answers.get(k, {}).get("state") != PV.ACCREDITED]
    rejections = {k: a["rejected"] for k, a in answers.items() if a.get("rejected")}
    payload = dict(
        task="TASK-433",
        artifact_set="accredited",
        note=("Accredited books driven under a sealed manifest. The 2026-09-11 books are "
              "PRESERVED at their own paths, still classified historical_incomplete, and are "
              "recomputed here only for comparison."),
        order=[f"{p}/{lab}" for p, lab in ORDER],
        run_id=RUN_ID,
        accredited_dir=PV._rel(ACC_DIR),
        reconciliation=recs,
        rows_accredited=rows,
        rows_historical=hist_rows,
        marks_accredited=marks_acc,
        turnover=turnover,
        inference_rule=CS.INFERENCE_RULE,
        known_validator_gap=(
            "CLOSED 2026-09-12 in provenance.py: `_check_data` compares the stored data block "
            "against the REQUESTED one, so the panel swap it used to miss is caught there now. "
            "`accredit_433.data_answers` is kept as a second, independent check rather than as "
            "the only one. What is NOT closed: `self_sha256` is an unkeyed digest produced by "
            "the same public `seal()` a writer calls, so a deliberate re-seal passes it. "
            "Integrity of the artifact, compatibility with a request, and statistical "
            "independence are three different claims; this file can speak to the first two."),
        inferred_turnover_superseded=INFERRED_TURNOVER_PCT,
        published_431=PUBLISHED_431,
        provenance=dict(
            accredited=[k for k, a in answers.items() if a["state"] == PV.ACCREDITED],
            still_historical_only=still,
            rejected=rejections,
            # Every block each accredited row actually compared, and every one it did not.
            compared_by_book={k: a["accreditation"]["compared"]
                              for k, a in answers.items() if a["accreditation"]},
            uncompared_by_book={k: a["accreditation"]["uncompared_why"]
                                for k, a in answers.items() if a["accreditation"]},
            uncompared_keys_by_book={k: a["accreditation"]["uncompared_keys"]
                                     for k, a in answers.items() if a["accreditation"]},
            # `not still` alone was the defect: it only ever asked whether a manifest was
            # present and self-sealed. It now means every expected book ANSWERED its own
            # effective request, with no identity block left uncompared for an unnamed reason.
            fully_accredited=(not still) and len(answers) == len(ORDER),
            validated_by="provenance.accredit against the scenario's effective request"),
    )
    if acc_books:
        first = min(str(pd.Timestamp(b.index[0]).date()) for b in acc_books.values())
        last = max(str(pd.Timestamp(b.index[-1]).date()) for b in acc_books.values())
        payload = HO.stamp(payload, first=first, last=last, declared="research+validation")
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    print("wrote", OUT_JSON, flush=True)

    if rows:
        print("\n--- ACCREDITED cost stress (deltas vs accredited base) ---", flush=True)
        print(CS.table(rows).to_string(index=False), flush=True)
    if hist_rows:
        print("\n--- HISTORICAL books, same statistics, for comparison only ---", flush=True)
        print(CS.table(hist_rows).to_string(index=False), flush=True)
    print("\n--- reconciliation ---", flush=True)
    for rec in recs:
        if "diff" not in rec:
            print(f"{rec['panel']}/{rec['scenario']}: accredited={rec['accredited_class']} "
                  f"historical={rec['historical_class']} - no pair to compare", flush=True)
            continue
        print(f"{rec['panel']}/{rec['scenario']}: sha_equal={rec['book_sha256_equal']} "
              f"cal_equal={rec['calendar_equal']} "
              f"max|dmark|={rec.get('max_abs_mark_diff')} "
              f"d_ann_net={rec['diff']['ann_net']:+.10f} "
              f"d_sharpe={rec['diff']['sharpe_excess']:+.10f} "
              f"d_maxdd={rec['diff']['maxdd_net']:+.10f}", flush=True)
        if "vs_published_431" in rec:
            v = rec["vs_published_431"]
            print(f"    vs TASK-431 published: d_ann_net={v['ann_net']:+.10f} "
                  f"d_rf={v['rf_ann_pct']:+.10f} d_sharpe={v['sharpe_excess']:+.10f} "
                  f"d_maxdd={v['maxdd_net']:+.10f}", flush=True)
    return payload


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="TASK-433: accredited books, additive to the old set")
    ap.add_argument("--only", help="panel:label, e.g. russell:base")
    ap.add_argument("--all", action="store_true", help="drive every missing book in order")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--reconcile", action="store_true")
    ap.add_argument("--verify-panels", action="store_true",
                    help="every accredited book's manifest data block vs its own panel's inputs")
    ap.add_argument("--progress-every", type=int, default=100)
    ap.add_argument("--run-id", help="publish into accredited/runs/<id>/ instead of the legacy "
                                     "directory, which holds the WITHDRAWN 2026-09-12 run")
    ap.add_argument("--new-run", action="store_true",
                    help="mint a run id from today's date and the code digest, and use it")
    args = ap.parse_args(argv)

    if args.new_run and args.run_id:
        ap.error("choose --run-id or --new-run, not both")
    if args.new_run or args.run_id:
        bound = use_run(args.run_id or mint_run_id())
        print(f"[run] id={bound['run_id']}\n[run] books -> {PV._rel(bound['acc_dir'])}"
              f"\n[run] report -> {PV._rel(bound['out_json'])}", flush=True)

    if args.status:
        for panel, label in ORDER:
            print(f"{panel}/{label}: accredited={accredited_state(panel, label)} "
                  f"historical={CS.cache_state(panel, label)}", flush=True)
        return 0
    if args.verify_panels:
        bad = 0
        for panel, label in ORDER:
            if accredited_state(panel, label) != PV.ACCREDITED:
                print(f"{panel}/{label}: not accredited, nothing to verify", flush=True)
                continue
            try:
                rec = data_answers(panel, acc_path(panel, label))
                print(f"{panel}/{label}: data block answers for {panel} "
                      f"({rec['inputs_compared']} inputs compared)", flush=True)
            except PanelMismatch as exc:
                bad += 1
                print(str(exc), flush=True)
        return 1 if bad else 0
    if args.only:
        panel, _, label = args.only.partition(":")
        produce(panel, label, progress_every=args.progress_every)
        return 0
    if args.all:
        for panel, label in ORDER:
            produce(panel, label, progress_every=args.progress_every)
    if args.reconcile or args.all:
        reconcile()
        return 0
    ap.error("choose --only, --all, --status or --reconcile")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
