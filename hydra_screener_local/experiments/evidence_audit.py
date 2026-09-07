"""TASK-ASTRA-11 — one evidence report that cannot overclaim.

Astra's confirmed complaint is not that the numbers are wrong, it is that the
labels are. Four separate ways the published evidence certifies properties
nobody measured:

  1. What the reports call "Sharpe" is net return over its own standard
     deviation with no risk-free subtraction (`redesign_lab.py:495`,
     `engine_backtest.py:56`). One sleeve carries a lot of cash, so ranking two
     sleeves on that number is not like-for-like.
  2. The multiplicity haircut hardcodes `N_TRIALS=38` and `rho=0.7`
     (`bootstrap_compare.py:32,33`) and returns an expected-max-Sharpe, not the
     deflated Sharpe: the real DSR needs the skew, the kurtosis and the
     dispersion of the *trialled* Sharpes.
  3. A reported p=0.009 sits inside a family of 15 comparisons on the same
     sample. Family-wise that is 0.135, not significance at 5%.
  4. `cost_model.cost_bp_per_side(adv_usd, price)` depends on ADV only — not on
     order size, AUM, observed spread or auction participation — so no "the edge
     dies at $X AUM" can be derived from it.

This module is measurement and presentation only. It imports nothing the live
path runs, it never touches state/, and it changes no score, gate or cost that
production uses. Its whole job is to make a missing number render as
"not measured" instead of as a default.

Design rules enforced in code, not in prose:

  * `NOT_MEASURED` is a sentinel, not None and not 0. It is falsy, it renders as
    "not measured", and numeric formatting of it is a TypeError by construction.
  * Every published number is a `Row` with a `basis` (what it is measured
    against) and a `provenance` (recomputed here / documented elsewhere).
  * `Report.overclaims()` lists label violations and `render()` refuses to print
    a report that has any. The raw ratio may not be called a Sharpe; an excess
    Sharpe may not be printed without an aligned risk-free series; a capacity
    figure may not be printed while its inputs are missing.

Usage (no network, reads only the tracked cone JSON):

    python experiments/evidence_audit.py
    python experiments/evidence_audit.py --draws 5000 --out report.md
    python experiments/evidence_audit.py --json out.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from dataclasses import dataclass, field

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
from scipy.stats import norm

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

CONE_PATH = os.path.join(ROOT, "data", "oos_cone_5050.json")
STEPS_PER_YEAR = 252 / 5  # 50.4 — the cone is 5-session steps
EULER_MASCHERONI = 0.5772156649015329
DEFAULT_BLOCKS = (1, 4, 13, 26)
DEFAULT_DRAWS = 5000


# --------------------------------------------------------------------------- #
# the null
# --------------------------------------------------------------------------- #
class _NotMeasured:
    """A number that does not exist. Falsy, prints as "not measured".

    Deliberately not None and not float('nan'): None invites `or 0.0` and nan
    invites arithmetic that silently propagates. Numeric formatting raises, so a
    caller that tries to print this as a figure gets a TypeError instead of a
    plausible-looking default.
    """

    __slots__ = ()
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __str__(self) -> str:
        return "not measured"

    def __repr__(self) -> str:
        return "NOT_MEASURED"

    def __float__(self):
        raise TypeError("not measured: refusing to produce a float for a number that was never measured")

    def __format__(self, spec: str) -> str:
        if spec and spec[-1] in "eEfFgGn%":
            raise TypeError(f"not measured: refusing numeric format {spec!r}")
        return format(str(self), spec)


NOT_MEASURED = _NotMeasured()


def is_measured(value) -> bool:
    """True only for a real, finite number (or a non-null string) actually computed."""
    if value is NOT_MEASURED or value is None:
        return False
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
        return bool(np.isfinite(float(value)))
    return True


class MislabelledEvidence(AssertionError):
    """Raised when a report would publish a row under a label it has not earned."""


class InsufficientEvidence(RuntimeError):
    """Raised by an estimator whose required inputs do not exist."""


# --------------------------------------------------------------------------- #
# rows
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Row:
    key: str
    label: str
    value: object
    unit: str = ""
    basis: str = ""
    provenance: str = ""
    missing: tuple = ()
    note: str = ""

    @property
    def measured(self) -> bool:
        return is_measured(self.value)

    def value_text(self) -> str:
        if not self.measured:
            miss = ", ".join(self.missing)
            return f"not measured (missing: {miss})" if miss else "not measured"
        suffix = (" " + self.unit) if self.unit else ""
        if isinstance(self.value, (int, np.integer)) and not isinstance(self.value, bool):
            return f"{int(self.value):,}{suffix}"
        if isinstance(self.value, (float, np.floating)):
            txt = f"{float(self.value):,.4f}".rstrip("0").rstrip(".")
            return f"{txt or '0'}{suffix}"
        return f"{self.value}{suffix}"

    def rendered(self) -> str:
        parts = [f"{self.label}: {self.value_text()}"]
        if self.basis:
            parts.append(f"basis: {self.basis}")
        if self.provenance:
            parts.append(f"provenance: {self.provenance}")
        if self.note:
            parts.append(self.note)
        return "  - " + "  |  ".join(parts)

    def as_dict(self) -> dict:
        return dict(key=self.key, label=self.label,
                    value=(self.value if self.measured else None),
                    measured=self.measured, unit=self.unit, basis=self.basis,
                    provenance=self.provenance, missing=list(self.missing), note=self.note)


# --------------------------------------------------------------------------- #
# 1 — the ratio and the excess Sharpe, never the same row
# --------------------------------------------------------------------------- #
RAW_RATIO_KEY = "ratio_over_zero"
EXCESS_SHARPE_KEY = "excess_sharpe"
RAW_RATIO_LABEL = "net return / own sd, annualised, vs zero (NOT a Sharpe ratio)"
EXCESS_SHARPE_LABEL = "excess Sharpe over the risk-free series"


def raw_ratio_over_zero(step_returns, steps_per_year: float = STEPS_PER_YEAR) -> float:
    """mean / own sd, annualised, measured against zero. NOT a Sharpe ratio."""
    x = np.asarray(step_returns, dtype=float)
    if x.size < 2:
        raise InsufficientEvidence("fewer than two steps")
    sd = x.std(ddof=1)
    if sd <= 0:
        raise InsufficientEvidence("zero dispersion")
    return float(x.mean() / sd * math.sqrt(steps_per_year))


def excess_sharpe(step_returns, rf_step_returns, steps_per_year: float = STEPS_PER_YEAR) -> float:
    """Sharpe of (r - rf) over the SAME steps. Raises if rf is absent or unaligned.

    This is the only function in this module allowed to produce a number called
    a Sharpe ratio. Without an aligned risk-free series there is no Sharpe, so
    there is no fallback here: the caller gets InsufficientEvidence and the
    report renders "not measured".
    """
    x = np.asarray(step_returns, dtype=float)
    if rf_step_returns is None:
        raise InsufficientEvidence("no risk-free (T-bill) series aligned to the return steps")
    rf = np.asarray(rf_step_returns, dtype=float)
    if rf.size != x.size:
        raise InsufficientEvidence(
            f"risk-free series has {rf.size} steps, returns have {x.size}: not aligned step-for-step")
    if not np.isfinite(rf).all():
        raise InsufficientEvidence("risk-free series has gaps: no step-for-step excess return")
    d = x - rf
    sd = d.std(ddof=1)
    if sd <= 0:
        raise InsufficientEvidence("zero dispersion of excess returns")
    return float(d.mean() / sd * math.sqrt(steps_per_year))


def ratio_rows(step_returns, rf_step_returns=None, steps_per_year: float = STEPS_PER_YEAR,
               provenance: str = "recomputed here") -> list:
    """The two rows that must never be collapsed into one."""
    rows = []
    try:
        raw = raw_ratio_over_zero(step_returns, steps_per_year)
        rows.append(Row(RAW_RATIO_KEY, RAW_RATIO_LABEL, round(raw, 4),
                        basis="zero — no risk-free subtraction", provenance=provenance,
                        note=("comparing two sleeves on this number is not like-for-like when they "
                              "hold different amounts of cash")))
    except InsufficientEvidence as exc:
        rows.append(Row(RAW_RATIO_KEY, RAW_RATIO_LABEL, NOT_MEASURED,
                        basis="zero — no risk-free subtraction", missing=(str(exc),)))
    try:
        ex = excess_sharpe(step_returns, rf_step_returns, steps_per_year)
        rows.append(Row(EXCESS_SHARPE_KEY, EXCESS_SHARPE_LABEL, round(ex, 4),
                        basis="aligned risk-free (T-bill) return, step for step",
                        provenance=provenance))
    except InsufficientEvidence as exc:
        rows.append(Row(EXCESS_SHARPE_KEY, EXCESS_SHARPE_LABEL, NOT_MEASURED,
                        basis="aligned risk-free (T-bill) return, step for step — absent",
                        missing=(str(exc),),
                        note=("no T-bill series is tracked in the repo; ^IRX lives only in the "
                              "gitignored cache, so no excess Sharpe exists for this cone")))
    return rows


# --------------------------------------------------------------------------- #
# 2 — sample size: weeks are not variance-equivalent observations
# --------------------------------------------------------------------------- #
def stationary_bootstrap_indices(n_steps: int, block: int, draws: int, seed: int = 0) -> np.ndarray:
    """Politis-Romano stationary bootstrap index matrix, geometric block mean `block`."""
    if n_steps < 2:
        raise InsufficientEvidence("fewer than two steps")
    if block < 1:
        raise ValueError("block must be >= 1")
    rng = np.random.default_rng(seed)
    idx = np.empty((draws, n_steps), dtype=int)
    idx[:, 0] = rng.integers(n_steps, size=draws)
    for j in range(1, n_steps):
        restart = rng.random(draws) < 1.0 / block
        idx[:, j] = np.where(restart, rng.integers(n_steps, size=draws), (idx[:, j - 1] + 1) % n_steps)
    return idx


_RESAMPLE_CACHE: dict = {}


def resample_summary(step_returns, block: int, draws: int = DEFAULT_DRAWS, seed: int = 0,
                     steps_per_year: float = STEPS_PER_YEAR) -> dict:
    """CAGR 90% interval, SE of the mean step, and the variance-equivalent N.

    Memoised on the exact series and resampling parameters: the report asks for
    the same draws twice (interval rows and sample-size rows) and a bootstrap of
    1084 steps is not free.
    """
    x = np.asarray(step_returns, dtype=float)
    ck = (hashlib.sha1(np.ascontiguousarray(x).tobytes()).hexdigest(), int(block), int(draws),
          int(seed), float(steps_per_year))
    if ck in _RESAMPLE_CACHE:
        return dict(_RESAMPLE_CACHE[ck])
    sample = x[stationary_bootstrap_indices(x.size, block, draws, seed)]
    cagr = 100.0 * (np.exp(np.log1p(sample).mean(axis=1) * steps_per_year) - 1.0)
    means = sample.mean(axis=1)
    out = dict(block=int(block), draws=int(draws),
               cagr_p05=float(np.percentile(cagr, 5)), cagr_p95=float(np.percentile(cagr, 95)),
               mean_se_bp=float(means.std(ddof=1) * 10000.0),
               variance_equivalent_n=float(x.var(ddof=1) / means.var(ddof=1)))
    _RESAMPLE_CACHE[ck] = out
    return dict(out)


def sample_size_rows(step_returns, blocks=DEFAULT_BLOCKS, draws: int = DEFAULT_DRAWS,
                     seed: int = 0, steps_per_year: float = STEPS_PER_YEAR) -> list:
    x = np.asarray(step_returns, dtype=float)
    rows = [Row("n_steps", "N of 5-session steps actually observed", int(x.size), unit="steps",
                basis="one row per 5-session step of the tracked cone",
                provenance="recomputed here",
                note=f"~{x.size / steps_per_year:.1f} years at {steps_per_year:g} steps/year")]
    for block in blocks:
        s = resample_summary(x, block, draws, seed, steps_per_year)
        rows.append(Row(f"variance_equivalent_n_block{block}",
                        f"variance-equivalent N of the mean, stationary block {block}",
                        round(s["variance_equivalent_n"], 1), unit="equivalent obs",
                        basis="var(step) / var(bootstrap mean) — an efficiency of the MEAN only",
                        provenance=f"recomputed here, {s['draws']} draws, seed {seed}",
                        note=("NOT new weeks; not a valid N for drawdown, tail or "
                              "strategy-selection claims")))
    return rows


def cone_interval_rows(step_returns, blocks=DEFAULT_BLOCKS, draws: int = DEFAULT_DRAWS,
                       seed: int = 0, steps_per_year: float = STEPS_PER_YEAR) -> list:
    rows = []
    for block in blocks:
        s = resample_summary(step_returns, block, draws, seed, steps_per_year)
        kind = "iid" if block == 1 else f"stationary block {block}"
        rows.append(Row(f"cagr_ci90_block{block}", f"CAGR 90% interval, {kind}",
                        f"{s['cagr_p05']:.3f} to {s['cagr_p95']:.3f}", unit="%",
                        basis="resampling of THIS selected history; stationarity assumed",
                        provenance=f"recomputed here, {s['draws']} draws, seed {seed}",
                        note=f"SE of the mean step {s['mean_se_bp']:.3f} bp"))
    return rows


# --------------------------------------------------------------------------- #
# 3 — the trial family and the family-wise p
# --------------------------------------------------------------------------- #
# The family as published, one row per comparison, same sample, same dates.
# Source: .comms/claude-algo-deep-dive-2026-09-05.md section 4 (283 cycles,
# paired t-test against the same baseline). Documented, not recomputed here.
DEEP_DIVE_FAMILY = (
    ("momentum without vol-scaling", 0.009),
    ("top 5 only", 0.094),
    ("fixed N = 10", 0.264),
    ("no short-term boost", 0.109),
    ("additive score (sign-safe)", 0.024),
    ("entry with 1-day lag", 0.675),
    ("no downtrend gate", 0.184),
    ("momentum with 5d skip", 0.433),
    ("sector control exempts 'Other'", 0.402),
    ("no sector control", 0.475),
    ("no strict bonus", 0.218),
    ("non-overlapping vol ratio", 0.632),
    ("fixed N = 28", 0.985),
    ("gate without the 'negative only' rule", 0.548),
    ("distance to the 252d (52w) high", 0.058),
)
DEEP_DIVE_FAMILY_SOURCE = ".comms/claude-algo-deep-dive-2026-09-05.md §4 (documented, 283 cycles)"


def holm_adjusted(p_values) -> list:
    """Holm step-down adjusted p-values, in the input order. Family-wise at 5%."""
    ps = [float(p) for p in p_values]
    m = len(ps)
    if m == 0:
        raise InsufficientEvidence("empty trial family")
    order = sorted(range(m), key=lambda i: ps[i])
    out = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * ps[i]))
        out[i] = running
    return out


def family_summary(trials, name: str, source: str) -> dict:
    """Bonferroni and Holm over one *registered* family. Families are never summed."""
    trials = list(trials)
    if not trials:
        raise InsufficientEvidence("empty trial family")
    ps = [float(p) for _, p in trials]
    m = len(ps)
    best = min(range(m), key=lambda i: ps[i])
    holm = holm_adjusted(ps)
    return dict(family=name, source=source, size=m,
                trials=[dict(trial=t, p_raw=p, p_holm=h) for (t, p), h in zip(trials, holm)],
                min_p_raw=ps[best], min_p_trial=trials[best][0],
                bonferroni_min_p=min(1.0, m * ps[best]), holm_min_p=holm[best],
                any_significant_5pct=bool(min(holm) < 0.05))


def family_rows(summary: dict) -> list:
    return [
        Row(f"family_{summary['family']}_size", f"family '{summary['family']}': comparisons declared",
            int(summary["size"]), unit="trials", basis="same sample, same dates, one baseline",
            provenance=summary["source"]),
        Row(f"family_{summary['family']}_min_p", f"family '{summary['family']}': smallest raw p",
            round(summary["min_p_raw"], 4),
            basis=f"per-comparison, uncorrected — trial: {summary['min_p_trial']}",
            provenance=summary["source"],
            note="a per-comparison p is not evidence about the family"),
        Row(f"family_{summary['family']}_fwer_p",
            f"family '{summary['family']}': family-wise p of the best trial (Bonferroni)",
            round(summary["bonferroni_min_p"], 4),
            basis=f"{summary['size']} comparisons on the same sample",
            provenance="recomputed here from the documented family",
            note=("family-wise significant at 5%" if summary["any_significant_5pct"]
                  else "NOT family-wise significant at 5%")),
        Row(f"family_{summary['family']}_holm_p",
            f"family '{summary['family']}': Holm-adjusted p of the best trial",
            round(summary["holm_min_p"], 4),
            basis=f"{summary['size']} comparisons, step-down", provenance="recomputed here"),
    ]


# --------------------------------------------------------------------------- #
# 4 — PSR measurable, DSR not (and the current haircut is neither)
# --------------------------------------------------------------------------- #
def probabilistic_sharpe(sr_per_step: float, n_obs: int, skew: float, excess_kurtosis: float,
                         benchmark_sr_per_step: float = 0.0) -> float:
    """Bailey & Lopez de Prado PSR. Needs skew and kurtosis, both of which exist here."""
    if n_obs < 3:
        raise InsufficientEvidence("fewer than three observations")
    kurt = float(excess_kurtosis) + 3.0  # the paper's gamma_4, not the excess
    denom = 1.0 - float(skew) * sr_per_step + ((kurt - 1.0) / 4.0) * sr_per_step ** 2
    if denom <= 0:
        raise InsufficientEvidence("non-positive Sharpe variance under the observed moments")
    z = (sr_per_step - benchmark_sr_per_step) * math.sqrt(n_obs - 1) / math.sqrt(denom)
    return float(norm.cdf(z))


def deflated_sharpe(sr_per_step: float, n_obs: int, skew: float, excess_kurtosis: float,
                    trial_sr_sd_per_step=None, n_trials=None) -> float:
    """The real DSR: PSR against SR*, the expected max Sharpe of the trial family.

    SR* needs the *dispersion of the trialled Sharpes* and the number of trials.
    `bootstrap_compare.expected_max_sharpe` substitutes a hardcoded N_TRIALS=38
    and rho=0.7 and never estimates that dispersion, so it cannot produce this
    number. Neither can this function without the inputs: it raises.
    """
    missing = []
    if not is_measured(trial_sr_sd_per_step) or float(trial_sr_sd_per_step) <= 0:
        missing.append("standard deviation of the trialled Sharpe ratios (the trial track record)")
    if not is_measured(n_trials) or int(n_trials) < 2:
        missing.append("the number of trials actually run (a declared, complete trial matrix)")
    if missing:
        raise InsufficientEvidence("; ".join(missing))
    n = float(int(n_trials))
    v = float(trial_sr_sd_per_step)
    z1 = norm.ppf(1.0 - 1.0 / n)
    z2 = norm.ppf(1.0 - 1.0 / (n * math.e))
    sr_star = v * ((1.0 - EULER_MASCHERONI) * z1 + EULER_MASCHERONI * z2)
    return probabilistic_sharpe(sr_per_step, n_obs, skew, excess_kurtosis, sr_star)


def deflation_rows(step_returns, trial_sr_sd_per_step=None, n_trials=None,
                   steps_per_year: float = STEPS_PER_YEAR) -> list:
    x = np.asarray(step_returns, dtype=float)
    s = pd.Series(x)
    sr_step = float(x.mean() / x.std(ddof=1))
    skew, exkurt = float(s.skew()), float(s.kurt())
    rows = [
        Row("skew", "skew of the step returns", round(skew, 4), basis="observed steps",
            provenance="recomputed here"),
        Row("excess_kurtosis", "excess kurtosis of the step returns", round(exkurt, 4),
            basis="observed steps", provenance="recomputed here"),
    ]
    try:
        psr = probabilistic_sharpe(sr_step, x.size, skew, exkurt, 0.0)
        rows.append(Row("psr_vs_zero", "PSR: P(true ratio > 0) given skew and kurtosis",
                        round(psr, 4), basis="benchmark 0, non-normal moments of THIS series",
                        provenance="recomputed here",
                        note="a PSR against zero says nothing about the trial family"))
    except InsufficientEvidence as exc:
        rows.append(Row("psr_vs_zero", "PSR: P(true ratio > 0) given skew and kurtosis",
                        NOT_MEASURED, basis="benchmark 0, non-normal moments of THIS series",
                        missing=(str(exc),)))
    try:
        dsr = deflated_sharpe(sr_step, x.size, skew, exkurt, trial_sr_sd_per_step, n_trials)
        rows.append(Row("dsr", "deflated Sharpe ratio (Bailey & Lopez de Prado)", round(dsr, 4),
                        basis="PSR against SR* from the trialled-Sharpe dispersion",
                        provenance="recomputed here"))
    except InsufficientEvidence as exc:
        rows.append(Row("dsr", "deflated Sharpe ratio (Bailey & Lopez de Prado)", NOT_MEASURED,
                        basis="PSR against SR* from the trialled-Sharpe dispersion",
                        missing=tuple(str(exc).split("; ")),
                        note=("bootstrap_compare.expected_max_sharpe (N_TRIALS=38, rho=0.7) is an "
                              "expected-max-Sharpe haircut on assumed constants, not this number")))
    return rows


# --------------------------------------------------------------------------- #
# 5 — price coverage per era, 2005 visible
# --------------------------------------------------------------------------- #
# Documented in .comms/claude-redesign-verdict-2026-09-06.md §1: membership is
# real PIT, prices are not survivorship-free; coverage 53% (2005) -> 95% (2023).
# Only the two endpoints are documented. The eras in between are NOT interpolated.
DOCUMENTED_COVERAGE = (("2005", 53.0), ("2023", 95.0))
COVERAGE_SOURCE = ".comms/claude-redesign-verdict-2026-09-06.md §1 (documented, not recomputed here)"
COVERAGE_ERAS = ("2005", "2008", "2011", "2014", "2017", "2020", "2023", "2026")


def coverage_rows(measured: dict | None = None, eras=COVERAGE_ERAS) -> list:
    """One row per era. An era with no number renders "not measured", never interpolated."""
    documented = dict(DOCUMENTED_COVERAGE)
    measured = dict(measured or {})
    rows = []
    for era in eras:
        key, label = f"coverage_{era}", f"price coverage of PIT membership, {era}"
        if era in measured:
            rows.append(Row(key, label, round(float(measured[era]), 1), unit="%",
                            basis="names with a price / PIT members on the era's last bar",
                            provenance="recomputed here from the panel"))
        elif era in documented:
            rows.append(Row(key, label, round(float(documented[era]), 1), unit="%",
                            basis="names with a price / PIT members",
                            provenance=COVERAGE_SOURCE,
                            note=("prices are NOT survivorship-free at this coverage; never quote "
                                  "an absolute level from this era without saying so")))
        else:
            rows.append(Row(key, label, NOT_MEASURED,
                            basis="names with a price / PIT members",
                            missing=("panel snapshot for this era (the caches are gitignored)",),
                            note="not interpolated between the documented endpoints"))
    return rows


# --------------------------------------------------------------------------- #
# 6 — cost model and capacity: the null that must stay null
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CapacityInputs:
    """What an "the edge dies at $X" claim would require. Absent by default."""

    executed_fills: int = 0
    order_sizes_usd: tuple = ()
    auction_volume_usd: tuple = ()
    arrival_and_decision_prices: int = 0
    fees_usd: object = None

    def missing(self) -> tuple:
        out = []
        if int(self.executed_fills) <= 0:
            out.append("executed fills (ticker, date/time, quantity, price)")
        if not tuple(self.order_sizes_usd):
            out.append("order sizes in dollars per ticker per tranche")
        if not tuple(self.auction_volume_usd):
            out.append("auction (MOC) volume for the names traded")
        if int(self.arrival_and_decision_prices) <= 0:
            out.append("decision / arrival / fill prices to measure slippage against")
        if self.fees_usd is None:
            out.append("fees actually paid")
        return tuple(out)

    @property
    def sufficient(self) -> bool:
        return not self.missing()


def cost_model_size_sensitivity(adv_usd: float = 5_000_000.0,
                                order_sizes_usd=(1_000.0, 100_000.0, 1_000_000.0, 10_000_000.0)) -> dict:
    """Measure whether the production cost curve responds to order size at all.

    `cost_bp_per_side(adv_usd, price)` takes no order size, so this calls it once
    per hypothetical order and reports the spread of the answers. A spread of
    zero is the finding: the 50/20/5 bp knots are a chosen curve on ADV, not a
    calibration of this account.
    """
    from cost_model import cost_bp_per_side

    bps = [float(cost_bp_per_side(adv_usd, 50.0)) for _ in order_sizes_usd]
    return dict(adv_usd=float(adv_usd), order_sizes_usd=[float(s) for s in order_sizes_usd],
                bp_per_side=bps, spread_bp=float(max(bps) - min(bps)),
                size_aware=bool(max(bps) - min(bps) > 0),
                inputs_absent=("order size", "AUM", "observed spread", "auction participation"))


def cost_rows(sensitivity: dict | None = None) -> list:
    s = sensitivity or cost_model_size_sensitivity()
    lo, hi = s["order_sizes_usd"][0], s["order_sizes_usd"][-1]
    return [
        Row("cost_bp_at_5m_adv", f"modelled cost per side at ${s['adv_usd']:,.0f} ADV",
            round(s["bp_per_side"][0], 1), unit="bp",
            basis="log-linear ADV curve, knots $0.5M/$5M/$50M -> 50/20/5 bp",
            provenance="recomputed here from experiments/cost_model.py",
            note="a chosen curve, not a calibration of this account; config COST_BP_PER_SIDE is 10 bp"),
        Row("cost_size_sensitivity_bp",
            "change in modelled cost per side across order sizes at fixed ADV",
            round(s["spread_bp"], 4), unit="bp",
            basis=f"orders ${lo:,.0f} to ${hi:,.0f} at ${s['adv_usd']:,.0f} ADV",
            provenance="recomputed here",
            note=("size-aware" if s["size_aware"] else
                  "zero: the function ignores order size, AUM, spread and auction participation, "
                  "so it cannot price impact")),
        Row("cost_basis_taxes", "tax treatment inside the reported net", "excluded",
            basis="net = gross - 2 * bp/10000 * turnover",
            provenance="experiments/cost_model.py:_net_from_turnover",
            note="every net number in this report is BEFORE taxes and before order minimums"),
    ]


def edge_death_aum(inputs: CapacityInputs, sensitivity: dict | None = None) -> float:
    """The AUM at which the edge dies. Raises unless the inputs exist.

    There is no default here on purpose. A cost function that does not see order
    size cannot be inverted for a size, so no arithmetic on this repo's current
    inputs produces this number.
    """
    missing = list(inputs.missing())
    s = sensitivity or cost_model_size_sensitivity()
    if not s["size_aware"]:
        missing.append("a cost model that responds to order size (the current curve depends on ADV only)")
    if missing:
        raise InsufficientEvidence("; ".join(missing))
    raise InsufficientEvidence(
        "inputs present but no impact model is calibrated in this repo: refusing to invent a curve")


def capacity_rows(inputs: CapacityInputs | None = None, sensitivity: dict | None = None) -> list:
    inputs = inputs if inputs is not None else CapacityInputs()
    label = "AUM at which the modelled edge dies"
    try:
        aum = edge_death_aum(inputs, sensitivity)
    except InsufficientEvidence as exc:
        return [Row("edge_death_aum", label, NOT_MEASURED, unit="USD",
                    basis="calibrated impact vs measured fills",
                    missing=tuple(str(exc).split("; ")),
                    note="any figure here would be invented; the report prints none")]
    return [Row("edge_death_aum", label, round(float(aum), 0), unit="USD",
                basis="calibrated impact vs measured fills", provenance="recomputed here")]


def participation_scenarios(adv_usd: float = 5_000_000.0,
                            aums=(100_000.0, 1_000_000.0, 10_000_000.0),
                            names=(6, 22), tranche_fraction: float | None = None) -> list:
    """HYPOTHESIS rows: order size as a share of ADV. Arithmetic, not slippage.

    tranche_fraction defaults to the v9 book share of one fully invested stock
    tranche: mix['stocks'] / tranches.
    """
    if tranche_fraction is None:
        from config import V9

        tranche_fraction = float(V9["mix"]["stocks"]) / float(V9["tranches"])
    rows = []
    for aum in aums:
        for n in names:
            order = float(aum) * tranche_fraction / n
            rows.append(Row(f"participation_aum{int(aum)}_n{n}",
                            f"HYPOTHESIS: order per name, AUM ${aum:,.0f}, n={n}",
                            round(order, 0), unit="USD",
                            basis=(f"AUM x {tranche_fraction:g} / n; "
                                   f"{100 * order / adv_usd:.3f}% of ${adv_usd:,.0f} ADV"),
                            provenance="arithmetic scenario, recomputed here",
                            note=("not MOC participation and not measured slippage; aggregate "
                                  "orders for one ticker across tranches may differ")))
    return rows


# --------------------------------------------------------------------------- #
# reserve status — a TEST looked at once is not an intact reserve
# --------------------------------------------------------------------------- #
def reserve_rows(dev_trials=None, test_looks: int = 1,
                 split: str = "DEV < 2016-01-01 <= TEST") -> list:
    rows = [Row("split", "pre-registered split", split, basis="fixed before looking",
                provenance="documented: .comms/claude-redesign-verdict-2026-09-06.md §1")]
    if is_measured(dev_trials):
        rows.append(Row("dev_trials", "configurations explored on DEV", int(dev_trials), unit="trials",
                        basis="declared trial matrix", provenance="recomputed here"))
    else:
        rows.append(Row("dev_trials", "configurations explored on DEV", NOT_MEASURED, unit="trials",
                        missing=("a complete, dated trial matrix (the '~35' in the verdict is an estimate)",),
                        note="without the matrix the multiplicity correction has no exact family size"))
    rows.append(Row("test_looks", "times the TEST reserve was inspected", int(test_looks), unit="looks",
                    basis="pre-registered finalists only",
                    provenance="documented: .comms/claude-redesign-verdict-2026-09-06.md §1",
                    note=("a reserve inspected once is spent for anything decided after that look; "
                          "it may not be presented as an untouched hold-out")))
    return rows


# --------------------------------------------------------------------------- #
# the report
# --------------------------------------------------------------------------- #
@dataclass
class Report:
    title: str
    panel: str
    sections: list = field(default_factory=list)  # (heading, [Row, ...])
    families: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def rows(self) -> list:
        return [r for _, rows in self.sections for r in rows]

    def row(self, key: str) -> Row:
        for r in self.rows():
            if r.key == key:
                return r
        raise KeyError(key)

    def unmeasured_keys(self) -> list:
        return [r.key for r in self.rows() if not r.measured]

    def overclaims(self) -> list:
        """Label violations. render() refuses to print while this is non-empty."""
        bad = []
        for r in self.rows():
            low = r.label.lower()
            if r.value is None:
                bad.append(f"{r.key}: value is None — use NOT_MEASURED, a null must be explicit")
            if r.key == RAW_RATIO_KEY:
                if "sharpe" in low and "not a sharpe" not in low:
                    bad.append(f"{r.key}: the raw ratio is labelled as a Sharpe ratio")
                if "zero" not in r.basis.lower():
                    bad.append(f"{r.key}: basis does not say the ratio is measured against zero")
            if r.key == EXCESS_SHARPE_KEY:
                if "excess" not in low:
                    bad.append(f"{r.key}: the excess-Sharpe row is not labelled as excess")
                if r.measured and "risk-free" not in r.basis.lower() and "t-bill" not in r.basis.lower():
                    bad.append(f"{r.key}: a Sharpe is published without naming the risk-free series")
                if not r.measured and "absent" not in r.basis.lower() and not r.missing:
                    bad.append(f"{r.key}: unmeasured excess Sharpe does not say what is absent")
            if r.key == "edge_death_aum" and r.measured:
                bad.append(f"{r.key}: a capacity figure is published, but no calibrated impact "
                           f"model exists in this repo")
            if r.key.startswith("variance_equivalent_n") and "variance-equivalent" not in low:
                bad.append(f"{r.key}: variance-equivalent N is not labelled as such")
            if r.key.startswith("participation_") and not low.startswith("hypothesis"):
                bad.append(f"{r.key}: a scenario is published without the HYPOTHESIS label")
            if r.measured and not r.provenance:
                bad.append(f"{r.key}: a published number without provenance")
        return bad

    def as_dict(self) -> dict:
        return dict(title=self.title, panel=self.panel, meta=self.meta, families=self.families,
                    sections=[dict(heading=h, rows=[r.as_dict() for r in rows])
                              for h, rows in self.sections],
                    unmeasured=self.unmeasured_keys(), overclaims=self.overclaims())


def load_cone(path: str = CONE_PATH) -> dict:
    with open(path, "rb") as fh:
        raw = fh.read()
    blob = json.loads(raw.decode("utf-8"))
    x = np.asarray(blob["step_returns"], dtype=float)
    return dict(step_returns=x, n=int(x.size), first=blob.get("first"), last=blob.get("last"),
                panel=blob.get("panel"), recipe=blob.get("recipe"),
                sha256=hashlib.sha256(raw).hexdigest(), path=path)


def build_report(cone: dict | None = None, rf_step_returns=None, capacity=None,
                 coverage_measured=None, blocks=DEFAULT_BLOCKS, draws: int = DEFAULT_DRAWS,
                 seed: int = 0, steps_per_year: float = STEPS_PER_YEAR,
                 trial_sr_sd_per_step=None, n_trials=None, dev_trials=None,
                 families=(("deep_dive", DEEP_DIVE_FAMILY, DEEP_DIVE_FAMILY_SOURCE),),
                 sensitivity=None) -> Report:
    cone = cone if cone is not None else load_cone()
    x = np.asarray(cone["step_returns"], dtype=float)
    capacity = capacity if capacity is not None else CapacityInputs()
    sensitivity = sensitivity or cost_model_size_sensitivity()

    cagr = 100.0 * (math.exp(float(np.log1p(x).sum()) * steps_per_year / x.size) - 1.0)
    head = [
        Row("cagr_net", "net CAGR of the cone", round(cagr, 4), unit="%",
            basis="compounded step returns, after modelled costs, BEFORE taxes",
            provenance="recomputed here from the tracked cone"),
        Row("step_sd", "standard deviation of one step",
            round(float(x.std(ddof=1)) * 100.0, 4), unit="%",
            basis="observed steps", provenance="recomputed here"),
        Row("autocorr_lag1", "lag-1 autocorrelation of the steps",
            round(float(pd.Series(x).autocorr(1)), 4),
            basis="observed steps", provenance="recomputed here",
            note="negative: the variance-equivalent N of the MEAN exceeds the step count"),
    ]

    fam_summaries = [family_summary(trials, name, src) for name, trials, src in families]
    fam_rows = [r for s in fam_summaries for r in family_rows(s)]

    return Report(
        title="Evidence audit — HYDRA v9 50/50 cone",
        panel=str(cone.get("panel") or "unknown"),
        sections=[
            ("Level", head),
            ("Risk-adjusted: the ratio and the Sharpe are two rows",
             ratio_rows(x, rf_step_returns, steps_per_year)),
            ("Sample size: observed steps vs variance-equivalent N",
             sample_size_rows(x, blocks, draws, seed, steps_per_year)),
            ("Resampled CAGR intervals", cone_interval_rows(x, blocks, draws, seed, steps_per_year)),
            ("Trial family and family-wise significance", fam_rows),
            ("Multiplicity haircut: PSR yes, DSR no",
             deflation_rows(x, trial_sr_sd_per_step, n_trials, steps_per_year)),
            ("Reserve status", reserve_rows(dev_trials)),
            ("Price coverage per era", coverage_rows(coverage_measured)),
            ("Cost model", cost_rows(sensitivity)),
            ("Capacity", capacity_rows(capacity, sensitivity)),
            ("Participation scenarios (hypothesis, not slippage)", participation_scenarios()),
        ],
        families=fam_summaries,
        meta=dict(cone_path=cone.get("path"), cone_sha256=cone.get("sha256"),
                  first=cone.get("first"), last=cone.get("last"), recipe=cone.get("recipe"),
                  n_steps=int(x.size), steps_per_year=steps_per_year,
                  draws=int(draws), seed=int(seed),
                  capacity_missing=list(capacity.missing())),
    )


def render(report: Report) -> str:
    bad = report.overclaims()
    if bad:
        raise MislabelledEvidence("refusing to render an overclaiming report:\n  " + "\n  ".join(bad))
    m = report.meta
    sha = str(m.get("cone_sha256") or "")
    out = [f"# {report.title}", ""]
    out.append(f"Panel: {report.panel}. Steps {m['first']} to {m['last']}, n={m['n_steps']}.")
    out.append(f"Source: `{m['cone_path']}` sha256 {sha[:16]}.")
    out.append(f"Recipe: {m['recipe']}.")
    out.append(f"Resampling: {m['draws']} draws, seed {m['seed']}, {m['steps_per_year']:g} steps/year.")
    out.append("")
    out.append("Every number below carries what it is measured against. A number that was not "
               "measured prints as \"not measured\" and names the missing input; nothing here "
               "falls back to a default. All net figures are before taxes.")
    for heading, rows in report.sections:
        out.append("")
        out.append(f"## {heading}")
        for r in rows:
            out.append(r.rendered())
    out.append("")
    out.append("## Trial families (never summed)")
    for s in report.families:
        out.append("")
        out.append(f"### {s['family']} — {s['size']} comparisons — {s['source']}")
        out.append("| trial | p raw | p Holm |")
        out.append("|---|---:|---:|")
        for t in s["trials"]:
            out.append(f"| {t['trial']} | {t['p_raw']:.3f} | {t['p_holm']:.3f} |")
        verdict = ("family-wise significant at 5%" if s["any_significant_5pct"]
                   else "NOT family-wise significant at 5%")
        out.append(f"Best raw p {s['min_p_raw']:.3f} ({s['min_p_trial']}); Bonferroni "
                   f"{s['bonferroni_min_p']:.3f}; Holm {s['holm_min_p']:.3f} — {verdict}.")
    out.append("")
    out.append("## Not measured")
    unmeasured = report.unmeasured_keys()
    if not unmeasured:
        out.append("  - (nothing)")
    for key in unmeasured:
        row = report.row(key)
        out.append(f"  - {key}: {', '.join(row.missing) or 'input absent'}")
    out.append("")
    out.append("Nothing in this report authorises a scoring, mix or production-cost change; "
               "those need Lucas's explicit approval (GROKBOARD rule 6).")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="evidence audit report (measurement only, no network)")
    ap.add_argument("--cone", default=CONE_PATH)
    ap.add_argument("--draws", type=int, default=DEFAULT_DRAWS)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None, help="write the markdown report here")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="write the machine-readable report here")
    args = ap.parse_args(argv)

    report = build_report(load_cone(args.cone), draws=args.draws, seed=args.seed)
    text = render(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {args.out}")
    else:
        print(text)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(report.as_dict(), fh, indent=2)
        print(f"wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
