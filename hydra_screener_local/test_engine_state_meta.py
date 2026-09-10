"""Audit phase 8 — persisted engine config, dynamic sleeves, calendar, differential.

Reproductions R-801..R-805 in docs/AUDIT_REPRODUCTIONS.md. No network.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "experiments"))

import core.portfolio_engine as E  # noqa: E402
from config import V9  # noqa: E402
from core.state_check import check  # noqa: E402

STOCKS = ("AAA", "BBB", "CCC")


def _frames(n=301, start="2025-01-01"):
    idx = pd.bdate_range(start, periods=n)
    stocks = pd.DataFrame({t: np.linspace(10.0, 20.0, n) for t in STOCKS}, index=idx)
    etf = pd.DataFrame({t: np.linspace(50.0, 60.0, n) for t in V9["etf_universe"]}, index=idx)
    return stocks, etf, idx


def _ranking():
    return pd.DataFrame({
        "ticker": list(STOCKS), "rank": [1, 2, 3], "sector": ["Tech"] * 3,
        "recommended": [True] * 3, "reason": [""] * 3, "composite": [1.0, 0.9, 0.8],
    })


# ------------------------------------------------------------------ R-801 calendar
def test_r801_the_renewal_week_does_not_depend_on_the_download_length():
    """R-801 — phase 8.8, and the most consequential finding of this phase.

    `bars_between` counted rows of whatever index was handed in. Probed on the base
    commit with a 700-session calendar and an anchor at its start:

        full index (700 bars) -> bars_between 699 -> week 139 -> renewal_slot None
        trimmed to 500 bars   -> bars_between 500 -> week 100 -> renewal_slot (100, 0)

    So a renewal fired or did not, and a *different tranche* renewed, purely because
    of how many bars the last download returned.
    """
    full = pd.bdate_range("2023-01-02", periods=700)
    anchor, today = str(full[0].date()), str(full[-1].date())

    st = E.new_state(100000.0, anchor, V9)
    E.record_calendar(st, full)                      # the run that saw the full calendar
    st["week_index"] = 39
    with_full = E.renewal_slot(st, full, today, V9)
    with_trimmed = E.renewal_slot(st, full[-500:], today, V9)
    assert with_full == with_trimmed, "a shorter download must not move the schedule"

    # and the count itself is stable
    assert E.bars_between(E.effective_calendar(st, full[-500:]), anchor, today) == \
        E.bars_between(full, anchor, today)


@pytest.mark.parametrize("n", [700, 600, 500, 400, 300])
def test_r801_every_download_length_gives_the_same_week(n):
    full = pd.bdate_range("2023-01-02", periods=700)
    anchor, today = str(full[0].date()), str(full[-1].date())
    st = E.new_state(100000.0, anchor, V9)
    E.record_calendar(st, full)
    cal = E.effective_calendar(st, full[-n:])
    assert E.bars_between(cal, anchor, today) == 699


def test_the_calendar_is_append_only_and_sorted():
    st = E.new_state(100000.0, "2025-01-01", V9)
    a = pd.bdate_range("2025-01-01", periods=10)
    b = pd.bdate_range("2025-02-01", periods=10)
    E.record_calendar(st, b)
    E.record_calendar(st, a)
    cal = st["calendar"]
    assert cal == sorted(cal)
    assert len(cal) == 20
    E.record_calendar(st, a)                          # idempotent
    assert len(st["calendar"]) == 20


def test_plan_records_the_calendar_it_ran_on():
    stocks, etf, idx = _frames()
    st = E.new_state(100000.0, str(idx[0].date()), V9)
    assert st["calendar"] == []
    st, _ = E.plan(st, str(idx[-1].date()), _ranking(), stocks, etf, 0.04, V9)
    assert len(st["calendar"]) == len(idx)
    assert st["calendar"][0] == str(idx[0].date())
    assert st["calendar"][-1] == str(idx[-1].date())


def test_calendar_covers_anchor_reports_when_the_count_cannot_be_trusted():
    full = pd.bdate_range("2023-01-02", periods=700)
    st = E.new_state(100000.0, str(full[0].date()), V9)
    assert E.calendar_covers_anchor(st, full) is True
    assert E.calendar_covers_anchor(st, full[-100:]) is False, \
        "an index that starts after the anchor cannot be trusted on its own"
    E.record_calendar(st, full)
    assert E.calendar_covers_anchor(st, full[-100:]) is True, \
        "but the persisted calendar covers it"


def test_a_renewal_stays_idempotent_on_the_same_week():
    stocks, etf, idx = _frames()
    st = E.new_state(100000.0, str(idx[0].date()), V9)
    st, orders = E.plan(st, str(idx[-1].date()), _ranking(), stocks, etf, 0.04, V9)
    assert orders
    week = st["week_index"]
    assert E.renewal_slot(st, idx, str(idx[-1].date()), V9) is None, "already renewed"
    assert st["week_index"] == week


# ------------------------------------------------------------------ R-802 persisted config
def test_r802_the_state_persists_everything_phase_8_1_asks_for():
    """R-802 — phase 8.1."""
    st = E.new_state(100000.0, "2026-01-02", V9)
    for key in ("schema_version", "config", "config_sha256", "mix", "sleeve_registry",
                "registry_sha256", "calendar", "last_mark_date"):
        assert key in st, key
    assert st["schema_version"] == E.STATE_SCHEMA
    assert st["mix"] == {"stocks": 0.5, "etf": 0.5}
    assert st["config"]["step_bars"] == V9["step_bars"]
    assert st["config_sha256"] == E.config_hash(V9)
    assert st["sleeve_registry"]["stocks"]["cost_bp"] == pytest.approx(V9["stock_cost_bp"])
    assert st["sleeve_registry"]["etf"]["cost_bp"] == pytest.approx(V9["etf_cost_bp"])
    assert st["registry_sha256"]


def test_r802_a_replay_uses_the_configuration_persisted_with_that_run():
    """R-802 — phase 8.2: not whatever the process imported."""
    st = E.new_state(100000.0, "2026-01-02", V9)
    st["config"] = dict(V9, step_bars=7, tranches=3)
    got = E.effective_config(st)
    assert got["step_bars"] == 7
    assert got["tranches"] == 3
    # an explicit cfg still wins, because that is how the lab drives a sweep
    assert E.effective_config(st, V9)["step_bars"] == V9["step_bars"]
    # and a state without a persisted config falls back to the module default
    assert E.effective_config({})["step_bars"] == V9["step_bars"]


def test_r802_the_persisted_step_bars_drives_the_renewal():
    full = pd.bdate_range("2025-01-01", periods=100)
    st = E.new_state(100000.0, str(full[0].date()), V9)
    E.record_calendar(st, full)
    st["config"] = dict(V9, step_bars=99)
    # 99 sessions after the anchor is a renewal under the persisted config, not under V9
    assert E.renewal_slot(st, full, str(full[-1].date())) == (1, 1)
    assert E.renewal_slot(st, full, str(full[-1].date()), V9) is None


def test_the_config_hash_notices_a_changed_parameter():
    a = E.config_hash(V9)
    b = E.config_hash(dict(V9, step_bars=6))
    assert a != b


# ------------------------------------------------------------------ R-803 mix
@pytest.mark.parametrize("mix,expect", [
    ({"stocks": -0.5, "etf": 1.5}, "negative"),
    ({"stocks": 0.5, "etf": 0.4}, "not 1"),
    ({"stocks": float("nan"), "etf": 0.5}, "not finite"),
    ({"stocks": 1.0}, "absent from mix"),
    ({"stocks": 0.5, "etf": 0.4, "crypto": 0.1}, "no such sleeve"),
    ({}, "non-empty mapping"),
])
def test_r803_an_impossible_mix_is_refused(mix, expect):
    """R-803 — phase 8.3/8.4: weights finite, non-negative, complete, summing to 1."""
    problems = E.validate_mix(mix, ["stocks", "etf"])
    assert problems, mix
    assert any(expect in p for p in problems), problems


def test_a_valid_mix_passes_including_thirds():
    assert E.validate_mix({"stocks": 0.5, "etf": 0.5}, ["stocks", "etf"]) == []
    third = 1.0 / 3.0
    assert E.validate_mix({"a": third, "b": third, "c": third}, ["a", "b", "c"]) == []
    assert E.MIX_SUM_TOL > 0


def test_r803_new_state_refuses_an_invalid_mix():
    with pytest.raises(ValueError) as exc:
        E.new_state(100000.0, "2026-01-02", dict(V9, mix={"stocks": 0.7, "etf": 0.7}))
    assert "invalid mix" in str(exc.value)


def test_r804_omitting_a_sleeve_cannot_hide_its_capital():
    """R-804 — phase 8.4. The loops walked a module constant, so a sleeve the state
    held but the constant did not would simply never be valued."""
    st = E.new_state(100000.0, "2026-01-02", V9)
    st["sleeves"]["bonds"] = {"tranches": [
        {"k": i, "opened": None, "units": {}, "cash": 250.0, "last_px": {}, "stale": {}}
        for i in range(V9["tranches"])]}

    assert "bonds" in E.sleeve_names(st)
    px = pd.Series({t: 10.0 for t in STOCKS})
    pe = pd.Series({t: 50.0 for t in V9["etf_universe"]})
    summary = E.summary_table(st, px, pe, V9)
    assert "bonds" in summary["sleeves"], "the extra sleeve must be valued"
    assert summary["sleeves"]["bonds"]["cash"] == pytest.approx(1000.0)
    assert summary["total"] == pytest.approx(101000.0)
    assert sum(s["share"] for s in summary["sleeves"].values()) == pytest.approx(1.0)

    # and state_check names the mix that does not mention it
    st["last_run_date"] = "2026-01-02"
    assert "mix_missing_sleeve" in [f.code for f in check(st)]


def test_sleeve_names_prefers_the_state_over_the_module_constant():
    assert E.sleeve_names({"sleeves": {"a": {}, "b": {}}}) == ["a", "b"]
    assert E.sleeve_names({"mix": {"x": 1.0}}) == ["x"]
    assert E.sleeve_names(None) == list(E.DEFAULT_SLEEVES)


def test_the_sleeve_registry_reports_cost_and_weight():
    st = E.new_state(100000.0, "2026-01-02", V9)
    reg = E.sleeve_registry(st)
    assert set(reg) == {"stocks", "etf"}
    assert reg["stocks"]["weight"] == pytest.approx(0.5)
    assert reg["etf"]["cost_bp"] == pytest.approx(V9["etf_cost_bp"])


def test_sleeve_cost_bp_falls_back_predictably():
    assert E.sleeve_cost_bp("stocks", V9) == pytest.approx(V9["stock_cost_bp"])
    assert E.sleeve_cost_bp("etf", V9) == pytest.approx(V9["etf_cost_bp"])
    assert E.sleeve_cost_bp("bonds", V9) == pytest.approx(V9["stock_cost_bp"])
    assert E.sleeve_cost_bp("bonds", dict(V9, sleeve_cost_bp={"bonds": 3.0})) == pytest.approx(3.0)


# ------------------------------------------------------------------ 8.7 phases
def test_the_mark_date_is_recorded_separately_from_the_run_date():
    """Phase 8.7: daily execution, weekly mark and stale mark are distinct facts."""
    stocks, etf, idx = _frames()
    st = E.new_state(100000.0, str(idx[0].date()), V9)
    assert st["last_mark_date"] is None
    st, _ = E.plan(st, str(idx[-1].date()), _ranking(), stocks, etf, 0.04, V9)
    assert st["last_run_date"] == str(idx[-1].date())
    assert st["last_mark_date"] == str(idx[-1].date())
    assert st["last_renewal_date"] == str(idx[-1].date())


# ------------------------------------------------------------------ R-805 differential
def test_r805_the_differential_compares_cash_not_only_orders():
    """R-805 — phase 8.9/8.10. The driver compared orders and fills and returned 0
    as soon as those matched: two engines could agree on every order and disagree on
    cash, and the command printed IDENTICAL."""
    import engine_diff as D

    a = E.new_state(100000.0, "2026-01-02", V9)
    b = E.new_state(100000.0, "2026-01-02", V9)
    assert D.compare_states(a, b, where="fresh") == []

    b["sleeves"]["stocks"]["tranches"][0]["cash"] += 0.01
    problems = D.compare_states(a, b, where="after plan")
    assert problems, "a cash-only divergence must be caught"
    assert any("cash" in p for p in problems)
    assert any("state" in p for p in problems)


def test_r805_every_required_projection_is_compared():
    import engine_diff as D

    labels = [name for name, _ in D.PROJECTIONS]
    assert labels == ["cash", "positions", "tranches", "fees", "state"]


@pytest.mark.parametrize("mutate,expect", [
    (lambda s: s["sleeves"]["stocks"]["tranches"][0].__setitem__("cash", 1.0), "cash"),
    (lambda s: s["sleeves"]["stocks"]["tranches"][0]["units"].__setitem__("AAA", 5.0), "positions"),
    (lambda s: s["sleeves"]["stocks"]["tranches"][1].__setitem__("opened", "2026-01-09"), "tranches"),
    (lambda s: s["ledger"].append({"sleeve": "stocks", "status": "filled", "side": "buy",
                                   "ticker": "AAA", "units": 1.0, "price": 1.0, "cost": 0.25}), "fees"),
    (lambda s: s.__setitem__("week_index", 99), "state"),
])
def test_r805_each_projection_catches_its_own_divergence(mutate, expect):
    import engine_diff as D

    a = E.new_state(100000.0, "2026-01-02", V9)
    b = E.new_state(100000.0, "2026-01-02", V9)
    mutate(b)
    problems = D.compare_states(a, b, where="x")
    assert any(expect in p for p in problems), (expect, problems)


def test_r805_the_config_hash_of_two_checkouts_is_not_a_divergence():
    """Two trees legitimately differ in their config hash; the *book* must not."""
    import engine_diff as D

    a = E.new_state(100000.0, "2026-01-02", V9)
    b = E.new_state(100000.0, "2026-01-02", V9)
    b["config_sha256"] = "different-checkout"
    b["sleeve_registry"] = {"stocks": {"cost_bp": 10.0, "weight": 0.5}}
    assert D.compare_states(a, b, where="x") == []


def test_r805_first_difference_points_at_the_exact_path():
    import engine_diff as D

    hit = D.first_difference({"a": {"b": [1, 2, 3]}}, {"a": {"b": [1, 9, 3]}})
    assert hit == "$.a.b[1]: 2 vs 9"
    assert D.first_difference({"a": 1}, {"a": 1}) is None
    assert "delta" in D.first_difference({"a": 1.0}, {"a": 1.5})
    assert "missing on other" in D.first_difference({"a": 1, "b": 2}, {"a": 1})


def test_r805_a_float_inside_tolerance_is_not_a_divergence():
    import engine_diff as D

    a = E.new_state(100000.0, "2026-01-02", V9)
    b = E.new_state(100000.0, "2026-01-02", V9)
    b["sleeves"]["stocks"]["tranches"][0]["cash"] += 1e-13
    assert D.compare_states(a, b, where="x") == []
