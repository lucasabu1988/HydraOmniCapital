"""Dependency-free secret sweep over the tracked tree (audit phase 10.6).

    python tools/check_secrets.py [--root .]

Gitleaks is the thorough scanner and runs first in CI; this is the fallback so the
gate still means something when the action is unavailable, and it catches the
project-specific mistake: committing a real `.env` next to `.env.example`.

Exit 0 = clean. Scans tracked text files only, skips caches and archives.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

SKIP_DIRS = {".git", "__pycache__", "data_cache", "node_modules", ".ruff_cache",
             ".pytest_cache", "archive", "build", "dist", "history", "runs"}
TEXT_SUFFIXES = {".py", ".toml", ".cfg", ".ini", ".txt", ".md", ".json", ".yml",
                 ".yaml", ".cmd", ".bat", ".sh", ".xml", ".env", ".pine", ".csv"}
#: files whose whole point is to show the *shape* of a secret
ALLOWLIST_NAMES = {".env.example", "check_secrets.py", "test_packaging.py", "SECURITY.md"}

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{24,}")),
    ("slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("discord webhook", re.compile(r"https://discord(?:app)?\.com/api/webhooks/\d+/[\w-]{20,}")),
    ("telegram bot token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b")),
    ("assigned credential", re.compile(
        r"(?i)\b(api[_-]?key|api[_-]?secret|secret[_-]?key|access[_-]?token|"
        r"auth[_-]?token|password|passwd|client[_-]?secret)\s*[:=]\s*"
        r"['\"][^'\"\s{}$<>]{12,}['\"]")),
]
#: a match that is obviously a placeholder rather than a credential
PLACEHOLDER = re.compile(
    r"(?i)(your[_-]?|example|placeholder|changeme|xxx+|\.\.\.|<[^>]+>|\$\{|"
    r"redacted|dummy|sample|fake|token_here|insert)")


def tracked_files(root: Path) -> list[Path]:
    """Git-tracked files, or a filesystem walk when git is unavailable."""
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=str(root),
                             capture_output=True, text=True, timeout=120)
        if out.returncode == 0 and out.stdout:
            return [root / p for p in out.stdout.split("\0") if p]
    except (OSError, subprocess.SubprocessError):
        pass
    return [p for p in root.rglob("*") if p.is_file()]


def scan(root: Path) -> list[str]:
    findings: list[str] = []
    for path in tracked_files(root):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in ALLOWLIST_NAMES:
            continue
        if path.suffix and path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(root)
        for label, rx in PATTERNS:
            for m in rx.finditer(text):
                snippet = m.group(0)[:60]
                if PLACEHOLDER.search(snippet):
                    continue
                line = text[:m.start()].count("\n") + 1
                findings.append(f"{rel}:{line}: {label}: {snippet}")
    return findings


def env_files(root: Path) -> list[str]:
    """A real `.env` must never be tracked, however harmless it looks."""
    out = []
    for path in tracked_files(root):
        if path.name == ".env" or (path.name.startswith(".env.")
                                   and not path.name.endswith(".example")):
            out.append(str(path.relative_to(root)))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="secret sweep")
    ap.add_argument("--root", type=str, default=str(REPO_ROOT))
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()

    tracked_env = env_files(root)
    findings = scan(root)

    print(f"secret sweep: {root}")
    for name in tracked_env:
        print(f"  TRACKED ENV FILE  {name}")
    for f in findings:
        print(f"  MATCH  {f}")

    if tracked_env or findings:
        print(f"secret sweep FAILED: {len(tracked_env)} env file(s), {len(findings)} match(es)")
        return 1
    print("secret sweep ok: no credential-shaped literal, no tracked .env")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
