"""TASK-438 - market impact overlay on the TASK-434 sidecars. IMPACT_MODELLED_NOT_MEASURED.

Pre-registered in `.comms/prereg-task-438-impact-2026-09-14.md` (sha256 on the board) BEFORE any
number existed. Every rule here is a line of that document; `test_impact.py` pins each with a
mutation. Nothing is driven: this is an overlay on the F1-proved fill sidecars of run
`20260914-cc34d9465892`, justified by TASK-433's measurement that turnover does not react to the
cost parameter (Russell stocks 10.776 -> 10.774 % per settle across 10 -> 50 bp).

The model, declared before anything was looked at:

    impact_bp(fill) = k * sigma_daily(ticker, t-1) * sqrt(participation(fill, C)) * 1e4

  * sigma_daily: std of close-to-close LOG returns over the previous SIGMA_WINDOW market bars ending
    at t-1 (the bar before the settle), on the panel's own index; full window or UNKNOWN. Read with
    the same previous-bar rule as ADV (`capacity.adv_prev_bar`) - one lookup rule in the repo.
  * participation: TASK-434's footprint participation at capital C, as a FRACTION (0.01 = 1 %);
    the fill inherits its footprint's (settle, sleeve, ticker) value.
  * k: 1.0 headline, band {0.5, 1.5} printed beside it. Not fitted - nothing to fit it to.
  * unknown sigma or unknown participation -> unknown impact; reported in the uncovered share by
    count and notional, never counted as zero.

From per-fill impact to a cost per side: the dollar-weighted mean of impact_bp over the covered
fills of a sleeve - the same unit as 433's bp per side, read against the rungs 20/8, 35/10, 50/15
on top of the 10/5 base. NOT MEASURABLE at a capital level when more than 5 % of the notional is
unknown. No spread, no intraday: not in the data, not invented.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

import capacity as C

LABEL = "IMPACT_MODELLED_NOT_MEASURED"
K_HEADLINE = 1.0
K_BAND = (0.5, 1.0, 1.5)
SIGMA_WINDOW = 63
SIGMA_WINDOW_SENSITIVITY = 21
BASE_BP = {"stocks": 10.0, "etf": 5.0}                      # 433's base scenario, per side
RUNGS_BP = {"conservative": {"stocks": 20.0, "etf": 8.0},   # 433's stress table, per side
            "stress": {"stocks": 35.0, "etf": 10.0},
            "smallcap_crisis": {"stocks": 50.0, "etf": 15.0}}
UNKNOWN_NOTIONAL_MAX = 0.05
FIXED_CAPITALS = (100_000.0, 500_000.0, 1_000_000.0, 19_721_522.63052529)   # the last: 434's Russell ceiling


# ----------------------------------------------------------------------------------------------
# sigma
# ----------------------------------------------------------------------------------------------
def sigma_panel(close: pd.DataFrame, window: int = SIGMA_WINDOW) -> pd.DataFrame:
    """Daily sigma (fraction) = rolling std of close-to-close log returns, full window or NaN.

    `min_periods` is pandas' fixed-window default (== window): a shortened window is never a
    sigma. Zero or non-positive closes give NaN returns, which blank the window rather than
    fabricate a volatility.
    """
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")
    c = close.astype("float64").where(close > 0)
    rets = np.log(c / c.shift(1))
    return rets.rolling(window).std()


def sigma_prev_bar(sig: pd.DataFrame, ticker: str, settle) -> float:
    """Sigma at the market bar immediately BEFORE `settle` - the one previous-bar rule (`capacity`)."""
    return C.adv_prev_bar(sig, ticker, settle)


# ----------------------------------------------------------------------------------------------
# per-fill impact
# ----------------------------------------------------------------------------------------------
def fills_with_footprints(fills: pd.DataFrame, adv_by_sleeve: dict, sigma_by_sleeve: dict) -> pd.DataFrame:
    """Each fill joined to its footprint's ADV (434's rule) and to its sleeve's sigma at t-1.

    `part_frac_at_1` is the footprint participation at capital 1.0 as a FRACTION; at capital C it
    is `part_frac_at_1 * C`. Unknown ADV or unknown sigma leave NaN, never 0.
    """
    fp = C.footprints(fills)
    fp = fp.rename(columns={"settle": "exec_date"})
    adv_vals = []
    for sleeve, ticker, settle in zip(fp["sleeve"], fp["ticker"], fp["exec_date"]):
        adv = adv_by_sleeve.get(sleeve)
        adv_vals.append(C.adv_prev_bar(adv, ticker, settle) if adv is not None else float("nan"))
    fp["adv_usd"] = adv_vals
    fp["part_frac_at_1"] = fp["net_dollars"].abs() / fp["adv_usd"]
    fp.loc[~(fp["adv_usd"] > 0), "part_frac_at_1"] = np.nan
    f = fills[fills["side"].isin(C.SIDE_SIGN)].copy()
    f = f.merge(fp[["exec_date", "sleeve", "ticker", "part_frac_at_1", "adv_usd"]],
                on=["exec_date", "sleeve", "ticker"], how="left")
    sig_vals = []
    for sleeve, ticker, settle in zip(f["sleeve"], f["ticker"], f["exec_date"]):
        sig = sigma_by_sleeve.get(sleeve)
        sig_vals.append(sigma_prev_bar(sig, ticker, settle) if sig is not None else float("nan"))
    f["sigma_daily"] = sig_vals
    f.loc[~(f["sigma_daily"] > 0), "sigma_daily"] = np.nan
    f["abs_dollars"] = f["dollars"].abs()
    f["known"] = f["part_frac_at_1"].notna() & f["sigma_daily"].notna()
    return f


def impact_bp(f: pd.DataFrame, capital: float, k: float = K_HEADLINE) -> pd.Series:
    """k * sigma * sqrt(participation at C) * 1e4, NaN where unknown. Participation is a fraction."""
    part = f["part_frac_at_1"] * float(capital)
    out = float(k) * f["sigma_daily"] * np.sqrt(part) * 1e4
    return out.where(f["known"], np.nan)


# ----------------------------------------------------------------------------------------------
# effective bp per side
# ----------------------------------------------------------------------------------------------
def effective_bp(f: pd.DataFrame, capital: float, k: float = K_HEADLINE) -> dict:
    """Dollar-weighted mean impact over the COVERED fills, per sleeve and total, with coverage.

    `measurable` is False when more than 5 % of a group's notional is unknown; the value is still
    computed on the covered fills and returned under that flag, never as a headline.
    """
    bp = impact_bp(f, capital, k)
    out = {}
    groups = [("total", f.index)] + [(s, idx) for s, idx in f.groupby("sleeve").groups.items()]
    for name, idx in groups:
        g = f.loc[idx]
        b = bp.loc[idx]
        known = g["known"]
        notional = float(g["abs_dollars"].sum())
        notional_known = float(g.loc[known, "abs_dollars"].sum())
        n, n_known = int(len(g)), int(known.sum())
        eff = (float((b[known] * g.loc[known, "abs_dollars"]).sum() / notional_known)
               if notional_known > 0 else float("nan"))
        unk_share = ((notional - notional_known) / notional) if notional > 0 else float("nan")
        out[name] = dict(
            eff_bp_side=eff, measurable=bool(n > 0 and unk_share <= UNKNOWN_NOTIONAL_MAX + 1e-12),
            n_fills=n, n_known=n_known, notional=notional, notional_known=notional_known,
            unknown_share_by_count=((n - n_known) / n) if n else float("nan"),
            unknown_share_by_notional=unk_share)
    return out


def curve(f: pd.DataFrame, grid=None, k: float = K_HEADLINE) -> list:
    """eff_bp_side vs capital on the 434 grid (10 k .. 100 M, ending exactly at 100 M)."""
    grid = list(grid or C.aum_grid())
    return [dict(capital=float(c), k=float(k), **{name: rec for name, rec in effective_bp(f, c, k).items()})
            for c in grid]


# ----------------------------------------------------------------------------------------------
# crossings against 433's rungs
# ----------------------------------------------------------------------------------------------
def crossings(curve_rows: list, rungs: dict = None, base: dict = None) -> dict:
    """For each rung and sleeve: the smallest capital whose eff_bp_side reaches (rung - base).

    Impact sits on top of 433's base 10/5 bp, so the *conservative* rung is +10 bp of impact on
    stocks (+3 on ETF), *stress* +25 (+5), *smallcap_crisis* +40 (+10). Bracketed; `grid_exhausted`
    when the top of the grid does not reach the rung; `not_measurable` when the crossing point's
    coverage gate fails.
    """
    rungs = rungs or RUNGS_BP
    base = base or BASE_BP
    out = {}
    for rung, per_sleeve in rungs.items():
        out[rung] = {}
        for sleeve, rung_bp in per_sleeve.items():
            target = float(rung_bp) - float(base[sleeve])
            passing = [r["capital"] for r in curve_rows
                       if sleeve in r and r[sleeve]["measurable"] and not (r[sleeve]["eff_bp_side"] >= target)]
            failing = [r["capital"] for r in curve_rows
                       if sleeve in r and r[sleeve]["measurable"] and r[sleeve]["eff_bp_side"] >= target]
            unmeasurable = [r["capital"] for r in curve_rows if sleeve in r and not r[sleeve]["measurable"]]
            first_reach = min(failing) if failing else None
            largest_below = max([c for c in passing if first_reach is None or c < first_reach], default=None)
            out[rung][sleeve] = dict(
                target_impact_bp=target, rung_bp_side=float(rung_bp), base_bp_side=float(base[sleeve]),
                capital_reaching_rung=first_reach, largest_capital_below=largest_below,
                grid_exhausted=(first_reach is None and bool(passing)),
                not_measurable_points=unmeasurable, label=LABEL)
    return out


# ----------------------------------------------------------------------------------------------
# the arithmetic cross-check
# ----------------------------------------------------------------------------------------------
def drag_pp_per_year(eff_bp_side: float, turnover_one_way_per_year: float) -> float:
    """Annual return drag in percentage points: turnover (one-way, fraction of NAV per year) x bp.

    433's measured delta-ann_net is authoritative; this is the same arithmetic 433 used to check
    its own cost deltas (2.266 predicted vs 2.353 observed on Russell 10 -> 50 bp).
    """
    if not (math.isfinite(eff_bp_side) and math.isfinite(turnover_one_way_per_year)):
        return float("nan")
    return float(turnover_one_way_per_year * eff_bp_side / 1e4 * 100.0)


def payload(f: pd.DataFrame, *, grid=None, capitals=FIXED_CAPITALS, ks=K_BAND, extra: dict | None = None) -> dict:
    """Everything this task publishes: LABEL on top, curves for each k, crossings for each k,
    fixed-capital rows, coverage everywhere."""
    grid = list(grid or C.aum_grid())
    curves = {str(k): curve(f, grid, k) for k in ks}
    out = dict(
        label=LABEL, model="impact_bp = k * sigma_daily(t-1) * sqrt(participation) * 1e4",
        k_headline=K_HEADLINE, k_band=list(ks), sigma_window=SIGMA_WINDOW,
        note=("modelled, not measured: no fill of ours has been measured against the tape; no spread, "
              "no intraday - not in the data, not invented"),
        curves=curves,
        crossings={str(k): crossings(curves[str(k)]) for k in ks},
        fixed=[dict(capital=float(c), k=float(k), **effective_bp(f, c, k)) for k in ks for c in capitals],
        coverage=effective_bp(f, 1.0, K_HEADLINE)["total"],
    )
    if extra:
        out.update(extra)
    return out
