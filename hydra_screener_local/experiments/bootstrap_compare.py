"""
TASK-332 — paired block bootstrap of T20−PROD and F1−PROD.

Inference on already-reported series (full sample), not a new variant.
Moving-block bootstrap, block = 13 weeks, 5000 draws. Also the Bailey &
López de Prado (2014) expected-max-Sharpe haircut for N=38 DEV trials, ρ≈0.7.

Import redesign_lab; never edit it.

ASTRA-07 (2026-09-06) — every interval this module printed before that date is
SUPERSEDED. Three defects, all in the estimator, none in the series:

 1. the annualised-gap interval was the percentile of ``CAGR(a - b)`` (the CAGR
    of the compounded difference series) while the point estimate was
    ``CAGR(a) - CAGR(b)``. Two different statistics side by side: with two
    constant series at 2%/step and 1%/step the point estimate is +106.18 pp and
    the old "interval" was a degenerate 65.12/65.12 — the point estimate sat
    outside its own interval. The published TASK-332 F1−PROD row shows the same
    signature (point +1.74 pp, "90% CI" [−1.96, +1.89]).
 2. the Sharpe difference called itself paired but resampled the two series in
    two successive ``block_bootstrap`` calls on the same RNG, so the block
    starts differed between them. A series bootstrapped against ITSELF then
    produced d_sharpe = 0.000 with an interval of −0.850 / +0.852.
 3. ``_compound_prod_to_f1`` compounded the PROD legs labelled ``(d, nxt]``
    while ``redesign_lab.run*`` labels every return FORWARD (``date=idx[t]``,
    return earned from ``t+lag`` to ``t+lag+hold``). The correct legs are
    ``[d, nxt)``: the old window was shifted one PROD step late, dropped the
    leg that opens the F1 window and pulled in the leg that opens the NEXT one,
    and gave the trailing F1 date whatever PROD legs happened to remain (one leg
    on the published 1084/542 grid, so the last row was under-covered).
    Proven by test_bootstrap_compare.py::test_compound_prod_to_f1_* (impulse).

Fix: ONE moving-block index matrix per replicate, applied to both series, with
every statistic differenced INSIDE the replicate.
"""
from __future__ import annotations

import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
from scipy.stats import norm

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import redesign_lab as L

SCRATCH = os.path.join(HERE, "_lab_scratch", "task332_series.json")
N_BOOT = 5000
BLOCK = 13
N_TRIALS = 38
RHO = 0.7
EMC = 0.5772156649  # Euler-Mascheroni


def expected_max_sharpe(n_trials, n_obs, step=5, rho=RHO):
    """E[max annualised SR] under the null SR=0, with trial correlation rho.

    Independent haircut: Bailey & López de Prado 2014 eq. for E[max SR].
    Correlated: replace N with N_eff = 1 + (N-1)*(1-rho).
    σ_SR ≈ 1/sqrt(years) under SR=0, years = n_obs * step / 252.
    """
    n_eff = 1.0 + (n_trials - 1) * (1.0 - rho)
    n_years = max(n_obs * step / 252.0, 0.5)
    sr_std = 1.0 / np.sqrt(n_years)

    def haircut(n):
        n = max(float(n), 2.0)
        z = (1 - EMC) * norm.ppf(1 - 1 / n) + EMC * norm.ppf(1 - 1 / (n * np.e))
        return float(sr_std * z)

    return dict(n_trials=n_trials, n_obs=int(n_obs), rho=rho, n_eff=round(n_eff, 2),
                e_max_sr_independent=round(haircut(n_trials), 3),
                e_max_sr_correlated=round(haircut(n_eff), 3))


def block_index_matrix(T, block=BLOCK, n=N_BOOT, rng=None):
    """(n, T) integer matrix of moving-block resampling positions into 0..T-1.

    ONE matrix per comparison, applied to EVERY series in it, is what makes the
    draws paired. Two separate calls to a resampler on the same RNG draw
    different block starts and are therefore independent, not paired (ASTRA-07,
    defect 2): the difference of the two marginals is then the difference of two
    INDEPENDENT bootstraps and its interval is far too wide -- wide enough that
    a series compared against itself got -0.850 / +0.852 around an exact zero.
    """
    rng = np.random.default_rng() if rng is None else rng
    T = int(T)
    if T < block + 1:
        raise ValueError("series shorter than one block")
    n_blocks = int(np.ceil(T / block))
    starts = rng.integers(0, T - block + 1, size=(n, n_blocks))
    idx = starts[:, :, None] + np.arange(block)[None, None, :]
    return idx.reshape(n, n_blocks * block)[:, :T]


def block_bootstrap(diff, block=BLOCK, n=N_BOOT, rng=None, idx=None):
    """Moving-block bootstrap paths of `diff`, length T.

    Pass `idx` from block_index_matrix to resample another series on the SAME
    block starts. Drawing a fresh matrix (idx=None) is only correct for a
    single-series statistic; never use two fresh calls for a paired difference.
    """
    x = np.asarray(diff, dtype=float)
    if idx is None:
        idx = block_index_matrix(len(x), block=block, n=n, rng=rng)
    return x[idx]


def ann_net(r, step):
    py = 252 / step
    r = np.asarray(r, dtype=float)
    if len(r) == 0 or np.any(r <= -1):
        return np.nan
    return float((1 + r).prod() ** (py / len(r)) - 1)


def sharpe(r, step):
    py = 252 / step
    r = np.asarray(r, dtype=float)
    sd = r.std(ddof=1)
    if sd == 0:
        return 0.0
    return float(r.mean() / sd * np.sqrt(py))


def summarise_diff(a, b, step, label, rng, n=N_BOOT, block=BLOCK):
    """Paired moving-block bootstrap of CAGR(a)-CAGR(b) and SR(a)-SR(b).

    `a` and `b` must be net-return series of equal length on the same dates and
    the same `step`. ONE index matrix is drawn per replicate and applied to both
    series, and each statistic is differenced INSIDE the replicate, so the
    interval estimates exactly the statistic the point estimate reports.

    Before ASTRA-07 this returned an interval for CAGR of the compounded
    (a - b) series next to a point estimate of CAGR(a) - CAGR(b) (defect 1) and
    an unpaired Sharpe difference (defect 2). Every d_ann_p* / d_sharpe_p*
    number this module printed before 2026-09-06 is superseded.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.shape != b.shape or a.ndim != 1:
        raise ValueError(f"a and b must be aligned 1-D series, got {a.shape} vs {b.shape}")
    idx = block_index_matrix(len(a), block=block, n=n, rng=rng)
    pa, pb = a[idx], b[idx]
    ann = np.array([ann_net(x, step) - ann_net(y, step) for x, y in zip(pa, pb)]) * 100
    sr_d = np.array([sharpe(x, step) - sharpe(y, step) for x, y in zip(pa, pb)])
    point_ann = (ann_net(a, step) - ann_net(b, step)) * 100
    point_sr = sharpe(a, step) - sharpe(b, step)
    return dict(
        label=label, n=len(a), step=step, n_boot=n, block=block,
        estimator="paired-blocks; diff of CAGRs and diff of Sharpes per replicate",
        d_ann_net_pp=round(point_ann, 2),
        d_ann_p05=round(float(np.percentile(ann, 5)), 2),
        d_ann_p10=round(float(np.percentile(ann, 10)), 2),
        d_ann_p90=round(float(np.percentile(ann, 90)), 2),
        d_ann_p95=round(float(np.percentile(ann, 95)), 2),
        p_le_prod=round(float((ann <= 0).mean()), 3),
        d_sharpe=round(point_sr, 3),
        d_sharpe_p05=round(float(np.percentile(sr_d, 5)), 3),
        d_sharpe_p95=round(float(np.percentile(sr_d, 95)), 3),
        p_sharpe_le_0=round(float((sr_d <= 0).mean()), 3),
    )


def _compound_prod_to_f1(prod: pd.Series, f1: pd.Series) -> pd.Series:
    """Compound 5-bar PROD net onto F1's 10-bar dates.

    `redesign_lab.run*` labels every cycle FORWARD: the record stamped `idx[t]`
    holds the return earned from `t + lag` to `t + lag + hold`. So the PROD legs
    that make up the F1 window OPENING at date d are the ones labelled
    ``[d, next_f1_date)`` -- d INCLUDED, the next F1 label EXCLUDED (it opens the
    following window).

    ASTRA-07 defect 3: this used ``(d, nxt]``, which dropped the leg opening the
    window and pulled in the leg opening the next one -- the PROD series was
    compared to F1 one PROD step (5 bars) late. Additionally the trailing F1
    date, having no right-hand label, took whatever PROD legs remained -- one leg
    on the published 1084/542 grid, more if PROD runs further past F1 -- and was
    compared against one 10-bar F1 return anyway. It is now accepted only if it
    holds as many legs as the interior windows, and dropped (NaN) otherwise.
    """
    f1_dates = list(f1.index)
    chunks = []
    for i, d in enumerate(f1_dates):
        mask = prod.index >= d
        if i + 1 < len(f1_dates):
            mask = mask & (prod.index < f1_dates[i + 1])
        chunks.append(prod[mask])
    interior = [len(c) for c in chunks[:-1]]
    want = max(set(interior), key=interior.count) if interior else 0
    out = []
    for i, chunk in enumerate(chunks):
        trailing_partial = i == len(chunks) - 1 and len(interior) > 0 and len(chunk) != want
        if chunk.empty or trailing_partial:
            out.append(np.nan)
        else:
            out.append(float((1 + chunk).prod() - 1))
    return pd.Series(out, index=f1.index)


# The TASK-332 table as published in .comms/grok-task-332-bootstrap.md on
# 2026-09-06, produced by the pre-ASTRA-07 estimator. Kept verbatim so a rerun
# prints the two side by side instead of silently overwriting the record. The
# point estimates (d_ann_net_pp, d_sharpe) are unaffected by defects 1 and 2 but
# ARE affected by defect 3 for the F1 row; every interval below is superseded.
SUPERSEDED_TASK332 = [
    dict(label="T20-PROD", n=1084, d_ann_net_pp=2.23, d_ann_p05=-2.61, d_ann_p95=4.24,
         d_sharpe=0.184, d_sharpe_p05=-0.286, d_sharpe_p95=0.636, p_le_prod=0.386),
    dict(label="F1-PROD", n=542, d_ann_net_pp=1.74, d_ann_p05=-1.96, d_ann_p95=1.89,
         d_sharpe=0.129, d_sharpe_p05=-0.362, d_sharpe_p95=0.625, p_le_prod=0.508),
]


def _series(P, name):
    df = L.run_any(P, L.CONFIGS[name])
    return df["net"]


def main():
    rng = np.random.default_rng(0)
    P = L.load_panel(oos=True)
    print(f"panel {P.close.shape}  FULL sample inference", flush=True)
    print("running PROD / F1 / T20 ...", flush=True)
    prod = _series(P, "PROD")
    f1 = _series(P, "F1")
    t20 = _series(P, "T20")
    print("  lens", len(prod), len(f1), len(t20), flush=True)

    # align T20 and PROD on common dates (both 5-bar)
    common = t20.index.intersection(prod.index)
    t20_a, prod_a = t20.loc[common], prod.loc[common]
    rows = [summarise_diff(t20_a.values, prod_a.values, L.step_of(L.CONFIGS["T20"]),
                           "T20-PROD", rng)]

    prod_on_f1 = _compound_prod_to_f1(prod, f1).dropna()
    f1_a = f1.loc[prod_on_f1.index]
    rows.append(summarise_diff(f1_a.values, prod_on_f1.values, L.step_of(L.CONFIGS["F1"]),
                               "F1-PROD", rng))

    cols = ["label", "n", "d_ann_net_pp", "d_ann_p05", "d_ann_p95",
            "d_sharpe", "d_sharpe_p05", "d_sharpe_p95", "p_le_prod"]
    print("\n=== SUPERSEDED (pre-ASTRA-07 estimator, as published 2026-09-06) ===")
    print("intervals below are NOT estimates of the point estimate beside them")
    print(pd.DataFrame(SUPERSEDED_TASK332)[cols].to_string(index=False))
    print("\n=== CURRENT (paired blocks, differences inside each replicate) ===")
    print(pd.DataFrame(rows).to_string(index=False))
    dsr = expected_max_sharpe(N_TRIALS, len(t20_a[t20_a.index < L.SPLIT]), step=5)
    print("\nDeflated-Sharpe haircut (Bailey & López de Prado 2014)")
    print(dsr)
    print(f"T20 full-sample Sharpe {sharpe(t20_a.values, 5):.3f}  "
          f"DEV Sharpe {sharpe(t20_a[t20_a.index < L.SPLIT].values, 5):.3f}")

    os.makedirs(os.path.dirname(SCRATCH), exist_ok=True)
    with open(SCRATCH, "w", encoding="utf-8") as f:
        json.dump({"rows": rows, "dsr": dsr,
                   "superseded_task332": SUPERSEDED_TASK332,
                   "estimator_fixed": "ASTRA-07 2026-09-06"}, f, indent=2, default=str)


if __name__ == "__main__":
    main()
