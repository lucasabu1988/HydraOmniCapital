"""TASK-373 — characterisation golden for the v9 engine. Engine not edited."""
from __future__ import annotations

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
