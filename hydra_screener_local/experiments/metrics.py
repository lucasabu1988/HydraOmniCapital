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


def max_drawdown(r) -> float:
    """Worst peak-to-trough of the compounded step returns, in percent (negative)."""
    x = pd.Series(r).dropna().astype(float)
    if x.empty:
        return float("nan")
    eq = (1 + x).cumprod()
    return float((eq / eq.cummax() - 1).min()) * 100


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
