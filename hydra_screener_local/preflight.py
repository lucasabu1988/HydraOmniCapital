"""TASK-352 — refuse to plan on bad data.

Pure function over already-fetched frames (no network). `daily.py` / `portfolio_v9.py`
print the table and stop on a hard fail unless `--force`.
"""
from __future__ import annotations

import os
import pandas as pd

from config import (
    MAX_BAR_AGE_SESSIONS,
    MAX_PRICE_AGE_SESSIONS,
    SECTOR_UNKNOWN_MAX_SHARE,
    V9,
)
from core.portfolio_engine import STATE_SCHEMA
from core.state_check import check as state_check
from data.quality import OBSERVED, classify, invalid_prices, summarize
from data.sectors import sector_degraded_message
from utils.trading_calendar import (
    first_bar_after,
    last_nyse_session_on_or_before,
    nyse_sessions_between,
)

KNOWN_SCHEMA_VERSIONS = {STATE_SCHEMA}
PRINT_SHARE_WARN = 0.90
ETF_UNIVERSE = list(V9["etf_universe"])


def last_bar_date(frame) -> str | None:
    if frame is None or getattr(frame, "empty", True) or len(frame) == 0:
        return None
    return str(pd.Timestamp(frame.index[-1]).normalize().date())


def last_weekday_session(asof) -> str:
    """Last regular NYSE session on or before `asof` (weekends and holidays skipped)."""
    return last_nyse_session_on_or_before(asof)


def _row(check: str, status: str, detail: str) -> dict:
    return {"check": check, "status": status, "detail": detail}


def _sessions_between(_frame, earlier: str, later: str) -> int | None:
    """Regular NYSE sessions strictly after `earlier` up to `later`, or None.

    Measured on the market calendar, not on the frame's own index: a frame that is
    missing the session cannot count it, which is exactly the case the age check
    exists to catch.
    """
    try:
        a, b = pd.Timestamp(earlier).normalize(), pd.Timestamp(later).normalize()
    except (TypeError, ValueError):
        return None
    if a == b:
        return 0
    if b < a:
        return None
    return nyse_sessions_between(a, b)


def evaluate(
    prices: pd.DataFrame | None,
    etf: pd.DataFrame | None,
    irx: pd.Series | pd.DataFrame | None,
    *,
    state: dict | None = None,
    ranking: pd.DataFrame | None = None,
    asof=None,
    last_session: str | None = None,
    backup_dir: str | None = None,
    etf_universe: list[str] | None = None,
    universe_report: dict | None = None,
    reports: dict | None = None,
) -> dict:
    """Run every check. `asof` is the wall-clock (or test clock) used to name the
    last NYSE session when `last_session` is omitted.

    `reports` are the per-frame fetch reports (`{"stocks": ..., "etf": ..., "^IRX": ...}`).
    They carry the provider name, the capture timestamp and the pre-ffill
    `last_observed` map, which is the only evidence that a price on the last bar was
    printed rather than carried (audit phase 2.5/2.6/2.7).
    """
    rows: list[dict] = []
    names = list(etf_universe or ETF_UNIVERSE)
    reports = dict(reports or {})

    stock_d = last_bar_date(prices)
    etf_d = last_bar_date(etf)
    if irx is None or len(irx) == 0:
        irx_d = None
    else:
        irx_d = last_bar_date(irx)

    session = last_session or last_weekday_session(asof if asof is not None else pd.Timestamp.now())
    bars = {"stocks": stock_d, "etf": etf_d, "^IRX": irx_d}
    if None in bars.values():
        missing = [k for k, v in bars.items() if v is None]
        rows.append(_row("last bars", "HARD", f"missing frame(s): {', '.join(missing)}"))
    elif len(set(bars.values())) != 1:
        rows.append(_row(
            "last bars", "HARD",
            f"stocks {stock_d}  etf {etf_d}  ^IRX {irx_d} — must match",
        ))
    elif stock_d != session:
        rows.append(_row(
            "last bars", "HARD",
            f"last bar {stock_d} != last NYSE session {session} (stale yfinance would price yesterday)",
        ))
    else:
        rows.append(_row("last bars", "OK", f"stocks/etf/^IRX = {stock_d} = session"))

    # A bar cannot postdate the as-of instant. Nothing checked this, so a frame
    # whose last row was a month in the future passed clean (repro R-207).
    asof_date = None
    if asof is not None:
        try:
            asof_date = str(pd.Timestamp(asof).normalize().date())
        except (TypeError, ValueError):
            asof_date = None
    if asof_date is None:
        rows.append(_row("bar not in the future", "SKIP", "no asof given"))
    else:
        future = {k: v for k, v in bars.items() if v is not None and v > asof_date}
        if future:
            rows.append(_row(
                "bar not in the future", "HARD",
                f"bar(s) after asof {asof_date}: " + ", ".join(f"{k} {v}" for k, v in sorted(future.items())),
            ))
        else:
            rows.append(_row("bar not in the future", "OK", f"every last bar <= asof {asof_date}"))

    # Explicit staleness budget instead of an implicit one.
    if stock_d is None or session is None:
        rows.append(_row("bar age", "SKIP", "no bar or no session"))
    else:
        age = _sessions_between(prices, stock_d, session)
        if age is None:
            age = 0 if stock_d == session else None
        if age is None:
            rows.append(_row("bar age", "WARN", f"cannot age {stock_d} against {session}"))
        elif age > int(MAX_BAR_AGE_SESSIONS):
            rows.append(_row(
                "bar age", "HARD",
                f"last bar {stock_d} is {age} session(s) before {session}; "
                f"budget MAX_BAR_AGE_SESSIONS={MAX_BAR_AGE_SESSIONS}",
            ))
        else:
            rows.append(_row("bar age", "OK", f"{age} session(s), budget {MAX_BAR_AGE_SESSIONS}"))

    # A finite but non-positive close is impossible. `pd.notna(-3.0)` is True, so a
    # negative ETF close used to pass the "ETFs present" check clean (repro R-206).
    bad_prices: dict[str, dict] = {}
    for label, frame in (("stocks", prices), ("etf", etf)):
        offenders = invalid_prices(frame, stock_d)
        if offenders:
            bad_prices[label] = offenders
    if bad_prices:
        detail = "; ".join(
            f"{label}: " + ", ".join(f"{t}={v!r}" for t, v in sorted(vals.items())[:6])
            + (f" (+{len(vals) - 6} more)" if len(vals) > 6 else "")
            for label, vals in sorted(bad_prices.items())
        )
        rows.append(_row("prices are valid", "HARD", f"close <= 0 or non-finite — {detail}"))
    else:
        rows.append(_row("prices are valid", "OK", "every close on the last bar is finite and > 0"))

    if prices is None or len(prices) == 0:
        rows.append(_row("universe print share", "HARD", "no stock prices"))
        share = 0.0
    else:
        last = prices.iloc[-1]
        share = float(pd.to_numeric(last, errors="coerce").notna().mean()) if len(last) else 0.0
        if share < PRINT_SHARE_WARN:
            rows.append(_row(
                "universe print share", "WARN",
                f"{share:.0%} with a print on {stock_d} (threshold {PRINT_SHARE_WARN:.0%})",
            ))
        else:
            rows.append(_row("universe print share", "OK", f"{share:.0%} with a print on {stock_d}"))

    if etf is None or len(etf) == 0:
        rows.append(_row("ETFs present", "HARD", f"0/{len(names)} — empty ETF frame"))
        n_ok = 0
    else:
        last_e = etf.iloc[-1]
        present = []
        missing_etf = []
        for t in names:
            p = float("nan")
            if t in etf.columns:
                p = pd.to_numeric(last_e.get(t), errors="coerce")
            if pd.notna(p):
                present.append(t)
            else:
                missing_etf.append(t)
        n_ok = len(present)
        if n_ok != len(names):
            rows.append(_row("ETFs present", "HARD", f"{n_ok}/{len(names)} missing {missing_etf}"))
        else:
            rows.append(_row("ETFs present", "OK", f"{n_ok}/{len(names)}"))

    # Provenance: which provider, when it was captured. A recommendation that only
    # carries a date is not reproducible (audit pre-work item 6, phase 2.5).
    provenance = {}
    for label in ("stocks", "etf", "^IRX"):
        rep = reports.get(label) or {}
        provenance[label] = {
            "source": rep.get("source"),
            "fetched_at": rep.get("fetched_at"),
            "last_bar": bars.get(label),
            "ffill_limit_bars": rep.get("ffill_limit_bars"),
            "requested": rep.get("requested"),
            "downloaded": rep.get("downloaded"),
        }
    unknown_src = [k for k, v in provenance.items() if not v["source"] or not v["fetched_at"]]
    if not reports:
        rows.append(_row("provenance", "WARN", "no fetch reports passed; source and capture time unknown"))
    elif unknown_src:
        rows.append(_row("provenance", "WARN", f"no source/timestamp for: {', '.join(sorted(unknown_src))}"))
    else:
        stamps = ", ".join(f"{k}={v['source']}@{v['fetched_at']}" for k, v in sorted(provenance.items()))
        rows.append(_row("provenance", "OK", stamps))

    # A forward-filled price may not authorise an execution (phase 2.6). The ETF
    # sleeve trades a fixed list, so every one of those names must be *printed*
    # on the planning bar, not carried.
    etf_quality = {}
    if etf is None or len(etf) == 0 or stock_d is None:
        rows.append(_row("ETF prices observed", "SKIP", "no ETF frame or no bar"))
    else:
        etf_quality = classify(
            etf[[c for c in etf.columns if c in names]] if len(names) else etf,
            stock_d,
            last_observed=(reports.get("etf") or {}).get("last_observed"),
            max_age_sessions=MAX_PRICE_AGE_SESSIONS,
        )
        summary = summarize(etf_quality)
        not_observed = sorted(t for t, rec in etf_quality.items() if rec["status"] != OBSERVED)
        if not reports.get("etf"):
            rows.append(_row(
                "ETF prices observed", "WARN",
                "no fetch report for the ETF frame: cannot prove these closes were printed, "
                "only that they are present",
            ))
        elif not_observed:
            detail = ", ".join(
                f"{t}={etf_quality[t]['status']}"
                + (f"(last {etf_quality[t]['last_observed']})" if etf_quality[t]["last_observed"] else "")
                for t in not_observed[:8]
            )
            rows.append(_row(
                "ETF prices observed", "HARD",
                f"{len(not_observed)}/{summary['total']} not printed on {stock_d}: {detail}",
            ))
        else:
            rows.append(_row("ETF prices observed", "OK", f"{summary['counts'][OBSERVED]}/{summary['total']} printed on {stock_d}"))

    if ranking is None:
        rows.append(_row("sector-unknown", "SKIP", "no ranking"))
    else:
        msg = sector_degraded_message(ranking)
        if msg:
            rows.append(_row("sector-unknown", "WARN", msg))
        else:
            rows.append(_row(
                "sector-unknown", "OK",
                f"Other share in 2n pool <= {SECTOR_UNKNOWN_MAX_SHARE:.0%}",
            ))

    pending = (state or {}).get("pending") or []
    today = stock_d or (str(pd.Timestamp(asof).date()) if asof is not None else None)
    if not pending:
        rows.append(_row("pending age", "SKIP", "no pending"))
    elif prices is None or len(prices) == 0 or not today:
        rows.append(_row("pending age", "WARN", "pending set but no price calendar"))
    else:
        planned = pending[0].get("planned")
        nxt = first_bar_after(prices.index, planned) if planned else None
        sessions = 0
        if planned:
            idx = pd.DatetimeIndex(prices.index).normalize()
            sessions = int(((idx > pd.Timestamp(planned).normalize())
                            & (idx <= pd.Timestamp(today).normalize())).sum())
        if sessions > 1:
            rows.append(_row(
                "pending age", "WARN",
                f"planned {planned}, {sessions} sessions behind today={today}"
                + (f" (t+1 was bar {nxt})" if nxt is not None else ""),
            ))
        else:
            rows.append(_row("pending age", "OK", f"planned {planned}, {sessions} session(s) behind"))

    env_dir = backup_dir if backup_dir is not None else os.environ.get("HYDRA_BACKUP_DIR")
    if not env_dir:
        rows.append(_row("HYDRA_BACKUP_DIR", "WARN", "unset — state/ backup stays on the same disk"))
    else:
        rows.append(_row("HYDRA_BACKUP_DIR", "OK", env_dir))

    if state is None:
        rows.append(_row("schema_version", "SKIP", "no state yet"))
    else:
        ver = state.get("schema_version")
        if ver not in KNOWN_SCHEMA_VERSIONS:
            rows.append(_row(
                "schema_version", "HARD",
                f"{ver!r} not in {sorted(KNOWN_SCHEMA_VERSIONS)}",
            ))
        else:
            rows.append(_row("schema_version", "OK", f"schema_version={ver}"))

    # Ledger replay vs stored tranches (TASK-360). preflight runs BEFORE settle, so on an
    # execution day the state still carries the pending orders and a ledger <= last_run_date;
    # the replay must be clean in that configuration too (proven on 1084 PIT plans, TASK-369).
    if state is None:
        rows.append(_row("state replay", "SKIP", "no state yet"))
    else:
        try:
            findings = state_check(state)
        except Exception as e:  # a crash in the checker is itself a hard stop
            findings = None
            rows.append(_row("state replay", "HARD", f"check failed: {e}"))
        if findings is not None:
            errs = [f for f in findings if f.level == "ERROR"]
            warns = [f for f in findings if f.level != "ERROR"]
            if errs:
                head = "; ".join(f"{f.code}: {f.message}" for f in errs[:3])
                more = f" (+{len(errs) - 3} more)" if len(errs) > 3 else ""
                rows.append(_row("state replay", "HARD", head + more))
            elif warns:
                head = "; ".join(f"{f.code}: {f.message}" for f in warns[:3])
                rows.append(_row("state replay", "WARN", head))
            else:
                rows.append(_row("state replay", "OK", "ledger replay matches every tranche"))

    # Universe source (TASK-375): a Tuesday run on the hardcoded fallback list is a WARN.
    if universe_report is None:
        rows.append(_row("universe source", "SKIP", "no report"))
    else:
        uname = universe_report.get("universe")
        count = universe_report.get("count")
        if universe_report.get("fallback"):
            rows.append(_row(
                "universe source", "WARN",
                f"{uname} resolved from the hardcoded fallback list ({count} names)",
            ))
        else:
            rows.append(_row(
                "universe source", "OK",
                f"{uname} via {universe_report.get('source_used') or 'network'} "
                f"({count} names, from_cache={universe_report.get('from_cache')})",
            ))

    hard = any(r["status"] == "HARD" for r in rows)
    warn = any(r["status"] == "WARN" for r in rows)
    return {
        "ok": not hard,
        "hard": hard,
        "warn": warn,
        "rows": rows,
        "session": session,
        "print_share": share,
        "etfs_ok": n_ok,
        "provenance": provenance,
        "price_quality": {"etf": etf_quality},
        "invalid_prices": bad_prices,
        "thresholds": {
            "MAX_BAR_AGE_SESSIONS": int(MAX_BAR_AGE_SESSIONS),
            "MAX_PRICE_AGE_SESSIONS": int(MAX_PRICE_AGE_SESSIONS),
            "PRINT_SHARE_WARN": float(PRINT_SHARE_WARN),
        },
    }


def format_table(result: dict) -> str:
    rows = result.get("rows") or []
    width = max((len(r["check"]) for r in rows), default=8)
    lines = ["[v9] preflight"]
    for r in rows:
        lines.append(f"  {r['check']:<{width}}  {r['status']:<4}  {r['detail']}")
    if result.get("hard"):
        lines.append("[v9] preflight HARD fail")
    return "\n".join(lines)


def raise_if_hard(result: dict, force: bool = False) -> None:
    if result.get("hard") and not force:
        raise SystemExit("preflight hard fail; pass --force to plan anyway")
