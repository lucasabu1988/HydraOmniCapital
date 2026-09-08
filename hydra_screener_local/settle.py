"""Drive the settle: snapshot first, confirm, reconcile, verify - and do the arithmetic for you.

The sequence in `.comms/merge-window-2026-09-09.md` works, but it leaves two things to human
memory at nine in the morning, and both were found the hard way:

1. **The snapshot.** `core/fills.apply_confirmations` does `fill.update(price=...)`, so confirming
   overwrites the PRESUMED price - the settle-day close the engine filled at - in place, and
   `report_lines()` never prints it. Miss the copy and the slippage of those fills is gone: the
   only reference left is `est_price`, the planning close, which mixes the overnight move into
   the execution. This driver takes the snapshot before anything writes, always.

2. **The residual is not supposed to be zero.** `accrue_interest` runs inside `plan()` and writes
   interest straight into each tranche's cash (`core/portfolio_engine.py`), so that money is in
   the book and not at the broker until the broker credits it. `reconcile.py` computes
   `residual = broker_cash - state_cash` and **deliberately subtracts nothing** ("we do not know
   which have settled"), so the residual comes out NEGATIVE by roughly the accrued interest. This
   driver reads both numbers out of reconcile's own output and nets them, so what you read is the
   part that is actually unexplained.

What it deliberately does NOT do: run `daily.py`. That step needs the real close and is the one
piece of the live path that has to run exactly as rehearsed - run it yourself first. This driver
starts at the confirmation and only ever INVOKES the live CLIs as subprocesses; it does not
import them, patch them, or pass `--force` to anything.

    python settle.py --fills fills.csv --state-dir <copy>      # rehearse against a copy
    python settle.py --fills fills.csv                         # snapshot + report, then stops
    python settle.py --fills fills.csv --write \\
                     --positions positions.csv --cash-total 85560.91

The safe default is deliberate: without `--write` nothing touches the book, and you get the diff
to read - which is the step the runbook asks for before writing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(HERE))

# resolved from --state-dir so the whole driver can be rehearsed against a COPY. Without this
# the only way to test it was on the live book, which is not a test.
STATE_DIR = HERE / "state"
STATE_FILE = STATE_DIR / "portfolio_v9.json"
BACKUP_DIR = STATE_DIR / "backup"


def use_state_dir(path) -> None:
    global STATE_DIR, STATE_FILE, BACKUP_DIR
    STATE_DIR = Path(path)
    STATE_FILE = STATE_DIR / "portfolio_v9.json"
    BACKUP_DIR = STATE_DIR / "backup"


# a residual this far from the interest explanation is worth stopping over, not shrugging at
RESIDUAL_TOLERANCE_PCT = 0.5

NUMBER = r"(-?[\d,]+\.?\d*)"


def _short(path: Path) -> str:
    """Repo-relative when it can be; absolute otherwise. `relative_to` RAISES on an outside path,
    and the rehearsal state dir is deliberately outside the repo."""
    try:
        return str(Path(path).relative_to(HERE))
    except ValueError:
        return str(path)


def _num(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except (TypeError, ValueError, AttributeError):
        return None


def parse_reconcile(out: str) -> dict:
    """Pull the two numbers that matter out of reconcile's own report.

    Parsed rather than recomputed on purpose: if this driver did its own arithmetic on the state
    it could agree with itself while disagreeing with the tool Lucas is reading.
    """
    got = {}
    for key, pattern in (
        ("interest_recorded", rf"interest recorded\s+{NUMBER}"),
        ("dividends_recorded", rf"dividends recorded\s+{NUMBER}"),
        ("fees_recorded", rf"fees recorded\s+{NUMBER}"),
        ("pending_buys", rf"pending buys\s+{NUMBER}"),
        ("pending_sells", rf"pending sells\s+{NUMBER}"),
        ("residual", rf"unexplained residual\s+{NUMBER}"),
        ("residual_pct", rf"unexplained residual.*?\(\s*{NUMBER}%"),
        ("cash_delta", rf"delta\s+{NUMBER}"),
        ("state_equity", rf"equity at state last_px\s+state\s+{NUMBER}"),
    ):
        m = re.search(pattern, out)
        if m:
            got[key] = _num(m.group(1))
    counts = re.search(
        r"match (\d+)\s+missing\(state-only\) (\d+)\s+unknown\(broker-only\) (\d+)\s+"
        r"quantity-diff (\d+)", out)
    if counts:
        got.update(match=int(counts.group(1)), missing=int(counts.group(2)),
                   unknown=int(counts.group(3)), quantity_diff=int(counts.group(4)))
    return got


def net_residual(rep: dict) -> dict:
    """What is left once the money that is in the book but not yet at the broker is netted out.

    `residual = broker_cash - state_cash`, and interest and ex-date dividends sit in state cash
    only, so each of them pushes the residual negative. Adding them back is the netting.

    The honest caveat, which the output carries: reconcile's figures are **cumulative** over the
    whole life of the book. Until the broker credits interest for the first time, cumulative and
    unpaid are the same number and this netting is exact. After that first credit they diverge,
    and this line has to be read as an upper bound rather than an identity.
    """
    residual = rep.get("residual")
    if residual is None:
        return {"ok": False, "reason": "reconcile printed no residual line"}
    interest = rep.get("interest_recorded") or 0.0
    dividends = rep.get("dividends_recorded") or 0.0
    netted = residual + interest + dividends
    equity = rep.get("state_equity") or 0.0
    pct = (abs(netted) / equity * 100.0) if equity else None
    return {
        "ok": True,
        "residual": round(residual, 4),
        "interest_in_book_not_at_broker": round(interest, 4),
        "dividends_ex_date_not_yet_paid": round(dividends, 4),
        "netted": round(netted, 4),
        "netted_pct_of_equity": round(pct, 4) if pct is not None else None,
        "within_tolerance": (pct is not None and pct <= RESIDUAL_TOLERANCE_PCT),
        "expected_sign": ("negative: interest and ex-date dividends are in the book and not at "
                          "the broker, so broker - state comes out below zero"),
        "cumulative_caveat": ("reconcile's interest/dividends are CUMULATIVE. Exact while the "
                              "broker has never credited interest; an upper bound after it has."),
    }


def explain_verify(out: str) -> dict:
    """Tell an expected attribution artefact apart from a real accounting failure.

    `accrue_interest` credits each tranche `cash * factor` from the cash as it stood when `plan()`
    ran - i.e. from the PRESUMED fills. `confirm_fills` then replaces those with the real ones and
    the tranche cash moves. `core/state_check.replay` re-derives the interest split from the
    post-confirmation weights (`_apply_interest` divides the sleeve's dollars by tranche weight),
    so stored and replayed cash disagree per tranche while the sleeve TOTAL is identical.

    Rehearsed on a copy 2026-09-08: 8 `ERROR replay_cash`, sleeve totals equal to 0.00e+00, units
    identical, worst tranche difference 0.2293 USD. Expect the same tomorrow. It is an attribution
    artefact, not a lost dollar - but this function proves that per run instead of assuming it, and
    anything that is NOT replay_cash is reported as the failure it is.
    """
    codes = set(re.findall(r"^\s*(?:ERROR|WARN)\s+(\w+)", out, re.M))
    result = {"codes": sorted(codes), "clean": not codes}
    if not codes or codes - {"replay_cash"}:
        result["explained"] = False
        result["reason"] = ("clean" if not codes else
                            f"findings beyond the known artefact: {sorted(codes - {'replay_cash'})}")
        return result
    try:
        from core.state_check import replay
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            st = json.load(f)
        rec = replay(st)
        sleeves, worst, units_ok = {}, 0.0, True
        for sl, blk in (st.get("sleeves") or {}).items():
            stored = sum(float(t.get("cash") or 0.0) for t in blk.get("tranches") or [])
            rebuilt = sum(float(t.get("cash") or 0.0) for t in rec[sl]["tranches"])
            sleeves[sl] = {"stored": round(stored, 6), "replayed": round(rebuilt, 6),
                           "diff": round(stored - rebuilt, 8)}
            for a, b in zip(blk.get("tranches") or [], rec[sl]["tranches"], strict=False):
                worst = max(worst, abs(float(a.get("cash") or 0.0) - float(b.get("cash") or 0.0)))
                for k in set(a.get("units") or {}) | set(b.get("units") or {}):
                    if abs(float((a.get("units") or {}).get(k, 0.0))
                           - float((b.get("units") or {}).get(k, 0.0))) > 1e-9:
                        units_ok = False
        totals_match = all(abs(v["diff"]) < 1e-6 for v in sleeves.values())
        result.update(explained=bool(totals_match and units_ok), sleeves=sleeves,
                      worst_tranche_diff=round(worst, 4), units_identical=units_ok,
                      reason=("interest attributed per tranche at accrual time, re-split by the "
                              "replay from post-confirmation weights: sleeve totals identical, "
                              "units identical, difference is attribution only"
                              if totals_match and units_ok else
                              "replay_cash with a sleeve total that does NOT match: this is not "
                              "the attribution artefact, treat it as a real break"))
    except Exception as e:                                  # never let the explainer be the failure
        result.update(explained=False, reason=f"could not replay the state to explain: {e}")
    return result


def order_guard(fills_csv: str) -> dict:
    """The mistake this driver exists to make impossible.

    `confirm_fills` matches a CSV row against the **ledger**, and the ledger only gets rows when
    `settle()` runs inside `daily.py`. Confirm before that and every row misses its key, takes the
    `confirmed_unplanned` branch of `core/fills.apply_confirmations` - which **still applies the
    units and the cash to the tranche** - while the pending orders stay pending and get settled
    again on the next run. Double position, wrong cash, and not one error message: rehearsed on a
    copy 2026-09-08, 26 of 26 rows came back `confirmed_unplanned  matched False`.

    So: if the book has pending orders and the ledger has nothing for the CSV's execution date,
    stop and say which command is missing.
    """
    import csv as _csv
    try:
        with open(fills_csv, "r", encoding="utf-8", newline="") as f:
            rows = list(_csv.DictReader(f))
    except OSError as e:
        return {"ok": False, "reason": f"cannot read {fills_csv}: {e}"}
    if not rows:
        return {"ok": False, "reason": f"{fills_csv} has no rows"}
    dates = {str(r.get("exec_date", "")).strip() for r in rows if r.get("exec_date")}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            st = json.load(f)
    except Exception as e:
        return {"ok": False, "reason": f"cannot read the state: {e}"}
    ledger = st.get("ledger") or []
    pending = st.get("pending") or []
    settled_dates = {str(f.get("exec_date")) for f in ledger}
    covered = dates & settled_dates
    if pending and not covered:
        return {
            "ok": False,
            "reason": (f"the ledger has nothing for {sorted(dates)} and {len(pending)} order(s) "
                       f"are still pending: `daily.py` has not settled them yet. Confirming now "
                       f"would book every row as `confirmed_unplanned` - applied to the tranches "
                       f"anyway - and leave the {len(pending)} pending to settle AGAIN on the "
                       f"next run: double position, wrong cash, no error message. "
                       f"Run `python daily.py` first."),
            "csv_dates": sorted(dates), "ledger_dates": sorted(settled_dates),
            "pending": len(pending),
        }
    # second guard of the same family, a warning rather than a refusal: a presumed fill with no
    # CSV row keeps whatever settle() booked at the planning estimate. That is the SNDK / LITE /
    # QQQ case - orders too small to buy one whole share - and the book would hold names Lucas
    # never bought unless he sends a row with units=0.
    keys = {(str(r.get("ticker", "")).strip().upper(), str(r.get("side", "")).strip().lower())
            for r in rows}
    orphans = sorted({
        (str(f.get("ticker")).upper(), str(f.get("side")).lower())
        for f in ledger
        if str(f.get("exec_date")) in dates and f.get("status") == "filled"
        and f.get("side") in ("buy", "sell")
    } - keys)
    return {"ok": True, "csv_dates": sorted(dates), "ledger_dates": sorted(settled_dates),
            "pending": len(pending), "rows": len(rows),
            "presumed_without_a_csv_row": [t for t, _s in orphans],
            "reason": (f"{len(rows)} row(s) for {sorted(covered) or sorted(dates)}; the ledger "
                       f"has entries for that date, so they can match")
                      + (f". WARNING: {len(orphans)} presumed fill(s) have NO row in the CSV "
                         f"({', '.join(t for t, _s in orphans[:8])}"
                         f"{'...' if len(orphans) > 8 else ''}) - they stay in the book at the "
                         f"planning estimate. If you did not buy them, send rows with units=0."
                         if orphans else "")}


def run_step(name: str, cmd: list[str], log_path: Path | None, dry: bool = False) -> dict:
    print("", flush=True)
    print(f"$ {' '.join(cmd)}", flush=True)
    if dry:
        print("  (dry run: not executed)", flush=True)
        return {"step": name, "cmd": cmd, "returncode": 0, "dry": True, "stdout": ""}
    proc = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
    print(out.rstrip(), flush=True)
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(out, encoding="utf-8")
        print(f"  -> {_short(log_path)}", flush=True)
    return {"step": name, "cmd": cmd, "returncode": proc.returncode, "stdout": out}


def snapshot(stamp: str, dry: bool = False) -> dict:
    """Copy the state before anything can overwrite a presumed price."""
    if not STATE_FILE.exists():
        return {"ok": False, "reason": f"no state at {STATE_FILE}"}
    dest = BACKUP_DIR / f"pre-confirm-{stamp}.json"
    if dest.exists():
        return {"ok": True, "path": str(dest), "reason": "already snapshotted today; kept the "
                                                         "first one, which is the pre-write state"}
    if dry:
        return {"ok": True, "path": str(dest), "reason": "dry run: not copied"}
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(STATE_FILE, dest)
    return {"ok": True, "path": str(dest), "reason": "copied"}


def state_summary() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            st = json.load(f)
    except Exception as e:
        return {"unreadable": str(e)}
    return {
        "last_run_date": st.get("last_run_date"),
        "pending": len(st.get("pending") or []),
        "ledger": len(st.get("ledger") or []),
        "interest_entries": len(st.get("interest") or []),
        "interest_dollars": round(sum(float(x.get("dollars") or 0.0)
                                      for x in (st.get("interest") or [])), 4),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Drive the settle without leaving anything to memory")
    ap.add_argument("--fills", required=True, help="broker fills CSV for confirm_fills.py")
    ap.add_argument("--write", action="store_true",
                    help="actually confirm. Without it: snapshot + report, then stop.")
    ap.add_argument("--positions", default=None, help="broker positions CSV for reconcile.py")
    ap.add_argument("--cash-total", type=float, default=None, help="broker cash, for reconcile.py")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD stamp for the artefacts")
    ap.add_argument("--dry-run", action="store_true", help="print the sequence, execute nothing")
    ap.add_argument("--state-dir", default=None,
                    help="settle a COPY instead of the live book (this is how you rehearse)")
    args = ap.parse_args(argv)

    if args.state_dir:
        use_state_dir(args.state_dir)
        print(f"[settle] REHEARSAL against {STATE_DIR} - the live book is not touched", flush=True)

    stamp = (args.date or str(date.today())).replace("-", "")
    py = sys.executable
    before = state_summary()
    print("[settle] state before:", before, flush=True)
    if not before:
        print("[settle] no state file; nothing to settle.", flush=True)
        return 1
    if not before.get("pending") and not args.write:
        print("[settle] WARNING: no pending orders. Either daily.py has not run yet (run it "
              "first) or this settle is already done.", flush=True)

    guard = order_guard(args.fills)
    print(f"[settle] order guard: {guard['reason']}", flush=True)
    if not guard["ok"]:
        print("[settle] REFUSING. Nothing was read, copied or written.", flush=True)
        return 2

    snap = snapshot(stamp, dry=args.dry_run)
    print(f"[settle] snapshot: {snap.get('reason')} -> {snap.get('path')}", flush=True)
    if not snap["ok"]:
        print("[settle] refusing to continue without a snapshot.", flush=True)
        return 1

    state_args = ["--state-dir", str(STATE_DIR)] if args.state_dir else []
    state_file_args = ["--state", str(STATE_FILE)] if args.state_dir else []
    steps = [run_step("confirm_report",
                      [py, "confirm_fills.py", "--report", "--from-csv", args.fills, *state_args],
                      BACKUP_DIR / f"confirm-report-{stamp}.txt", args.dry_run)]
    if steps[-1]["returncode"] != 0:
        print("[settle] the report failed; nothing was written. Fix the CSV and re-run.",
              flush=True)
        return steps[-1]["returncode"]

    if not args.write:
        print("", flush=True)
        print("[settle] STOPPED before writing, which is the default. Read the diff above; when "
              "it is right, re-run with --write --positions <csv> [--cash-total N].", flush=True)
        return 0

    steps.append(run_step("confirm_write",
                          [py, "confirm_fills.py", "--from-csv", args.fills, *state_args],
                          BACKUP_DIR / f"confirm-write-{stamp}.txt", args.dry_run))
    if steps[-1]["returncode"] != 0:
        print(f"[settle] confirmation FAILED. The pre-write state is at {snap['path']}.",
              flush=True)
        return steps[-1]["returncode"]

    netted = None
    if args.positions:
        cmd = [py, "reconcile.py", args.positions, *state_file_args]
        if args.cash_total is not None:
            cmd += ["--cash-total", str(args.cash_total)]
        steps.append(run_step("reconcile", cmd, BACKUP_DIR / f"reconcile-{stamp}.txt",
                              args.dry_run))
        rep = parse_reconcile(steps[-1]["stdout"])
        netted = net_residual(rep)
        print("", flush=True)
        print("[settle] residual, netted of what is in the book but not at the broker:", flush=True)
        if not netted["ok"]:
            print("  could not read reconcile's numbers:", netted["reason"], flush=True)
        else:
            print(f"  reconcile residual (broker - state) {netted['residual']:,.2f}", flush=True)
            print(f"  + interest in the book, unpaid       "
                  f"{netted['interest_in_book_not_at_broker']:,.2f}", flush=True)
            print(f"  + dividends at ex-date, unpaid       "
                  f"{netted['dividends_ex_date_not_yet_paid']:,.2f}", flush=True)
            print(f"  = UNEXPLAINED                        {netted['netted']:,.2f}"
                  + (f"  ({netted['netted_pct_of_equity']:.3f}% of equity)"
                     if netted["netted_pct_of_equity"] is not None else ""), flush=True)
            print(f"  {netted['cumulative_caveat']}", flush=True)
            if netted["within_tolerance"]:
                print("  within tolerance: the gap is explained. Anything left would be an "
                      "unconfirmed fill or a broker fee the book does not know about.", flush=True)
            else:
                print(f"  ABOVE {RESIDUAL_TOLERANCE_PCT}% OF EQUITY: do not wave this through. "
                      f"Check for an unconfirmed fill, a fee, or a wrong --cash-total.", flush=True)
    else:
        print("[settle] no --positions given, so no reconcile and no netting.", flush=True)

    steps.append(run_step("verify_state", [py, "verify_state.py", *state_file_args],
                          BACKUP_DIR / f"verify-state-{stamp}.txt", args.dry_run))
    verified = explain_verify(steps[-1]["stdout"]) if not args.dry_run else {"clean": True}
    print("", flush=True)
    if verified.get("clean"):
        print("[settle] verify_state clean.", flush=True)
    elif verified.get("explained"):
        print("[settle] verify_state reported replay_cash, and it is the EXPECTED artefact:",
              flush=True)
        print(f"  {verified['reason']}", flush=True)
        for sl, v in (verified.get("sleeves") or {}).items():
            print(f"    {sl:<8} stored {v['stored']:,.6f}  replayed {v['replayed']:,.6f}  "
                  f"diff {v['diff']:.2e}", flush=True)
        print(f"    worst tranche difference {verified.get('worst_tranche_diff')} USD, "
              f"units identical: {verified.get('units_identical')}", flush=True)
        print("  The sleeve totals and every position agree; only the per-tranche split of the "
              "interest differs. The book is not short a dollar. The real fix is to record "
              "interest per tranche so the replay need not re-split it (TASK-415).", flush=True)
    else:
        print(f"[settle] verify_state FAILED and it is not the known artefact: "
              f"{verified.get('reason')}", flush=True)

    after = state_summary()
    record = {
        "stamp": stamp, "wrote": bool(args.write), "dry_run": bool(args.dry_run),
        "snapshot": snap, "state_before": before, "state_after": after,
        "residual_netting": netted, "verify": verified if not args.dry_run else None,
        "steps": [{k: v for k, v in s.items() if k != "stdout"} for s in steps],
        "all_ok": all(s["returncode"] == 0 for s in steps),
    }
    log = BACKUP_DIR / f"settle-{stamp}.json"
    if not args.dry_run:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    print("", flush=True)
    print("[settle] state after:", after, flush=True)
    print(f"[settle] {'all steps exited 0' if record['all_ok'] else 'A STEP FAILED - read above'}"
          f"; record -> {_short(log)}", flush=True)
    return 0 if record["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
