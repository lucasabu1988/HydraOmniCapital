"""Paper book (2026-09-10): a second state directory that never shares the live book's off-disk
backup or journal, and a daily.py that can be pointed at it. No network."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import daily as daily_mod  # noqa: E402
import journal as J  # noqa: E402
import portfolio_v9 as V  # noqa: E402
from core.books import backup_folder, book_of, journal_dir_for, off_disk_dest  # noqa: E402
from test_portfolio_v9_cli import FakeEngine, _market, _rank  # noqa: E402


def test_book_names_follow_the_directory():
    assert book_of(Path("x/state")) is None
    assert book_of(Path("x/state_paper")) == "paper"
    assert book_of(Path("x/state_")) == "state_"          # a degenerate name is its own book, never the live one
    assert book_of(Path("x/sandbox")) == "sandbox"
    assert backup_folder(None) == "state_v9" and backup_folder("paper") == "state_v9_paper"
    assert journal_dir_for(None, "R") == Path("R/journal") and journal_dir_for("paper", "R") == Path("R/journal_paper")


def test_off_disk_dest_honours_the_env_and_the_book(monkeypatch, tmp_path):
    monkeypatch.delenv("HYDRA_BACKUP_DIR", raising=False)
    assert off_disk_dest("2026-09-10", None) is None
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path))
    assert off_disk_dest("2026-09-10", None) == tmp_path / "state_v9" / "20260910"
    assert off_disk_dest("2026-09-10", "paper") == tmp_path / "state_v9_paper" / "20260910"


def test_a_paper_run_backs_up_beside_the_live_book_never_inside_it(tmp_path, monkeypatch):
    dest = tmp_path / "off"
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(dest))
    V._OFFDISK_WARNED = False
    out = V.run(tmp_path / "state_paper", capital=50000.0, fetch_fn=_market, rank_fn=_rank,
                engine=FakeEngine(), silent=True)
    assert Path(out["state_path"]).parent.name == "state_paper"
    paper = dest / "state_v9_paper" / "20260904"
    assert (paper / "portfolio_v9.json").exists() and list(paper.glob("instructions_*.md"))
    assert not (dest / "state_v9").exists(), "the paper book must not write into the live book's backup folder"


def test_the_live_book_still_backs_up_where_it_always_did(tmp_path, monkeypatch):
    dest = tmp_path / "off"
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(dest))
    V._OFFDISK_WARNED = False
    V.run(tmp_path / "state", capital=100000.0, fetch_fn=_market, rank_fn=_rank, engine=FakeEngine(), silent=True)
    assert (dest / "state_v9" / "20260904" / "portfolio_v9.json").exists()
    assert not (dest / "state_v9_state").exists()


def test_the_journal_of_a_paper_run_lives_in_journal_paper_and_backs_up_beside_it(tmp_path, monkeypatch):
    dest = tmp_path / "off"
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(dest))
    monkeypatch.setattr(J, "DEFAULT_DIR", tmp_path / "journal")
    monkeypatch.setattr(J, "load_oos_step_returns", lambda: [])
    out = V.run(tmp_path / "state_paper", capital=50000.0, fetch_fn=_market, rank_fn=_rank,
                engine=FakeEngine(), silent=True)
    rev = J.append_from_v9(out, note="paper")
    assert Path(rev).parent == tmp_path / "journal_paper"
    assert list((dest / "state_v9_paper" / "20260904").glob("*.json"))
    assert not (tmp_path / "journal").exists() and not (dest / "state_v9").exists()
    err = J.append_error("boom", state_dir=str(tmp_path / "state_paper"), today="2026-09-05")
    assert Path(err).parent == tmp_path / "journal_paper"
    assert (dest / "state_v9_paper" / "20260905").exists()


def test_daily_passes_the_book_through_to_the_engine(monkeypatch):
    import config
    monkeypatch.setattr(config, "ALGO_VERSION", "v9")
    seen = {}
    monkeypatch.setattr(daily_mod, "run_screener", lambda universe: 0)
    monkeypatch.setattr(daily_mod, "backup_history_after_run", lambda: None)
    monkeypatch.setattr(daily_mod, "print_tv_instructions", lambda: None)
    monkeypatch.setattr("portfolio_v9.run", lambda *a, **k: seen.update(k))
    rc = daily_mod.main(["--skip-screener", "--state-dir", "state_paper", "--v9-capital", "50000"])
    assert rc == 0
    assert seen["state_dir"] == daily_mod.ROOT / "state_paper" and seen["capital"] == pytest.approx(50000.0)
    seen.clear()
    rc = daily_mod.main(["--skip-screener"])
    assert rc == 0 and "state_dir" not in seen, "without --state-dir the live book is untouched by this change"
