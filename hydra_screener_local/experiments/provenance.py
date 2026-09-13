"""TASK-433 - the run manifest for a lab book, and the cache check that refuses on mismatch.

The previous cycle's forensics found the same defect at two call sites: `os.path.exists(path)`
was the whole cache test, so any file with the right NAME was consumed as the right BOOK. A
poisoned base that moved the evaluated window to 2014-2026 was accepted silently and still got a
clean holdout stamp. Existence is not identity, and a float64 Series carries no identity at all -
the eight books on disk load as bare `Series float64 814` with `attrs == {}` and `name is None`.

So identity lives in a separate sealed document beside the book, `<book>.manifest.json`, and
`accredit()` COMPARES it against what the caller is asking for. A rejection names the field:

    CACHE REJECTED [costs] russell_stress.pkl: stored stock_bp=35.0 etf_bp=10.0; requested
    stock_bp=20.0 etf_bp=8.0. The cached book was priced at costs other than the ones asked for.

Deliberately a SIDECAR and not `Series.attrs`: attrs ride inside the pickle, so whoever rewrote
the book would have rewritten them too. A separate file can be hashed on its own.

WHAT `self_sha256` IS AND IS NOT. It is an UNKEYED digest of the manifest's own body, computed by
the public `seal()`. It detects an ACCIDENTAL edit and DRIFT - a hand-fixed number, a merge, a
half-written file, a field changed by a script that did not re-seal - and that is all it detects.
It is NOT tamper-evidence against a deliberate adversary: measured on 2026-09-12, re-pricing a
real manifest from 35/10 to 20/8, moving `config.v9_effective` to agree, and re-running the same
public `seal()` was ACCEPTED, and the 10/5 base book answered the 20/8 question. Closing that
needs a secret this module does not have and will not pretend to have; every claim below is a
claim about a manifest nobody re-sealed on purpose. What survives a re-sealer is the part of the
check that does not consult the manifest at all: `result` re-hashes the BOOK and `data` re-hashes
the INPUT FILES, and both compare against the world rather than against the document.

What the manifest records, and which substitution each field refuses:

    artifact  the file name the manifest was written for              - a book in another's slot
    result    hash of the book itself                                 - an edit after the fact
    code      content hashes of every module that can move a number   - a different engine
    costs     stock/etf bp per side, never the blend                  - a different price
    config    V9 as RESOLVED at run time, the lab config, the freeze  - a different surface
    data      full sha256 of every input FILE the run opened          - a different panel
    calendar  the book's own mark grid                                - a different window
    sectors   requested mode compared; the mapper's own info recorded - pit vs fixed
    units     on_disk / consumed / divisor per rate-like quantity     - the 342 % T-bill
    period    the `holdout.stamp()` block, about the BOOK             - an undeclared read
    protocol  prereg hash, board task, the verdict rule               - a moved goalpost
    universe  columns and coverage - DERIVED, see below               - not an independent check
    engine    measured turnover, charged costs, event counts          - recorded, not compared
    run / written_utc / schema                                        - recorded, not compared

IDENTITY IS COMPARED, NEVER TRUSTED. `artifact` sat in `NEVER_COMPARED` until 2026-09-12 and that
was the whole of the book-swap hole: the field that NAMES the book is precisely the field a swap
moves. Moving `sp500_base.pkl` and its manifest into the `russell_base` slot and asking the
Russell question returned the S&P book - wealth 3.439693 where Russell is 2.431955 - for all four
cost pairs in both directions, and every published TASK-433 delta is Russell-minus-S&P, so a file
rename inverted the entire economic content. Two comparisons refuse it, and both are needed:

  * `artifact`  the BASENAME the manifest was written for against the basename it is consumed
                from. The basename IS the slot - `<panel>_<label>.pkl` in both `cost_stress` and
                `accredit_433` - so a rename into another slot is refused by name. Only the
                basename: a different DIRECTORY under the same file name is a relocation, which
                carries no economic content, and is recorded as `CACHE DEGRADED [artifact]`.
                On its own this is a check on a LABEL, which is why it is not the only one.
  * `data`      the request's OWN block against the stored one, sha256 by sha256. This is the
                substantive one: it compares the INPUT BYTES the two panels read, so it refuses a
                swap however the file is named, and it is what makes the line above - `data ... a
                different panel` - true. Until 2026-09-12 it was false: `_check_data` only
                re-hashed the files the STORED manifest named, which answers "have these inputs
                moved since" and never "are these the inputs I asked for".

AN UNDECLARED IDENTITY FIELD IS A REFUSAL, NOT A SKIP. `IDENTITY_BLOCKS` names what makes a book
THIS book; a request that leaves one of them out, `None` or `{}` is REJECTED naming the block,
because "I did not say" must not read the same as "it agrees". That closes two more holes found
on 2026-09-12: `req['costs'] = {}` was accepted AND still listed as compared, and `calendar` was
skipped whenever the request omitted it - which is what `run()` does for the first book of a run,
so a 604-mark 2014-2026 base with a valid manifest was accredited, became the anchor, and the run
published `fully_accredited=True` over the poisoned window. The one legitimate undeclared case is
that first book, which DEFINES the grid and has no anchor to be compared against; the caller must
now say so in `request['calendar_anchor']`, in words, and the accreditation records `calendar` as
UNCOMPARED and prints `CACHE DEGRADED [calendar]` instead of passing in silence.

DERIVED IS NOT THE SAME AS IGNORED. `universe`, and all of `sectors` except `requested_mode`, are
RECORDED and compared only if a caller happens to declare them, because a cache reader cannot
produce them without loading the 264 MB panel the cache exists to avoid. That is defensible only
because their identity is carried by a field that IS compared - the columns come out of
`price_close`, whose sha256 is now compared as `data:price_close` - and it was NOT defensible
before that comparison existed. Every such field is named in `_accreditation.uncompared_keys`, so
the record of what was actually checked is true rather than flattering.

WHERE A COST MISMATCH SURFACES. `costs` is checked BEFORE `config` on purpose. The bp values are
baked into `config.v9_effective_sha256`, so under the old order every real cost mismatch surfaced
as `[config.v9_effective_sha256]` - "driven under a different configuration" - and the `[costs]`
message quoted above was reachable only from a hand-edited manifest. The pair is the more precise
diagnosis of the same fact, so it is asked first and the quoted message is now the one a caller
actually gets.

A git rev cannot do the `code` job here and saying so is the point: the tree is dirty, the base
books were driven from a working tree thirteen minutes before the PR that published them merged,
and several of the files that can move a number - `cost_stress.py` and this one among them - are
untracked and have no blob at all. Content hashes describe what actually executed; `code.git` is
recorded beside them so a dirty run is DESCRIBED, not hidden.

Nothing in this module deletes, overwrites or repairs anything. A book that fails is left where
it is; a book with no manifest is `CACHE UNACCREDITED` - history, never a cache hit.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import holdout as HO  # noqa: E402

SCHEMA = "hydra.lab.manifest/1"
MANIFEST_SUFFIX = ".manifest.json"
#: deliberately NOT `.manifest.json`: no validator may ever mistake a classification for an
#: accreditation. See `classify_historical`.
PROVENANCE_SUFFIX = ".provenance.json"

REJECTED = "CACHE REJECTED"
UNACCREDITED = "CACHE UNACCREDITED"
DEGRADED = "CACHE DEGRADED"

#: Every module that can reach a published number. Two ways in: this list, and a sweep of
#: `sys.modules` at write time (`unenumerated`), so an import the list forgot is still recorded.
ENUMERATED_MODULES = (
    "experiments/cost_stress.py",
    "experiments/provenance.py",
    "experiments/metrics.py",
    "experiments/holdout.py",
    "experiments/engine_backtest.py",
    "experiments/run_russell_prereg.py",
    "experiments/redesign_lab.py",
    "experiments/sleeve_lab.py",
    "config.py",
    "core/portfolio_engine.py",
    "core/tranche_book.py",
    "core/signals.py",
    "core/regime.py",
    "core/filters.py",
    "core/meta_layer.py",
    "data/sectors.py",
    "data/pit.py",
    "data/universe.py",
)

#: Recorded in `code.deps`; a MINOR/PATCH drift is degraded, a MAJOR drift is refused.
DEPENDENCIES = ("pandas", "numpy", "scipy", "python")


# --------------------------------------------------------------------------- digests

def sha256_json(obj) -> str:
    """Canonical digest of a JSON-able object - the sort_keys/compact form `utils.runlog` uses."""
    blob = json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def sha256_lf(path: str) -> str:
    """Source digest with CRLF folded to LF, so a Windows and a Linux checkout agree.

    The same normalisation `holdout.sha256_lf` and `run_russell_prereg.sha256_file(lf=True)`
    already use; code identity must not move because of a line ending.
    """
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()


_DIGEST_MEMO: dict = {}


def sha256_bytes(path: str, *, chunk: int = 4 << 20) -> str:
    """Streamed digest of the file's raw bytes, memoised within this process only.

    Full hashing is affordable - 0.40 s for the 264 MB `close.pkl` - so there is no performance
    argument for a weaker check, and the threat model is deliberate substitution, which a
    timestamp cannot see. The memo is keyed on (size, mtime_ns) and lives in memory for one run:
    it saves rehashing the same 264 MB once per book, and it is revalidated on every call. It is
    never written to disk, because an on-disk memo would put a forgeable mtime on the
    accreditation path.
    """
    st = os.stat(path)
    key = (os.path.abspath(path), st.st_size, st.st_mtime_ns)
    if key in _DIGEST_MEMO:
        return _DIGEST_MEMO[key]
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    _DIGEST_MEMO[key] = h.hexdigest()
    return _DIGEST_MEMO[key]


def book_sha256(book: pd.Series) -> str:
    """Digest of a book's values AND index, via `hash_pandas_object`.

    Independent of float formatting and of how the pickle was written, which is what makes it a
    seal on the numbers rather than on the container.
    """
    h = pd.util.hash_pandas_object(pd.Series(book), index=True)
    return hashlib.sha256(np.asarray(h).tobytes()).hexdigest()


def calendar_sha256(index) -> str:
    """Digest of the mark grid as dates - the evaluated window, not the phase it came from."""
    marks = pd.DatetimeIndex(index)
    blob = "|".join(d.strftime("%Y-%m-%d") for d in marks)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _short(digest, n: int = 12) -> str:
    return str(digest)[:n] if digest else str(digest)


def _rel(path: str) -> str:
    """Repo-relative, forward-slashed, so a manifest reads the same on either platform."""
    try:
        return os.path.relpath(os.path.abspath(path), ROOT).replace(os.sep, "/")
    except ValueError:
        return str(path).replace(os.sep, "/")


# --------------------------------------------------------------------------- code identity

def _git(args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def git_state() -> dict:
    """Recorded beside the content hashes, never instead of them.

    `dirty_paths` and `untracked` are kept so a run driven from a working tree is DESCRIBED.
    That is not hypothetical: the TASK-431 base books were driven at 10:36 on 2026-09-11 and the
    PR that published them merged at 10:49, so a commit id alone would have named a tree that did
    not exist when the engine ran.
    """
    porcelain = _git(["status", "--porcelain"]).splitlines()
    return dict(
        commit=_git(["rev-parse", "HEAD"]) or None,
        dirty=bool(porcelain),
        dirty_paths=sorted(ln[3:] for ln in porcelain if not ln.startswith("??")),
        untracked=sorted(ln[3:] for ln in porcelain if ln.startswith("??")),
    )


def _dep_versions() -> dict:
    out = {"python": sys.version.split()[0]}
    for name in DEPENDENCIES:
        if name == "python":
            continue
        try:
            out[name] = getattr(__import__(name), "__version__", None)
        except Exception:
            out[name] = None
    return out


def loaded_lab_modules() -> list[str]:
    """Every module loaded from this repo, swept out of `sys.modules` at write time.

    The enumerated list is a claim about what matters; this is a measurement of what was
    imported. Anything here and not there lands in `code.unenumerated`, so the list cannot
    silently miss an import that moved a number.
    """
    out = set()
    root = os.path.abspath(ROOT) + os.sep
    for mod in list(sys.modules.values()):
        path = getattr(mod, "__file__", None)
        if not path:
            continue
        path = os.path.abspath(path)
        if not path.startswith(root) or "__pycache__" in path or not path.endswith(".py"):
            continue
        name = os.path.basename(path)
        if name.startswith("test_") or name == "conftest.py":
            continue
        out.add(_rel(path))
    return sorted(out)


def code_identity(enumerated=ENUMERATED_MODULES) -> dict:
    """`code` block: content hashes of the executing modules, plus git recorded beside them.

    Two maps, and the split is deliberate. `modules` is the ENUMERATED list - the claim about
    what can move a number - and `modules_combined` digests exactly that, so it is a property of
    the repo and not of whatever else happened to be imported in this process. `swept` is the
    measurement: every repo module actually loaded that the list does not name. Comparing the
    combined digest over the sweep would make two honest runs disagree whenever one of them had
    also imported something unrelated, so the sweep is compared module by module on the names
    both sides loaded, and anything only one side loaded is recorded rather than refused.
    """
    listed = [m for m in enumerated if os.path.exists(os.path.join(ROOT, m))]
    modules = {rel: sha256_lf(os.path.join(ROOT, rel)) for rel in sorted(listed)}
    swept = {rel: sha256_lf(os.path.join(ROOT, rel))
             for rel in loaded_lab_modules()
             if rel not in modules and os.path.exists(os.path.join(ROOT, rel))}
    return dict(
        modules=modules,
        modules_combined=sha256_json(modules),
        swept=swept,
        unenumerated=sorted(swept),
        missing=sorted(m for m in enumerated if not os.path.exists(os.path.join(ROOT, m))),
        entry=_rel(sys.argv[0]) if sys.argv and sys.argv[0] else None,
        git=git_state(),
        deps=_dep_versions(),
    )


def data_identity(inputs: dict) -> dict:
    """`data` block from {logical name -> path or None}.

    A file the run did not open is recorded as `null`, never omitted: an absent key would let a
    panel swap look like a shorter manifest instead of a different one.
    """
    out: dict = {}
    for name, path in sorted(inputs.items()):
        if path is None:
            out[name] = None
            continue
        st = os.stat(path)
        rec = dict(path_repo_rel=_rel(path), bytes=int(st.st_size),
                   sha256=sha256_bytes(path),
                   mtime_utc=datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat())
        out[name] = rec
    return out


# --------------------------------------------------------------------------- the manifest

def manifest_path(book_path: str) -> str:
    return str(book_path) + MANIFEST_SUFFIX


def provenance_path(book_path: str) -> str:
    return str(book_path) + PROVENANCE_SUFFIX


def result_block(book: pd.Series) -> dict:
    b = pd.Series(book)
    idx = pd.DatetimeIndex(b.index)
    return dict(kind="book", n=int(len(b)),
                first=str(idx[0].date()) if len(idx) else None,
                last=str(idx[-1].date()) if len(idx) else None,
                dtype=str(b.dtype), sha256=book_sha256(b),
                wealth=round(float(b.iloc[-1] / b.iloc[0]), 6) if len(b) > 1 else None)


def calendar_block(book: pd.Series) -> dict:
    idx = pd.DatetimeIndex(pd.Series(book).index)
    return dict(n_marks=int(len(idx)),
                first=str(idx[0].date()) if len(idx) else None,
                last=str(idx[-1].date()) if len(idx) else None,
                sha256=calendar_sha256(idx))


def seal(manifest: dict) -> dict:
    """Stamp `self_sha256` over everything else, so an edited manifest stops verifying."""
    body = {k: v for k, v in manifest.items() if k != "self_sha256"}
    out = dict(body)
    out["self_sha256"] = sha256_json(body)
    return out


def seal_ok(manifest: dict) -> tuple[bool, str, str]:
    body = {k: v for k, v in manifest.items() if k != "self_sha256"}
    want = sha256_json(body)
    got = str(manifest.get("self_sha256") or "")
    return (want == got), got, want


def build_manifest(book: pd.Series, book_path: str, request: dict, *,
                   engine: dict | None = None, now=None) -> dict:
    """The sealed document for one book. `request` supplies every declared block verbatim.

    Whatever the caller declares is what gets compared later, so the caller reads the values out
    of the LIVE objects (V9 inside the cost override, the resolved lab config, the sector mapper's
    own `info`) rather than out of the defaults as written in source. `engine` is recorded and
    never compared: it is an output of the run, not an input to the decision.
    """
    now = now or datetime.now(timezone.utc)
    m = {
        "schema": SCHEMA,
        "artifact": _rel(book_path),
        "written_utc": now.isoformat(),
        "run": dict(host=platform.node(), argv=list(sys.argv),
                    python=sys.version.split()[0], platform=platform.platform()),
        "code": request.get("code") or code_identity(),
        "config": dict(request.get("config") or {}),
        "costs": dict(request.get("costs") or {}),
        "data": dict(request.get("data") or {}),
        "calendar": calendar_block(book),
        "universe": dict(request.get("universe") or {}),
        "sectors": dict(request.get("sectors") or {}),
        "units": dict(request.get("units") or {}),
        "period": dict(request.get("period") or {}),
        "protocol": dict(request.get("protocol") or {}),
        "result": result_block(book),
        "engine": dict(engine or {}),
    }
    return seal(m)


def write_manifest(book: pd.Series, book_path: str, request: dict, *,
                   engine: dict | None = None) -> dict:
    """Write `<book>.manifest.json` beside the book. Atomic: a half-written seal is not a seal."""
    m = build_manifest(book, book_path, request, engine=engine)
    path = manifest_path(book_path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(m, fh, indent=2, default=str)
    os.replace(tmp, path)
    return m


def read_manifest(book_path: str) -> dict | None:
    path = manifest_path(book_path)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- the validator

class CacheRejected(Exception):
    """A cached book is not the book that was asked for. Carries the field that differed."""

    def __init__(self, message: str, *, tag: str, field: str):
        super().__init__(message)
        self.tag, self.field = tag, field


def _line(tag: str, field: str, artifact: str, body: str) -> str:
    return f"{tag} [{field}] {artifact}: {body}"


def _major(v) -> str | None:
    return str(v).split(".")[0] if v else None


def _check_seal(stored: dict, req: dict, art: str) -> list[tuple[str, str, str]]:
    ok, got, want = seal_ok(stored)
    if ok:
        return []
    return [(REJECTED, "self_sha256",
             f"the manifest's own seal does not verify (records {_short(got)}, recomputes "
             f"{_short(want)}). The manifest was edited after it was written.")]


def _check_artifact(stored: dict, req: dict, art: str) -> list:
    """The manifest names the book it was written for; a swap moves exactly that name.

    Compared on the BASENAME, which is the slot: `cost_stress.book_path` and
    `accredit_433.acc_path` both spell it `<panel>_<label>.pkl`, so `sp500_base.pkl` consumed out
    of the `russell_base` slot is refused here by name. A different DIRECTORY under the same
    basename is a relocation - a restored backup, a fixture tree - which moves no number, so it is
    recorded as DEGRADED and not refused.

    This is a check on a LABEL and is deliberately not the only defence: `_check_data` compares
    the input BYTES the two panels read, which is the same refusal made on content.
    """
    want = str(stored.get("artifact") or "")
    if not want:
        return [(REJECTED, "artifact",
                 "the manifest names no artifact at all, so there is nothing to compare this "
                 "file against. A manifest that does not say which book it is written for cannot "
                 "accredit one.")]
    wb, gb = os.path.basename(want), os.path.basename(str(art))
    if wb != gb:
        return [(REJECTED, "artifact",
                 f"the manifest was written for {wb}; it is being consumed from {gb}. A book "
                 "moved into another book's slot is not that book - the file name carries the "
                 "panel and the scenario, and every delta published for this task is one panel "
                 "minus the other. This file is not deleted.")]
    if want != str(art):
        return [(DEGRADED, "artifact",
                 f"written at {want}, consumed from {art} - the same book under a different "
                 "directory. A relocation moves no number; recorded, not refused.")]
    return []


def _check_result(stored: dict, req: dict, art: str) -> list:
    want = stored.get("result") or {}
    got = req.get("_artifact_result") or {}
    if not want.get("sha256"):
        # FAIL CLOSED. This is the ONLY check that looks at the bytes actually loaded, so a
        # manifest that records no result digest certifies nothing about the book beside it -
        # and `return []` here used to read as agreement, with `result` still listed in
        # `compared`. Reachable without a re-sealer: `schema` is never compared, so a manifest
        # under a different schema whose `result` block is shaped differently landed here.
        return [(REJECTED, "result",
                 "the manifest records no result sha256, so nothing identifies the book it sits "
                 "beside. A missing digest is not agreement; it is the absence of the only "
                 "evidence that ties this manifest to these bytes.")]
    if want.get("sha256") == got.get("sha256"):
        return []
    return [(REJECTED, "result",
             f"manifest records result sha256 {_short(want.get('sha256'))} "
             f"({want.get('n')} marks, wealth {want.get('wealth')}); the file on disk hashes to "
             f"{_short(got.get('sha256'))} ({got.get('n')} marks, wealth {got.get('wealth')}). "
             "The book was modified after its manifest was written.")]


def _check_code(stored: dict, req: dict, art: str) -> list:
    want, got = stored.get("code") or {}, req.get("code") or {}
    if not got:
        return []
    out = []
    if want.get("modules_combined") != got.get("modules_combined"):
        a, b = want.get("modules") or {}, got.get("modules") or {}
        moved = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        out.append((REJECTED, "code",
                    f"stored code {_short(want.get('modules_combined'))}; running "
                    f"{_short(got.get('modules_combined'))}. {len(moved)} module(s) differ: "
                    f"{', '.join(moved[:6])}. The book was produced by different code."))
    ws, gs = want.get("swept") or {}, got.get("swept") or {}
    for name in sorted(set(ws) & set(gs)):
        if ws[name] != gs[name]:
            out.append((REJECTED, "code.swept",
                        f"stored {name} {_short(ws[name])}; running {_short(gs[name])}. A module "
                        "the enumerated list does not name was loaded by both runs and has "
                        "changed."))
    for name, wv in sorted((want.get("deps") or {}).items()):
        gv = (got.get("deps") or {}).get(name)
        if gv is None or wv is None or gv == wv:
            continue
        if _major(wv) != _major(gv):
            out.append((REJECTED, "code.deps",
                        f"stored {name} {wv}; running {name} {gv}. A major version change has "
                        "moved dtype and groupby semantics under this code before."))
        else:
            out.append((DEGRADED, "code.deps",
                        f"built on {name} {wv}, running {name} {gv} - float64 arithmetic "
                        "unchanged, recorded not refused."))
    return out


def _check_config(stored: dict, req: dict, art: str) -> list:
    want, got = stored.get("config") or {}, req.get("config") or {}
    out = []
    for key in ("v9_effective_sha256", "lab_config_sha256", "algo_version",
                "start_bar", "step_bars", "capital", "whole_shares"):
        if key not in got:
            continue
        if want.get(key) != got.get(key):
            out.append((REJECTED, f"config.{key}",
                        f"stored {want.get(key)!r}; requested {got.get(key)!r}. The cached book "
                        "was driven under a different configuration."))
    return out


def _check_costs(stored: dict, req: dict, art: str) -> list:
    """The pair per sleeve, never the blend, and an absent value is a mismatch and not a pass.

    `if not got: return []` used to head this function, so `req['costs'] = {}` was accepted while
    `_accreditation.compared` still listed `costs`. `costs` is an identity block now, so an empty
    one never reaches here; a half-declared one lands on the `is not None` test below and is
    refused rather than skipped.
    """
    want, got = stored.get("costs") or {}, req.get("costs") or {}
    ws, we = want.get("stock_bp_per_side"), want.get("etf_bp_per_side")
    gs, ge = got.get("stock_bp_per_side"), got.get("etf_bp_per_side")
    same = (ws is not None and gs is not None and float(ws) == float(gs)
            and we is not None and ge is not None and float(we) == float(ge))
    if same:
        return []
    return [(REJECTED, "costs",
             f"stored stock_bp={ws} etf_bp={we}; requested stock_bp={gs} etf_bp={ge}. "
             "The cached book was priced at costs other than the ones asked for. Drive the "
             "scenario or point at the right book; this file is not deleted.")]


def _sha_of(rec) -> str | None:
    return rec.get("sha256") if isinstance(rec, dict) else None


def _describe_input(rec) -> str:
    if not isinstance(rec, dict):
        return "no such input (null)"
    return f"{rec.get('path_repo_rel')} sha256 {_short(rec.get('sha256'))}"


def _check_data(stored: dict, req: dict, art: str) -> list:
    """Two different questions, asked in this order, each named by its logical input.

    FIRST - are these the inputs I ASKED FOR? The request's own `data` block against the stored
    one, sha256 by sha256 over the UNION of logical names, so an input one side names and the
    other leaves null is a mismatch and not a shorter manifest. This is the comparison the shipped
    code did not make at all, and the one that refuses a panel swap: until 2026-09-12 the S&P
    book, moved into the `russell_base` slot with its own manifest, answered the Russell question
    with wealth 3.439693. `accredit_433.data_answers` was the local guard for one caller's produce
    path; this is the same comparison, inside the validator, for every caller.

    SECOND, and only once the first agrees - have those inputs MOVED since? The stored sha256
    against the CURRENT bytes on disk, which is the comparison existence cannot make. Asked
    second because "you handed me a different panel" and "your panel changed under you" are
    different diagnoses, and the first explains the second away if it fires.

    The logical name is inside the tag either way, so a panel swap reads `[data:price_close]` and
    a membership swap `[data:membership]`: two diagnoses, not one 'data' failure.
    """
    want = stored.get("data") or {}
    asked = req.get("data") or {}
    out = []
    for name in sorted(set(want) | set(asked)):
        if _sha_of(want.get(name)) == _sha_of(asked.get(name)):
            continue
        out.append((REJECTED, f"data:{name}",
                    f"the manifest was written over {_describe_input(want.get(name))}; the "
                    f"request asks for {_describe_input(asked.get(name))}. The cached book was "
                    "driven on a different input, so it answers a different question - a file "
                    "name is not a panel. This file is not deleted."))
    if out:
        return out
    for name, rec in sorted(want.items()):
        if not rec:
            continue
        path = os.path.join(ROOT, rec.get("path_repo_rel", ""))
        if not os.path.exists(path):
            out.append((REJECTED, f"data:{name}",
                        f"stored sha256 {_short(rec.get('sha256'))} "
                        f"({rec.get('bytes')} bytes) at {rec.get('path_repo_rel')}; that file is "
                        "gone. The input the book was driven on is no longer on disk."))
            continue
        now_sha = sha256_bytes(path)
        if now_sha != rec.get("sha256"):
            out.append((REJECTED, f"data:{name}",
                        f"stored sha256 {_short(rec.get('sha256'))} ({rec.get('bytes')} bytes); "
                        f"current sha256 {_short(now_sha)} ({os.path.getsize(path)} bytes) at "
                        f"{rec.get('path_repo_rel')}. The panel changed under the book."))
    return out


def _check_calendar(stored: dict, req: dict, art: str) -> list:
    """Same length and different dates is a different diagnosis from short and truncated.

    The window shift is the attack that was accepted silently last cycle: a poisoned base moved
    the evaluated window to 2014-2026 and still received a clean holdout stamp.
    """
    want, got = stored.get("calendar") or {}, req.get("calendar") or {}
    if not got or want.get("sha256") == got.get("sha256"):
        return []
    wn, gn = want.get("n_marks"), got.get("n_marks")
    if wn == gn:
        return [(REJECTED, "calendar",
                 f"stored window {want.get('first')}..{want.get('last')} "
                 f"(n={wn}, sha {_short(want.get('sha256'))}); requested "
                 f"{got.get('first')}..{got.get('last')} (n={gn}, sha {_short(got.get('sha256'))}). "
                 "Same length, different dates: the book does not answer for the requested period.")]
    short = int(gn or 0) - int(wn or 0)
    where = ""
    try:
        part = HO.partition_of(want.get("last"))
        where = f" and stops inside '{part}'" if part else ""
    except Exception:
        where = ""
    verb = f"{abs(short)} marks {'short' if short > 0 else 'long'}"
    return [(REJECTED, "calendar",
             f"stored n={wn} marks {want.get('first')}..{want.get('last')}; requested n={gn} "
             f"marks {got.get('first')}..{got.get('last')}. The cached book is {verb}{where}; "
             "it cannot answer for the requested period.")]


def _check_mapping(block: str, keys) -> callable:
    def check(stored: dict, req: dict, art: str) -> list:
        want, got = stored.get(block) or {}, req.get(block) or {}
        out = []
        for key in keys:
            if key not in got:
                continue
            if want.get(key) != got.get(key):
                out.append((REJECTED, f"{block}.{key}",
                            f"stored {want.get(key)!r}; requested {got.get(key)!r}. The cached "
                            f"book does not answer for the requested {block}."))
        return out
    return check


def _check_units(stored: dict, req: dict, art: str) -> list:
    """Exact dict equality. Nothing in a float64 series distinguishes 0.0151 from 1.51.

    On the shipped `irx.pkl` the 25th percentile is 0.085 and the minimum -0.105, so neither
    magnitude nor sign can tell percent from decimal. Declared units are the only check there is.
    """
    want, got = stored.get("units") or {}, req.get("units") or {}
    if not got or want == got:
        return []
    moved = sorted(k for k in set(want) | set(got) if want.get(k) != got.get(k))
    return [(REJECTED, "units",
             f"stored {json.dumps({k: want.get(k) for k in moved}, sort_keys=True)}; requested "
             f"{json.dumps({k: got.get(k) for k in moved}, sort_keys=True)}. The cached book or "
             "its statistics were computed under a different unit contract.")]


def _check_period(stored: dict, req: dict, art: str) -> list:
    want, got = stored.get("period") or {}, req.get("period") or {}
    out = []
    if "declared" in got and want.get("declared") != got.get("declared"):
        out.append((REJECTED, "period.declared",
                    f"stored {want.get('declared')!r}; requested {got.get('declared')!r}. "
                    "The cached book was entitled to a different partition."))
    if "spanned" in got and set(want.get("spanned") or []) != set(got.get("spanned") or []):
        out.append((REJECTED, "period.spanned",
                    f"stored {sorted(want.get('spanned') or [])}; requested "
                    f"{sorted(got.get('spanned') or [])}. The cached book reads a different "
                    "set of partitions."))
    if "holdout_sha256" in got and want.get("holdout_sha256") != got.get("holdout_sha256"):
        out.append((REJECTED, "period.holdout_sha256",
                    f"stored {_short(want.get('holdout_sha256'))}; requested "
                    f"{_short(got.get('holdout_sha256'))}. The holdout declaration moved."))
    return out


#: Fail-fast and fixed, so exactly one tag is emitted for one cause. `self_sha256` first, because
#: a manifest that does not verify cannot be quoted for anything else; then `result`, before
#: anything that could mask a silent content edit; then `artifact`, the name the manifest was
#: written for. `costs` precedes `config` because the bp pair is baked into
#: `config.v9_effective_sha256`, so under the old order every real cost mismatch surfaced as
#: "driven under a different configuration" - true, and the less precise of two names for one
#: fact. `data` and `code` come before the cheap label fields so a substituted input is named as
#: a substitution and not as a date mismatch.
CHECKS = (
    ("self_sha256", _check_seal),
    ("result", _check_result),
    ("artifact", _check_artifact),
    ("code", _check_code),
    ("costs", _check_costs),
    ("config", _check_config),
    ("data", _check_data),
    ("calendar", _check_calendar),
    ("universe", _check_mapping("universe", ("columns_sha256", "membership_source",
                                             "coverage_sha256", "n_columns"))),
    ("sectors", _check_mapping("sectors", ("requested_mode", "mode", "ident", "map_sha256",
                                           "snapshot_date"))),
    ("units", _check_units),
    ("period", _check_period),
    ("protocol", _check_mapping("protocol", ("prereg_sha256", "board_task",
                                             "verdict_rule_sha256"))),
)

#: Recorded, never compared: outputs of the run and facts about the machine that ran it.
#: `artifact` was in this tuple until 2026-09-12, which WAS the book-swap hole - the manifest
#: carries a distinguishing name and the validator was told never to look at it. It is compared
#: now; nothing left here distinguishes one book from another.
NEVER_COMPARED = ("run", "engine", "written_utc", "schema")

#: Checked whether or not the caller asked: the seal, the book's own hash, and the name the
#: manifest was written for. Those are about the DOCUMENT and the BOOK, not about the request, so
#: a caller cannot narrow its way out of them by declaring less.
ALWAYS_CHECKED = ("self_sha256", "result", "artifact")

#: IDENTITY: what makes this book THIS book rather than a different one with the same file name.
#: A request that leaves one of these out - missing, `None`, or `{}` - is REJECTED naming the
#: block, because "I did not say" must not read the same as "it agrees". The tuple beside each
#: block is the keys the request must actually put on the table. A key the stored manifest carries
#: and the request does not is NAMED in `_accreditation.uncompared_keys` rather than refused: a
#: cache reader cannot recompute `config.start_bar` or the sector map without loading the panel
#: the cache exists to avoid, and a true record of what was skipped is worth more than a rule that
#: would make every cache hit impossible. Ordered as CHECKS is, so one cause is named first.
IDENTITY_BLOCKS = {
    "code": ("modules_combined",),
    "costs": ("stock_bp_per_side", "etf_bp_per_side"),
    "config": ("v9_effective_sha256", "lab_config_sha256", "algo_version", "step_bars"),
    "data": (),
    "calendar": (),
    "sectors": ("requested_mode",),
    "units": (),
    "period": ("declared", "holdout_sha256"),
    "protocol": ("board_task", "verdict_rule_sha256"),
}

#: NOT identity, with the reason written down beside each rather than assumed. Compared when a
#: caller declares them and recorded otherwise, because their identity is already carried by a
#: field that IS compared - which is a true statement only since `_check_data` began comparing the
#: request's own block on 2026-09-12.
DERIVED_BLOCKS = {
    "universe": "the columns come out of price_close, compared by its bytes as data:price_close",
}

#: The one legitimate reason an identity block cannot be declared. The FIRST book of a run DEFINES
#: the mark grid, so there is no anchor to compare its calendar against; the caller says so here,
#: in words, and `accredit` then records `calendar` as UNCOMPARED and emits `CACHE DEGRADED
#: [calendar]`. Nothing in this module constrains that book's window, and a run that consumes one
#: now says so out loud instead of skipping in silence.
ANCHOR_DECLARATION = "calendar_anchor"


def _declared(field: str, req: dict) -> bool:
    """Did the request actually put something comparable on the table for `field`?"""
    v = req.get(field, None)
    return isinstance(v, dict) and bool(v)


def _identity_problems(field: str, req: dict) -> list:
    """Refuse an identity block the request did not declare. Fail closed, by name."""
    keys = IDENTITY_BLOCKS.get(field)
    if keys is None:
        return []
    if field == "calendar" and not _declared(field, req):
        if str(req.get(ANCHOR_DECLARATION) or "").strip():
            return []                                  # declared out loud; handled in `accredit`
        return [(REJECTED, "calendar",
                 "the request declares neither a mark grid nor "
                 f"{ANCHOR_DECLARATION!r}. The window is identity: a book that answers for "
                 "2014-2026 is not the book that answers for 2010-2026, and an undeclared window "
                 "is the substitution this module exists to refuse - a 604-mark base with a valid "
                 "manifest was accredited this way and became the anchor for the whole run. Pass "
                 f"the anchor's calendar block, or declare {ANCHOR_DECLARATION!r} in words if this "
                 "book DEFINES the grid.")]
    if not _declared(field, req):
        shown = "missing" if field not in req else repr(req.get(field))
        return [(REJECTED, field,
                 f"the request declares no {field!r} block ({shown}). {field!r} is an identity "
                 "field - it is part of what makes this book this book - so an undeclared one is "
                 "refused and never silently uncompared.")]
    got = req[field]
    return [(REJECTED, f"{field}.{key}",
             f"the request's {field!r} block does not declare {key!r}. It is an identity field "
             "and cannot be left to the manifest to assert about itself.")
            for key in keys if got.get(key) is None]


def _undeclared_keys(field: str, stored: dict, req: dict) -> list:
    """Keys the stored manifest carries that the request never put up for comparison.

    `ALWAYS_CHECKED` is excluded: those blocks are compared against the BOOK and against the
    manifest's own body, not against anything the request declares, so every one of their keys
    would list here and say nothing.
    """
    if field in ALWAYS_CHECKED:
        return []
    want, got = stored.get(field) or {}, req.get(field) or {}
    if not isinstance(want, dict) or not isinstance(got, dict):
        return []
    return [f"{field}.{k}" for k in sorted(want) if k not in got]


def accredit(book_path: str, request: dict, *, explain_all: bool = False,
             echo: bool = True) -> tuple[pd.Series, dict]:
    """Load a cached book only if its manifest answers for what is being asked.

    Raises `CacheRejected` on any mismatch, naming the field. A missing manifest is its own tag -
    `CACHE UNACCREDITED` - because "we never recorded this" is a different statement from "this
    is the wrong book", and the eight books already on disk are in the first case, not the second.

    Nothing is deleted, moved or repaired. `explain_all` prints every mismatch for a human and
    still raises on the first one, so the exit is the same either way.

    The returned `_accreditation` block is a TRUE record of what was checked and not a flattering
    one. `compared` lists only the blocks a comparison actually ran on: a block the request left
    empty is refused, never listed. `uncompared` names every block that was not compared and
    `uncompared_why` says why for each - derived from a compared field, nothing requested, or the
    declared calendar anchor. `uncompared_keys` names the individual keys the stored manifest
    carries and the request did not put up, `config.start_bar` and the sector map among them.
    """
    art = _rel(book_path)
    if not os.path.exists(book_path):
        raise FileNotFoundError(book_path)
    stored = read_manifest(book_path)
    if stored is None:
        raise CacheRejected(
            _line(UNACCREDITED, "manifest", art,
                  f"no {os.path.basename(book_path)}{MANIFEST_SUFFIX} beside the book. Historical "
                  "artifact with incomplete provenance; it may be reported as history but never "
                  "consumed as a cache hit. Drive an accredited book beside it - the old file is "
                  "preserved."),
            tag=UNACCREDITED, field="manifest")
    book = pd.read_pickle(book_path)
    req = dict(request)
    req["_artifact_result"] = result_block(book)

    compared, degraded, problems = [], [], []
    uncompared, why, uncompared_keys = [], {}, []

    def _emit(tag, name, body):
        line = _line(tag, name, art, body)
        if tag == DEGRADED:
            degraded.append(line)
            if echo:
                print(line, flush=True)
            return
        problems.append(line)
        if not explain_all:
            raise CacheRejected(line, tag=tag, field=name)

    for field, check in CHECKS:
        missing = _identity_problems(field, req)
        if missing:
            uncompared.append(field)
            why[field] = "REFUSED: an identity field the request did not declare"
            for tag, name, body in missing:
                _emit(tag, name, body)
            continue
        if field == "calendar" and not _declared(field, req):
            uncompared.append(field)
            why[field] = (f"declared anchor ({str(req.get(ANCHOR_DECLARATION)).strip()}): this "
                          "book DEFINES the grid, so nothing here constrains its window")
            _emit(DEGRADED, "calendar",
                  "not compared: the request declares that this book DEFINES the mark grid "
                  f"({str(req.get(ANCHOR_DECLARATION)).strip()}). Nothing in this accreditation "
                  "constrains its window - it is the anchor every other book is compared to, and "
                  "it is compared to nothing.")
            continue
        if field not in ALWAYS_CHECKED and not _declared(field, req):
            uncompared.append(field)
            why[field] = DERIVED_BLOCKS.get(field) or "nothing requested"
            continue
        compared.append(field)
        uncompared_keys.extend(_undeclared_keys(field, stored, req))
        for tag, name, body in check(stored, req, art):
            _emit(tag, name, body)
    if problems:
        if echo:
            for ln in problems:
                print(ln, flush=True)
        raise CacheRejected(problems[0], tag=REJECTED,
                            field=problems[0].split("[", 1)[1].split("]", 1)[0])

    out = dict(stored)
    out["_accreditation"] = dict(
        compared=compared,
        uncompared=sorted(uncompared),
        uncompared_why={k: why[k] for k in sorted(why)},
        uncompared_keys=sorted(set(uncompared_keys)),
        degraded=degraded,
        accredited_utc=datetime.now(timezone.utc).isoformat(),
    )
    if echo and uncompared:
        print(f"[accredit] {art}: not compared: "
              + "; ".join(f"{k} ({why[k]})" for k in sorted(uncompared)), flush=True)
    if echo and out["_accreditation"]["uncompared_keys"]:
        print(f"[accredit] {art}: recorded but not compared (the request declares no value): "
              f"{', '.join(out['_accreditation']['uncompared_keys'])}", flush=True)
    return book, out


# --------------------------------------------------------------- the books that came before

HISTORICAL = "historical_incomplete"
ACCREDITED = "accredited"

#: What a sidecar must NOT claim, said in the sidecar itself. Three rounded statistics agreeing
#: is satisfied by any book with the same returns however produced, and is silent on code
#: identity, on units, and on which panel bytes were read.
CORROBORATION_NOTE = (
    "The base books matching the TASK-431 row on ann_net / sharpe_excess / maxdd is "
    "CORROBORATION of the config and the period, NOT proof of provenance. No hash of any of "
    "these books was recorded by anything, by anyone, at any time, so there is no proof to be "
    "had. Agreement of three rounded statistics is satisfied by any book with the same returns "
    "however produced."
)

#: Manifest fields for which NO evidence exists for the pre-manifest books. Listed explicitly,
#: because an omitted field reads as an oversight and an listed one reads as a finding.
ABSENT_FOR_HISTORICAL = (
    "code.modules", "code.modules_combined", "result.sha256", "calendar.sha256",
    "data.*.sha256", "units", "engine.counts", "self_sha256",
)


def classify_historical(book_path: str, *, evidence=(), absent=ABSENT_FOR_HISTORICAL,
                        corroboration: str = CORROBORATION_NOTE, note: str = "") -> dict:
    """Describe a book that has no manifest, without inventing one.

    Writes `<book>.provenance.json` - a different filename from `<book>.manifest.json` on
    purpose, so no validator can ever mistake a classification for an accreditation. Everything
    under `observed` is recomputed NOW from the artifact and is true of the file as it sits;
    everything under `contemporaneous_evidence` is a fact found on disk, each with what it
    supports and what it does not. Nothing here is retrospective metadata about how the run was
    made, because none exists.
    """
    book = pd.read_pickle(book_path)
    st = os.stat(book_path)
    rec = dict(
        schema="hydra.lab.provenance/1",
        cls=HISTORICAL,
        file=dict(path_repo_rel=_rel(book_path), bytes=int(st.st_size),
                  sha256_now=sha256_bytes(book_path),
                  mtime_utc=datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()),
        observed=dict(result_block(book), calendar_sha256=calendar_sha256(pd.Series(book).index)),
        contemporaneous_evidence=[dict(e) for e in evidence],
        absent=list(absent),
        corroboration=corroboration,
        note=note,
        classified_utc=datetime.now(timezone.utc).isoformat(),
    )
    rec = seal(rec)
    path = provenance_path(book_path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=2, default=str)
    os.replace(tmp, path)
    return rec


def classify(book_path: str) -> str:
    """`accredited` only when a manifest is there AND its own seal verifies; else historical."""
    stored = read_manifest(book_path)
    if stored is None:
        return HISTORICAL
    return ACCREDITED if seal_ok(stored)[0] else HISTORICAL
