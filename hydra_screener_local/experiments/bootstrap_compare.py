"""
TASK-332 — paired block bootstrap of T20−PROD and F1−PROD.

Inference on already-reported series (full sample), not a new variant.
Moving-block bootstrap, block = 13 weeks, 5000 draws. Also the Bailey &
López de Prado (2014) expected-max-Sharpe haircut for N=38 DEV trials, ρ≈0.7.

Import redesign_lab; never edit it.
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


def block_bootstrap(diff, block=BLOCK, n=N_BOOT, rng=None):
    """Moving-block bootstrap paths of `diff`, length T."""
    rng = np.random.default_rng() if rng is None else rng
    x = np.asarray(diff, dtype=float)
    T = len(x)
    if T < block + 1:
        raise ValueError("series shorter than one block")
    n_blocks = int(np.ceil(T / block))
    out = np.empty((n, T))
    max_start = T - block + 1
    for i in range(n):
        starts = rng.integers(0, max_start, size=n_blocks)
        path = np.concatenate([x[s:s + block] for s in starts])[:T]
        out[i] = path
    return out


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


def summarise_diff(a, b, step, label, rng):
    """a minus b, both net-return series aligned."""
    d = np.asarray(a, float) - np.asarray(b, float)
    paths = block_bootstrap(d, rng=rng)
    ann = np.array([ann_net(p, step) for p in paths]) * 100
    # Sharpe of (base + diff) vs Sharpe of base is messy; report Sharpe of each
    # reconstructed series: a* = b_mean_path + d_path is wrong. Instead bootstrap
    # the two series with the SAME block starts.
    sr_a = np.array([sharpe(p, step) for p in block_bootstrap(a, rng=rng)])
    sr_b = np.array([sharpe(p, step) for p in block_bootstrap(b, rng=rng)])
    sr_d = sr_a - sr_b
    point_ann = (ann_net(a, step) - ann_net(b, step)) * 100
    point_sr = sharpe(a, step) - sharpe(b, step)
    return dict(
        label=label, n=len(d), step=step,
        d_ann_net_pp=round(point_ann, 2),
        d_ann_p05=round(float(np.percentile(ann, 5)), 2),
        d_ann_p10=round(float(np.percentile(ann, 10)), 2),
        d_ann_p90=round(float(np.percentile(ann, 90)), 2),
        d_ann_p95=round(float(np.percentile(ann, 95)), 2),
        p_le_prod=round(float((ann <= 0).mean()), 3),
        d_sharpe=round(point_sr, 3),
        d_sharpe_p05=round(float(np.percentile(sr_d, 5)), 3),
        d_sharpe_p95=round(float(np.percentile(sr_d, 95)), 3),
    )


def _compound_prod_to_f1(prod: pd.Series, f1: pd.Series) -> pd.Series:
    """Compound 5-bar PROD net onto F1's 10-bar dates."""
    out = []
    f1_dates = list(f1.index)
    for i, d in enumerate(f1_dates):
        nxt = f1_dates[i + 1] if i + 1 < len(f1_dates) else None
        chunk = prod[prod.index > d]
        if nxt is not None:
            chunk = chunk[chunk.index <= nxt]
        if chunk.empty:
            out.append(np.nan)
        else:
            out.append(float((1 + chunk).prod() - 1))
    return pd.Series(out, index=f1.index)


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

    print(pd.DataFrame(rows).to_string(index=False))
    dsr = expected_max_sharpe(N_TRIALS, len(t20_a[t20_a.index < L.SPLIT]), step=5)
    print("\nDeflated-Sharpe haircut (Bailey & López de Prado 2014)")
    print(dsr)
    print(f"T20 full-sample Sharpe {sharpe(t20_a.values, 5):.3f}  "
          f"DEV Sharpe {sharpe(t20_a[t20_a.index < L.SPLIT].values, 5):.3f}")

    os.makedirs(os.path.dirname(SCRATCH), exist_ok=True)
    with open(SCRATCH, "w", encoding="utf-8") as f:
        json.dump({"rows": rows, "dsr": dsr}, f, indent=2, default=str)


if __name__ == "__main__":
    main()
