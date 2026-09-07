"""TASK-360 — check a portfolio state, optionally restore a backup.

TASK-ASTRA-12 adds three read-only drills on top: verify a backup against its manifest,
restore it into an ISOLATED directory (never over a live book), and close out a manual
execution against a broker CSV.

    python verify_state.py
    python verify_state.py --state state/portfolio_v9.json
    python verify_state.py --restore state/backup/foo.json --yes
    python verify_state.py --verify-backup D:/hydra_backups/state_v9/20260904
    python verify_state.py --restore-into D:/tmp/drill --from-backup-dir D:/hydra_backups/state_v9/20260904
    python verify_state.py --closeout broker_executions.csv --sheet state/instructions_20260904.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.state_check import Finding, check, format_findings, replay  # noqa: E402
from core.state_migrations import SchemaError, migrate  # noqa: E402
from utils.trading_calendar import is_nyse_session  # noqa: E402

ROOT = Path(__file__).resolve().parent
DEFAULT_STATE = ROOT / "state" / "portfolio_v9.json"
BACKUP_MANIFEST = "backup_manifest.json"
STATE_NAME = "portfolio_v9.json"
# A run is recoverable only if all four roles made it into the copy (portfolio_v9.py writes
# the manifest). The journal is written after the sheet, so a first copy legitimately lacks
# it — that is exactly the hole this check closes instead of assuming.
REQUIRED_ROLES = ("state", "sheet_md", "sheet_json", "journal")
UNITS_TOL = 1e-6
PRICE_TOL = 1e-6


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _report(label: str, state: dict) -> tuple[str, bool]:
    try:
        migrate(state)
    except SchemaError as e:
        text = f"{label}: SCHEMA {e}"
        return text, True
    findings = check(state)
    text = f"{label}:\n{format_findings(findings)}"
    hard = any(f.level == "ERROR" for f in findings)
    return text, hard


# --------------------------------------------------------------------------- backup verification

def read_backup_manifest(backup_dir) -> dict | None:
    path = Path(backup_dir) / BACKUP_MANIFEST
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def verify_backup(backup_dir) -> list[Finding]:
    """Recompute sha256 for every file the manifest claims. A copy2 is not a backup."""
    backup_dir = Path(backup_dir)
    out: list[Finding] = []
    if not backup_dir.exists():
        return [Finding("ERROR", "BACKUP_MISSING", f"backup dir not found: {backup_dir}")]
    manifest = read_backup_manifest(backup_dir)
    if manifest is None:
        return [Finding("ERROR", "BACKUP_NO_MANIFEST",
                        f"no readable {BACKUP_MANIFEST} in {backup_dir}: nothing to verify against")]
    entries = dict(manifest.get("files") or {})
    if not entries:
        out.append(Finding("ERROR", "BACKUP_EMPTY", f"{BACKUP_MANIFEST} lists no files"))
    roles = set()
    for name, rec in sorted(entries.items()):
        target = backup_dir / name
        if not target.exists():
            out.append(Finding("ERROR", "BACKUP_FILE_MISSING", f"{name}: in manifest, not on disk"))
            continue
        digest = sha256_file(target)
        if digest != rec.get("sha256"):
            out.append(Finding("ERROR", "BACKUP_HASH_MISMATCH",
                               f"{name}: sha256 {digest[:12]} != manifest {str(rec.get('sha256'))[:12]}"))
            continue
        if rec.get("collides_with"):
            out.append(Finding("ERROR", "BACKUP_NAME_COLLISION",
                               f"{name}: two sources share this name ({rec['collides_with']})"))
        roles.add(rec.get("role"))
    missing = [r for r in (manifest.get("required_roles") or REQUIRED_ROLES) if r not in roles]
    if missing:
        out.append(Finding("ERROR", "BACKUP_INCOMPLETE",
                           f"missing role(s) {', '.join(missing)} in {backup_dir}"))
    return out


def backup_is_complete(backup_dir) -> bool:
    return not any(f.level == "ERROR" for f in verify_backup(backup_dir))


# --------------------------------------------------------------------------- isolated restore

class RestoreRefused(RuntimeError):
    """The target is not an isolated directory. Never restore over a live book."""


def _assert_isolated(target: Path, live_state: Path | None = None) -> None:
    target = Path(target)
    live = Path(live_state) if live_state is not None else DEFAULT_STATE
    live_dir = live.resolve().parent
    try:
        resolved = target.resolve()
    except OSError as e:  # pragma: no cover - unresolvable path
        raise RestoreRefused(f"cannot resolve {target}: {e}") from e
    if resolved == live_dir or live_dir in resolved.parents or resolved in live_dir.parents:
        raise RestoreRefused(f"refused: {resolved} is the live state tree ({live_dir})")
    if (resolved / STATE_NAME).exists():
        raise RestoreRefused(f"refused: {resolved} already holds a {STATE_NAME}")
    if resolved.exists() and any(resolved.iterdir()):
        raise RestoreRefused(f"refused: {resolved} is not empty")


def restore_into(backup_dir, target_dir, *, live_state: Path | None = None) -> dict:
    """Copy a verified backup into an empty, isolated directory and replay the book.

    Writes nothing outside `target_dir`. Returns
    {"target", "files", "hashes", "findings", "state", "replay"}.
    Raises RestoreRefused rather than touching a directory that could be a live book.
    """
    backup_dir = Path(backup_dir)
    target = Path(target_dir)
    _assert_isolated(target, live_state)
    findings = list(verify_backup(backup_dir))
    manifest = read_backup_manifest(backup_dir) or {}
    entries = dict(manifest.get("files") or {})
    target.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    hashes: dict[str, str] = {}
    for name in sorted(entries):
        src = backup_dir / name
        if not src.exists():
            continue
        shutil.copy2(src, target / name)
        hashes[name] = sha256_file(target / name)
        if hashes[name] != entries[name].get("sha256"):
            findings.append(Finding("ERROR", "RESTORE_HASH_MISMATCH",
                                    f"{name}: restored copy differs from the manifest"))
        copied.append(name)
    shutil.copy2(backup_dir / BACKUP_MANIFEST, target / BACKUP_MANIFEST)

    state = None
    rec = None
    state_path = target / STATE_NAME
    if state_path.exists():
        try:
            state = _load(state_path)
        except (OSError, json.JSONDecodeError) as e:
            findings.append(Finding("ERROR", "RESTORE_STATE_UNREADABLE", f"{STATE_NAME}: {e}"))
        if state is not None:
            try:
                migrate(state)
                findings.extend(check(state))
                rec = replay(state)
            except SchemaError as e:
                findings.append(Finding("ERROR", "RESTORE_SCHEMA", str(e)))
    else:
        findings.append(Finding("ERROR", "RESTORE_NO_STATE", f"no {STATE_NAME} in {backup_dir}"))
    return {"target": target, "files": copied, "hashes": hashes,
            "findings": findings, "state": state, "replay": rec}


# --------------------------------------------------------------------------- manual close-out

BOOKED = {"filled", "confirmed", "confirmed_unplanned"}


def _key(row: dict) -> tuple:
    return (str(row.get("exec_date") or row.get("date") or ""),
            str(row.get("ticker") or "").upper(),
            str(row.get("side") or "").lower())


def read_broker_csv(path) -> list[dict]:
    """Broker executions, same columns confirm_fills.py already accepts.

    exec_date, ticker, side, units, price[, sleeve, tranche, fee]. Read-only.
    """
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def _f(x, default=0.0) -> float:
    try:
        if x is None or x == "":
            return default
        v = float(x)
        return default if v != v else v
    except (TypeError, ValueError):
        return default


def closeout(state: dict, broker_rows: list[dict], *, sheet: dict | None = None) -> list[Finding]:
    """Prove the sheet -> broker fills -> book chain closed. Read-only, no network.

    Reconciling positions alone cannot say whether the FILL was timely, so this compares by
    (exec_date, ticker, side): a holiday exec_date, an order the book presumes but the broker
    never executed, an order the broker executed twice, and a confirmation that only arrives
    after the book has already renewed on presumed numbers.
    """
    out: list[Finding] = []
    exec_dates: set[str] = set()

    if sheet:
        sheet_exec = str(sheet.get("exec_date") or "")
        if sheet_exec:
            exec_dates.add(sheet_exec)
            if not is_nyse_session(sheet_exec):
                out.append(Finding("ERROR", "SHEET_EXEC_NOT_SESSION",
                                   f"sheet {sheet.get('date')} asks for MOC on {sheet_exec}, "
                                   f"which is not an NYSE session"))
        for o in sheet.get("orders") or []:
            planned = str(o.get("planned") or "")
            if planned and not is_nyse_session(planned):
                out.append(Finding("WARN", "ORDER_PLANNED_NOT_SESSION",
                                   f"order {o.get('ticker')} planned on {planned}, not a session"))

    ledger = list(state.get("ledger") or [])
    booked = {}
    for f in ledger:
        if str(f.get("status") or "") in BOOKED:
            booked.setdefault(_key(f), []).append(f)
    if not exec_dates:
        exec_dates = {k[0] for k in booked}

    broker: dict[tuple, list[dict]] = {}
    for r in broker_rows:
        broker.setdefault(_key(r), []).append(r)

    renewal = str(state.get("last_renewal_date") or state.get("last_run_date") or "")

    for key, fills in sorted(booked.items()):
        if key[0] not in exec_dates:
            continue
        rows = broker.get(key) or []
        book_units = sum(_f(f.get("units")) for f in fills)
        if not rows:
            out.append(Finding("ERROR", "ORDER_NOT_EXECUTED",
                               f"{key[0]} {key[2]} {key[1]}: book holds {book_units:.4f} units, "
                               f"broker CSV has no execution"))
            continue
        broker_units = sum(_f(r.get("units")) for r in rows)
        if len(rows) > 1:
            out.append(Finding("ERROR", "ORDER_EXECUTED_TWICE",
                               f"{key[0]} {key[2]} {key[1]}: {len(rows)} broker executions "
                               f"({broker_units:.4f} units) against one booked order "
                               f"({book_units:.4f})"))
        elif abs(broker_units - book_units) > UNITS_TOL:
            level = "ERROR" if broker_units > book_units + UNITS_TOL else "WARN"
            out.append(Finding(level, "FILL_UNITS_MISMATCH",
                               f"{key[0]} {key[2]} {key[1]}: broker {broker_units:.4f} units vs "
                               f"book {book_units:.4f}"))
        broker_px = _f(rows[0].get("price"))
        book_px = _f(fills[0].get("price"))
        if broker_px and abs(broker_px - book_px) > PRICE_TOL:
            presumed = any(str(f.get("status")) == "filled" for f in fills)
            if presumed and renewal and key[0] < renewal:
                later = [f for f in ledger
                         if str(f.get("exec_date") or "") > key[0] and str(f.get("status") or "") in BOOKED]
                out.append(Finding("ERROR", "LATE_CONFIRMATION",
                                   f"{key[0]} {key[2]} {key[1]}: still presumed at {broker_px:.4f} "
                                   f"vs book {book_px:.4f}; the book renewed on {renewal} and "
                                   f"{len(later)} later fill(s) plus "
                                   f"{len(state.get('pending') or [])} pending order(s) were "
                                   f"decided on the presumed number"))
            else:
                out.append(Finding("WARN", "FILL_PRICE_MISMATCH",
                                   f"{key[0]} {key[2]} {key[1]}: broker {broker_px:.4f} vs "
                                   f"book {book_px:.4f}"))

    for key, rows in sorted(broker.items()):
        if key in booked:
            continue
        if key[0] not in exec_dates and not any(k[0] == key[0] for k in booked):
            continue
        units = sum(_f(r.get("units")) for r in rows)
        out.append(Finding("ERROR", "BROKER_UNPLANNED",
                           f"{key[0]} {key[2]} {key[1]}: {units:.4f} units at the broker with no "
                           f"booked order"))
    return out


# --------------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="HYDRA state integrity")
    p.add_argument("--state", default=str(DEFAULT_STATE))
    p.add_argument("--restore", default=None, help="backup JSON to copy over the state")
    p.add_argument("--yes", action="store_true", help="required to actually restore")
    p.add_argument("--verify-backup", default=None,
                   help="backup directory to check against its backup_manifest.json (read-only)")
    p.add_argument("--restore-into", default=None,
                   help="empty directory to restore a backup into; never the live state tree")
    p.add_argument("--from-backup-dir", default=None,
                   help="backup directory used by --restore-into")
    p.add_argument("--closeout", default=None,
                   help="broker executions CSV to close the sheet -> fills -> book chain (read-only)")
    p.add_argument("--sheet", default=None, help="instructions_<date>.json for --closeout")
    args = p.parse_args(argv)

    if args.verify_backup:
        findings = verify_backup(args.verify_backup)
        print(f"backup {args.verify_backup}:\n{format_findings(findings)}")
        if not args.restore_into and not args.closeout:
            return 1 if any(f.level == "ERROR" for f in findings) else 0

    if args.restore_into:
        if not args.from_backup_dir:
            print("--restore-into needs --from-backup-dir")
            return 1
        try:
            res = restore_into(args.from_backup_dir, args.restore_into, live_state=Path(args.state))
        except RestoreRefused as e:
            print(str(e))
            return 2
        print(f"restored {len(res['files'])} file(s) -> {res['target']}")
        print(format_findings(res["findings"]))
        return 1 if any(f.level == "ERROR" for f in res["findings"]) else 0

    state_path = Path(args.state)
    if not state_path.exists():
        print(f"state not found: {state_path}")
        return 1

    current = _load(state_path)
    text, hard = _report(f"state {state_path}", current)
    print(text)

    if args.closeout:
        sheet = _load(Path(args.sheet)) if args.sheet else None
        findings = closeout(current, read_broker_csv(args.closeout), sheet=sheet)
        print(f"\ncloseout {args.closeout}:\n{format_findings(findings)}")
        if any(f.level == "ERROR" for f in findings):
            hard = True

    if args.restore:
        backup_path = Path(args.restore)
        if not backup_path.exists():
            print(f"backup not found: {backup_path}")
            return 1
        backup = _load(backup_path)
        btext, bhard = _report(f"backup {backup_path}", backup)
        print()
        print(btext)
        if not args.yes:
            print("\nrestore refused: pass --yes to copy the backup over the state")
            return 2
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        keep_dir = state_path.parent / "backup"
        keep_dir.mkdir(parents=True, exist_ok=True)
        kept = keep_dir / f"{ts}_replaced.json"
        shutil.copy2(state_path, kept)
        shutil.copy2(backup_path, state_path)
        print(f"\nrestored {backup_path} -> {state_path}")
        print(f"previous state kept at {kept}")
        return 1 if bhard else 0

    return 1 if hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
