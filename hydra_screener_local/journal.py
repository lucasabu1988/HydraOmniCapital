"""TASK-355 — persist the weekly journal and re-render JOURNAL.md.

    python journal.py                  # rebuild JOURNAL.md from journal/*.json
    python journal.py --dir path
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_DIR = ROOT / "journal"
AUDIT_MIX = ROOT / "experiments" / "_sweep_cache_etf" / "audit_steps.pkl"


def load_oos_step_returns(path: Path = AUDIT_MIX) -> list[float]:
    """JSON first (TASK-381); pickle only if the tracked cone file is absent."""
    from core.journal import load_oos_step_returns as _core_load
    return _core_load(path)


def load_records(journal_dir: Path) -> list[dict]:
    recs = []
    for p in sorted(journal_dir.glob("*.json")):
        if p.name.upper() == "JOURNAL.JSON":
            continue
        try:
            recs.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    recs.sort(key=lambda r: str(r.get("date") or ""))
    return recs


def prior_total(journal_dir: Path, today: str) -> float | None:
    recs = [r for r in load_records(journal_dir) if str(r.get("date")) < today]
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
                backup_date: str | None = None) -> Path:
    """Write journal/<date>.json (update in place) and rebuild JOURNAL.md.

    Observations are appended and never overwritten. The rest of the record is
    replaced with the latest run of that date.
    """
    from core.journal import render_markdown

    journal_dir = Path(journal_dir)
    journal_dir.mkdir(parents=True, exist_ok=True)
    date_s = str(record.get("date") or date.today())
    path = journal_dir / f"{date_s}.json"
    old = None
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            old = None
    record = dict(record)
    record["observations"] = merge_observations(old, record, note)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2, default=str, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    tmp.replace(path)
    md = journal_dir / "JOURNAL.md"
    md.write_text(render_markdown(load_records(journal_dir)), encoding="utf-8")
    dest_root = os.environ.get("HYDRA_BACKUP_DIR")
    if dest_root:
        dest = Path(dest_root) / "state_v9" / (backup_date or date_s).replace("-", "")
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest / path.name)
        if md.exists():
            shutil.copy2(md, dest / md.name)
    return path


def append_from_v9(out: dict, journal_dir: Path | None = None, note: str | None = None,
                   oos_step_returns: list[float] | None = None,
                   errors: list | None = None) -> Path:
    """Build + persist a record from portfolio_v9.run()'s return dict."""
    from core.journal import build_record

    journal_dir = Path(journal_dir or DEFAULT_DIR)
    today = out.get("today") or str(date.today())
    oos = oos_step_returns if oos_step_returns is not None else load_oos_step_returns()
    recs = load_records(journal_dir)
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
    )
    return save_record(record, journal_dir, note=note, backup_date=today)


def append_error(message: str, journal_dir: Path | None = None, note: str | None = None,
                 today: str | None = None) -> Path:
    from core.journal import build_record
    journal_dir = Path(journal_dir or DEFAULT_DIR)
    today = today or str(date.today())
    record = build_record(date=today, state={}, errors=[message])
    return save_record(record, journal_dir, note=note, backup_date=today)


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
