"""TASK-417 — write did.sizing into a paper-journal date from its instruction sheet.

The 2026-09-10 paper book was created before #71 merged, so neither the sheet payload
nor the journal carried the day-one sizing loss. This recomputes `sizing_summary`
from `instructions_<date>.json` and writes (or repairs) `journal_paper/<date>.json`.

Idempotent: a second run leaves the same record. Never touches `state/` or
`portfolio_v9.json`.

    python tools/backfill_sizing.py --sheet state_paper/instructions_20260910.json
    python tools/backfill_sizing.py --sheet PATH --journal-dir DIR
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.sizing import sizing_summary  # noqa: E402

DEFAULT_JOURNAL = ROOT / "journal_paper"


def load_sheet(path: Path) -> dict:
    sheet = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(sheet, dict):
        raise ValueError(f"{path} is not a JSON object")
    if not sheet.get("date"):
        raise ValueError(f"{path} has no date")
    return sheet


def apply_sizing(record: dict, sizing: dict) -> tuple[dict, bool]:
    """Put `sizing` at did.sizing. Returns (record, changed)."""
    rec = dict(record)
    did = dict(rec.get("did") or {})
    if did.get("sizing") == sizing:
        return rec, False
    did["sizing"] = sizing
    rec["did"] = did
    return rec, True


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(obj, indent=2, default=str, ensure_ascii=False) + "\n"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(blob, encoding="utf-8")
    tmp.replace(path)


def backfill(sheet_path: Path, journal_dir: Path) -> tuple[Path, dict, bool]:
    sheet = load_sheet(sheet_path)
    date_s = str(sheet["date"])
    sizing = sizing_summary(sheet.get("orders") or [])
    pointer = Path(journal_dir) / f"{date_s}.json"
    if pointer.exists():
        try:
            existing = json.loads(pointer.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise ValueError(f"{pointer} is not readable JSON: {e}") from e
        if not isinstance(existing, dict):
            raise ValueError(f"{pointer} is not a JSON object")
        rec, changed = apply_sizing(existing, sizing)
    else:
        rec, changed = apply_sizing({"date": date_s}, sizing)
    if changed:
        _write_json(pointer, rec)
    return pointer, rec, changed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="TASK-417: backfill did.sizing from an instruction sheet")
    ap.add_argument("--sheet", type=Path, required=True, help="instructions_<date>.json")
    ap.add_argument("--journal-dir", type=Path, default=DEFAULT_JOURNAL,
                    help="paper journal directory (default: journal_paper/)")
    args = ap.parse_args(argv)
    path, rec, changed = backfill(args.sheet, args.journal_dir)
    sz = (rec.get("did") or {}).get("sizing") or {}
    print(f"{path} {'written' if changed else 'unchanged'}", flush=True)
    print(
        f"  n_buys={sz.get('n_buys')} target={sz.get('target_dollars')} "
        f"achievable={sz.get('achievable_dollars')} loss={sz.get('loss_dollars')} "
        f"share={sz.get('loss_share')} zero={sz.get('zero_share_names')}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
