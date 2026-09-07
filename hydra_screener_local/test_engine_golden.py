"""TASK-373 — characterisation golden for the v9 engine. Engine not edited."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import V9  # noqa: E402
import core.portfolio_engine as E  # noqa: E402
from core.state_check import check  # noqa: E402

SEED = 373
N_STOCKS = 60
N_HIST = 260
N_WEEKS = 30
STEP = 5
DEAD = "S00"
GHOST = "S01"
FIXTURE = Path(__file__).parent / "test_fixtures" / "engine_golden_v9.json"
ATOL = 1e-9

# ASTRA-09: the golden is pinned by the sha256 of its *canonical* JSON (sorted keys, no spacing,
# so CRLF checkouts and re-indentation do not move it). Regenerating the fixture to make a test
# pass is the failure mode this pin exists to stop: if this hash moves, the run that moved it must
# be reported with the `_diff` output, not committed. A merge that starts persisting metadata in
# the state (config / mix / sleeve_registry / calendar) legitimately changes `final_state` — that
# is a deliberate re-pin with the diff quoted in the commit body, reviewed by a human.
GOLDEN_CANON_SHA256 = "95769e08f51b6cafe9f2beffa7dab63756f82d81e35d3fa00a97e00a546e0ef5"
GOLDEN_SHAPE = {"steps": 30, "transfers": 42, "interest": 58, "write_offs": 4}
# projections the golden must compare; "orders" alone is not a book
GOLDEN_PROJECTIONS = ("steps", "transfers", "interest", "write_offs", "final_state")


def _market():
    rng = np.random.default_rng(SEED)
    n_bars = N_HIST + N_WEEKS * STEP + 4
    idx = pd.bdate_range("2020-01-02", periods=n_bars)
    stocks = [f"S{i:02d}" for i in range(N_STOCKS)]
    rets = rng.normal(0.0004, 0.012, size=(n_bars, N_STOCKS))
    px = 50.0 * np.exp(np.cumsum(rets, axis=0))
    stock = pd.DataFrame(px, index=idx, columns=stocks)
    # DEAD stops printing at week 12 (bar N_HIST + 12*STEP)
    dead_from = N_HIST + 12 * STEP
    stock.loc[idx[dead_from]:, DEAD] = np.nan
    etfs = list(V9["etf_universe"])
    etf = pd.DataFrame(index=idx, columns=etfs, dtype=float)
    # Two regimes: first ~15 weeks of the live window all-on (strong 12m), then crash all-off.
    up = np.linspace(100.0, 160.0, n_bars)
    down_start = N_HIST + 15 * STEP
    crash = np.concatenate([
        np.linspace(100.0, 160.0, down_start),
        np.linspace(160.0, 70.0, n_bars - down_start),
    ])
    for i, name in enumerate(etfs):
        series = crash if i >= 5 else up  # TLT/IEF/GLD/DBC/VNQ crash; equity ETFs stay up
        noise = rng.normal(0, 0.15, n_bars)
        etf[name] = series + noise
        vol = rng.uniform(0.8, 1.2)
        etf[name] = etf[name] * vol
    irx = pd.Series(0.04, index=idx, name="^IRX")
    return idx, stock, etf, irx, stocks


def _ranking(week: int, stocks: list[str], n: int = 8) -> pd.DataFrame:
    # Rotate the ranked list every week so names enter and leave.
    rot = stocks[week % len(stocks):] + stocks[: week % len(stocks)]
    # Keep DEAD recommended for the first 12 weeks so it is held when prints stop.
    if week < 12 and DEAD in rot:
        rot = [DEAD] + [s for s in rot if s != DEAD]
    # Week 3: GHOST at the top so a buy is pending, then we NaN its settle bar.
    if week == 3:
        rot = [GHOST] + [s for s in rot if s != GHOST]
    return pd.DataFrame({
        "ticker": rot,
        "rank": range(1, len(rot) + 1),
        "sector": ["Other"] * len(rot),
        "reason": [""] * len(rot),
        "recommended_count": n,
        "recommended": [i < n for i in range(len(rot))],
    })


def _slim_order(o: dict) -> dict:
    keep = ("sleeve", "tranche", "ticker", "side", "dollars", "est_units", "est_price",
            "units", "price", "cost", "status", "close", "planned", "exec_date", "week")
    out = {k: o[k] for k in keep if k in o}
    return out


def drive():
    idx, stock, etf, irx, stocks = _market()
    cfg = dict(V9)
    start = N_HIST
    st = E.new_state(1000.0, str(idx[start].date()), cfg)
    steps = []
    prev_t = None
    ghost_settle = start + 3 * STEP + 1  # t+1 of week-3 plan
    stock = stock.copy()
    stock.iloc[ghost_settle, stock.columns.get_loc(GHOST)] = np.nan

    for week in range(N_WEEKS):
        t = start + week * STEP
        today = str(idx[t].date())
        fills = []
        if st.get("pending") and prev_t is not None:
            e = prev_t + 1
            fills = E.settle(st, str(idx[e].date()), stock.iloc[e], etf.iloc[e], cfg)
            E.mark(st, stock.iloc[e], etf.iloc[e], cfg)
        rk = _ranking(week, stocks)
        st, orders = E.plan(st, today, rk, stock.iloc[: t + 1], etf.iloc[: t + 1], irx.iloc[: t + 1], cfg)
        errors = [f for f in check(json.loads(json.dumps(st))) if f.level == "ERROR"]
        if errors:
            pytest.fail(f"state_check ERROR at {today}: {errors[0]}")
        steps.append({
            "week": week,
            "date": today,
            "orders": [_slim_order(o) for o in orders],
            "fills": [_slim_order(f) for f in fills],
        })
        prev_t = t

    if st.get("pending") and prev_t is not None:
        e = prev_t + 1
        if e < len(idx):
            fills = E.settle(st, str(idx[e].date()), stock.iloc[e], etf.iloc[e], cfg)
            steps[-1]["final_fills"] = [_slim_order(f) for f in fills]

    blob = {
        "seed": SEED,
        "n_weeks": N_WEEKS,
        "steps": steps,
        "transfers": list(st.get("transfers") or []),
        "interest": list(st.get("interest") or []),
        "write_offs": list(st.get("write_offs") or []),
        "final_state": json.loads(json.dumps(st)),
    }
    return blob, st


def _close(a, b, atol=ATOL) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if a is None or b is None:
            return a == b
        return abs(float(a) - float(b)) <= atol
    if type(a) is not type(b) and not (
        isinstance(a, (int, float)) and isinstance(b, (int, float))
    ):
        if isinstance(a, (int, float)) or isinstance(b, (int, float)):
            try:
                return abs(float(a) - float(b)) <= atol
            except (TypeError, ValueError):
                return False
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return False
        return all(_close(a[k], b[k], atol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        return all(_close(x, y, atol) for x, y in zip(a, b, strict=True))
    return a == b


def _diff(a, b, path="$") -> list[str]:
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{path}.{k} missing in actual")
            elif k not in b:
                out.append(f"{path}.{k} missing in fixture")
            else:
                out.extend(_diff(a[k], b[k], f"{path}.{k}"))
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path} len {len(a)} != {len(b)}")
            return out
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            out.extend(_diff(x, y, f"{path}[{i}]"))
        return out
    if not _close(a, b):
        out.append(f"{path}: {a!r} != {b!r}")
    return out


def test_engine_golden():
    blob, st = drive()
    n_wo = len(blob["write_offs"])
    n_nf = sum(1 for s in blob["steps"] for f in s.get("fills") or [] if f.get("status") == "not_filled")
    n_nf += sum(1 for f in blob["steps"][-1].get("final_fills") or [] if f.get("status") == "not_filled")
    assert n_wo >= 1, "golden market must force a write-off"
    assert n_nf >= 1, "golden market must force a not_filled"
    errors = [f for f in check(json.loads(json.dumps(st))) if f.level == "ERROR"]
    assert errors == [], errors

    regen = os.environ.get("HYDRA_REGEN_GOLDEN") == "1"
    if regen:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        old = json.loads(FIXTURE.read_text(encoding="utf-8")) if FIXTURE.exists() else None
        FIXTURE.write_text(json.dumps(blob, indent=2, default=str) + "\n", encoding="utf-8")
        if old is None:
            print("wrote new golden", FIXTURE)
        else:
            diffs = _diff(blob, old)
            print(f"regenerated {FIXTURE}; {len(diffs)} diff line(s)")
            for line in diffs[:30]:
                print(" ", line)
        return

    if not FIXTURE.exists():
        pytest.fail(f"golden missing: {FIXTURE} (set HYDRA_REGEN_GOLDEN=1 to create)")
    want = json.loads(FIXTURE.read_text(encoding="utf-8"))
    diffs = _diff(blob, want)
    assert diffs == [], "golden mismatch:\n" + "\n".join(diffs[:40])


# ------------------------------------------------------------------ ASTRA-09 merge invariants
def _canonical(blob: dict) -> str:
    return json.dumps(blob, sort_keys=True, separators=(",", ":"))


def _load_golden() -> dict:
    assert FIXTURE.exists(), f"golden missing: {FIXTURE}"
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_golden_fixture_is_pinned_and_was_not_regenerated():
    """The 50/50 golden is the contract, not a snapshot to be refreshed.

    Hashing the canonical JSON (not the bytes) so a CRLF checkout or a reformat is not a false
    alarm, and so a changed number is not hidden by one.
    """
    blob = _load_golden()
    got = hashlib.sha256(_canonical(blob).encode("utf-8")).hexdigest()
    assert got == GOLDEN_CANON_SHA256, (
        "the golden fixture changed. STOP and report it: run `python -m pytest test_engine_golden.py "
        "-q` to see the `_diff` lines, decide whether the engine change was intended, and only then "
        "re-pin GOLDEN_CANON_SHA256 in the same commit with the diff in the commit body. "
        f"expected {GOLDEN_CANON_SHA256}, got {got}")
    assert {k: len(blob[k]) for k in GOLDEN_SHAPE} == GOLDEN_SHAPE


def test_the_suite_never_regenerates_the_golden():
    """`HYDRA_REGEN_GOLDEN=1` makes test_engine_golden overwrite the fixture and pass.

    That is a deliberate, reviewed act; it must never happen inside a normal run, a CI job or an
    agent's acceptance gate. This test is the tripwire, so a regen run reports one failure by
    design.
    """
    assert os.environ.get("HYDRA_REGEN_GOLDEN") != "1", (
        "HYDRA_REGEN_GOLDEN=1 is set: this run rewrites the golden instead of checking it")


def test_the_golden_drives_the_5050_two_sleeve_engine():
    """What the fixture is a golden *of*: production's two sleeves at 50/50, four tranches."""
    cfg = dict(V9)
    assert cfg["mix"] == {"stocks": 0.5, "etf": 0.5}
    assert cfg["tranches"] == 4 and cfg["step_bars"] == 5
    assert list(E._sleeves(cfg)) == ["stocks", "etf"]
    blob = _load_golden()
    assert list(blob["final_state"]["sleeves"]) == ["stocks", "etf"]
    assert blob["final_state"]["capital_reference"] == 1000.0
    assert blob["seed"] == SEED and blob["n_weeks"] == N_WEEKS


def test_the_golden_compares_the_full_state_not_only_the_order_list():
    """Orders, fills, fees, transfers, interest, write-offs and the whole final state.

    Two engines can agree on every order and disagree on cash; the diff has to reach the book.
    """
    blob = _load_golden()
    assert set(GOLDEN_PROJECTIONS) <= set(blob)
    st = blob["final_state"]
    for key in ("sleeves", "ledger", "pending", "transfers", "interest", "write_offs",
                "week_index", "last_run_date", "last_renewal_date", "capital_reference"):
        assert key in st, key
    # fees are compared: every filled ledger row carries the cost it charged
    filled = [f for f in st["ledger"] if f.get("status") == "filled"]
    assert filled and all("cost" in f for f in filled)
    assert sum(float(f["cost"]) for f in filled) > 0.0
    # transfers are compared, and they net to zero across the whole run
    assert blob["transfers"]
    assert sum(float(t["dollars"]) for t in blob["transfers"]) == pytest.approx(0.0, abs=1e-9)
    # per-tranche cash and units are in the compared payload
    tr0 = st["sleeves"]["stocks"]["tranches"][0]
    assert {"cash", "units", "last_px", "stale", "opened"} <= set(tr0)


def _mutate_cash(b):
    b["final_state"]["sleeves"]["stocks"]["tranches"][0]["cash"] += 0.01


def _mutate_units(b):
    b["final_state"]["sleeves"]["etf"]["tranches"][1]["units"]["SPY"] = 1.0


def _mutate_fee(b):
    row = next(f for f in b["final_state"]["ledger"] if f.get("status") == "filled")
    row["cost"] = float(row["cost"]) + 0.001


def _mutate_transfer(b):
    b["transfers"][0]["dollars"] = float(b["transfers"][0]["dollars"]) + 0.01


def _mutate_interest(b):
    b["interest"][0]["dollars"] = float(b["interest"][0]["dollars"]) + 1e-6


def _mutate_week(b):
    b["final_state"]["week_index"] = 999


def _mutate_order(b):
    b["steps"][7]["orders"][0]["dollars"] = float(b["steps"][7]["orders"][0]["dollars"]) + 0.01


def _mutate_writeoff(b):
    b["write_offs"][0]["dollars"] = float(b["write_offs"][0].get("dollars") or 0.0) + 1.0


@pytest.mark.parametrize("mutate,expect", [
    (_mutate_cash, "cash"),
    (_mutate_units, "units"),
    (_mutate_fee, "cost"),
    (_mutate_transfer, "transfers"),
    (_mutate_interest, "interest"),
    (_mutate_week, "week_index"),
    (_mutate_order, "orders"),
    (_mutate_writeoff, "write_offs"),
])
def test_each_projection_of_the_golden_catches_its_own_divergence(mutate, expect):
    """A one-cent change anywhere in the compared payload must show up as a diff line.

    This guards the comparison itself: `_close`'s tolerance is 1e-9, and a golden that "passes"
    because the diff never looks at a field is the thing being ruled out here.
    """
    want = _load_golden()
    got = copy.deepcopy(want)
    mutate(got)
    diffs = _diff(got, want)
    assert diffs, f"a change to {expect} produced no diff line"
    assert any(expect in d for d in diffs), (expect, diffs[:5])


@pytest.mark.xfail(strict=True, reason=(
    "ASTRA-09: the n-sleeve state has no persisted calendar, so the golden cannot compare one. The "
    "hardening side records it (record_calendar / effective_calendar) and the renewal schedule "
    "depends on it — a merge that keeps N sleeves but drops the calendar leaves the week index at "
    "the mercy of the download length. When the merge lands, the golden must carry the calendar, "
    "the fixture is re-pinned deliberately, and this marker goes away."))
def test_the_golden_compares_the_persisted_calendar():
    blob = _load_golden()
    assert "calendar" in blob["final_state"]
    got = copy.deepcopy(blob)
    got["final_state"]["calendar"] = list(blob["final_state"]["calendar"])[:-1]
    assert any("calendar" in d for d in _diff(got, blob))
