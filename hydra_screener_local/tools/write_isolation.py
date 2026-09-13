"""Write-isolation barrier: refuse any write whose RESOLVED REAL PATH is protected.

WHY THIS SHAPE AND NOT THE OBVIOUS ONE
--------------------------------------
The incident of 2026-09-12 was not "a test wrote to the wrong place". It was a test that
redirected `accredit_433.acc_path` onto `cost_stress.book_path` and then wrote "into the
accredited slot" -- which, after the redirect, WAS
`experiments/_lab_scratch/cost_stress/russell_stress.pkl`, an 814-mark evidence book. It was
overwritten with an 8-mark synthetic.

`accredit_433.not_historical()` is a real guard and it did not stop this, because it sits
INSIDE the function whose path was mutated: it validated the path the mutated builder handed
it, and the mutated builder handed it a path outside the historical set. Any guard that routes
through `acc_path()` / `book_path()` has the same hole by construction. So this barrier is:

  * PATH-BASED, not function-based. It does not know what a book, a slot or a manifest is. It
    knows one thing: the set of directories that hold evidence. Whoever asks -- `open`,
    `os.replace`, `shutil.copy`, `pandas.to_pickle`, a monkeypatched path builder, a helper
    three modules down -- gets the same answer.
  * INSTALLED BEFORE MODULES ARE IMPORTED. A `conftest.py` at the rootdir is imported by pytest
    at collection, before any test module. Binding inside a test body is too late: by the time
    you restore a mutated function in a `finally:`, the write has already landed.
  * RESOLVED THROUGH LINKS. `os.path.realpath` collapses symlinks and NTFS junctions in every
    component, so `tmp/alias/russell_stress.pkl` where `tmp/alias` is a junction into the
    protected root is refused on the same rule as the direct path.
  * LOUD. `WriteIsolationError` inherits from `BaseException`, NOT `Exception`, deliberately.
    Production code in this tree is full of `except Exception:` fallbacks; a guard that a
    fallback can swallow is not a guard. `pytest.raises` accepts BaseException subclasses, so
    testing it is unaffected.

SECOND, INDEPENDENT CONTROL: FILE IDENTITY
------------------------------------------
A hardlink defeats every path-based rule, because a hardlink is not a link -- it is a second
NAME for the same bytes, and `realpath` has nothing to resolve. So at install time the barrier
indexes `(st_dev, st_ino)` of every file under every protected root, and a write to an EXISTING
file whose identity is in that index is refused whatever its path. This is the only case where
the barrier looks at the filesystem instead of the string.

Hashes before/after are a THIRD control and live in the tests, never here: a hash tells you the
barrier failed, it does not stop the write.

WHAT THIS DOES NOT COVER - measured on this machine, not assumed, and written here rather than
in a README so it travels with the code:

  * non-Python subprocesses. `cmd /c echo > file` is NOT stopped. A Python child IS stopped,
    but only when it starts with the barrier armed (PYTHONPATH + HYDRA_WRITE_BARRIER=1, via the
    sitecustomize layer); a child launched without that env writes freely.
  * handles opened BEFORE install(). The guard sits on the opening call, so a file object that
    already exists keeps writing through its own handle.
  * raw file descriptors. `os.write` on an fd obtained before the guard, or through a path this
    module does not wrap, is NOT stopped.
  * C-level path openers. `ctypes` -> `ucrtbase._wfopen` is NOT stopped, and neither is any
    extension module that opens by path in C. `numpy.ndarray.tofile` happens to be refused, but
    via an implementation detail (it routes through builtins.open), not by design.
  * anything that creates a file through a driver this module has not wrapped, e.g. a new
    sqlite database file in a protected root.

The barrier is therefore the MINIMUM SUFFICIENT protection for the 2026-09-12 incident and the
adversarial write tests that follow it - Python-level path writes from this process and from
armed Python children. It is not a general sandbox and must not be described as one.
"""
from __future__ import annotations

import builtins
import io
import os
import shutil
import stat as _stat_mod
import sys

__all__ = [
    "WriteIsolationError", "install", "uninstall", "is_installed",
    "write_barrier", "protected_roots", "exempt_roots", "refresh_identity_index",
    "repo_evidence_roots", "check_path",
]


class WriteIsolationError(BaseException):
    """A write was aimed at a protected root. Inherits BaseException on purpose (module doc)."""


# --------------------------------------------------------------------------- path resolution

def _strip_extended(p: str) -> str:
    if p.startswith("\\\\?\\UNC\\"):
        return "\\\\" + p[8:]
    if p.startswith("\\\\?\\"):
        return p[4:]
    return p


def _key(path) -> str:
    """The single canonical form every decision is made on: absolute, link-resolved, normcased."""
    s = os.fspath(path)
    if isinstance(s, bytes):
        s = os.fsdecode(s)
    s = _strip_extended(os.path.realpath(os.path.abspath(s)))
    return os.path.normcase(s)


def _within(child: str, root: str) -> bool:
    return child == root or child.startswith(root + os.sep)


# --------------------------------------------------------------------------- state

_STATE = {
    "installed": False,
    "protected": [],      # list[str] canonical keys
    "exempt": [],         # list[str] canonical keys, carve-outs INSIDE a protected root
    "ids": set(),         # {(st_dev, st_ino)} of files under protected roots
    "saved": [],          # [(owner, attr, original)]
}


def is_installed() -> bool:
    return _STATE["installed"]


def protected_roots() -> list:
    return list(_STATE["protected"])


def exempt_roots() -> list:
    return list(_STATE["exempt"])


# --------------------------------------------------------------------------- the decision

def _refuse(path_key, attempted, who, reason, root):
    raise WriteIsolationError(
        "WRITE ISOLATION BARRIER: refused.\n"
        "  called by      : " + str(who) + "\n"
        "  attempted path : " + repr(attempted) + "\n"
        "  resolves to    : " + str(path_key) + "\n"
        "  protected root : " + str(root) + "\n"
        "  rule           : " + str(reason) + "\n"
        "  The barrier is path-based and knows nothing about which function asked. If this is a\n"
        "  legitimate output, send it to tmp_path / a disposable directory. If this is a test\n"
        "  fixture, it must never be written into an evidence directory at all."
    )


def check_path(path, who="check_path"):
    """Raise if `path` resolves inside a protected root. Returns the canonical key otherwise."""
    if not _STATE["installed"]:
        return ""
    try:
        k = _key(path)
    except (TypeError, ValueError):
        return ""
    for ex in _STATE["exempt"]:
        if _within(k, ex):
            return k
    for root in _STATE["protected"]:
        if _within(k, root):
            _refuse(k, path, who, "resolved real path lies inside a protected root", root)
    # second control: file identity (a hardlink alias has nothing for realpath to resolve)
    if _STATE["ids"]:
        try:
            st = os.stat(k)
        except (OSError, ValueError):
            return k
        if (st.st_dev, st.st_ino) in _STATE["ids"]:
            _refuse(k, path, who,
                    "target is a hardlink alias of a file inside a protected root "
                    "(st_dev=%r, st_ino=%r)" % (st.st_dev, st.st_ino),
                    "<identity index>")
    return k


def _is_fd(path):
    return isinstance(path, int)


_WRITE_MODE_CHARS = ("w", "a", "x", "+")


def _mode_writes(mode):
    try:
        m = mode if isinstance(mode, str) else str(mode)
    except Exception:
        return True
    return any(c in m for c in _WRITE_MODE_CHARS)


_WRITE_FLAGS = 0
for _n in ("O_WRONLY", "O_RDWR", "O_APPEND", "O_CREAT", "O_TRUNC", "O_TEMPORARY"):
    _WRITE_FLAGS |= getattr(os, _n, 0)


# --------------------------------------------------------------------------- patching

def _guard(owner, attr, wrapper_factory):
    original = getattr(owner, attr, None)
    if original is None:
        return None
    who = getattr(owner, "__name__", str(owner)) + "." + attr
    setattr(owner, attr, wrapper_factory(original, who))
    _STATE["saved"].append((owner, attr, original))
    return original


def _w_open(original, who):
    def guarded(file, mode="r", *a, **kw):
        if not _is_fd(file) and _mode_writes(kw.get("mode", mode)):
            check_path(file, who)
        return original(file, mode, *a, **kw)
    guarded.__wrapped__ = original
    return guarded


def _w_osopen(original, who):
    def guarded(path, flags, *a, **kw):
        if not _is_fd(path) and (flags & _WRITE_FLAGS):
            check_path(path, who)
        return original(path, flags, *a, **kw)
    guarded.__wrapped__ = original
    return guarded


def _w_one(original, who):
    def guarded(*a, **kw):
        if a and not _is_fd(a[0]):
            check_path(a[0], who)
        return original(*a, **kw)
    guarded.__wrapped__ = original
    return guarded


def _w_two(original, who):
    """Both ends checked: a rename/link may write the destination OR alias the source."""
    def guarded(*a, **kw):
        if len(a) > 1:
            if not _is_fd(a[1]):
                check_path(a[1], who + " [dst]")
            if not _is_fd(a[0]):
                check_path(a[0], who + " [src]")
        return original(*a, **kw)
    guarded.__wrapped__ = original
    return guarded


def _w_dst_only(original, who):
    def guarded(*a, **kw):
        if len(a) > 1 and not _is_fd(a[1]):
            check_path(a[1], who + " [dst]")
        return original(*a, **kw)
    guarded.__wrapped__ = original
    return guarded


def _w_method(cls, name, who, argno=0):
    """Bound-method form: argno 0 means `self` is the path, 1 means the first argument is."""
    original = getattr(cls, name, None)
    if original is None:
        return

    def guarded(self, *a, **kw):
        if argno == 0:
            check_path(self, who)
        elif a:
            check_path(a[0], who)
        return original(self, *a, **kw)
    guarded.__wrapped__ = original
    setattr(cls, name, guarded)
    _STATE["saved"].append((cls, name, original))


def _w_path_open(original, who):
    def guarded(self, mode="r", *a, **kw):
        if _mode_writes(kw.get("mode", mode)):
            check_path(self, who)
        return original(self, mode, *a, **kw)
    guarded.__wrapped__ = original
    return guarded


def _w_two_self(original, who):
    def guarded(self, target, *a, **kw):
        check_path(self, who + " [self]")
        check_path(target, who + " [target]")
        return original(self, target, *a, **kw)
    guarded.__wrapped__ = original
    return guarded


def patch_optional_writers(allow_import=True):
    """Guard pandas/numpy entry points BY NAME. Idempotent; safe to call after install().

    Not required for correctness -- `pd.to_pickle`, `to_csv`, `to_json` and even
    `numpy.ndarray.tofile` were MEASURED to funnel through `builtins.open` on this build, and
    the barrier catches them there. It buys two things: a refusal that names the real caller,
    and coverage of `to_parquet` / `to_hdf` / `to_excel`, where the path is handed to a C++ or
    HDF5 writer that opens the file itself and never touches `builtins.open`.

    `allow_import=False` is for `sitecustomize`, where importing pandas at interpreter startup
    would be absurd. Call it again from conftest once pandas is loaded.
    """
    pd = sys.modules.get("pandas")
    if pd is None and allow_import:
        try:
            import pandas as pd
        except Exception:
            pd = None
    if pd is not None and getattr(pd.to_pickle, "__wrapped__", None) is None:
        _guard(pd, "to_pickle", _w_dst_only)
        for cls_name in ("DataFrame", "Series"):
            cls = getattr(pd, cls_name, None)
            if cls is None:
                continue
            for m in ("to_pickle", "to_csv", "to_json", "to_parquet", "to_feather",
                      "to_excel", "to_hdf", "to_stata", "to_orc"):
                if getattr(cls, m, None) is not None:
                    _w_method(cls, m, "pandas." + cls_name + "." + m, argno=1)
    np = sys.modules.get("numpy")
    if np is None and allow_import:
        try:
            import numpy as np
        except Exception:
            np = None
    if np is not None and getattr(np.save, "__wrapped__", None) is None:
        for attr in ("save", "savez", "savez_compressed", "savetxt"):
            _guard(np, attr, _w_one)


def _install_patches(import_optional=True):
    import pathlib

    # 1. the universal funnel. `io.open IS builtins.open`, but pathlib.Path.open looks up
    #    `io.open` as a MODULE ATTRIBUTE at call time, so both names must be rebound.
    _guard(builtins, "open", _w_open)
    _guard(io, "open", _w_open)
    _guard(os, "open", _w_osopen)

    # 2. os-level mutation that never passes through open()
    for attr in ("remove", "unlink", "rmdir", "removedirs", "mkdir", "makedirs",
                 "truncate", "chmod", "utime", "mknod"):
        _guard(os, attr, _w_one)
    for attr in ("rename", "renames", "replace", "link", "symlink"):
        _guard(os, attr, _w_two)

    # 3. shutil: its fast paths (CopyFileEx / os.sendfile) do not always reach builtins.open,
    #    so every entry point is guarded by name.
    for attr in ("copyfile", "copy", "copy2", "copytree", "move", "copymode", "copystat"):
        _guard(shutil, attr, _w_dst_only)
    _guard(shutil, "rmtree", _w_one)

    # 4. pathlib. write_text/write_bytes reach io.open (already covered), but are guarded
    #    directly so the refusal names the real caller.
    orig_open = getattr(pathlib.Path, "open", None)
    if orig_open is not None:
        pathlib.Path.open = _w_path_open(orig_open, "pathlib.Path.open")
        _STATE["saved"].append((pathlib.Path, "open", orig_open))
    for name in ("write_text", "write_bytes", "unlink", "rmdir", "mkdir", "touch", "chmod"):
        _w_method(pathlib.Path, name, "pathlib.Path." + name)
    for name in ("rename", "replace", "symlink_to", "hardlink_to"):
        orig = getattr(pathlib.Path, name, None)
        if orig is None:
            continue
        setattr(pathlib.Path, name, _w_two_self(orig, "pathlib.Path." + name))
        _STATE["saved"].append((pathlib.Path, name, orig))

    # 5. pandas / numpy writers, by name. See patch_optional_writers for why this is extra
    #    rather than load-bearing.
    patch_optional_writers(allow_import=import_optional)


# --------------------------------------------------------------------------- roots

def repo_evidence_roots(screener=None):
    r"""Every directory in this repo a test could reach that holds evidence or live state.

    Enumerated from the code, not guessed:
      experiments/_lab_scratch   cost_stress.OUT_DIR + SCRATCH, accredit_433.ACC_DIR + OUT_JSON,
                                 BASE_BOOKS (engine_book_*.pkl), provenance manifests
                                 (`<book>.manifest.json`, `.provenance`), russell_prereg_cache/,
                                 task431.json / task431_run.log, the INCIDENT record
      state/, state_paper/       the live v9 book, cash, positions, ledger, instruction sheets
      journal/, journal_paper/   core.commit.append_journal -- the append-only run journal
      runs/                      utils.runlog.DEFAULT_RUNS_DIR, read by data.fetch
      history/                   gitignored price history, zipped by daily.py
      backups/                   any in-repo backup drop
      $HYDRA_BACKUP_DIR          resolved from the environment AS INHERITED -- on this machine
                                 C:\Users\caslu\OneDrive\HydraBackups, the only off-disk copy of
                                 the live book. conftest.py redirects the variable; that redirect
                                 is containment, this is the wall behind it.
    """
    if screener is None:
        screener = os.environ.get("HYDRA_SCREENER_DIR") or os.getcwd()
    screener = os.path.abspath(os.fspath(screener))
    roots = [os.path.join(screener, p) for p in (
        os.path.join("experiments", "_lab_scratch"),
        "state", "state_paper", "journal", "journal_paper", "runs", "history", "backups",
    )]
    backup = os.environ.get("HYDRA_BACKUP_DIR")
    if backup:
        # INSTALL ORDER IS LOAD-BEARING. The repo's conftest.py rebinds HYDRA_BACKUP_DIR to a
        # throwaway temp dir at import. If the barrier is installed AFTER that line it protects
        # the throwaway and leaves the operator's real backup root wide open -- which is the
        # exact class of mistake this module exists to prevent, so it is said out loud.
        if "hydra-test-backup" in backup:
            sys.stderr.write(
                "[write-isolation] WARNING: HYDRA_BACKUP_DIR is already the test redirect (%s).\n"
                "[write-isolation] The real backup root was NOT captured and is NOT protected.\n"
                "[write-isolation] Install the barrier BEFORE conftest._redirect_backup_dir().\n"
                % backup)
        roots.append(backup)
    out, seen = [], set()
    for r in roots:
        try:
            k = _key(r)
        except (TypeError, ValueError):
            continue
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def refresh_identity_index():
    """(Re)build the (st_dev, st_ino) index over the protected roots. Read-only walk."""
    ids = set()
    for root in _STATE["protected"]:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                try:
                    st = os.stat(os.path.join(dirpath, fn), follow_symlinks=False)
                except OSError:
                    continue
                if _stat_mod.S_ISREG(st.st_mode):
                    ids.add((st.st_dev, st.st_ino))
    _STATE["ids"] = ids
    return len(ids)


# --------------------------------------------------------------------------- install

def install(protected=None, exempt=(), index_identities=True, screener=None,
            import_optional=True):
    """Install the barrier process-wide. Call at IMPORT time, before any module under test.

    `protected` defaults to `repo_evidence_roots(screener)`. `exempt` is for carve-outs that
    live INSIDE a protected root and must stay writable (there are none by default; prefer
    tmp_path over an exemption). `import_optional=False` keeps pandas/numpy out of the import
    graph, which is what `sitecustomize` needs.
    """
    if _STATE["installed"]:
        return protected_roots()
    roots = repo_evidence_roots(screener) if protected is None else [_key(p) for p in protected]
    _STATE["protected"] = [r for r in roots if r]
    _STATE["exempt"] = [_key(p) for p in exempt]
    _STATE["installed"] = True
    _install_patches(import_optional=import_optional)
    if index_identities:
        refresh_identity_index()
    return protected_roots()


def uninstall():
    for owner, attr, original in reversed(_STATE["saved"]):
        try:
            setattr(owner, attr, original)
        except Exception:
            pass
    _STATE["saved"] = []
    _STATE["installed"] = False
    _STATE["protected"] = []
    _STATE["exempt"] = []
    _STATE["ids"] = set()


class write_barrier:
    """Standalone context manager for ad-hoc scripts.

        with write_barrier(["/path/to/evidence"]):
            drive_the_thing()

    Same barrier, same rules; it just unwinds on exit. For a pytest session use `install()`
    from conftest.py instead -- a context manager entered in a test body is already too late.
    """

    def __init__(self, protected=None, exempt=(), index_identities=True, screener=None):
        self._args = (protected, exempt, index_identities, screener)
        self._owned = False

    def __enter__(self):
        protected, exempt, idx, screener = self._args
        if not _STATE["installed"]:
            self._owned = True
            install(protected, exempt=exempt, index_identities=idx, screener=screener)
        return self

    def __exit__(self, *exc):
        if self._owned:
            uninstall()
        return False
