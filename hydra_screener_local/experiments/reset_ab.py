"""TASK-409 / H-002 - pair reset vs full weekly 50/50 reset, with the two confounds removed.

H-002 asks whether renewing one PAIR of tranches a week (production: the pair is split equally by
value, the sleeves drift 47-51% in between) beats resetting the whole book to 50/50 every week.
The only comparison on record was the engine (7.10 / 0.75 / 0.57 / -17.8) against the lab mix
(6.91 / 0.74 / 0.56 / -19.5), and SPEC 9.5 already says why that is not an answer:

  1. the lab's T20 earned no interest on idle cash while the engine's stock sleeve does, and
  2. the lab row dated t covers t+1..t+6 while the engine's return at t covers t-5..t.

The second one is real and is fixed here with a shift. **The first one does not exist**: running
this script showed that `audit_steps.pkl`'s `P_5050` is `mix(T20_cy + ETF)` - the T-bill variant -
to machine precision (0.0e+00 against it, 2.2e-04 against `mix(T20 + ETF)`), so the published mix
always had cash at the T-bill and SPEC 9.5's explanation of the gap was wrong. It is corrected
there. The script still rebuilds the mix from `T20_cy` explicitly, so the claim is checked on every
run instead of trusted, and reports the confounded row next to it: identical columns are the proof.

What remains is lab accounting against engine accounting, stated rather than hidden: the fully
clean version needs a full-weekly-reset flag inside `core/portfolio_engine.plan`, which is a
live-path file frozen until the first settle is verified
(`.comms/merge-window-2026-09-09.md`).

The bootstrap is PAIRED by construction: one matrix of block indices is drawn and applied to both
series, so a draw compares the two rules on the same resampled weeks. Drawing separately is the
defect `fix/astra-07` found in TASK-332, and it is not repeated here.

    python experiments/reset_ab.py            # PIT panel; caches the engine book series
    python experiments/reset_ab.py --refresh  # ignore the cached engine series
"""
from __future__ import annotations

import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import metrics as M  # noqa: E402

AUDIT_STEPS = os.path.join(HERE, "_sweep_cache_etf", "audit_steps.pkl")
ENGINE_CACHE = os.path.join(HERE, "_lab_scratch", "engine_book_oos.pkl")
SCRATCH = os.path.join(HERE, "_lab_scratch", "task409.json")
STEP = 5
BLOCK = 13
N_BOOT = 5000


def block_index_matrix(T: int, block: int = BLOCK, n: int = N_BOOT, rng=None) -> np.ndarray:
    """(n, T) positions drawn as moving blocks. ONE matrix, applied to both series: that is what
    makes the comparison paired."""
    rng = np.random.default_rng() if rng is None else rng
    if T < block + 1:
        raise ValueError("series shorter than one block")
    n_blocks = int(np.ceil(T / block))
    starts = rng.integers(0, T - block + 1, size=(n, n_blocks))
    offs = np.arange(block)
    idx = (starts[:, :, None] + offs[None, None, :]).reshape(n, -1)[:, :T]
    return idx


def paired_difference(a: pd.Series, b: pd.Series, rf: pd.Series, *, rng=None,
                      n: int = N_BOOT, block: int = BLOCK) -> dict:
    """a minus b on their common dates: point estimates and paired bootstrap intervals."""
    common = a.index.intersection(b.index).intersection(rf.index)
    if len(common) < block + 1:
        raise ValueError(f"only {len(common)} common dates: not enough for a {block}-step block")
    x = a.loc[common].astype(float).to_numpy()
    y = b.loc[common].astype(float).to_numpy()
    r = rf.loc[common].astype(float).to_numpy()
    idx = block_index_matrix(len(common), block=block, n=n, rng=rng)

    def ann(v):
        return (np.prod(1 + v, axis=-1) ** (M.periods_per_year(STEP) / v.shape[-1]) - 1) * 100

    def sharpe(v, rate):
        ex = v - rate
        sd = ex.std(axis=-1, ddof=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(sd > 0, ex.mean(axis=-1) / sd * np.sqrt(M.periods_per_year(STEP)), 0.0)

    d_ann_paths = ann(x[idx]) - ann(y[idx])
    d_sharpe_paths = sharpe(x[idx], r[idx]) - sharpe(y[idx], r[idx])
    per_step = x - y
    return dict(
        n=int(len(common)),
        first=str(pd.Timestamp(common[0]).date()), last=str(pd.Timestamp(common[-1]).date()),
        a_ann=round(float(ann(x)), 2), b_ann=round(float(ann(y)), 2),
        a_sharpe=round(float(sharpe(x, r)), 3), b_sharpe=round(float(sharpe(y, r)), 3),
        d_ann_pp=round(float(ann(x) - ann(y)), 2),
        d_ann_p05=round(float(np.percentile(d_ann_paths, 5)), 2),
        d_ann_p95=round(float(np.percentile(d_ann_paths, 95)), 2),
        p_a_le_b=round(float((d_ann_paths <= 0).mean()), 3),
        d_sharpe=round(float(sharpe(x, r) - sharpe(y, r)), 3),
        d_sharpe_p05=round(float(np.percentile(d_sharpe_paths, 5)), 3),
        d_sharpe_p95=round(float(np.percentile(d_sharpe_paths, 95)), 3),
        mean_step_diff_bp=round(float(per_step.mean() * 1e4), 2),
        se_step_diff_bp=round(float(per_step.std(ddof=1) / np.sqrt(len(per_step)) * 1e4), 2),
    )


def verdict(d: dict) -> str:
    """The rule written before looking: an interval that straddles zero is indistinguishable."""
    if d["d_sharpe_p05"] <= 0 <= d["d_sharpe_p95"] and d["d_ann_p05"] <= 0 <= d["d_ann_p95"]:
        return ("INDISTINGUISHABLE: both paired intervals straddle zero. H-002 closes as 'no "
                "measurable difference' - production keeps the pair reset because it is already "
                "there, not because it won.")
    if d["d_ann_p05"] > 0 and d["d_sharpe_p05"] > 0:
        return "FULL WEEKLY RESET WINS on both metrics at the 5th percentile."
    if d["d_ann_p95"] < 0 and d["d_sharpe_p95"] < 0:
        return "PAIR RESET WINS on both metrics at the 95th percentile."
    return "MIXED: one metric separates from zero and the other does not. Not a decision."


def load_lab(path: str = AUDIT_STEPS) -> dict:
    if not os.path.exists(path):
        return {}
    return pd.read_pickle(path)


def engine_series(refresh: bool = False) -> pd.Series:
    """The engine's book marks on the PIT panel, cached because the run takes minutes."""
    if not refresh and os.path.exists(ENGINE_CACHE):
        return pd.read_pickle(ENGINE_CACHE)
    import engine_backtest as EB
    import redesign_lab as L
    import sleeve_lab as S
    P = L.load_panel(oos=True)
    P.ETF = S.load_etfs(P.close.index)
    ser, _ = EB.drive_engine(P)
    os.makedirs(os.path.dirname(ENGINE_CACHE), exist_ok=True)
    pd.to_pickle(ser, ENGINE_CACHE)
    return ser


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="TASK-409: pair reset vs full weekly reset")
    ap.add_argument("--refresh", action="store_true", help="re-run the engine instead of the cache")
    ap.add_argument("--boot", type=int, default=N_BOOT)
    args = ap.parse_args(argv)

    lab = load_lab()
    if not lab or "T20_cy" not in lab or "ETF" not in lab:
        print("SKIP:", AUDIT_STEPS, "missing or has no T20_cy/ETF frames")
        return 0
    import redesign_lab as L
    import sleeve_lab as S

    print("full weekly 50/50 reset, stock sleeve earning the T-bill (T20_cy + ETF)...", flush=True)
    full = S.mix([lab["T20_cy"], lab["ETF"]], "equal")["net"]
    confounded = lab["P_5050"]["net"] if "P_5050" in lab else None

    print("engine (pair reset)...", flush=True)
    book = engine_series(refresh=args.refresh)
    pair = book.pct_change().dropna()

    P = L.load_panel(oos=True)
    rf = M.step_risk_free(P.IRX, book.index)

    # the lab row dated t covers t+1..t+6; shift it onto the engine's mark dates
    full_aligned = full.shift(1).dropna()
    rng = np.random.default_rng(0)
    rows = {}
    rows["deconfounded"] = paired_difference(full_aligned, pair, rf, rng=rng, n=args.boot)
    if confounded is not None:
        rows["as_published"] = paired_difference(confounded.shift(1).dropna(), pair, rf,
                                                 rng=np.random.default_rng(0), n=args.boot)
    d = rows["deconfounded"]
    print("", flush=True)
    print(pd.DataFrame(rows).to_string(), flush=True)
    print("", flush=True)
    print("A = full weekly 50/50 reset (lab, T-bill on idle stock cash), "
          "B = pair reset (production engine)", flush=True)
    print("verdict:", verdict(d), flush=True)
    if "as_published" in rows:
        moved = round(rows["as_published"]["d_ann_pp"] - d["d_ann_pp"], 2)
        if moved == 0.0:
            print("the two columns are identical, which is the finding: the published mix ALREADY "
                  "had cash at the T-bill, so the interest confound SPEC 9.5 blamed never existed.",
                  flush=True)
        else:
            print(f"removing the interest confound moved the annual difference by {moved} pp "
                  f"({rows['as_published']['d_ann_pp']} -> {d['d_ann_pp']}).", flush=True)
    print("Residual, stated: this is lab accounting against engine accounting. The fully clean "
          "A/B needs a full-weekly-reset flag in core/portfolio_engine.plan, which is frozen "
          "until the first settle is verified.", flush=True)

    os.makedirs(os.path.dirname(SCRATCH), exist_ok=True)
    with open(SCRATCH, "w", encoding="utf-8") as f:
        json.dump(dict(rows=rows, verdict=verdict(d), block=BLOCK, n_boot=args.boot,
                       note="paired bootstrap: one block-index matrix applied to both series"),
                  f, indent=2, default=str)
    print("wrote", SCRATCH, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
