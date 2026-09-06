"""TASK-365 — portfolio registry (`portfolios.toml`).

`resolve("default")` reproduces today's book exactly: `state/`, `journal/`, `config.V9` unchanged.
Other names get their own state/journal directories and a cfg = deep-merge(V9, overrides). The
engine already takes `cfg`; nothing here touches scoring. Pure: reads one TOML file, no network.
"""
from __future__ import annotations

import copy
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from config import V9

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_FILE = ROOT / "portfolios.toml"
DEFAULT_NAME = "default"


class PortfolioError(Exception):
    """Unknown or disabled portfolio, or a bad registry file."""


@dataclass(frozen=True)
class Portfolio:
    name: str
    label: str
    enabled: bool
    state_dir: Path
    journal_dir: Path
    capital: float
    cfg: dict = field(repr=False)

    @property
    def is_default(self) -> bool:
        return self.name == DEFAULT_NAME

    @property
    def backup_subdir(self) -> str:
        """Where the off-disk backup lands: today's path for default, a sub-folder otherwise."""
        return "state_v9" if self.is_default else f"state_v9/{self.name}"


def deep_merge(base: dict, overrides: dict | None) -> dict:
    out = copy.deepcopy(base)
    for k, v in (overrides or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_registry(path: str | Path | None = None) -> dict:
    """{name: raw table}. A missing file yields the implicit default only."""
    p = Path(path) if path is not None else REGISTRY_FILE
    if not p.exists():
        return {DEFAULT_NAME: {}}
    try:
        with p.open("rb") as f:
            raw = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise PortfolioError(f"portfolios registry unreadable: {p}: {e}") from e
    if not isinstance(raw, dict):
        raise PortfolioError(f"portfolios registry is not a table: {p}")
    if DEFAULT_NAME not in raw:
        raw[DEFAULT_NAME] = {}
    return raw


def _build(name: str, table: dict, root: Path) -> Portfolio:
    if not isinstance(table, dict):
        raise PortfolioError(f"portfolio [{name}] is not a table")
    is_default = name == DEFAULT_NAME
    state_dir = table.get("state_dir") or ("state" if is_default else f"state_{name}")
    journal_dir = table.get("journal_dir") or ("journal" if is_default else f"journal/{name}")
    overrides = table.get("overrides") or {}
    if not isinstance(overrides, dict):
        raise PortfolioError(f"portfolio [{name}].overrides is not a table")
    if is_default and overrides:
        # the live book is config.V9 by definition; a default override would silently change production
        raise PortfolioError("portfolio [default] must not carry overrides; edit config.V9 with rule-6 approval")
    cfg = deep_merge(V9, overrides)
    return Portfolio(
        name=name,
        label=str(table.get("label") or name),
        enabled=bool(table.get("enabled", is_default)),
        state_dir=(root / state_dir).resolve() if not Path(state_dir).is_absolute() else Path(state_dir),
        journal_dir=(root / journal_dir).resolve() if not Path(journal_dir).is_absolute() else Path(journal_dir),
        capital=float(table.get("capital_reference", 100000.0)),
        cfg=cfg,
    )


def resolve(name: str | None = None, *, allow_disabled: bool = False,
            registry_path: str | Path | None = None, root: Path | None = None) -> Portfolio:
    name = str(name or DEFAULT_NAME)
    reg = load_registry(registry_path)
    if name not in reg:
        raise PortfolioError(f"unknown portfolio {name!r}; known: {', '.join(sorted(reg))}")
    pf = _build(name, reg[name], root or ROOT)
    if not pf.enabled and not allow_disabled:
        raise PortfolioError(f"portfolio {name!r} is disabled in portfolios.toml (pass --allow-disabled to run it)")
    return pf


def names(registry_path: str | Path | None = None) -> list[str]:
    return sorted(load_registry(registry_path))
