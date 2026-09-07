"""A committed, deterministic lab panel so the lab/engine parity tests actually RUN.

Why this file exists. `test_portfolio_engine.py::test_parity_stock_targets_with_redesign_lab` and
`test_review_341.py::test_parity_stock_targets_reproduced` both called `L.load_panel(oos=False)`,
which reads `experiments/_sweep_cache/` — a gitignored yfinance download that exists only in the
operator's production tree. Everywhere else (CI, every worktree, every fresh clone) they called
`pytest.skip` and the suite still printed [PASS]. A silently skipped parity test is this project's
oldest recurring defect: the pair of them had never run outside one machine.

What parity actually asserts is a CODE-PATH equivalence — `core.portfolio_engine.stock_targets`
must reproduce `redesign_lab.select` + equal weights + vol-scaled exposure, name for name and
weight for weight. That property does not need the real price history; it needs a panel that
drives both implementations through the same branches. So this module builds one from a fixed
seed: no network, no cache, no fixture binary in git, same numbers on every machine.

It is a fixture, not evidence. Nothing measured here is a statement about the strategy's returns:
the prices are synthetic. Headline numbers still come from the real panel, and the tests that
consume the real panel say so.

The panel is built so that every branch the parity test can take is taken (asserted by
`test_portfolio_engine.py::test_lab_fixture_exercises_every_parity_branch`, so the fixture cannot
quietly go degenerate):
  * >= 50 eligible names on every tested bar, so `rank_day` returns a frame;
  * a common market factor whose volatility changes in blocks, so the SPY regime, the meta-layer
    aggression and therefore `dynamic_count` move, and the vol-target exposure is below 1 on some
    bars and pinned at 1 on others;
  * dispersion wide enough that the veto gate fires;
  * six sectors plus an `Other` bucket, so the hard sector cap binds and the `Other` exemption is
    exercised.
"""
import os

import numpy as np
import pandas as pd

SECTORS = ["Technology", "Energy", "Healthcare", "Financials", "Industrials", "Utilities"]
#: market-factor daily sigma, cycled in blocks: quiet -> normal -> stressed
VOL_BLOCKS = (0.004, 0.009, 0.016, 0.007)
BLOCK_BARS = 60


def sector_map(columns, n_other=8):
    """Deterministic sector assignment: round-robin over SECTORS, the last `n_other` in `Other`."""
    cols = list(columns)
    out = {t: SECTORS[i % len(SECTORS)] for i, t in enumerate(cols)}
    for t in cols[len(cols) - n_other:]:
        out[t] = "Other"
    return out


def build_frames(n_members=80, n_rows=470, seed=20260907, start="2024-01-02"):
    """(close, volume, spy) — the three pickles `backtest_variant_sweep.Panels` reads."""
    idx = pd.bdate_range(start, periods=n_rows)
    rng = np.random.default_rng(seed)

    sigma = np.array([VOL_BLOCKS[(i // BLOCK_BARS) % len(VOL_BLOCKS)] for i in range(n_rows)])
    mkt = 0.0004 + rng.normal(0.0, 1.0, n_rows) * sigma          # common factor, regime-switching vol
    spy = pd.Series(100.0 * np.exp(np.cumsum(mkt)), index=idx)

    close, volume = {}, {}
    for i in range(n_members):
        beta = 0.6 + 0.8 * ((i * 7) % n_members) / n_members     # deterministic spread of betas
        drift = (i - n_members / 2) * 0.00012                    # winners and losers, both signs
        idio = rng.normal(0.0, 0.009, n_rows)
        close[f"S{i:02d}"] = 60.0 * np.exp(np.cumsum(drift + beta * mkt + idio))
        # volume moves so VRATIO (and therefore the strict-filter bonus) is not constant
        volume[f"S{i:02d}"] = 2_000_000.0 * np.exp(rng.normal(0.0, 0.35, n_rows))
    return (pd.DataFrame(close, index=idx), pd.DataFrame(volume, index=idx), spy)


def build_etf_frames(n_rows=470, seed=20260907, start="2024-01-02"):
    """(etf_closes, tbill_daily) for the ETF-trend parity test.

    Same purpose as `build_frames`: the ETF parity test called `sleeve_lab.load_etfs`, which reads
    the gitignored `experiments/_sweep_cache_etf/`, so it skipped everywhere but one machine. The
    property under test — `sleeves.etf_trend.target_weights` reproduces the lab's inverse-vol
    time-series-momentum rule — needs the branches, not the real ETFs:
      * `TLT`/`DBC` trend DOWN over the 12-month window -> the signal is off, their share stays in
        T-bill (so the weights must not sum to 1);
      * `IEF` drifts up by LESS than the accumulated T-bill -> off through the hurdle, not the sign,
        which is the bug this rule had before TASK-347;
      * `VNQ` has no history before bar 120 -> ineligible while `t - 252` falls in the gap, so
        `eligible()` is exercised rather than assumed;
      * volatilities differ by a factor of ~4 across the universe, so inverse-vol weights are not
        equal weights in disguise.
    The T-bill is a real-ish 4.2% -> 5.1% annualised ramp, never zero, so the hurdle always bites.
    """
    idx = pd.bdate_range(start, periods=n_rows)
    rng = np.random.default_rng(seed + 1)
    tb = pd.Series(np.linspace(0.042, 0.051, n_rows), index=idx) / 252.0   # annualised/252, per bar

    #                    daily drift, daily sigma
    spec = {"SPY": (0.00045, 0.008), "QQQ": (0.00060, 0.011), "IWM": (0.00030, 0.012),
            "EFA": (0.00035, 0.009), "EEM": (0.00020, 0.013), "TLT": (-0.00040, 0.007),
            "IEF": (0.00005, 0.003), "GLD": (0.00040, 0.008), "DBC": (-0.00025, 0.010),
            "VNQ": (0.00050, 0.011)}
    out = {}
    for name, (drift, sigma) in spec.items():
        px = 100.0 * np.exp(np.cumsum(drift + rng.normal(0.0, sigma, n_rows)))
        if name == "VNQ":
            px[:120] = np.nan                      # listed late: ineligible until t - 252 clears it
        out[name] = px
    return pd.DataFrame(out, index=idx), tb


def build_panel(dirpath, **kw):
    """A real `Panels` with the real derived feature panels, loaded through the real loader.

    Writes the three pickles into `dirpath` (use pytest's `tmp_path`) and loads them with
    `bvs.Panels` + `redesign_lab.prepare_panel`, so the object under test is the same class the
    lab runs on — no stubs, no monkeypatching of the panel. Returns the prepared `Panels`.
    """
    import backtest_variant_sweep as bvs
    import redesign_lab as L

    close, volume, spy = build_frames(**kw)
    os.makedirs(dirpath, exist_ok=True)
    close.to_pickle(os.path.join(dirpath, "close.pkl"))
    volume.to_pickle(os.path.join(dirpath, "volume.pkl"))
    spy.to_frame("SPY").to_pickle(os.path.join(dirpath, "spy.pkl"))
    P = bvs.Panels(cache_dir=dirpath)
    P.PIT_META = None
    return L.prepare_panel(P, sectors=sector_map(close.columns))
