"""Return statistics with the risk-free leg the old ones never had (TASK-404).

Every HYDRA number published so far called `mean/sd * sqrt(periods)` on the NET return a
"Sharpe ratio". It is not one: no risk-free series is subtracted, and the v9 book holds a
sleeve that earns the 13-week T-bill on idle cash (`accrue_interest`), so the omission
flatters the strategy exactly where it holds the most cash. This module keeps both numbers
side by side and names them for what they are:

    ratio_net_vol   mean/sd * sqrt(periods) on the NET return  (the old "Sharpe")
    sharpe_excess   the same on NET - RISK-FREE, compounded over the same bars

`step_risk_free` builds the risk-free leg from the same annualised-decimal ^IRX series the
engine accrues interest with, compounded bar by bar over each step, so the two legs cover
the same calendar. Nothing here reads a file or a global: pass the series in.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BARS_PER_YEAR = 252.0


def periods_per_year(step: int) -> float:
    return BARS_PER_YEAR / float(step)


def annualised_return(r, step: int) -> float:
    """Compounded annual return in percent from per-step returns."""
    x = np.asarray(pd.Series(r).dropna(), dtype=float)
    if len(x) == 0 or np.any(x <= -1):
        return float("nan")
    py = periods_per_year(step)
    return float(((1 + x).prod() ** (py / len(x)) - 1) * 100)


def net_vol_ratio(r, step: int) -> float:
    """mean/sd * sqrt(periods). NOT a Sharpe ratio: no risk-free leg. Kept because every
    number published before 2026-09-08 is this quantity, and comparisons need it."""
    x = pd.Series(r).dropna().astype(float)
    if x.empty:
        return float("nan")
    sd = x.std()                    # ddof=1, the convention every published number used
    return float(x.mean() / sd * np.sqrt(periods_per_year(step))) if sd else 0.0


def drawdown_curve(r) -> pd.Series:
    """The whole under-water path `max_drawdown` takes its minimum of, as a decimal (<= 0).

    This is the single definition of a HYDRA drawdown; every caller that needs the path (the
    trough, the peak that preceded it, a per-year slice) must take it from here rather than
    re-spelling `(1 + r).cumprod()`, because the spelling is exactly where the bug lived.

    The compounded curve starts at 1.0 *before* the first step, so the running peak is floored
    at the capital that went in. Without that floor a loss on the FIRST step is measured from
    what is left after it -- the running peak at step one is the post-loss equity -- and a book
    that falls 20% and climbs back to par reports a drawdown of zero. The floor is what makes
    the first period count.

    The returned series is indexed like `r` (NaNs dropped), one value per step.
    """
    x = pd.Series(r).dropna().astype(float)
    if x.empty:
        return x
    eq = (1 + x).cumprod()
    return eq / eq.cummax().clip(lower=1.0) - 1


def max_drawdown(r) -> float:
    """Worst peak-to-trough of the compounded step returns, in percent (negative)."""
    dd = drawdown_curve(r)
    if dd.empty:
        return float("nan")
    return float(dd.min()) * 100


def annual_max_drawdown(r, *, peak: str) -> dict:
    """Worst drawdown of each calendar year, in percent (negative), keyed by the year.

    `peak` is required and has no default on purpose. "The 2016 drawdown" is two different
    numbers depending on where the high-water mark comes from, the gap between them runs to
    ten percentage points on the real books, and a silent default would let a caller publish
    one while meaning the other:

      peak="year"   the running peak RESETS on 1 Jan, floored at the capital standing at the
                    start of the year. This reads the year on its own -- "a book opened on
                    1 Jan, how far under water did it get?" -- and it is the honest partner of
                    a year-standalone return, which is what an annual table usually reports.
                    The year's FIRST return is inside the measure: a January loss shows as a
                    drawdown instead of being swallowed by a peak set after it.

      peak="carry"  the running peak is carried in from the whole history, so a year that
                    merely fails to regain a high struck in an earlier year still reports a
                    deep drawdown. This is the statement read: how far the book is below its
                    all-time high. On the cached books it is the deeper number in most years
                    and it is NOT comparable to a year-standalone return.

    Neither reading is more correct; they answer different questions. What is wrong is the old
    form, which reset the peak each year but then dropped the year's first return out of the
    peak -- reporting a quiet zero for a year whose only move was a loss.
    """
    x = pd.Series(r).dropna().astype(float)
    if x.empty:
        return {}
    idx = pd.DatetimeIndex(x.index)
    if peak == "year":
        return {int(y): max_drawdown(g) for y, g in x.groupby(idx.year)}
    if peak == "carry":
        dd = drawdown_curve(x)
        return {int(y): float(g.min()) * 100 for y, g in dd.groupby(idx.year)}
    raise ValueError("peak must be 'year' or 'carry', not %r" % (peak,))


def step_risk_free(irx: pd.Series, dates, forward: bool = False, step: int = 5) -> pd.Series:
    """Risk-free return of each step, compounded from the daily annualised ^IRX.

    `irx` is the annualised decimal rate on the price calendar (what `redesign_lab` exposes
    as `P.IRX` and what `accrue_interest` divides by 252). `dates` are the marks.

    forward=False (the engine's convention): the value at mark d covers the bars strictly
    after the previous mark up to and including d, so the first mark has no return and the
    result is indexed by `dates[1:]`.

    forward=True (the lab's convention): the row dated d covers the `step` bars after d, so
    the result is indexed by every mark whose window fits inside the calendar.
    """
    rate = pd.Series(irx).astype(float)
    rate.index = pd.DatetimeIndex(rate.index)
    rate = rate.sort_index()
    if rate.empty:
        raise ValueError("no risk-free series: cannot build an excess return")
    factor = (1.0 + rate / BARS_PER_YEAR).cumprod()
    cal = factor.index
    marks = pd.DatetimeIndex(pd.Series(list(dates)).astype("datetime64[ns]"))
    pos = cal.get_indexer(marks)
    if (pos < 0).any():
        missing = marks[pos < 0]
        raise ValueError(f"{len(missing)} mark(s) are not bars of the risk-free calendar, "
                         f"first {missing[0].date()}")
    out = {}
    if forward:
        for m, p in zip(marks, pos):
            end = p + int(step)
            if end >= len(cal):
                continue
            out[m] = float(factor.iloc[end] / factor.iloc[p] - 1.0)
    else:
        for m_prev, m, p_prev, p in zip(marks[:-1], marks[1:], pos[:-1], pos[1:]):
            out[m] = float(factor.iloc[p] / factor.iloc[p_prev] - 1.0)
    return pd.Series(out, dtype=float).sort_index()


def sharpe_excess(r, rf, step: int) -> float:
    """The real thing: mean/sd * sqrt(periods) on NET - RISK-FREE, on their common dates."""
    net = pd.Series(r).astype(float).dropna()
    rate = pd.Series(rf).astype(float).dropna()
    net.index = pd.DatetimeIndex(net.index)
    rate.index = pd.DatetimeIndex(rate.index)
    common = net.index.intersection(rate.index)
    if len(common) == 0:
        raise ValueError("net and risk-free series share no dates")
    excess = net.loc[common] - rate.loc[common]
    sd = excess.std()               # ddof=1, same convention as net_vol_ratio
    return float(excess.mean() / sd * np.sqrt(periods_per_year(step))) if sd else 0.0


def annualised_risk_free(rf, step: int) -> float:
    """The risk-free leg itself, annualised and in percent — the size of what was omitted."""
    return annualised_return(rf, step)


def stats(r, label: str, step: int = 5, rf=None) -> dict:
    """Both ratios, named, plus the risk-free level that separates them.

    `rf` is optional only so a series with no calendar (a synthetic draw, a unit test) can
    still be described; when it is None the Sharpe keys are None rather than a number that
    would be a lie.
    """
    net = pd.Series(r).dropna().astype(float)
    if net.empty:
        return dict(config=label, cycles=0)
    out = dict(
        config=label,
        cycles=int(len(net)),
        ann_net=round(annualised_return(net, step), 2),
        ratio_net_vol=round(net_vol_ratio(net, step), 2),
        maxdd_net=round(max_drawdown(net), 1),
    )
    if rf is None:
        out.update(sharpe_excess=None, rf_ann_pct=None, ratio_minus_sharpe=None)
        return out
    se = sharpe_excess(net, rf, step)
    rate = pd.Series(rf).astype(float).dropna()
    rate.index = pd.DatetimeIndex(rate.index)
    common = pd.DatetimeIndex(net.index).intersection(rate.index)
    out.update(
        sharpe_excess=round(se, 2),
        rf_ann_pct=round(annualised_risk_free(rate.loc[common], step), 2),
        ratio_minus_sharpe=round(out["ratio_net_vol"] - se, 2),
    )
    return out
