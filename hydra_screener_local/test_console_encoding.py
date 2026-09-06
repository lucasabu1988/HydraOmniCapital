"""TASK-380 — every entry-point script reconfigures stdout for cp1252 consoles."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKIP_PARTS = {"__pycache__", "data_cache", "_lab_scratch"}
SKIP_NAMES = {"_inject_reconfigure.py", "_scan_cp1252.py"}


def _entry_points():
    out = []
    for p in ROOT.rglob("*.py"):
        if any(s in p.parts for s in SKIP_PARTS) or p.name in SKIP_NAMES:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if 'if __name__ == "__main__"' not in text and "if __name__ == '__main__'" not in text:
            continue
        out.append(p)
    return out


def test_every_entrypoint_reconfigures_stdout():
    missing = []
    for p in _entry_points():
        text = p.read_text(encoding="utf-8", errors="replace")
        if "reconfigure" not in text:
            missing.append(str(p.relative_to(ROOT)))
    assert missing == [], f"entry points missing stdout.reconfigure: {missing}"
