"""Where a macro level sits in its own history - pure, offline, and honest about the sample.

Companion to `data/macro.py` (phase 1 of the Buffett-indicator work, Lucas 2026-09-08). That
module fetches and snapshots; this one turns a level into a position within a history, which is
the only form in which such a number could ever reach a decision.

Two rules are baked in because both are places this kind of number goes wrong:

1. **Expanding, never full-sample.** The percentile of the value at t is computed against the
   values known UP TO t. Ranking today's reading inside a window that includes 2030 is the same
   look-ahead as ranking a stock against its own future.
2. **The effective sample size travels with the number.** The indicator is autocorrelated at
   ~0.98 per quarter, so 85 quarters are not 85 observations. `describe()` reports how many
   independent EPISODES the series actually contains (threshold crossings, not observations), and
   `enough_episodes_to_decide()` is the gate H-008 has to pass before anyone builds a rule on it.
   Measured 2026-09-08 on the real FRED series: **14 episodes since 1947, but only 4 that overlap
   the 2004-2026 window where a price panel exists** - and two of those four last 3 and 4 quarters
   while the other two are single runs of 54 and 58 quarters. So the gate passes on the macro
   history and FAILS on the window a backtest could use, which is the whole reason phase 2 stops
   at a pre-registration.

A third property falls out of the first two and is worth knowing before building anything on it:
a **percentile rule habituates**. With a midrank expanding percentile, a level that stays elevated
stops scoring as extreme - 8 flat quarters followed by identical high ones give a run that ends
after 5 observations, because the high value becomes the norm it is compared against. That is the
standard real-world criticism of the Buffett indicator (expensive since 2013 and still climbing),
and it is a feature here, not a defect to be "fixed" with a full-sample percentile, which would be
look-ahead. Pinned by `test_episodes_are_contiguous_runs_not_observations`.

Nothing in `core/` does network I/O; nothing here reads a clock. Pass the series in.
"""
from __future__ import annotations

MIN_EPISODES_TO_DECIDE = 5
DEFAULT_EXPENSIVE_PERCENTILE = 80.0


def _sorted_items(series: dict) -> list[tuple[str, float]]:
    return sorted(((str(k), float(v)) for k, v in series.items()), key=lambda kv: kv[0])


def percentile_as_known(series: dict, at: str, *, min_history: int = 8) -> float | None:
    """Where the value at `at` sits among the values known up to and including `at`, 0-100.

    None when `at` is not in the series, or when fewer than `min_history` observations precede
    it - a percentile over three points is noise wearing a number's clothes.
    """
    items = _sorted_items(series)
    known = [v for k, v in items if k <= str(at)]
    if not known or str(at) not in {k for k, _ in items}:
        return None
    if len(known) < min_history:
        return None
    value = next(v for k, v in items if k == str(at))
    below = sum(1 for v in known if v < value)
    ties = sum(1 for v in known if v == value)
    # midrank, so a value equal to everything seen scores 50 rather than 0 or 100
    return round(100.0 * (below + 0.5 * ties) / len(known), 2)


def expanding_percentiles(series: dict, *, min_history: int = 8) -> dict:
    """{date: percentile as known then}. Dates without enough history are omitted, not zeroed."""
    out = {}
    for date, _ in _sorted_items(series):
        pct = percentile_as_known(series, date, min_history=min_history)
        if pct is not None:
            out[date] = pct
    return out


def episodes(series: dict, *, threshold_pct: float = DEFAULT_EXPENSIVE_PERCENTILE,
             min_history: int = 8, window_start: str | None = None) -> list[dict]:
    """Contiguous runs above `threshold_pct` of the expanding percentile.

    This is the honest unit of sample size for a slow indicator: a rule that acts when the
    indicator is 'expensive' gets one observation per EPISODE, not one per quarter.

    `window_start` keeps only episodes that reach into the window where a test could actually
    run - i.e. where a price panel exists. The percentile is still expanding over ALL history
    known at each date, so no information is thrown away; what shrinks is the count of episodes
    that a backtest on that window could observe. Measured 2026-09-08 on the FRED series: 14
    episodes since 1947, but only **4** overlap 2004-2026, and two of those last 3 and 4 quarters
    while the other two are single runs of 54 and 58 quarters. The 2011-2026 stretch is ONE
    observation, not 58.
    """
    pcts = expanding_percentiles(series, min_history=min_history)
    runs, current = [], None
    for date in sorted(pcts):
        above = pcts[date] >= threshold_pct
        if above and current is None:
            current = {"start": date, "end": date, "observations": 1,
                       "peak_percentile": pcts[date]}
        elif above:
            current["end"] = date
            current["observations"] += 1
            current["peak_percentile"] = max(current["peak_percentile"], pcts[date])
        elif current is not None:
            runs.append(current)
            current = None
    if current is not None:
        runs.append(current)
    if window_start is not None:
        runs = [r for r in runs if r["end"] >= str(window_start)]
    return runs


def enough_episodes_to_decide(series: dict, *, threshold_pct: float = DEFAULT_EXPENSIVE_PERCENTILE,
                              minimum: int = MIN_EPISODES_TO_DECIDE, min_history: int = 8,
                              window_start: str | None = None) -> dict:
    """The gate H-008 must pass before the indicator is allowed to change anything.

    Pre-declared, so the answer cannot be renegotiated after looking at returns: fewer than
    `minimum` independent episodes means the effect is not measurable on this data, and the
    pre-registered conclusion is 'unmeasurable', not 'no effect' and not 'small effect'.
    """
    eps = episodes(series, threshold_pct=threshold_pct, min_history=min_history,
                   window_start=window_start)
    return {
        "episodes": len(eps),
        "window_start": str(window_start) if window_start else None,
        "minimum_required": minimum,
        "enough": len(eps) >= minimum,
        "detail": eps,
        "verdict": ("enough episodes to attempt a measurement" if len(eps) >= minimum else
                    f"{len(eps)} episode(s) against a pre-declared minimum of {minimum}: "
                    f"UNMEASURABLE on this sample - not 'no effect'"),
    }


def describe(series: dict, at: str | None = None, *,
             threshold_pct: float = DEFAULT_EXPENSIVE_PERCENTILE, min_history: int = 8,
             window_start: str | None = None) -> dict:
    """One record for a run log: level, where it sits, and how little the sample supports."""
    items = _sorted_items(series)
    if not items:
        return {"observations": 0, "value": None, "percentile": None, "episodes": 0,
                "note": "empty series"}
    at = str(at) if at is not None else items[-1][0]
    value = dict(items).get(at)
    gate = enough_episodes_to_decide(series, threshold_pct=threshold_pct,
                                     minimum=MIN_EPISODES_TO_DECIDE, min_history=min_history,
                                     window_start=window_start)
    return {
        "as_of": at,
        "value": round(value, 4) if value is not None else None,
        "percentile_as_known": percentile_as_known(series, at, min_history=min_history),
        "observations": len(items),
        "first": items[0][0],
        "last": items[-1][0],
        "min": round(min(v for _, v in items), 4),
        "max": round(max(v for _, v in items), 4),
        "median": round(sorted(v for _, v in items)[len(items) // 2], 4),
        "episodes_above_threshold": gate["episodes"],
        "episode_window_start": gate["window_start"],
        "enough_episodes_to_decide": gate["enough"],
        "note": "observability only; this number changes no order (phase 1, H-008 PROPOSED)",
    }
