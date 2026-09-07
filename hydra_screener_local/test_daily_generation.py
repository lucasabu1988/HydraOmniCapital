"""TASK-395 — the daily run publishes ONE complete generation, or reports itself incomplete.

Defect 4 of the rejected branch was an ordering defect: `finalize_journal` called
`append_from_v9` first, which already copied the journal off disk through `save_record`'s ambient
env read; `copy_state_off_disk` had already copied the state; the protected copy and the
verification ran afterwards. A later rejection could not undo what had been overwritten.

Here nothing leaves the local disk until every role of the run exists, and then the whole set is
published in one indivisible operation under one run_id. These tests drive `daily.main` end to
end with a fake market and assert on the generation, on the run_status marker, and on the exit
code — the run must not report success when the backup did not land.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import daily as daily_mod  # noqa: E402
import journal as J  # noqa: E402
import portfolio_v9 as V  # noqa: E402
from backup_service import verify_generation  # noqa: E402
from test_portfolio_v9_cli import FakeEngine, _market, _rank  # noqa: E402


def _wire(monkeypatch, tmp_path, *, authorise=True, backup_dir=None):
    """A daily run whose screener, prints and PnL refresh are stubbed out, and whose v9 step
    writes into tmp_path. `authorise=False` is the 2026-09-06 shape: a fixture tree that the entry
    point never declared."""
    monkeypatch.setattr(daily_mod, "run_screener", lambda universe: 0)
    monkeypatch.setattr(daily_mod, "backup_history_after_run", lambda: None)
    monkeypatch.setattr(daily_mod, "print_tv_instructions", lambda: None)
    monkeypatch.setattr(daily_mod, "maybe_refresh_pnl", lambda x: None)
    monkeypatch.setattr(J, "DEFAULT_DIR", tmp_path / "journal")
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(backup_dir if backup_dir is not None
                                               else tmp_path / "off"))
    if authorise:
        monkeypatch.setattr(daily_mod, "live_source_roots", lambda: (tmp_path.resolve(),))

    real_run = V.run

    def fake_run(*a, **k):
        return real_run(tmp_path / "state", capital=100000.0, fetch_fn=_market, rank_fn=_rank,
                        engine=FakeEngine(), silent=True,
                        backup_context=k.get("backup_context"),
                        publish_backup=k.get("publish_backup", True))

    monkeypatch.setattr("portfolio_v9.run", fake_run)
    V._OFFDISK_WARNED = False


def _generations(root: Path) -> list[Path]:
    date_dir = root / "state_v9" / "20260904"
    if not date_dir.is_dir():
        return []
    return sorted(p for p in date_dir.iterdir() if p.is_dir())


def test_a_daily_run_publishes_one_generation_holding_every_role(tmp_path, monkeypatch):
    _wire(monkeypatch, tmp_path)
    rc = daily_mod.main(["--skip-screener", "--no-instructions", "--v9", "--note", "lucas note"])
    assert rc == 0

    gens = _generations(tmp_path / "off")
    assert len(gens) == 1, gens
    gen = gens[0]
    assert not any(f.level == "ERROR" for f in verify_generation(gen, require_profile="daily_v9"))
    names = sorted(p.name for p in gen.iterdir())
    assert "portfolio_v9.json" in names
    assert "instructions_20260904.md" in names and "instructions_20260904.json" in names
    assert "2026-09-04.json" in names and "JOURNAL.md" in names

    manifest = json.loads((gen / "backup_manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == gen.name
    assert {e["run_id"] for e in manifest["files"].values()} == {gen.name}, \
        "every role of one execution must carry that execution's run_id"

    status = json.loads((tmp_path / "state" / "run_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "complete"


def test_the_journal_is_in_the_same_generation_as_the_state(tmp_path, monkeypatch):
    """The journal is written AFTER the sheet, so the rejected branch could only add it by copying
    a second time into an existing directory. A generation is published whole instead: the journal
    record in the copy has to be byte-identical to the local one written by this same run."""
    _wire(monkeypatch, tmp_path)
    assert daily_mod.main(["--skip-screener", "--no-instructions", "--v9"]) == 0
    gen = _generations(tmp_path / "off")[0]
    local = (tmp_path / "journal" / "2026-09-04.json").read_bytes()
    assert (gen / "2026-09-04.json").read_bytes() == local
    local_state = (tmp_path / "state" / "portfolio_v9.json").read_bytes()
    assert (gen / "portfolio_v9.json").read_bytes() == local_state


def test_an_unauthorised_tree_makes_the_run_incomplete_and_publishes_nothing(tmp_path, monkeypatch):
    """The 2026-09-06 shape with the real destination configured: a fixture tree nobody declared.

    Before TASK-392 this wrote the fixture into `<HYDRA_BACKUP_DIR>/state_v9/20260904/`. Now the
    service refuses the sources, the destination stays untouched, and — this is the part the
    rejected branch got right and is worth keeping — the run reports itself INCOMPLETE and exits
    non-zero instead of finishing 0 on a printed warning.
    """
    _wire(monkeypatch, tmp_path, authorise=False)
    monkeypatch.setattr(daily_mod, "live_source_roots",
                        lambda: (Path(__file__).resolve().parent,))
    rc = daily_mod.main(["--skip-screener", "--no-instructions", "--v9"])
    assert rc == 1
    assert _generations(tmp_path / "off") == []
    status = json.loads((tmp_path / "state" / "run_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "incomplete"
    assert "SOURCE_NOT_AUTHORISED" in status["detail"]
    # the journal still landed locally: local persistence is not the backup's business
    assert (tmp_path / "journal" / "2026-09-04.json").exists()


def test_two_daily_runs_of_one_date_leave_two_intact_generations(tmp_path, monkeypatch):
    """A rerun may not update the state inside yesterday's copy while keeping its sheets."""
    _wire(monkeypatch, tmp_path)
    assert daily_mod.main(["--skip-screener", "--no-instructions", "--v9"]) == 0
    first = _generations(tmp_path / "off")[0]
    first_state = (first / "portfolio_v9.json").read_bytes()

    assert daily_mod.main(["--skip-screener", "--no-instructions", "--v9"]) == 0
    gens = _generations(tmp_path / "off")
    assert len(gens) == 2, gens
    for gen in gens:
        assert not any(f.level == "ERROR"
                       for f in verify_generation(gen, require_profile="daily_v9"))
    assert (first / "portfolio_v9.json").read_bytes() == first_state, \
        "the first generation was modified by the second run"


def test_without_a_configured_root_the_run_still_completes_but_says_so(tmp_path, monkeypatch,
                                                                      capsys):
    _wire(monkeypatch, tmp_path)
    monkeypatch.delenv("HYDRA_BACKUP_DIR", raising=False)
    rc = daily_mod.main(["--skip-screener", "--no-instructions", "--v9"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "HYDRA_BACKUP_DIR" in out
    status = json.loads((tmp_path / "state" / "run_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "complete"
    assert "HYDRA_BACKUP_DIR" in (status["detail"] or "")
