"""Bind an audited baseline artefact to the exact inputs that produced it (audit phase 6.8/6.9).

`experiments/_sweep_cache_etf/audit_steps.pkl` is the out-of-sample step series the
journal compares live weeks against. Nothing tied it to the panel, the sector map, the
configuration or the code it came from, so a baseline could quietly outlive any of
them and the comparison would still print a percentile.

The key is a sha256 over four component hashes. Change any one of them and the
baseline is invalid and must be regenerated; `check_baseline()` says so instead of
letting the run compare against a stale artefact.

Pure: hashing files and dicts, no network, no pickle loading.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

KEY_SUFFIX = ".key.json"
#: files whose content defines the measurement, not merely how it is displayed
DEFAULT_CODE_FILES = (
    "config.py",
    "core/signals.py",
    "core/meta_layer.py",
    "core/regime.py",
    "core/filters.py",
    "core/portfolio_engine.py",
    "core/tranche_book.py",
    "experiments/redesign_lab.py",
    "experiments/sleeve_lab.py",
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_json(obj) -> str:
    return sha256_text(json.dumps(obj, sort_keys=True, default=str, separators=(",", ":")))


def sha256_file(path) -> str | None:
    p = Path(path)
    if not p.exists():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()


def code_hash(root, files=DEFAULT_CODE_FILES) -> dict:
    """{file: sha256} plus a combined digest over the whole set.

    A missing file is recorded as None rather than skipped, so deleting a module
    invalidates the baseline instead of silently shrinking the fingerprint.
    """
    root = Path(root)
    per_file = {str(f): sha256_file(root / f) for f in files}
    return {"files": per_file, "combined": sha256_json(per_file)}


def frame_hash(frame) -> str | None:
    """A content hash for a panel or price frame: shape, index ends, and the values.

    Uses pandas' own row hashing so it is stable across runs and does not depend on
    float formatting.
    """
    if frame is None or getattr(frame, "empty", True):
        return None
    import numpy as np
    import pandas as pd
    from pandas.util import hash_pandas_object

    try:
        # .values is ndarray | ExtensionArray; only the former has tobytes()
        rows = np.asarray(hash_pandas_object(frame, index=True))
        payload = {
            "shape": list(frame.shape),
            "columns": [str(c) for c in frame.columns],
            "first": str(pd.Timestamp(frame.index[0])),
            "last": str(pd.Timestamp(frame.index[-1])),
            "rows_sha256": hashlib.sha256(rows.tobytes()).hexdigest(),
        }
    except (TypeError, ValueError):
        payload = {"shape": list(getattr(frame, "shape", ())),
                   "repr_sha256": sha256_text(repr(frame))}
    return sha256_json(payload)


def baseline_key(*, panel_sha: str | None, sector_sha: str | None,
                 config_sha: str | None, code_sha: str | None) -> str:
    """The single identity of an audited baseline (phase 6.8)."""
    return sha256_json({
        "panel": panel_sha,
        "sector_map": sector_sha,
        "config": config_sha,
        "code": code_sha,
    })


def key_path(artefact) -> Path:
    return Path(str(artefact) + KEY_SUFFIX)


def write_baseline_key(artefact, *, panel_sha=None, sector_sha=None,
                       config_sha=None, code_sha=None, note: str | None = None) -> Path:
    """Record the key next to the artefact. Called when the baseline is generated."""
    components = {"panel": panel_sha, "sector_map": sector_sha,
                  "config": config_sha, "code": code_sha}
    payload = {
        "artefact": Path(artefact).name,
        "artefact_sha256": sha256_file(artefact),
        "key": baseline_key(panel_sha=panel_sha, sector_sha=sector_sha,
                            config_sha=config_sha, code_sha=code_sha),
        "components": components,
        "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": note,
    }
    path = key_path(artefact)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def read_baseline_key(artefact) -> dict | None:
    path = key_path(artefact)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def check_baseline(artefact, *, panel_sha=None, sector_sha=None,
                   config_sha=None, code_sha=None) -> dict:
    """Is this baseline still valid for these inputs? (phase 6.9)

    Returns {"valid", "reason", "expected", "recorded", "changed"}. An unkeyed
    artefact is *not* valid: it may predate the binding, and that is exactly the case
    where a stale comparison goes unnoticed.
    """
    artefact = Path(artefact)
    expected = baseline_key(panel_sha=panel_sha, sector_sha=sector_sha,
                            config_sha=config_sha, code_sha=code_sha)
    if not artefact.exists():
        return {"valid": False, "reason": f"baseline artefact missing: {artefact}",
                "expected": expected, "recorded": None, "changed": []}
    recorded = read_baseline_key(artefact)
    if recorded is None:
        return {"valid": False,
                "reason": (f"{artefact.name} carries no {KEY_SUFFIX} sidecar; it cannot be "
                           f"tied to a panel, sector map, config or code version — regenerate it"),
                "expected": expected, "recorded": None, "changed": []}
    if recorded.get("key") == expected:
        return {"valid": True, "reason": "baseline key matches",
                "expected": expected, "recorded": recorded, "changed": []}
    have = recorded.get("components") or {}
    want = {"panel": panel_sha, "sector_map": sector_sha, "config": config_sha, "code": code_sha}
    changed = sorted(k for k in want if have.get(k) != want[k])
    return {
        "valid": False,
        "reason": (f"baseline is stale: {', '.join(changed) or 'key'} changed since it was "
                   f"generated — regenerate it before comparing"),
        "expected": expected,
        "recorded": recorded,
        "changed": changed,
    }
