"""OPS4-01: `--force` states a reason and leaves a trace, and skips nothing new.

Before this, one boolean skipped every HARD preflight row - including the two reserved for a
state, cash, positions or ledger that cannot be trusted - and left NO record of having been
used. Not in the journal, not on the sheet, not in the state, not in a manifest. After the
fact a forced run could only be inferred from a SUCCESSFUL record whose `preflight.hard` was
true, and `daily.py` exposed the flag on the one command in the runbook.

Scope, deliberately narrow: this adds a required reason and a durable trace. It does NOT
widen what `--force` may skip, does not turn it on by default, and is not a way to resolve
stale data. The three guards outside its reach stay outside it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import daily  # noqa: E402
import portfolio_v9 as P9  # noqa: E402


def _pf(hard=True, rows=None):
    return dict(hard=hard, rows=rows if rows is not None else [
        dict(check="last bars", status="HARD", detail="stale"),
        dict(check="unfilled orders", status="HARD", detail="ASTRA-03"),
        dict(check="HYDRA_BACKUP_DIR", status="WARN", detail="unset"),
    ])


# ------------------------------------------------------------------ the reason is required

@pytest.mark.parametrize("reason", [None, "", "   ", "\t\n"])
def test_force_without_a_reason_is_refused(reason):
    """Empty, blank and whitespace-only are all "no reason"."""
    with pytest.raises(P9.ForceWithoutReason) as exc:
        P9.run(force=True, force_reason=reason, silent=True)
    assert "--force-reason" in str(exc.value)


def test_the_refusal_names_what_force_would_have_skipped():
    """An operator reading it must learn what the flag actually does."""
    with pytest.raises(P9.ForceWithoutReason) as exc:
        P9.run(force=True, force_reason=None, silent=True)
    msg = str(exc.value).lower()
    assert "every hard" in msg
    assert "ledger" in msg, "the message must name the checks reserved for untrusted state"


def test_the_refusal_happens_before_any_work():
    """The run's own data is untouched by a refused override: no fetch, no state read."""
    called = []
    with pytest.raises(P9.ForceWithoutReason):
        P9.run(force=True, force_reason=" ", silent=True,
               fetch_fn=lambda *a, **k: called.append("fetched"))
    assert called == [], "the provider was called before the override was validated"


# ------------------------------------------------------------------------- what is recorded

def test_the_record_names_the_overridden_checks_and_only_those():
    rec = P9.build_force_record(_pf(), "yahoo is late, prices verified by hand",
                                today="2026-09-14", book="live", run_id="run-1")
    assert rec["forced"] is True
    assert rec["reason"] == "yahoo is late, prices verified by hand"
    assert rec["overridden_hard_checks"] == ["last bars", "unfilled orders"]
    assert rec["n_overridden"] == 2, "a WARN row is not an override"
    assert rec["preflight_was_hard"] is True
    assert rec["book"] == "live"
    assert rec["date"] == "2026-09-14"
    assert rec["run_id"] == "run-1"
    assert rec["algo_version"] == P9.ALGO_VERSION


def test_the_record_carries_a_timestamp_and_whatever_identity_exists():
    rec = P9.build_force_record(_pf(), "because", today="2026-09-14", book=None, run_id=None)
    assert rec["at_utc"].endswith("+00:00"), "the stamp must be UTC and unambiguous"
    assert set(rec["by"]) == {"user", "host"}, "identity is recorded, never invented"
    assert rec["book"] == "live", "an unnamed book is the live one"


def test_the_reason_is_stored_stripped_but_not_reworded():
    rec = P9.build_force_record(_pf(), "  stale ETF bar, checked on the exchange  ",
                                today="2026-09-14", book="paper", run_id=None)
    assert rec["reason"] == "stale ETF bar, checked on the exchange"


def test_forcing_with_no_hard_row_is_still_recorded_as_forced():
    """The flag was used. That is a fact about the run even when it overrode nothing."""
    rec = P9.build_force_record(_pf(hard=False, rows=[]), "belt and braces",
                                today="2026-09-14", book="live", run_id=None)
    assert rec["forced"] is True
    assert rec["n_overridden"] == 0
    assert rec["preflight_was_hard"] is False


# ------------------------------------------------------------------ the trace is on the sheet

def _sheet(force_record):
    state = dict(capital_reference=100000.0, week_index=0, last_renewal_date="2026-09-04",
                 sleeves={}, pending=[], ledger=[])
    return P9.render_instructions("2026-09-14", [], [], {}, state, "2026-09-15",
                                  force_record=force_record)


def test_a_forced_sheet_says_so_at_the_top_with_its_reason():
    rec = P9.build_force_record(_pf(), "yahoo is late, prices verified by hand",
                                today="2026-09-14", book="live", run_id="r1")
    md = _sheet(rec)["md_text"]
    head = md.split("## ", 1)[0]
    assert "FORCED RUN" in head, "the warning must be above the first section, not buried"
    assert "yahoo is late, prices verified by hand" in head
    assert "last bars" in head and "unfilled orders" in head


def test_an_unforced_sheet_says_nothing_about_forcing():
    md = _sheet(None)["md_text"]
    assert "FORCED" not in md.upper()


def test_the_sheet_payload_carries_the_record_for_machines_too():
    rec = P9.build_force_record(_pf(), "checked by hand", today="2026-09-14",
                               book="live", run_id="r1")
    payload = _sheet(rec)["payload"]
    assert payload["force"]["reason"] == "checked by hand"
    assert payload["force"]["overridden_hard_checks"] == ["last bars", "unfilled orders"]
    assert _sheet(None)["payload"]["force"] is None


# ------------------------------------------------------ the operational entry point drops it

def test_daily_no_longer_exposes_force():
    """The one command in the runbook can no longer skip every gate with six characters."""
    parser = daily.build_parser() if hasattr(daily, "build_parser") else None
    src = (ROOT / "daily.py").read_text(encoding="utf-8")
    assert '"--force"' not in src, "daily.py still offers --force"
    assert '"force": args.force' not in src, "daily.py still forwards force"
    if parser is not None:
        with pytest.raises(SystemExit):
            parser.parse_args(["--force"])


def test_daily_says_why_the_flag_is_gone():
    src = (ROOT / "daily.py").read_text(encoding="utf-8")
    assert "OPS4-01" in src and "portfolio_v9.py directly" in src, (
        "removing a flag without saying why invites putting it back")


def test_portfolio_v9_cli_pairs_the_flag_with_the_reason():
    src = (ROOT / "portfolio_v9.py").read_text(encoding="utf-8")
    assert '"--force-reason"' in src
    assert "force_reason=args.force_reason" in src


# ----------------------------------------------------------------- nothing new is skippable

def test_force_did_not_become_a_key_that_opens_more_doors():
    """The guards outside --force must STAY outside it. Pinned, not assumed."""
    src = (ROOT / "portfolio_v9.py").read_text(encoding="utf-8")
    # the settle refusal has its own flag and is not reachable from --force
    assert "allow_intraday" in src
    for guard in ("raise_if_hard(pf, force=force)",):
        assert guard in src, f"{guard} must remain the ONLY force-aware gate"
    assert src.count("not force") <= 3, (
        "a new `not force` branch appeared: --force must not gain reach")


def test_the_journal_record_carries_the_force_block():
    src = (ROOT / "journal.py").read_text(encoding="utf-8")
    assert '"force": out.get("force")' in src, "a forced run must be visible in the journal"


def test_run_returns_the_record_so_every_consumer_can_see_it():
    src = (ROOT / "portfolio_v9.py").read_text(encoding="utf-8")
    assert "force=force_record," in src
