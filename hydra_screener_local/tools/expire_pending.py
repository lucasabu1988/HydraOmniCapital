"""HYDRA-OPS-02: an instruction sheet that was never executed expires ON THE RECORD.

Why this exists
---------------
The live book planned 30 orders on 2026-09-04 for execution at the close of 2026-09-08.
Nothing was executed (Lucas, confirmed 2026-09-13). So the book sat with 30 entries in
`state["pending"]` and an EMPTY ledger - and `engine.plan` refuses to plan a new week while
anything is pending (`core/portfolio_engine.py:469`), so the book could not advance at all.

`confirm_fills.py` is NOT the tool for this, and that is worth writing down because it is the
obvious wrong turn. Confirming `units=0` means "the broker never filled this planned line",
and `core/fills.py:238` requires a matching planned line IN THE LEDGER to attach it to. The
settle never ran, so nothing was ever booked as presumed: there is no event to correct, and
every row would come back rejected with "units=0 confirms a planned line never filled, but no
plan matches this key". An empty ledger is not a confirmation problem.

What expiry is, and what it is not
----------------------------------
It is a RECLASSIFICATION, not a deletion. Each order moves from `pending` - an obligation the
engine will settle at the next close - to `expired`, a record of an instruction that was
issued and never acted on. Every field it had is kept, plus when it expired, why, and who
decided.

It moves NO money, and that is asserted rather than promised: nothing filled, so there is
nothing to reverse, and `_fingerprint()` is compared before and after across cash, units, last
marks, the ledger, `capital_reference`, `week_index`, `anchor_date`, `last_run_date`,
`last_renewal_date` and every tranche's `opened` mark. A single difference is a refusal with
the state unwritten.

`opened` stays in particular. The tranche really was renewed on 2026-09-04: a plan ran, a
renewal slot was consumed, a sheet was issued. What did not happen is the execution - and that
is exactly what this records. Rewriting `opened` would be inventing a different history, and
`renewal_slot` counts from `anchor_date` and `week_index` anyway, so it would change nothing
about the schedule while making the state say something false.

It refuses instead of guessing when a premise does not hold: no reason given, the plan is not
yet past its execution day, the ledger already carries events from this plan, or the settle
left obligations in `state["unfilled"]`. In each of those the right tool is a different one,
and the message says which.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: where the reclassified orders land. A new key, never an existing one: `write_offs` is the
#: engine's record of positions written off inside a sleeve, and reusing it would make an
#: unexecuted instruction look like a lost holding.
EXPIRED_KEY = "expired"

#: a reason has to say something. The bar is deliberately low and deliberately non-zero: the
#: point is that a human wrote a sentence, the same rule `--force` got in OPS4-01.
MIN_REASON_CHARS = 12


class ExpiryRefused(SystemExit):
    """Nothing was written. The message names the premise that did not hold."""


def _who() -> dict:
    """Whatever identity this machine can actually offer. Never invented."""
    import getpass
    import platform
    try:
        user = getpass.getuser()
    except Exception:                                    # noqa: BLE001 - recorded as unknown
        user = None
    return dict(user=user, host=platform.node() or None)


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def plan_dates(pending: list) -> list:
    """Every distinct `planned` date among the pending orders, in order."""
    out = []
    for o in pending or []:
        d = str(o.get("planned") or "")
        if d and d not in out:
            out.append(d)
    return out


def _fingerprint(state: dict) -> dict:
    """Everything expiry must leave exactly as it found it."""
    sleeves = {}
    for name, sl in (state.get("sleeves") or {}).items():
        sleeves[name] = [
            dict(k=t.get("k"), opened=t.get("opened"), cash=t.get("cash"),
                 units=dict(t.get("units") or {}), last_px=dict(t.get("last_px") or {}),
                 stale=dict(t.get("stale") or {}))
            for t in (sl.get("tranches") or [])
        ]
    return dict(
        sleeves=sleeves,
        ledger=copy.deepcopy(state.get("ledger") or []),
        transfers=copy.deepcopy(state.get("transfers") or []),
        write_offs=copy.deepcopy(state.get("write_offs") or []),
        unfilled=copy.deepcopy(state.get("unfilled") or []),
        dividends=copy.deepcopy(state.get("dividends") or []),
        capital_reference=state.get("capital_reference"),
        week_index=state.get("week_index"),
        anchor_date=state.get("anchor_date"),
        last_run_date=state.get("last_run_date"),
        last_renewal_date=state.get("last_renewal_date"),
        algo_version=state.get("algo_version"),
        schema_version=state.get("schema_version"),
    )


def _differences(before: dict, after: dict) -> list:
    """Named differences, not a bare boolean - a refusal has to say what moved."""
    return [key for key in sorted(set(before) | set(after))
            if before.get(key) != after.get(key)]


def refusals(state: dict, today: str, reason: str) -> list:
    """Every premise that does not hold. Collected, not short-circuited."""
    out = []
    if len((reason or "").strip()) < MIN_REASON_CHARS:
        out.append(
            f"--reason must say what expired and why (at least {MIN_REASON_CHARS} characters). "
            "This writes the live book; an unexplained edit is indistinguishable from a mistake.")

    pending = list(state.get("pending") or [])
    dates = plan_dates(pending)
    if not dates:
        out.append("the pending orders carry no `planned` date, so there is no plan to expire")
    for d in dates:
        if str(today) <= str(d):
            out.append(
                f"the plan of {d} has not reached its execution day yet (today={today}): orders "
                "waiting for t+1 are not expired, they are waiting. Re-run after the close.")

    booked = [e for e in (state.get("ledger") or []) if str(e.get("planned") or "") in dates]
    if booked:
        out.append(
            f"{len(booked)} ledger event(s) already carry planned={dates}: this plan WAS settled, "
            "at least in part. Expiry is for a plan nothing was booked from; correct booked "
            "events with confirm_fills.py (--from-csv, or --cancel by event_id).")

    unfilled = list(state.get("unfilled") or [])
    if unfilled:
        out.append(
            f"{len(unfilled)} unresolved obligation(s) in state['unfilled']: a settle ran and "
            "could not book them. Answer those with confirm_fills.py first - expiring around "
            "them would leave the ASTRA-03 HARD gate standing with nothing to clear it.")
    return out


def expire(state: dict, *, reason: str, today: str, run_id=None, by=None) -> dict:
    """Move `pending` to `expired` in place. Raises ExpiryRefused and changes nothing otherwise."""
    pending = list(state.get("pending") or [])
    if not pending:
        return dict(expired=0, orders=[], plans=[], no_op=True,
                    why="nothing pending: the book has no unsettled instructions")

    problems = refusals(state, today, reason)
    if problems:
        raise ExpiryRefused(
            "refusing to expire; nothing was written:\n  - " + "\n  - ".join(problems))

    plans = plan_dates(pending)
    before = _fingerprint(state)
    stamp = dict(expired_on=str(today), expired_reason=reason.strip(),
                 expired_at_utc=_utc_now_iso(), expired_by=by or _who(),
                 expired_run_id=run_id,
                 expired_note="issued and never executed; no fill was ever booked for it")
    records = [dict(o, **stamp) for o in pending]

    state.setdefault(EXPIRED_KEY, []).extend(records)
    state["pending"] = []

    moved = _differences(before, _fingerprint(state))
    if moved:
        # Cannot happen by construction, which is exactly why it is checked: the whole claim of
        # this tool is that it is economically inert, and a claim nothing tests is a comment.
        state["pending"] = pending
        del state[EXPIRED_KEY][len(state[EXPIRED_KEY]) - len(records):]
        raise ExpiryRefused(
            "refusing to expire; nothing was written: expiry changed " + ", ".join(moved)
            + " and it must change nothing but `pending` and `expired`.")

    return dict(expired=len(records), orders=records, plans=plans, no_op=False,
                why=reason.strip())


def report_lines(rep: dict, state: dict) -> list:
    if rep.get("no_op"):
        return [f"[expire] {rep['why']} - nothing to do"]
    tickers = sorted({str(o.get("ticker")) for o in rep["orders"]})
    dollars = sum(float(o.get("dollars") or 0.0) for o in rep["orders"])
    by_sleeve = {}
    for o in rep["orders"]:
        by_sleeve[str(o.get("sleeve"))] = by_sleeve.get(str(o.get("sleeve")), 0) + 1
    return [
        f"[expire] {rep['expired']} order(s) planned {', '.join(rep['plans'])} -> expired",
        "[expire]   by sleeve: " + ", ".join(f"{k}={v}" for k, v in sorted(by_sleeve.items())),
        f"[expire]   {len(tickers)} ticker(s), {dollars:,.2f} USD of instructions never executed",
        f"[expire]   reason: {rep['why']}",
        f"[expire]   ledger stays at {len(state.get('ledger') or [])} event(s); "
        "no cash and no units moved",
    ]


def backup_pre_change(state_dir: Path, today: str, book, silent: bool = False):
    """A verified off-disk generation of the PRE-change book, or None if there is no destination."""
    from portfolio_v9 import STATE_NAME, copy_state_off_disk
    files = [state_dir / STATE_NAME]
    files += sorted(state_dir.glob("instructions_*.json"))
    files += sorted(state_dir.glob("instructions_*.md"))
    return copy_state_off_disk(today, files, silent=silent, book=book)


def main(argv=None) -> int:
    from portfolio_v9 import DEFAULT_STATE_DIR, STATE_NAME, load_state, save_state

    p = argparse.ArgumentParser(
        description="Reclassify unexecuted pending orders as expired (HYDRA-OPS-02)")
    p.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    p.add_argument("--reason", default="", help="what expired and why (required)")
    p.add_argument("--today", default=None, help="date of the decision (default: today)")
    p.add_argument("--apply", action="store_true",
                   help="write the state. Without it this is a dry run and touches nothing.")
    p.add_argument("--no-backup", action="store_true",
                   help="apply even though no off-disk generation could be written")
    args = p.parse_args(argv)

    from datetime import date as _date
    today = args.today or str(_date.today())
    state_dir = Path(args.state_dir)
    path = state_dir / STATE_NAME
    state = load_state(path)
    if not state:
        print(f"[expire] no state at {path}")
        return 1

    # The dry run rehearses on a COPY, so a refusal and a success leave the same file on disk.
    try:
        rep = expire(copy.deepcopy(state), reason=args.reason, today=today)
    except ExpiryRefused as exc:
        print(str(exc))
        return 2

    for line in report_lines(rep, state):
        print(line)
    if rep.get("no_op"):
        return 0
    if not args.apply:
        print("[expire] DRY RUN - nothing written. Re-run with --apply to commit.")
        return 0

    from core.books import book_of
    book = book_of(state_dir)
    generation = None
    try:
        generation = backup_pre_change(state_dir, today, book, silent=False)
    except Exception as exc:                             # noqa: BLE001 - reported, then decided
        print(f"[expire] off-disk backup FAILED: {type(exc).__name__}: {exc}")
    if generation is None and not args.no_backup:
        print("[expire] ABORT - no verified off-disk generation of the pre-change book was "
              "written, and this edits the live book. Set HYDRA_BACKUP_DIR to a reachable "
              "destination, or pass --no-backup to proceed without one on the record.")
        return 3
    if generation is not None:
        print(f"[expire] pre-change generation: {generation}")

    rep = expire(state, reason=args.reason, today=today)

    from core.ledger import check_invariants, format_violations
    violations = check_invariants(state)
    if violations:
        print(format_violations(violations))
        print("[expire] ABORT - invariants broken; state not written")
        return 1

    backup = save_state(path, state)
    print(f"[expire] wrote {path}" + (f" (local backup {backup})" if backup else ""))

    try:
        import journal
        journal.append_error(
            f"HYDRA-OPS-02: {rep['expired']} pending order(s) planned "
            f"{', '.join(rep['plans'])} reclassified as expired - {rep['why']}",
            today=today, state_dir=state_dir)
    except Exception as exc:                             # noqa: BLE001 - the write already landed
        print(f"[expire] AVISO: journal entry not written ({type(exc).__name__}: {exc})")

    out = state_dir / f"expired_{today.replace('-', '')}.json"
    out.write_text(json.dumps(rep["orders"], indent=1, default=str), encoding="utf-8")
    print(f"[expire] the expired instructions are also written verbatim to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
