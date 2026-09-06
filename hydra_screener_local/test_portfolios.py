"""TASK-365 — portfolio registry: default is byte-identical to no flag; overrides deep-merge; disabled refused."""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import portfolio_v9 as V  # noqa: E402
from config import V9  # noqa: E402
from core import portfolios as P  # noqa: E402
from test_portfolio_v9_cli import FakeEngine, _market, _rank  # noqa: E402


def test_registry_file_parses_and_default_matches_v9():
    reg = P.load_registry()
    assert "default" in reg and "paper_t20_only" in reg and "paper_half_size" in reg
    d = P.resolve("default")
    assert d.is_default and d.enabled
    assert d.cfg == V9                                   # the live book is config.V9, untouched
    assert d.state_dir == (P.ROOT / "state").resolve()
    assert d.journal_dir == (P.ROOT / "journal").resolve()
    assert d.capital == 100000.0 and d.backup_subdir == "state_v9"
    assert P.resolve(None).name == "default"


def test_overrides_deep_merge_only_the_named_book():
    pf = P.resolve("paper_t20_only", allow_disabled=True)
    assert pf.cfg["mix"] == {"stocks": 1.0, "etf": 0.0}
    assert pf.cfg["etf_universe"] == V9["etf_universe"] and pf.cfg["hold_bars"] == V9["hold_bars"]
    assert V9["mix"] == {"stocks": 0.5, "etf": 0.5}       # the global was not mutated
    assert pf.state_dir.name == "state_paper_t20_only" and pf.backup_subdir == "state_v9/paper_t20_only"
    half = P.resolve("paper_half_size", allow_disabled=True)
    assert half.capital == 50000.0 and half.cfg == V9


def test_disabled_and_unknown_are_refused():
    with pytest.raises(P.PortfolioError, match="disabled"):
        P.resolve("paper_t20_only")
    with pytest.raises(P.PortfolioError, match="unknown portfolio"):
        P.resolve("nope")


def test_default_may_not_carry_overrides(tmp_path):
    reg = tmp_path / "p.toml"
    reg.write_text('[default]\n[default.overrides]\nmix = { stocks = 0.6, etf = 0.4 }\n', encoding="utf-8")
    with pytest.raises(P.PortfolioError, match="must not carry overrides"):
        P.resolve("default", registry_path=reg)


def test_missing_registry_yields_implicit_default(tmp_path):
    pf = P.resolve("default", registry_path=tmp_path / "absent.toml", root=tmp_path)
    assert pf.cfg == V9 and pf.state_dir == (tmp_path / "state").resolve()


def _sheet_and_state(state_dir: Path):
    sheet = next(state_dir.glob("instructions_*.md")).read_text(encoding="utf-8")
    state = (state_dir / "portfolio_v9.json").read_text(encoding="utf-8")
    return sheet, state


def test_default_portfolio_is_byte_identical_to_no_flag(tmp_path):
    """The parity that matters: --portfolio default writes exactly what the old CLI writes."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    V.run(a, capital=100000.0, fetch_fn=_market, rank_fn=_rank, engine=FakeEngine(), silent=True)
    V.run(b, capital=100000.0, fetch_fn=_market, rank_fn=_rank, engine=FakeEngine(), silent=True,
          cfg=P.resolve("default").cfg)
    sa, ta = _sheet_and_state(a)
    sb, tb = _sheet_and_state(b)
    assert sa == sb and ta == tb


def test_named_book_uses_its_own_dir_cfg_and_capital(tmp_path, monkeypatch):
    reg = tmp_path / "p.toml"
    reg.write_text(
        '[default]\n'
        '[mini]\nenabled = true\nstate_dir = "state_mini"\njournal_dir = "journal/mini"\ncapital_reference = 25000.0\n'
        '[mini.overrides]\nmix = { stocks = 1.0, etf = 0.0 }\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(P, "REGISTRY_FILE", reg)
    monkeypatch.setattr(P, "ROOT", tmp_path)
    eng = FakeEngine()
    out = V.run(V.DEFAULT_STATE_DIR, fetch_fn=_market, rank_fn=_rank, engine=eng, silent=True, portfolio="mini")
    assert Path(out["state_path"]).parent == (tmp_path / "state_mini").resolve()
    assert out["portfolio"] == "mini" and out["journal_dir"] == str((tmp_path / "journal" / "mini").resolve())
    st = json.loads(Path(out["state_path"]).read_text(encoding="utf-8"))
    assert st["capital_reference"] == 25000.0
    assert not (V.DEFAULT_STATE_DIR / "instructions_2026-09-04.md").exists()   # the live dir was not touched


def test_offdisk_backup_subdir_for_named_books(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "bk"))
    f = tmp_path / "s.json"
    f.write_text("{}", encoding="utf-8")
    d1 = V.copy_state_off_disk("2026-09-04", [f], silent=True)
    d2 = V.copy_state_off_disk("2026-09-04", [f], silent=True, subdir="state_v9/mini")
    assert d1 == tmp_path / "bk" / "state_v9" / "20260904"
    assert d2 == tmp_path / "bk" / "state_v9" / "mini" / "20260904"
