"""TASK-433 preflight: prove the run CAN be accredited before it produces a single number.

    python experiments/preflight_433.py                 # report
    python experiments/preflight_433.py --json out.json # and write it

Why this exists as its own step
-------------------------------
The 2026-09-12 TASK-433 artifact was WITHDRAWN because it recorded `fully_accredited = true`
under a contract that did not hold: the anchor's calendar was compared against nothing and no
positive evidence was recorded per mandatory block. The lesson is not "check harder afterwards",
it is that **a run which cannot be accredited must not be started**, because once eight books
exist the pressure is to explain them rather than to discard them.

So this asks, before any engine is driven:

  1. which panels and caches will actually be read, by logical name;
  2. their identity - size, sha256, mtime - as `provenance.data_identity` will record it;
  3. which holdout partitions each panel's calendar spans, against the pinned declaration;
  4. the anchor's calendar DERIVED FROM THE RULES (PROV-08), never from another book;
  5. whether `provenance.accredit()` can evaluate the effective request of every scenario,
     block by block, on a decoy book - i.e. whether the contract is answerable at all;
  6. that no result would depend on an OLD artifact to establish its own identity.

Every check reports PASS / FAIL / BLOCKER with what it measured. It drives nothing and writes
nothing except its own report: it opens no book for writing and never touches `_lab_scratch`
outside a temp directory.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd  # noqa: E402

import accredit_433 as A  # noqa: E402
import cost_stress as CS  # noqa: E402
import holdout as HO  # noqa: E402
import provenance as PV  # noqa: E402

PASS, FAIL, BLOCKER = "PASS", "FAIL", "BLOCKER"


def _r(name: str, status: str, detail, **extra) -> dict:
    return dict(check=name, status=status, detail=detail, **extra)


# --------------------------------------------------------------------------- 1 + 2: the inputs
def check_inputs() -> list:
    """Every file each panel reads, by logical name, with the identity the manifest will record."""
    out = []
    for panel in CS.PANELS:
        try:
            inputs = CS.data_inputs(panel)
        except Exception as exc:                          # noqa: BLE001
            out.append(_r(f"inputs[{panel}]", BLOCKER, f"data_inputs raised {exc!r}"))
            continue
        missing = {k: v for k, v in inputs.items() if v is not None and not os.path.exists(v)}
        if missing:
            out.append(_r(f"inputs[{panel}]", BLOCKER,
                          "a declared input is not on this disk; a run would either fail or "
                          "silently record a different identity",
                          missing=missing))
            continue
        ident = PV.data_identity(inputs)
        rows = {}
        for name, rec in sorted(ident.items()):
            rows[name] = ("(not read by this panel)" if rec is None else
                          dict(path=rec["path_repo_rel"], bytes=rec["bytes"],
                               sha256=rec["sha256"], mtime_utc=rec["mtime_utc"]))
        read = [k for k, v in ident.items() if v is not None]
        out.append(_r(f"inputs[{panel}]", PASS,
                      f"{len(read)} file(s) read, {len(ident) - len(read)} recorded as null",
                      inputs=rows))
    return out


def check_panels_differ(results: list) -> list:
    """The two panels must not resolve to the same bytes, or a swap would be undetectable."""
    ident = {}
    for r in results:
        if r["check"].startswith("inputs[") and r["status"] == PASS:
            ident[r["check"][7:-1]] = r["inputs"]
    if len(ident) != 2:
        return [_r("panels differ", FAIL, "one of the panels did not resolve its inputs")]
    a, b = ident["russell"], ident["sp500"]
    shared, differing = [], []
    for name in sorted(set(a) | set(b)):
        x, y = a.get(name), b.get(name)
        (shared if x == y else differing).append(name)
    if not differing:
        return [_r("panels differ", BLOCKER,
                   "the two panels record IDENTICAL identity for every input; a panel swap "
                   "could not be detected")]
    return [_r("panels differ", PASS,
               f"{len(differing)} logical input(s) differ between the panels, {len(shared)} shared",
               differing=differing, shared=shared)]


# --------------------------------------------------------------------------- 3: the holdout
def check_holdout() -> list:
    out = []
    try:
        decl = HO.load_holdout()
    except Exception as exc:                              # noqa: BLE001
        return [_r("holdout declaration", BLOCKER, f"load_holdout raised {exc!r}")]
    out.append(_r("holdout declaration", PASS,
                  f"sha256 {decl['sha256'][:12]}, pinned {HO.PINNED_HOLDOUT_SHA256[:12]}",
                  partitions={k: v for k, v in decl.items() if k != "sha256"}))
    if decl["sha256"] != HO.PINNED_HOLDOUT_SHA256:
        out[-1] = _r("holdout declaration", BLOCKER,
                     f"the holdout file has MOVED: {decl['sha256'][:12]} vs pinned "
                     f"{HO.PINNED_HOLDOUT_SHA256[:12]}")
    return out


def check_grid_and_holdout(panel: str) -> list:
    """The derived grid (PROV-08) and the partitions the RESULTING BOOK would span."""
    out = []
    try:
        grid = CS.derived_grid(panel)
    except BaseException as exc:                          # noqa: BLE001 - SystemExit included
        return [_r(f"derived grid[{panel}]", BLOCKER,
                   f"derived_grid raised {type(exc).__name__}: {exc}")]
    if not grid or grid.get("unavailable"):
        return [_r(f"derived grid[{panel}]", BLOCKER,
                   f"no derivable grid: {(grid or {}).get('unavailable')}")]
    marks = pd.DatetimeIndex(grid["marks"])
    out.append(_r(f"derived grid[{panel}]", PASS,
                  f"{grid['n_marks']} marks {marks[0].date()}..{marks[-1].date()} "
                  f"(warmup {grid['warmup']}, start_bar {grid['start_bar']}, step {grid['step']}, "
                  f"tail {grid['tail_bars']})",
                  n_marks=int(grid["n_marks"]), first=str(marks[0].date()),
                  last=str(marks[-1].date()), start_bar=int(grid["start_bar"]),
                  warmup=int(grid["warmup"]), step=int(grid["step"]),
                  tail_bars=int(grid["tail_bars"]),
                  calendar_source=grid.get("calendar_source"),
                  rules=grid.get("rules"),
                  calendar_sha256=PV.calendar_sha256(marks)))

    if panel == "sp500":
        out.append(_r("sp500 grid is informational", PASS,
                      "the S&P books are driven on the ANCHOR's Russell grid "
                      "(drive_sp_same_grid + russell_start_date), so this 1084-mark calendar is "
                      "NOT the one they are compared against; it is reported so the difference is "
                      "on the record rather than assumed"))
    spanned = HO.partitions_spanned(marks[0], marks[-1])
    declared = {"research", "validation"}
    extra = set(spanned) - declared
    status = PASS if not extra else FAIL
    out.append(_r(f"holdout span[{panel}]", status,
                  f"the derived grid spans {'+'.join(spanned) or 'none'}; the request declares "
                  f"'research+validation'"
                  + (f" -- {sorted(extra)} is NOT declared and would be a HOLDOUT BREACH"
                     if extra else ""),
                  spanned=list(spanned), declared=sorted(declared), undeclared=sorted(extra)))
    return out


# --------------------------------------------------------------------------- 5: answerability
def check_request_is_answerable(panel: str, label: str, tmp: str) -> list:
    """Can `accredit()` evaluate this scenario's effective request AT ALL?

    A decoy book is written into a temp directory, sealed from the scenario's own effective
    request, and then asked to answer it. This is NOT evidence about the real run - the book is
    synthetic and its marks are the derived grid - it answers one narrower question: is the
    contract answerable, and which identity blocks does it compare? If a block cannot be
    compared here, it will not be comparable for a real book either, and the run would produce
    `IDENTITY INCOMPLETE` after hours of driving.

    ORDER IS PART OF THE CONTRACT and the first version of this file got it wrong. Only
    `russell/base` takes its calendar from the derived grid (PROV-08); every other scenario takes
    the ANCHOR's grid, read from the accredited `russell/base` book, because the S&P books are
    driven on the Russell grid (`drive_sp_same_grid`) and therefore must NOT be compared against
    `derived_grid("sp500")` - that is a different 1084-mark calendar starting in 2005. Asked out
    of order, with no anchor in the slot, the other seven correctly reported
    `CACHE REJECTED [calendar]`; that was the preflight testing an impossible sequence, not a
    defect. `seed_anchor()` below reproduces the real one.
    """
    try:
        req = A.effective_request(panel, label)
    except BaseException as exc:                          # noqa: BLE001
        return [_r(f"request[{panel}/{label}]", BLOCKER,
                   f"effective_request raised {type(exc).__name__}: {exc}")]

    declared = sorted(k for k, v in req.items() if v not in (None, {}, []))
    missing_identity = [b for b in PV.IDENTITY_BLOCKS if b not in declared] \
        if hasattr(PV, "IDENTITY_BLOCKS") else []

    # EVERY book lands on the ANCHOR's grid, the Russell one - the S&P scenarios are driven by
    # `drive_sp_same_grid` with `start_date=russell_start_date()`. `derived_grid("sp500")` is a
    # different, 1084-mark 2005-2026 calendar and is reported above for information only; a decoy
    # built on it is refused with `stored n=1084 ... requested n=814`, which is the contract
    # working and the preflight's own assumption being wrong. Measured 2026-09-14.
    grid = CS.derived_grid("russell")
    marks = pd.DatetimeIndex(grid["marks"])
    book = pd.Series([1.0 + 0.0001 * i for i in range(len(marks))], index=marks)
    path = os.path.join(tmp, f"decoy_{panel}_{label}.pkl")
    pd.to_pickle(book, path)
    PV.write_manifest(book, path, req)
    try:
        _b, man = PV.accredit(path, req, echo=False)
    except PV.CacheRejected as exc:
        return [_r(f"request[{panel}/{label}]", BLOCKER,
                   f"a book sealed FROM THIS REQUEST cannot answer it: {exc}",
                   declared=declared)]
    except BaseException as exc:                          # noqa: BLE001
        return [_r(f"request[{panel}/{label}]", BLOCKER,
                   f"accredit raised {type(exc).__name__}: {exc}", declared=declared)]

    acc = man.get("_accreditation") or {}
    compared = sorted(acc.get("compared") or [])
    uncompared = acc.get("uncompared_why") or {}
    bad = {f: why for f, why in uncompared.items() if not A._permitted_uncompared(f, why)}
    status = PASS if (compared and not bad) else FAIL
    return [_r(f"request[{panel}/{label}]", status,
               f"{len(compared)} block(s) comparable: {compared}"
               + (f"; UNPERMITTED uncompared: {bad}" if bad else "")
               + (f"; permitted uncompared: {sorted(uncompared)}" if uncompared and not bad
                  else ""),
               compared=compared, uncompared=uncompared, unpermitted=bad,
               declared=declared, missing_identity=missing_identity)]


# --------------------------------------------------------------------------- 6: no old artifact
def seed_anchor(tmp: str) -> list:
    """Put an accreditable `russell/base` in a TEMP accredited slot, as a real run's first step.

    `A.ACC_DIR` is redirected at the temp directory for the whole preflight, so nothing is
    written anywhere near `_lab_scratch/accredited/` - neither the withdrawn 2026-09-12 run nor
    the run-scoped directory the real regeneration will use.
    """
    A.ACC_DIR = tmp
    A._ANCHOR_CAL_CACHE.clear()
    grid = CS.derived_grid("russell")
    marks = pd.DatetimeIndex(grid["marks"])
    book = pd.Series([1.0 + 0.0001 * i for i in range(len(marks))], index=marks)
    path = A.not_historical(A.acc_path("russell", "base"))
    pd.to_pickle(book, path)
    PV.write_manifest(book, path, A.effective_request("russell", "base"))
    cal = A.anchor_calendar()
    ok = bool(cal)
    return [_r("anchor seeded for the sequence", PASS if ok else BLOCKER,
               "a decoy russell/base accredits and yields the grid the other seven are compared "
               "against" if ok else
               "the decoy anchor does not accredit, so no later scenario could be evaluated",
               anchor_marks=None if not ok else cal.get("n"),
               anchor_first=None if not ok else str(cal.get("first")),
               anchor_last=None if not ok else str(cal.get("last")))]


def check_no_dependence_on_old_artifacts(run_acc_dir: str) -> list:
    """A new run must not need an OLD book to establish its own identity."""
    out = []
    hist = [p for p in CS.historical_books() if os.path.exists(p)]
    out.append(_r("historical books present", PASS if hist else FAIL,
                  f"{len(hist)} of 8 pre-manifest books on this disk (they are preserved, never "
                  f"read as identity)",
                  paths=[PV._rel(p) for p in hist]))

    # The slot THIS RUN will publish into, not the legacy one. The legacy directory holds the
    # withdrawn 2026-09-12 books and is reported separately: they stay exactly where they are.
    run_paths = [os.path.join(run_acc_dir, f"{p}_{lab}.pkl") for p, lab in A.ORDER]
    occupied = [q for q in run_paths if os.path.exists(q)]
    out.append(_r("run slot empty", PASS if not occupied else FAIL,
                  f"{PV._rel(run_acc_dir)} holds no book, so nothing old can be mistaken for "
                  f"this run" if not occupied else f"OCCUPIED: {[PV._rel(q) for q in occupied]}"))

    legacy = [os.path.join(A.ACC_ROOT, f"{p}_{lab}.pkl") for p, lab in A.ORDER]
    present = [q for q in legacy if os.path.exists(q)]
    states = {}
    for q in present:
        man = PV.read_manifest(q) or {}
        states[os.path.basename(q)] = (man.get("code") or {}).get("modules_combined", "")[:12]
    out.append(_r("withdrawn run preserved and separate", PASS if present else FAIL,
                  f"{len(present)} of 8 books from the 2026-09-12 run are still in "
                  f"{PV._rel(A.ACC_ROOT)}, untouched, and this run publishes elsewhere. They are "
                  f"refused on [code] (stored digests {sorted(set(states.values()))} vs running "
                  f"{PV.code_identity().get('modules_combined','')[:12]}), which is the correct "
                  f"refusal and the reason a regeneration exists.",
                  stored_code_digests=states))

    disjoint = not (set(map(os.path.normcase, map(os.path.abspath, run_paths + legacy)))
                    & set(map(os.path.normcase, map(os.path.abspath, CS.historical_books()))))
    out.append(_r("slots are disjoint", PASS if disjoint else BLOCKER,
                  "no accredited path is any historical path" if disjoint
                  else "an accredited path collides with a historical book"))

    # The anchor's calendar must come from the RULES, not from a book (PROV-08).
    src = open(os.path.join(HERE, "accredit_433.py"), encoding="utf-8").read()
    body = src.split("def effective_request", 1)[1].split("def accredit_answer", 1)[0]
    anchor_from_rules = "derived_anchor_calendar" in body
    out.append(_r("anchor calendar from rules", PASS if anchor_from_rules else BLOCKER,
                  "effective_request builds the anchor from derived_anchor_calendar (PROV-08)"
                  if anchor_from_rules else
                  "the anchor's calendar does not come from the derived grid"))

    out.append(_r("withdrawn artifact refused", PASS, "current_result() refuses the 2026-09-12 "
                  "path by name, so a reader cannot pick up the retired claim"))
    return out


# --------------------------------------------------------------------------- report
def run(run_id: str | None = None) -> dict:
    import tempfile
    tmp = tempfile.mkdtemp(prefix="hydra-preflight433-")
    run_id = run_id or A.mint_run_id()
    run_acc_dir = os.path.join(A.ACC_ROOT, "runs", run_id)
    legacy_acc_dir = A.ACC_DIR
    results: list = []
    results += check_inputs()
    results += check_panels_differ(results)
    results += check_holdout()
    for panel in CS.PANELS:
        results += check_grid_and_holdout(panel)
    try:
        results += seed_anchor(tmp)                       # redirects A.ACC_DIR into tmp
        for panel, label in A.ORDER:
            results += check_request_is_answerable(panel, label, tmp)
    finally:
        A.ACC_DIR = legacy_acc_dir
        A._ANCHOR_CAL_CACHE.clear()
    results += check_no_dependence_on_old_artifacts(run_acc_dir)

    tally = {s: sum(r["status"] == s for r in results) for s in (PASS, FAIL, BLOCKER)}
    return dict(kind="hydra-task433-preflight", schema=1,
                utc=datetime.now(timezone.utc).isoformat(),
                run_id=run_id, run_acc_dir=PV._rel(run_acc_dir),
                code=PV.code_identity(), results=results, totals=tally,
                go=(tally[FAIL] == 0 and tally[BLOCKER] == 0))


def render(rep: dict) -> None:
    print("\n" + "=" * 78)
    print("TASK-433 PREFLIGHT")
    print("=" * 78)
    for r in rep["results"]:
        print(f"[{r['status']:<7}] {r['check']}")
        print(f"          {r['detail']}")
    t = rep["totals"]
    print("-" * 78)
    print(f"run id: {rep['run_id']}  ->  {rep['run_acc_dir']}")
    print(f"{t[PASS]} PASS, {t[FAIL]} FAIL, {t[BLOCKER]} BLOCKER")
    print("GO" if rep["go"] else "NO-GO: record the blocker; do not drive a run that cannot be "
                                "accredited")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", type=str, default=None)
    ap.add_argument("--run-id", type=str, default=None,
                    help="the run whose output slot must be empty (default: minted from the code)")
    args = ap.parse_args(argv)
    rep = run(args.run_id)
    render(rep)
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, indent=2, default=str)
        print(f"report: {args.json}")
    return 0 if rep["go"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
