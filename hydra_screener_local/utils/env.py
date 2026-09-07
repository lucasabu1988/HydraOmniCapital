"""
Centralized environment loader for HYDRA project.

Supports .env file (with or without python-dotenv) so that webhook config,
feature flags, etc. "just work" without having to export vars in every shell session.

Usage (in any main script):
    from utils.env import load_hydra_env
    load_hydra_env()

Safe to call multiple times. Does not override already-set environment variables.
"""

import os
from pathlib import Path
from typing import Optional


def load_hydra_env(env_path: Optional[Path] = None) -> int:
    """
    Load variables from .env into os.environ.

    - Prefers python-dotenv if installed (for advanced .env features).
    - Falls back to a tiny pure-Python parser (KEY=val, ignores # comments and blanks).
    - Never overrides existing env vars (shell wins).

    Returns: approximate number of variables loaded (0 if no .env or error).
    """
    if env_path is None:
        env_path = Path(".env")

    if not env_path.exists():
        # Also try relative to project root if called from subdir
        alt = Path(__file__).parent.parent / ".env"
        if alt.exists():
            env_path = alt
        else:
            return 0

    loaded = 0
    try:
        from dotenv import load_dotenv
        # override=False means don't clobber existing env
        load_dotenv(dotenv_path=str(env_path), override=False)
        return 1  # we don't have exact count from dotenv easily
    except Exception:
        pass  # fall through to pure parser

    # Minimal parser (good enough for URLs, tokens, simple strings)
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
                loaded += 1
        return loaded
    except Exception as e:
        # Don't crash the whole program just because .env is weird
        print(f"[WARN] Could not load .env ({env_path}): {e}")
        return 0
