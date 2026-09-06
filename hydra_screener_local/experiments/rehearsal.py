"""Tuesday rehearsal on a COPY of the live state (TASK-383).

Never touches `state/` or `journal/`. Copies `state/` to a scratch directory, runs
`portfolio_v9.run` against the copy, builds (does not persist) the journal record,
runs the ledger replay check on the copy, and writes a human-readable report.

Modes
-----
  today        real fetch, today's session. With pending orders planned on Friday
               and no later close, settle and plan are skipped (the "still waiting"
               path). This is what a run on a non-execution day looks like.
  simulate-t1  real fetch, then a synthetic bar dated at the NEXT NYSE session is
               appended to every price frame at the LAST CLOSE (prices unchanged),
               so settle -> dividends(none) -> interest -> plan -> sheet -> journal
               all run exactly as they will on the execution day. Fake prices, real
               plumbing. The sheet it writes is a rehearsal artefact in the copy.

Usage
-----
    python experiments/rehearsal.py --mode today
    python experiments/rehearsal.py --mode simulate-t1 --keep
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import traceback
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

import portfolio_v9 as PV  # noqa: E402
from core.journal import build_record, render_markdown  # noqa: E402
from core.state_check import check, format_findings  # noqa: E402
from utils.trading_calendar import next_nyse_session  # noqa: E402

SCRATCH = HERE / "_lab_scratch" / "rehearsal_state"
COMMS = ROOT.parent / ".comms"


def copy_state(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for f in src.iterdir():
        if f.is_file() and (f.suffix in (".json", ".md", ".csv")):
            shutil.copy2(f, dst / f.name)


def synthetic_t1(data: dict) -> tuple[dict, str]:
    """Append one bar at the next NYSE session with the last close repeated."""
    last = pd.Timestamp(data["prices"].index[-1]).normalize()
    t1 = pd.Timestamp(next_nyse_session(last))
    out = dict(data)
    for key in ("prices", "volumes", "etf"):
        fr = data[key]
        if fr is None or len(fr) == 0:
            continue
        row = fr.iloc[[-1]].copy()
        row.index = pd.DatetimeIndex([t1])
        out[key] = pd.concat([fr, row])
    for key in ("spy", "irx"):
        s = data[key]
        if s is None or len(s) == 0:
            continue
        add = pd.Series([s.iloc[-1]], index=pd.DatetimeIndex([t1]))
        out[key] = pd.concat([s, add])
    return out, t1.strftime("%Y-%m-%d")


def none_fields(obj, prefix="") -> list[str]:
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            if hasattr(v, "size") and hasattr(v, "tolist"):      # numpy scalar/array
                if getattr(v, "size", 1) == 0:
                    out.append(p)
            elif v is None or (isinstance(v, (list, dict, str)) and len(v) == 0):
                out.append(p)
            else:
                out.extend(none_fields(v, p))
    return out


def non_native(obj, prefix="") -> list[str]:
    """Fields json.dumps would only save through default=str (numpy, Timestamp, ...)."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                out.extend(non_native(v, p))
            elif isinstance(v, list):
                for i, x in enumerate(v):
                    if isinstance(x, dict):
                        out.extend(non_native(x, f"{p}[{i}]"))
                    elif x is not None and not isinstance(x, (str, int, float, bool, list, dict)):
                        out.append(f"{p}[{i}]: {type(x).__name__}")
            elif v is not None and not isinstance(v, (str, int, float, bool)):
                out.append(f"{p}: {type(v).__name__}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=("today", "simulate-t1"), default="today")
    ap.add_argument("--state-dir", default=str(ROOT / "state"))
    ap.add_argument("--scratch", default=str(SCRATCH))
    ap.add_argument("--keep", action="store_true", help="keep the scratch copy after the run")
    ap.add_argument("--out", default=None, help="report path (default .comms/journal-rehearsal-<date>.md)")
    args = ap.parse_args(argv)

    src = Path(args.state_dir)
    scratch = Path(args.scratch)
    if scratch.resolve() == src.resolve():
        raise SystemExit("scratch must differ from the live state dir")
    copy_state(src, scratch)
    live_state_before = (src / PV.STATE_NAME).read_bytes()
    live_mtime_before = (src / PV.STATE_NAME).stat().st_mtime

    print(f"[rehearsal] mode={args.mode} copy -> {scratch}")

    # 1. real market data (network), optionally with the synthetic t+1 bar
    data = PV.fetch_v9_market(None)
    session_label = PV._last_date(data["prices"])
    if args.mode == "simulate-t1":
        data, session_label = synthetic_t1(data)
        print(f"[rehearsal] synthetic bar appended at {session_label} (last close repeated)")

    # 2. the production step on the copy, console captured
    buf = io.StringIO()
    err = None
    out = None
    with contextlib.redirect_stdout(buf):
        try:
            # fetch_fn is injected (so the synthetic bar can be used) but dividends must still
            # take the real network path: run() skips them when fetch_fn is set unless told otherwise.
            out = PV.run(state_dir=scratch, fetch_fn=lambda _u: data,
                         dividend_fn=lambda tickers: PV.fetch_dividends(tickers))
        except BaseException as e:  # noqa: BLE001 - report everything
            err = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
    console = buf.getvalue()
    print(console)

    # 3. reports
    from data.sectors import sector_report
    from data.universe import universe_report
    try:
        sec = sector_report()
    except Exception as e:  # noqa: BLE001
        sec = {"error": str(e)}
    try:
        uni = universe_report()
    except Exception as e:  # noqa: BLE001
        uni = {"error": str(e)}

    record = None
    record_md = ""
    if out is not None:
        record = build_record(
            date=out["today"], state=out["state"], ranking=out.get("ranking"), summary=out.get("summary"),
            orders=out.get("orders") or out.get("sheet_orders"), fills=out.get("fills"),
            preflight=out.get("preflight"), prices=out.get("prices"), etf=out.get("etf"), irx=out.get("irx"),
            prior_total=None, live_curve=[], last_bars=out.get("last_bars"),
        )
        record_md = render_markdown([record])

    copy_state_after = json.loads((scratch / PV.STATE_NAME).read_text(encoding="utf-8"))
    findings = check(copy_state_after)

    live_unchanged = (src / PV.STATE_NAME).read_bytes() == live_state_before \
        and (src / PV.STATE_NAME).stat().st_mtime == live_mtime_before
    journal_dir_exists = (ROOT / "journal").exists()

    lines = [
        f"# Tuesday rehearsal — mode `{args.mode}` — session {session_label}",
        "",
        f"Live `state/portfolio_v9.json` unchanged: **{live_unchanged}**. `journal/` exists after the run: "
        f"**{journal_dir_exists}** (expected False). Scratch copy: `{scratch}`.",
        "",
        "## Console (portfolio_v9.run on the copy)",
        "", "```", console.rstrip(), "```", "",
    ]
    if err:
        lines += ["## EXCEPTION", "", "```", err.rstrip(), "```", ""]
    if out is not None:
        st = out["state"]
        lines += [
            "## Result",
            "",
            f"- today = {out['today']}, orders planned = {len(out['orders'])}, fills settled = {len(out['fills'])}, "
            f"pending after run = {len(st.get('pending') or [])}, ledger = {len(st.get('ledger') or [])}, "
            f"last_run_date = {st.get('last_run_date')}, week_index = {st.get('week_index')}",
            f"- interest records = {len(st.get('interest') or [])}, dividends records = {len(st.get('dividends') or [])}, "
            f"transfers = {len(st.get('transfers') or [])}, write_offs = {len(st.get('write_offs') or [])}",
            f"- sheet: {out['instructions_md']}",
            f"- sector_warning: {out.get('sector_warning')}",
            "",
        ]
    lines += ["## sector_report()", "", "```", json.dumps(sec, indent=2, default=str), "```", "",
              "## universe_report()", "", "```", json.dumps(uni, indent=2, default=str), "```", "",
              "## verify_state on the copy", "", "```", format_findings(findings), "```", ""]
    if record is not None:
        nf = none_fields(record)
        nn = non_native(record)
        cone_block = (record.get("expectation") or {})
        lines += ["## Journal record (built, NOT persisted)", "",
                  f"None/empty fields ({len(nf)}): " + (", ".join(f"`{x}`" for x in nf) if nf else "none"), "",
                  f"Non-JSON-native fields ({len(nn)}, saved via default=str): " + (", ".join(f"`{x}`" for x in nn) if nn else "none"), "",
                  "Expectation block:", "", "```", json.dumps(cone_block, indent=2, default=str), "```", "",
                  "### Rendered record", "", record_md.rstrip(), ""]

    out_path = Path(args.out) if args.out else COMMS / f"journal-rehearsal-{session_label.replace('-', '')}-{args.mode}.md"
    out_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"[rehearsal] report -> {out_path}")
    print(f"[rehearsal] live state unchanged: {live_unchanged}; findings on copy: {len(findings)}")

    if not args.keep:
        shutil.rmtree(scratch, ignore_errors=True)
        print("[rehearsal] scratch copy removed")
    return 0 if (err is None and live_unchanged and not findings) else 1


if __name__ == "__main__":
    sys.exit(main())
