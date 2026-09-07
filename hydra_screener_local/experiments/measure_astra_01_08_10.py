"""Read-only reproduction of Astra findings 01 / 08 / 10 on synthetic fixtures.

Writes nothing: no state/, no data_cache/, no history/, no network. Every number quoted in
`.comms/astra-prereg-01-08-10.md` under "measured here" comes from this script, so the numbers
in the pre-registration can be re-derived in any fresh worktree:

    cd hydra_screener_local && python experiments/measure_astra_01_08_10.py

It measures the CURRENT behaviour (the defect), not a proposed fix. The three fixes are scoring /
accounting-policy / selection changes and wait for Lucas's approval (GROKBOARD rule 6).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import portfolio_engine as E  # noqa: E402
from core.signals import generate_daily_candidates  # noqa: E402


# --------------------------------------------------------------------------- fixtures
def astra01_ranking() -> pd.DataFrame:
    """Astra's fixture: 60 names, +0.2%/bar drift, then the last ten bars down 30%."""
    idx = pd.bdate_range("2025-01-01", periods=300)
    t = np.arange(300)
    prices = pd.DataFrame(
        {f"A{i}": 30 * np.exp(0.002 * t + 0.02 * np.sin(t * 0.8 + i)) for i in range(60)}, index=idx
    )
    prices.iloc[-10:] *= 0.7
    spy = pd.Series(100 * np.exp(0.001 * t), index=idx)
    vol = pd.DataFrame(1_000_000.0, index=idx, columns=prices.columns)
    ranking = generate_daily_candidates(
        prices, spy, vol, sector_map={x: "Other" for x in prices}, momentum_window="mom12_7"
    )
    return ranking, prices


def owned_state() -> dict:
    """One filled 10-unit position at 20.00 in tranche 0, run date 2026-09-11."""
    s = E.new_state(8000, "2026-09-04")
    s["last_run_date"] = "2026-09-11"
    tr = s["sleeves"]["stocks"]["tranches"][0]
    tr.update(units={"AAA": 10.0}, last_px={"AAA": 20.0}, cash=800.0)
    s["ledger"] = [
        dict(
            exec_date="2026-09-08", sleeve="stocks", tranche=0, ticker="AAA", side="buy",
            units=10.0, price=20.0, dollars=200.0, cost=0.0, status="filled",
        )
    ]
    return s


# --------------------------------------------------------------------------- measurements
def measure_01() -> dict:
    ranking, prices = astra01_ranking()
    targets = E.stock_targets(ranking, set(), prices)
    reasons = ranking["reason"].astype(str)
    return {
        "recommended_true": int(ranking["recommended"].sum()),
        "recommended_count": int(ranking["recommended_count"].iloc[0]),
        "n_targets": int(len(targets)),
        "sum_weights": round(float(targets.sum()), 6),
        "max_weight": round(float(targets.max()), 6) if len(targets) else None,
        "reasons_startswith_vetado": int(reasons.str.startswith("Vetado").sum()),
        "reason_counts": {k: int(v) for k, v in reasons.value_counts().items()},
    }


def measure_01_partial() -> dict:
    """Not the degenerate case: only the top-ranked half of the universe is shocked, so the veto
    bites part of the list. Question: are the slots the veto opened refilled with names that were
    never `recommended`?"""
    idx = pd.bdate_range("2025-01-01", periods=300)
    t = np.arange(300)
    prices = pd.DataFrame(
        {f"A{i}": 30 * np.exp((0.004 - 0.00008 * i) * t + 0.02 * np.sin(t * 0.8 + i)) for i in range(60)},
        index=idx,
    )
    shocked = [f"A{i}" for i in range(15)]          # the strongest 12-7 names get the late drop
    prices.loc[prices.index[-10:], shocked] *= 0.75
    spy = pd.Series(100 * np.exp(0.001 * t), index=idx)
    vol = pd.DataFrame(1_000_000.0, index=idx, columns=prices.columns)
    ranking = generate_daily_candidates(
        prices, spy, vol, sector_map={x: "Other" for x in prices}, momentum_window="mom12_7"
    )
    n_dyn = int(ranking["recommended_count"].iloc[0])
    rec = set(ranking.loc[ranking["recommended"], "ticker"])
    targets = E.stock_targets(ranking, set(), prices)
    picked = list(targets.index)
    extra = sorted(set(picked) - rec)
    rows = ranking[ranking["ticker"].isin(extra)]
    # would the downtrend gate (config GATE_MIN_RET_SHORT_PCT=-5.0, GATE_MAX_DIST_TO_HIGH_PCT=-8.0)
    # have vetoed these names had they ever carried the `recommended` flag?
    detail = [
        {
            "ticker": r.ticker, "rank": int(r["rank"]), "reason": r.reason,
            "ret_10d_pct": round(float(r.ret_5d_10d), 2),
            "dist_20d_high_pct": round(float(r.dist_20d_high), 2),
            "gate_would_veto": bool(
                r.ret_5d_10d < 0 and (r.dist_20d_high < -8.0 or r.ret_5d_10d < -5.0)
            ),
        }
        for _, r in rows.iterrows()
    ]
    return {
        "recommended_true": len(rec),
        "recommended_count": n_dyn,
        "n_targets": len(picked),
        "picked_not_recommended": extra,
        "n_picked_not_recommended": len(extra),
        "picked_not_recommended_detail": detail,
        "n_picked_the_gate_would_have_vetoed": sum(d["gate_would_veto"] for d in detail),
    }


def measure_08() -> dict:
    s = owned_state()
    tr0 = s["sleeves"]["stocks"]["tranches"][0]
    cash_before = float(tr0["cash"])
    for _ in range(10):
        E.mark(s, pd.Series({"AAA": np.nan}), pd.Series(dtype=float))
    tr = s["sleeves"]["stocks"]["tranches"][0]
    return {
        "marks": 10,
        "distinct_dates": 1,
        "units_after": tr["units"].get("AAA"),
        "cash_before": cash_before,
        "cash_after": float(tr["cash"]),
        "cash_minted": round(float(tr["cash"]) - cash_before, 6),
        "write_offs": s["write_offs"],
        "write_off_dates": sorted({w.get("date") for w in s["write_offs"]}),
    }


def measure_10() -> dict:
    ranking = pd.DataFrame(
        {
            "ticker": [f"A{i}" for i in range(10)],
            "rank": range(1, 11),
            "sector": ["Technology"] * 6 + ["Energy"] * 4,
            "reason": ["ok"] * 10,
        }
    )
    picked = E.select_tranche_names(ranking, 10, {f"A{i}" for i in range(6)}, 2.0, 5)
    counts: dict = {}
    sectors = dict(zip(ranking["ticker"], ranking["sector"]))
    for name in picked:
        counts[sectors[name]] = counts.get(sectors[name], 0) + 1
    # the concentration a clamped tranche actually carries: n=6 is the floor of dynamic_count
    return {
        "picked": picked,
        "sector_counts": counts,
        "cap": 5,
        "technology_over_cap": max(0, counts.get("Technology", 0) - 5),
        "share_of_tranche_at_n6_for_5_names": round(5 / 6, 4),
        "share_of_tranche_at_n28_for_5_names": round(5 / 28, 4),
    }


def measure_10_overfill() -> dict:
    """Second effect of the same unguarded first loop: with buffer=2.0 the keep zone is the top
    2n, so MORE than n held names can be kept before the fill loop runs. `picked[:n]` truncates
    by rank afterwards, but `counts` was already charged for the names that get truncated away."""
    n = 6                                            # the clamp floor of dynamic_count
    ranking = pd.DataFrame(
        {
            "ticker": [f"A{i}" for i in range(12)],
            "rank": range(1, 13),
            "sector": ["Technology"] * 8 + ["Energy"] * 4,
            "reason": ["ok"] * 12,
        }
    )
    held = {f"A{i}" for i in range(8)}               # 8 holdings, all inside the top 2n = 12
    picked = E.select_tranche_names(ranking, n, held, 2.0, 5)
    sectors = dict(zip(ranking["ticker"], ranking["sector"]))
    counts: dict = {}
    for name in picked:
        counts[sectors[name]] = counts.get(sectors[name], 0) + 1
    return {"n": n, "held": sorted(held), "picked": picked, "sector_counts": counts,
            "cap": 5, "technology_over_cap": max(0, counts.get("Technology", 0) - 5)}


def main() -> int:
    out = {
        "ASTRA-01": measure_01(),
        "ASTRA-01-partial": measure_01_partial(),
        "ASTRA-08": measure_08(),
        "ASTRA-10": measure_10(),
        "ASTRA-10-overfill": measure_10_overfill(),
    }
    print(json.dumps(out, indent=2, default=str))
    a1, a8, a10 = out["ASTRA-01"], out["ASTRA-08"], out["ASTRA-10"]
    print(
        f"\nASTRA-01  recommended={a1['recommended_true']}  dynamic_count={a1['recommended_count']}"
        f"  positive_targets={a1['n_targets']}  gross_exposure={a1['sum_weights']}"
    )
    print(
        f"ASTRA-08  10 marks / 1 date -> units {a8['units_after']}  cash "
        f"{a8['cash_before']} -> {a8['cash_after']} (+{a8['cash_minted']})"
    )
    print(
        f"ASTRA-10  cap=5 -> Technology={a10['sector_counts'].get('Technology')} "
        f"(over cap by {a10['technology_over_cap']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
