"""DOC-01: what `daily.py` returns, and which stage it blames.

The contract, reviewed rather than assumed. `portfolio_v9` runs even when the screener
failed, and that is INTENTIONAL: it consumes no screener artefact - `fetch_v9_market` calls
get_universe / fetch_prices_and_volume / fetch_spy / fetch_etf_closes / fetch_tbill itself
and `build_ranking` re-ranks - so a failed screener cannot hand it a stale or partial
ranking. The screener's own output is the parked Pine artefact.

What WAS wrong is the reporting. `exit_code` is the first failure's code, and the closing
line said "Screener exited with code N" for every one of them, so a v9 abort was announced
under the screener's name. These tests pin the code AND the attribution, with the screener
actually failing rather than stubbed to 0 - every existing test of `daily.main` stubs it to 0,
so this path had no coverage at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import daily  # noqa: E402


@pytest.fixture
def no_side_effects(monkeypatch):
    """Nothing here touches history, the journal, the network or a book.

    The journal stubs are not decoration. `daily.py`'s error paths call
    `journal.append_error`, which mkdirs the real `journal/` directory - the write barrier
    refused it while this file was being written, which is precisely what SAFE-04 armed it
    for. A test that exercises a failure path must own its destinations.
    """
    import journal
    monkeypatch.setattr(daily, "backup_history_after_run", lambda *a, **k: None)
    monkeypatch.setattr(daily, "print_tv_instructions", lambda *a, **k: None)
    monkeypatch.setattr(journal, "append_error", lambda *a, **k: None)
    monkeypatch.setattr(journal, "append_from_v9", lambda *a, **k: "(journal stubbed)")


def _main(monkeypatch, capsys, *, screener_rc, v9):
    monkeypatch.setattr(daily, "run_screener", lambda *a, **k: screener_rc)
    import portfolio_v9
    monkeypatch.setattr(portfolio_v9, "run", v9)
    rc = daily.main(["--no-instructions"])
    return rc, capsys.readouterr().out


def _ok_v9(**kw):
    return dict(today="2026-09-14", orders=[], fills=[], no_trades=True,
                state_path="", instructions_md="", run_id="r", run_status="committed")


# ------------------------------------------------------------------ the screener fails

def test_v9_still_runs_when_the_screener_fails(no_side_effects, monkeypatch, capsys):
    """Intentional, and the reason is data-flow: v9 fetches and ranks on its own."""
    ran = []
    rc, out = _main(monkeypatch, capsys, screener_rc=2,
                    v9=lambda **kw: (ran.append(1), _ok_v9())[1])
    assert ran == [1], "v9 must still run; it shares no artefact with the screener"
    assert rc == 2, "the screener's code is what the caller sees"


def test_a_failed_screener_is_reported_as_the_screener(no_side_effects, monkeypatch, capsys):
    rc, out = _main(monkeypatch, capsys, screener_rc=2, v9=lambda **kw: _ok_v9())
    assert rc == 2
    assert "The screener exited with code 2" in out


def test_a_failed_screener_does_not_back_up_history(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(daily, "backup_history_after_run", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(daily, "print_tv_instructions", lambda *a, **k: None)
    _main(monkeypatch, capsys, screener_rc=2, v9=lambda **kw: _ok_v9())
    assert calls == [], "history was zipped after a failed screener run"


# ------------------------------------------------------------------------- v9 fails

def test_a_v9_abort_is_reported_as_v9_and_not_as_the_screener(no_side_effects, monkeypatch,
                                                              capsys):
    """The misattribution this ticket is about."""
    def boom(**kw):
        raise SystemExit("preflight hard fail; pass --force to plan anyway")

    rc, out = _main(monkeypatch, capsys, screener_rc=0, v9=boom)
    assert rc == 1
    assert "v9 exited with code 1" in out
    assert "Screener exited" not in out, "a v9 abort was announced as a screener failure"


def test_a_v9_abort_says_the_book_was_not_advanced(no_side_effects, monkeypatch, capsys):
    """An operator reading the last line must not think the ritual half-ran."""
    def boom(**kw):
        raise SystemExit("preflight hard fail")

    rc, out = _main(monkeypatch, capsys, screener_rc=0, v9=boom)
    assert "the book was NOT advanced" in out


def test_an_unexpected_v9_exception_is_also_attributed_to_v9(no_side_effects, monkeypatch,
                                                             capsys):
    def boom(**kw):
        raise RuntimeError("something else entirely")

    rc, out = _main(monkeypatch, capsys, screener_rc=0, v9=boom)
    assert rc == 1
    assert "v9 exited with code 1" in out


def test_the_screeners_code_wins_when_both_fail(no_side_effects, monkeypatch, capsys):
    """First failure's code, and the stage named is the one that produced it."""
    def boom(**kw):
        raise SystemExit("v9 too")

    rc, out = _main(monkeypatch, capsys, screener_rc=3, v9=boom)
    assert rc == 3, "the screener failed first; its code is the one returned"
    assert "The screener exited with code 3" in out
    assert "the book was NOT advanced" not in out, (
        "that line is only true when the screener itself completed")


# ------------------------------------------------------------------------ nothing fails

def test_a_clean_run_returns_zero_and_blames_nobody(no_side_effects, monkeypatch, capsys):
    rc, out = _main(monkeypatch, capsys, screener_rc=0, v9=lambda **kw: _ok_v9())
    assert rc == 0
    assert "exited with code" not in out
    assert "Daily ritual complete" in out


# ------------------------------------------------------------- the drift is actually gone

def test_no_live_code_still_claims_v8_4_or_opt_in():
    for rel in ("portfolio_v9.py", "config.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "Production runs v8.4" not in src, f"{rel} still says production is v8.4"
        assert "ALGO_VERSION stays v8.4" not in src, f"{rel} still says v8.4"
        assert "this CLI is\nopt-in" not in src, f"{rel} still calls the v9 CLI opt-in"


def test_the_architecture_doc_stops_implying_the_flag_is_load_bearing():
    src = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "A production day (`python daily.py`)" in src
    assert "`--v9` is **redundant**" in src
    assert "independent" in src, "the doc must say the screener does not gate the plan"


def test_the_runbook_names_the_verified_backup_generation():
    src = (ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    assert "20260904_LIVE_VERIFIED" in src
    assert "DO_NOT_RESTORE.txt" in src, "the contaminated generations must be called out"
    assert "not broker fills" in src, "the scope of LIVE_VERIFIED must stay bounded"
