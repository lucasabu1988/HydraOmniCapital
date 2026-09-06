"""TASK-359 — run manifest + file log. Live callers wait until the freeze lifts."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from config import ALGO_VERSION, FILTERS, V9

_MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _MODULE_DIR.parent
DEFAULT_RUNS_DIR = PROJECT_ROOT / "runs"
KEEP_LAST = 90
ENV_NAMES = ("HYDRA_BACKUP_DIR", "UNIVERSE")
_LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"


def _native(value):
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, (datetime,)):
        return value.isoformat()
    return value


def _sha256_json(obj) -> str:
    blob = json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _git_info(cwd: Path | None = None) -> tuple[str | None, bool]:
    p = (cwd or PROJECT_ROOT).resolve()
    for _ in range(8):
        if (p / ".git").exists():
            break
        if p.parent == p:
            return None, False
        p = p.parent
    else:
        return None, False
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=p, text=True, stderr=subprocess.DEVNULL,
        ).strip()
        dirty = bool(subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=p, text=True, stderr=subprocess.DEVNULL,
        ).strip())
        return commit or None, dirty
    except (OSError, subprocess.CalledProcessError):
        return None, False


def _pkg_version(name: str) -> str | None:
    try:
        mod = __import__(name)
        return getattr(mod, "__version__", None)
    except Exception:
        return None


def _fingerprint_frame(frame) -> dict:
    if frame is None or getattr(frame, "empty", True) or len(frame) == 0:
        return {"last_bar": None, "shape": [0, 0], "last_row_sha256": None}
    idx = getattr(frame, "index", None)
    last_bar = None
    if idx is not None and len(idx):
        try:
            last_bar = str(pd.Timestamp(idx[-1]).date())
        except Exception:
            last_bar = str(idx[-1])
    shape = list(frame.shape)
    last = frame.iloc[-1]
    if hasattr(last, "to_dict"):
        payload = {str(k): _native(v) for k, v in last.to_dict().items()}
    else:
        payload = _native(last)
    digest = _sha256_json(payload)
    return {"last_bar": last_bar, "shape": shape, "last_row_sha256": digest}


class RunContext:
    def __init__(self, directory: Path, manifest: dict, logger: logging.Logger):
        self.directory = Path(directory)
        self.manifest = manifest
        self.logger = logger
        self._log_path = self.directory / "log.txt"
        self._manifest_path = self.directory / "manifest.json"

    def fingerprint(self, name: str, frame) -> dict:
        rec = _fingerprint_frame(frame)
        self.manifest.setdefault("fingerprints", {})[str(name)] = rec
        self._write_manifest()
        self.logger.info("fingerprint %s last_bar=%s shape=%s", name, rec["last_bar"], rec["shape"])
        return rec

    def artifact(self, path) -> str:
        p = str(Path(path))
        arts = self.manifest.setdefault("artifacts", [])
        if p not in arts:
            arts.append(p)
            self._write_manifest()
        self.logger.info("artifact %s", p)
        return p

    def finish(self, exit_status: int = 0, exception: BaseException | str | None = None) -> dict:
        end = datetime.now(timezone.utc)
        start = datetime.fromisoformat(self.manifest["start"])
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        self.manifest["end"] = end.isoformat()
        self.manifest["duration_s"] = round((end - start).total_seconds(), 3)
        self.manifest["exit_status"] = int(exit_status)
        if exception is None:
            self.manifest["exception"] = None
        else:
            self.manifest["exception"] = exception if isinstance(exception, str) else f"{type(exception).__name__}: {exception}"
        self._write_manifest()
        self.logger.info("finish exit=%s duration_s=%s", exit_status, self.manifest["duration_s"])
        return self.manifest

    def close_log(self) -> None:
        for h in list(self.logger.handlers):
            try:
                h.close()
            except Exception:
                pass
            self.logger.removeHandler(h)

    def _write_manifest(self) -> None:
        tmp = self._manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.manifest, indent=2, default=str), encoding="utf-8")
        tmp.replace(self._manifest_path)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is not None:
            self.finish(exit_status=1, exception=exc)
        elif self.manifest.get("exit_status") is None:
            self.finish(exit_status=0)
        self.close_log()
        return False


def start_run(
    name: str,
    argv: list[str] | None = None,
    *,
    runs_dir: str | Path | None = None,
    now: datetime | None = None,
    git_info: tuple[str | None, bool] | None = None,
) -> RunContext:
    """Create `runs/<YYYYMMDD_HHMMSS>_<name>/` with manifest.json + log.txt."""
    runs = Path(runs_dir) if runs_dir is not None else DEFAULT_RUNS_DIR
    runs.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(name).strip()) or "run"
    directory = runs / f"{stamp}_{slug}"
    n = 1
    while directory.exists():
        n += 1
        directory = runs / f"{stamp}_{slug}_{n}"
    directory.mkdir(parents=True, exist_ok=False)

    commit, dirty = git_info if git_info is not None else _git_info()
    env_set = [n for n in ENV_NAMES if os.environ.get(n)]
    start = datetime.now(timezone.utc)
    manifest = {
        "name": str(name),
        "directory": str(directory),
        "git_commit": commit,
        "git_dirty": bool(dirty),
        "ALGO_VERSION": ALGO_VERSION,
        "config_sha256": {
            "V9": _sha256_json(V9),
            "FILTERS": _sha256_json(FILTERS),
        },
        "versions": {
            "python": sys.version.split()[0],
            "pandas": _pkg_version("pandas"),
            "numpy": _pkg_version("numpy"),
            "yfinance": _pkg_version("yfinance"),
        },
        "hostname": platform.node(),
        "argv": list(argv if argv is not None else sys.argv),
        "env_set": env_set,
        "start": start.isoformat(),
        "end": None,
        "duration_s": None,
        "exit_status": None,
        "exception": None,
        "fingerprints": {},
        "artifacts": [],
    }
    logger = logging.getLogger(f"hydra.runlog.{directory.name}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)
    fh = logging.FileHandler(directory / "log.txt", encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(_LOG_FORMAT))
    logger.addHandler(fh)
    ctx = RunContext(directory, manifest, logger)
    ctx._write_manifest()
    logger.info("start %s commit=%s dirty=%s", name, commit, dirty)
    return ctx


def latest_run(runs_dir: str | Path | None = None) -> Path | None:
    runs = Path(runs_dir) if runs_dir is not None else DEFAULT_RUNS_DIR
    if not runs.exists():
        return None
    dirs = sorted((p for p in runs.iterdir() if p.is_dir() and (p / "manifest.json").exists()), key=lambda p: p.name)
    return dirs[-1] if dirs else None


def load_manifest(run_dir: str | Path) -> dict:
    return json.loads(Path(run_dir).joinpath("manifest.json").read_text(encoding="utf-8"))


def prune(runs_dir: str | Path | None = None, keep: int = KEEP_LAST) -> int:
    """Delete oldest run dirs so at most `keep` remain. Returns how many were removed."""
    runs = Path(runs_dir) if runs_dir is not None else DEFAULT_RUNS_DIR
    if not runs.exists():
        return 0
    dirs = sorted((p for p in runs.iterdir() if p.is_dir()), key=lambda p: p.name)
    extra = dirs[:-int(keep)] if keep >= 0 else dirs
    for p in extra:
        shutil.rmtree(p, ignore_errors=True)
    return len(extra)
