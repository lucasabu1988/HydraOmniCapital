"""Operational alerts for the v9 daily run (audit phase 9.8). Pure; no I/O, no network.

The run already refuses to proceed on a hard preflight failure. These are the
conditions that do not stop a run but must not go unnoticed either: stale data, a
missing instruction sheet, cash the broker and the book disagree about, a partially
executed week, an unverified dividend window, or a run left needing recovery.

Everything here is derived from the run's own outputs, so an unattended run can print
them and a notifier can forward them without re-deriving anything.
"""
from __future__ import annotations

from core.numbers import as_finite

# severities, most serious first
ERROR = "ERROR"
WARN = "WARN"
INFO = "INFO"
SEVERITY_ORDER = {ERROR: 0, WARN: 1, INFO: 2}

#: how much unexplained cash difference is worth an alert, in dollars
CASH_RESIDUAL_TOL = 1.0


class Alert:
    __slots__ = ("level", "code", "message")

    def __init__(self, level: str, code: str, message: str):
        self.level = level
        self.code = code
        self.message = message

    def __repr__(self) -> str:
        return f"Alert({self.level!r}, {self.code!r}, {self.message!r})"

    def __eq__(self, other) -> bool:
        return isinstance(other, Alert) and \
            (self.level, self.code, self.message) == (other.level, other.code, other.message)

    def as_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "message": self.message}


def collect(out: dict | None = None, *, state: dict | None = None,
            instructions_exists: bool | None = None,
            reconcile: dict | None = None,
            pending_runs: list | None = None) -> list[Alert]:
    """Every alert this run raises, most serious first.

    `out` is `portfolio_v9.run()`'s return dict. Each source is optional so the
    function is usable from the dashboard and from a scheduler that only has part of
    the picture.
    """
    out = dict(out or {})
    state = state if state is not None else out.get("state")
    alerts: list[Alert] = []

    # --- stale or degraded data ---------------------------------------------------
    pf = out.get("preflight") or {}
    for row in pf.get("rows") or []:
        if row.get("status") == "HARD":
            alerts.append(Alert(ERROR, "preflight_hard",
                                f"{row.get('check')}: {row.get('detail')}"))
        elif row.get("status") == "WARN":
            alerts.append(Alert(WARN, "preflight_warn",
                                f"{row.get('check')}: {row.get('detail')}"))

    quality = (pf.get("price_quality") or {}).get("etf") or {}
    not_observed = sorted(t for t, rec in quality.items() if rec.get("status") != "observed")
    if not_observed:
        alerts.append(Alert(ERROR, "stale_prices",
                            f"{len(not_observed)} ETF close(s) not printed on the planning bar: "
                            f"{', '.join(not_observed[:6])}"))

    if out.get("sector_warning"):
        alerts.append(Alert(WARN, "sectors_degraded", str(out["sector_warning"])))

    # --- the sheet -----------------------------------------------------------------
    if instructions_exists is False:
        alerts.append(Alert(ERROR, "sheet_missing",
                            f"instruction sheet not on disk: {out.get('instructions_md')}"))

    # --- partial or unfinished execution -------------------------------------------
    status = str(out.get("run_status") or "")
    if status == "failed_pending_recovery":
        alerts.append(Alert(ERROR, "recovery_required",
                            f"run {out.get('run_id')} needs recovery before the next run"))
    elif status and status not in ("committed", "settled"):
        alerts.append(Alert(WARN, "run_incomplete", f"run {out.get('run_id')} ended {status!r}"))

    for run in (pending_runs or []):
        if run.get("needs_recovery"):
            alerts.append(Alert(ERROR, "recovery_required",
                                f"staged run {run.get('run_id')} is past COMMIT_INTENT"))

    pending = list((state or {}).get("pending") or [])
    if pending:
        planned = pending[0].get("planned")
        today = out.get("today")
        if planned and today and str(planned) < str(today):
            alerts.append(Alert(WARN, "awaiting_confirmation",
                                f"{len(pending)} order(s) planned {planned} still unsettled "
                                f"on {today}"))

    for err in (out.get("errors") or []):
        alerts.append(Alert(ERROR, "run_error", str(err)))

    data_errors = list((state or {}).get("data_errors") or [])
    today = out.get("today")
    todays = [e for e in data_errors if str(e.get("date")) == str(today)] if today else data_errors
    if todays:
        names = sorted({str(e.get("ticker")) for e in todays})
        alerts.append(Alert(WARN, "orders_refused",
                            f"{len(todays)} order(s) refused on unusable prices: "
                            f"{', '.join(names[:6])}"))

    # --- dividends ------------------------------------------------------------------
    dv = out.get("dividend_report") or {}
    if dv and dv.get("verified") is False:
        alerts.append(Alert(WARN, "dividends_unverified",
                            f"dividend coverage held at {dv.get('coverage_through')}; "
                            f"{dv.get('open_gaps')} open gap(s)"))
    for conflict in dv.get("conflicts") or []:
        alerts.append(Alert(WARN, "dividend_conflict",
                            f"{conflict.get('ticker')} {conflict.get('ex_date')}: "
                            f"conflicting amounts {conflict.get('values')}"))
    for bad in dv.get("rejected") or []:
        alerts.append(Alert(WARN, "dividend_rejected", str(bad.get("reason"))))

    # --- cash reconciliation ---------------------------------------------------------
    rec = reconcile if reconcile is not None else out.get("reconcile")
    if rec:
        residual = as_finite((rec or {}).get("residual"))
        if residual is not None and abs(residual) > CASH_RESIDUAL_TOL:
            alerts.append(Alert(ERROR, "cash_unreconciled",
                                f"unexplained residual {residual:,.2f} USD between the broker "
                                f"and the book"))
        for name, diff in sorted(((rec or {}).get("units_diff") or {}).items()):
            alerts.append(Alert(ERROR, "units_unreconciled",
                                f"{name}: broker and book differ by {diff}"))

    alerts.sort(key=lambda a: (SEVERITY_ORDER.get(a.level, 9), a.code, a.message))
    return alerts


def worst_level(alerts: list[Alert]) -> str | None:
    if not alerts:
        return None
    return min((a.level for a in alerts), key=lambda level: SEVERITY_ORDER.get(level, 9))


def has_errors(alerts: list[Alert]) -> bool:
    return any(a.level == ERROR for a in alerts)


def format_alerts(alerts: list[Alert]) -> str:
    if not alerts:
        return "alerts: none"
    lines = [f"alerts: {len(alerts)} ({sum(1 for a in alerts if a.level == ERROR)} error)"]
    for a in alerts:
        lines.append(f"  {a.level:<5} {a.code:<22} {a.message}")
    return "\n".join(lines)
