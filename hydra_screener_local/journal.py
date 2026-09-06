"""TASK-355 — persist the weekly journal and re-render JOURNAL.md.

    python journal.py                  # rebuild JOURNAL.md from journal/*.json
    python journal.py --dir path
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import argparse
import json
import os
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_DIR = ROOT / "journal"
AUDIT_MIX = ROOT / "experiments" / "_sweep_cache_etf" / "audit_steps.pkl"


def load_oos_step_returns(path: Path = AUDIT_MIX) -> list[float]:
    """JSON first (TASK-381); pickle only if the tracked cone file is absent."""
    from core.journal import load_oos_step_returns as _core_load
    return _core_load(path)


REVISION_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_r(\d+)$")
STATUS_OK = "ok"
STATUS_FAILED = "failed"


def load_records(journal_dir: Path) -> list[dict]:
    """One record per date: the current pointer, newest date last.

    Per-date revisions live in `<date>_r<NN>.json` and are skipped here, so the
    equity curve and `prior_total` see exactly one number per day.
    """
    recs = []
    for p in sorted(Path(journal_dir).glob("*.json")):
        if p.name.upper() == "JOURNAL.JSON":
            continue
        if REVISION_RE.match(p.stem):
            continue
        try:
            recs.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    recs.sort(key=lambda r: str(r.get("date") or ""))
    return recs


def load_revisions(journal_dir: Path, date: str) -> list[dict]:
    """Every revision ever written for `date`, oldest first (audit phase 9.5)."""
    out = []
    for p in sorted(Path(journal_dir).glob(f"{date}_r*.json")):
        m = REVISION_RE.match(p.stem)
        if not m:
            continue
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rec.setdefault("revision", int(m.group(2)))
        out.append(rec)
    out.sort(key=lambda r: int(r.get("revision") or 0))
    return out


def next_revision(journal_dir: Path, date: str) -> int:
    revs = load_revisions(journal_dir, date)
    return (max(int(r.get("revision") or 0) for r in revs) + 1) if revs else 1


def latest_successful(journal_dir: Path, date: str) -> dict | None:
    """The newest revision for `date` that actually completed."""
    ok = [r for r in load_revisions(journal_dir, date)
          if str(r.get("status") or STATUS_OK) == STATUS_OK]
    return ok[-1] if ok else None


def successful_records(journal_dir: Path) -> list[dict]:
    """Records for days that actually completed.

    A day that only ever failed has a book total of 0.0, and letting that into the
    equity curve or into `prior_total` invents a -100% step (found by the phase-9
    tests). A failure is evidence of a failure, not a valuation.
    """
    return [r for r in load_records(journal_dir)
            if str(r.get("status") or STATUS_OK) == STATUS_OK]


def prior_total(journal_dir: Path, today: str) -> float | None:
    recs = [r for r in successful_records(journal_dir) if str(r.get("date")) < today]
    if not recs:
        return None
    tot = (recs[-1].get("book") or {}).get("total")
    try:
        return float(tot) if tot is not None else None
    except (TypeError, ValueError):
        return None


def merge_observations(existing: dict | None, incoming: dict, note: str | None) -> list:
    notes = list((existing or {}).get("observations") or [])
    extra = list(incoming.get("observations") or [])
    for n in extra:
        if n not in notes:
            notes.append(n)
    if note and note not in notes:
        notes.append(note)
    return notes


def save_record(record: dict, journal_dir: Path, note: str | None = None,
                backup_date: str | None = None, *, status: str = STATUS_OK,
                run_id: str | None = None, error=None,
                inputs: dict | None = None, outputs: dict | None = None) -> Path:
    """Append a revision for this date and update the pointer. Never overwrites.

    Audit phase 9.3/9.4/9.5. Before this the journal wrote `<date>.json` in place:

    * a second run of the same day replaced the first, so the evidence of what was
      recommended earlier that day was gone (repro R-901);
    * `append_error()` went through the same path, so a failed run *deleted the
      successful record* for that date — a book total of 123,456 became 0.0
      (repro R-902).

    Now every run writes an immutable `<date>_r<NN>.json`, and `<date>.json` is a
    pointer to the newest **successful** revision. A failure is recorded as its own
    revision and listed on the pointer, but it never replaces a good record.
    """
    from core.journal import render_markdown

    journal_dir = Path(journal_dir)
    journal_dir.mkdir(parents=True, exist_ok=True)
    date_s = str(record.get("date") or date.today())
    pointer = journal_dir / f"{date_s}.json"

    old = latest_successful(journal_dir, date_s)
    if old is None and pointer.exists():
        try:
            old = json.loads(pointer.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            old = None

    revision = next_revision(journal_dir, date_s)
    record = dict(record)
    record["observations"] = merge_observations(old, record, note)
    record["revision"] = revision
    record["run_id"] = run_id or f"{date_s}_r{revision:02d}"
    record["parent_run_id"] = (old or {}).get("run_id")
    record["status"] = str(status)
    record["error"] = error if error is not None else (record.get("process") or {}).get("errors") or None
    record["inputs"] = inputs if inputs is not None else record.get("inputs") or {}
    record["outputs"] = outputs if outputs is not None else record.get("outputs") or {}
    record["created_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    rev_path = journal_dir / f"{date_s}_r{revision:02d}.json"
    blob = json.dumps(record, indent=2, default=str, ensure_ascii=False) + "\n"
    if not rev_path.exists():                     # revisions are write-once
        tmp = rev_path.with_suffix(".json.tmp")
        tmp.write_text(blob, encoding="utf-8")
        tmp.replace(rev_path)

    revisions_index = [
        {"revision": r.get("revision"), "run_id": r.get("run_id"),
         "status": r.get("status", STATUS_OK), "created_at": r.get("created_at")}
        for r in load_revisions(journal_dir, date_s)
    ]

    if str(status) == STATUS_OK or old is None:
        # a day that only ever failed still needs a visible record
        current = dict(record, revisions=revisions_index)
        tmp = pointer.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current, indent=2, default=str, ensure_ascii=False) + "\n",
                       encoding="utf-8")
        tmp.replace(pointer)
    else:
        try:
            current = json.loads(pointer.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = dict(old)
        current["revisions"] = revisions_index
        current["last_failure"] = {"revision": revision, "run_id": record["run_id"],
                                   "error": record["error"], "at": record["created_at"]}
        tmp = pointer.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current, indent=2, default=str, ensure_ascii=False) + "\n",
                       encoding="utf-8")
        tmp.replace(pointer)

    md = journal_dir / "JOURNAL.md"
    md.write_text(render_markdown(load_records(journal_dir)), encoding="utf-8")
    dest_root = os.environ.get("HYDRA_BACKUP_DIR")
    if dest_root:
        dest = Path(dest_root) / "state_v9" / (backup_date or date_s).replace("-", "")
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pointer, dest / pointer.name)
        shutil.copy2(rev_path, dest / rev_path.name)
        if md.exists():
            shutil.copy2(md, dest / md.name)
    return rev_path


def append_from_v9(out: dict, journal_dir: Path | None = None, note: str | None = None,
                   oos_step_returns: list[float] | None = None,
                   errors: list | None = None, status: str = STATUS_OK) -> Path:
    """Build + persist a record from portfolio_v9.run()'s return dict."""
    from core.journal import build_record

    journal_dir = Path(journal_dir or DEFAULT_DIR)
    today = out.get("today") or str(date.today())
    oos = oos_step_returns if oos_step_returns is not None else load_oos_step_returns()
    recs = successful_records(journal_dir)
    curve = [r.get("book", {}).get("total") for r in recs if str(r.get("date")) <= today]
    record = build_record(
        date=today,
        state=out.get("state"),
        ranking=out.get("ranking"),
        summary=out.get("summary"),
        orders=out.get("orders") or out.get("sheet_orders"),
        fills=out.get("fills"),
        preflight=out.get("preflight"),
        reconcile=out.get("reconcile"),
        prices=out.get("prices"),
        etf=out.get("etf"),
        irx=out.get("irx"),
        prior_total=prior_total(journal_dir, today),
        live_curve=curve,
        oos_step_returns=oos,
        errors=errors,
        last_bars=out.get("last_bars"),
        manifest_path=out.get("manifest_path"),
    )
    # phase 9.2: what each stage actually received, recorded rather than assumed
    inputs = {
        "universe_requested": out.get("universe_requested"),
        "universe_effective": out.get("universe_effective"),
        "universe_report": out.get("universe_report"),
        "last_bars": out.get("last_bars"),
        "provenance": (out.get("preflight") or {}).get("provenance"),
        "dividend_coverage": (out.get("dividend_report") or {}).get("coverage_through"),
    }
    outputs = {
        "run_id": out.get("run_id"),
        "run_status": out.get("run_status"),
        "state_path": out.get("state_path"),
        "instructions_md": out.get("instructions_md"),
        "n_orders": len(out.get("orders") or []),
        "n_fills": len(out.get("fills") or []),
    }
    return save_record(record, journal_dir, note=note, backup_date=today,
                       status=status, run_id=out.get("run_id"),
                       error=list(errors or []) or None,
                       inputs=inputs, outputs=outputs)


def append_error(message: str, journal_dir: Path | None = None, note: str | None = None,
                 today: str | None = None, run_id: str | None = None) -> Path:
    """Record a failed run as its own revision. Never touches a successful record."""
    from core.journal import build_record
    journal_dir = Path(journal_dir or DEFAULT_DIR)
    today = today or str(date.today())
    record = build_record(date=today, state={}, errors=[message])
    return save_record(record, journal_dir, note=note, backup_date=today,
                       status=STATUS_FAILED, error=[str(message)], run_id=run_id)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Rebuild JOURNAL.md from journal/*.json")
    p.add_argument("--dir", type=str, default=str(DEFAULT_DIR))
    args = p.parse_args(argv)
    d = Path(args.dir)
    d.mkdir(parents=True, exist_ok=True)
    from core.journal import render_markdown
    recs = load_records(d)
    (d / "JOURNAL.md").write_text(render_markdown(recs), encoding="utf-8")
    print(f"journal: {len(recs)} record(s) -> {d / 'JOURNAL.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
