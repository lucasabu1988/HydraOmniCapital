"""Re-print the pending orders of a saved state in whole shares. Read-only.

The 2026-09-04 sheet was written before TASK-353 added the share columns, so the orders Lucas has
to execute list fractional `est. units` only. `daily.py` will not regenerate that sheet — planning
is skipped while pending orders wait for t+1 (portfolio_v9.main: "skip plan — pending not settled")
— so this prints the same orders again with the whole-share view, without touching the state.

    python reprint_sheet.py                          # live state, to stdout
    python reprint_sheet.py --state <path>            # any saved state or backup
    python reprint_sheet.py --out output/pending_shares.md   # also write the markdown

`--out` refuses any path inside state/ and any name that reads like an order sheet
(`instructions_*`, `portfolio_v9.json`): a VIEW of the book must never be mistakable for the book
or for the sheet being traded.

Nothing here writes to state/: the state file is opened for reading and never re-serialised.
Rounding is display-only, exactly as on the sheet — the engine still books dollars, and the
presumed fills stay fractional (see portfolio_v9.whole_share_display).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from portfolio_v9 import whole_share_display

STATE_DEFAULT = Path(__file__).parent / "state" / "portfolio_v9.json"


def load_pending(state_path: Path) -> tuple[list, dict]:
    """Return (pending orders, state) from a state JSON. Read-only."""
    with open(state_path, encoding="utf-8") as fh:
        state = json.load(fh)
    return list(state.get("pending") or []), state


ORDER_SHEET_NAMES = ("instructions_", "portfolio_v9.json")


def refuse_out(out: Path, state_path: Path) -> str | None:
    """Why `out` must not be written, or None. The state directory holds the sheet Lucas trades
    from and the book itself; a view of them never belongs in there, whatever the name."""
    out_r, state_r = out.resolve(), state_path.resolve()
    state_dir = state_r.parent
    if out_r == state_r:
        return "that is the state file"
    if out_r.parent == state_dir or state_dir in out_r.parents:
        return f"it is inside the state directory ({state_dir}) — write the view somewhere else"
    name = out_r.name
    if name.startswith(ORDER_SHEET_NAMES[0]) or name == ORDER_SHEET_NAMES[1]:
        return f"'{name}' is the name of an order sheet or of the book — pick a name that is not"
    return None


def exec_date_from_sheet(state_path: Path, planned: str | None) -> str | None:
    """The exec date the sheet promised, if its JSON sibling is still next to the state."""
    if not planned:
        return None
    sheet = state_path.parent / f"instructions_{planned.replace('-', '')}.json"
    if not sheet.exists():
        return None
    try:
        with open(sheet, encoding="utf-8") as fh:
            return json.load(fh).get("exec_date")
    except (OSError, ValueError):
        return None


def render(pending: list, state: dict, exec_date: str | None = None) -> str:
    planned = pending[0].get("planned") if pending else None
    sheet = f"state/instructions_{planned.replace('-', '')}.md" if planned else "the instruction sheet"
    lines = [
        f"# Whole-share VIEW of the pending orders (planned {planned or '—'})",
        "",
        f"**This is not an order sheet.** The sheet to execute is `{sheet}`; this only re-renders the "
        "same orders in whole shares. Generated read-only from the state — no orders, dates or "
        "amounts of its own.",
        "",
    ]
    if exec_date:
        lines += [f"Those orders execute at the close of {exec_date} (MOC t+1).", ""]
    cap = state.get("capital_reference")
    if cap:
        lines += [f"Capital reference: {cap:,.2f} USD  |  week index: {state.get('week_index')}", ""]

    if not pending:
        lines += ["**No pending orders in this state.**", ""]
        return "\n".join(lines)

    lines += [
        f"{len(pending)} order(s). Shares are display-only: the book still trades the dollar amount.",
        "",
        "| sleeve | tranche | side | ticker | $ | est. price | shares | $ at est | leftover |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    leftover_by: dict = {}
    no_price = []
    zero_shares = []
    for o in pending:
        ws = whole_share_display(o)
        price = o.get("est_price")
        if ws is None:
            no_price.append(o.get("ticker"))
            sh = at = left = ""
        else:
            if ws["shares"] == 0:
                zero_shares.append((o.get("ticker"), o.get("dollars", 0.0), float(price)))
            sh, at, left = str(ws["shares"]), f"{ws['at_est']:.2f}", f"{ws['leftover']:.2f}"
            if o.get("side") == "buy":
                key = (o.get("sleeve"), o.get("tranche"))
                leftover_by[key] = leftover_by.get(key, 0.0) + ws["leftover"]
        lines.append(
            f"| {o.get('sleeve')} | {o.get('tranche')} | {o.get('side')} | {o.get('ticker')} | "
            f"{o.get('dollars', 0):.2f} | {'' if price is None else f'{price:.4f}'} | "
            f"{sh} | {at} | {left} |"
        )

    if zero_shares:
        lines += [
            "",
            "## One share costs more than the order",
            "",
            "At the estimated price these buy **no position** in whole shares: the dollars stay in "
            "cash while the book's presumed fill books them, and only `confirm_fills.py` closes that "
            "gap. The estimate is the planning close, not the execution close — each line gives the "
            "price at which one share does fit, so a fall into it changes the answer.",
            "",
        ]
        for tk, dollars, price in zero_shares:
            move = (dollars / price - 1.0) * 100.0 if price else float("nan")
            lines.append(
                f"- **{tk}**: order {dollars:.2f} USD, one share {price:.2f} USD — one share fits "
                f"at or below {dollars:.2f} USD ({move:+.1f}% from the estimate)"
            )
    if leftover_by:
        lines += ["", "Cash left unspent by rounding (buys):", ""]
        for (sleeve, k), amt in sorted(leftover_by.items(), key=lambda kv: str(kv[0])):
            lines.append(f"- {sleeve} tranche {k}: **{amt:.2f}** USD")
        lines.append(f"- **total: {sum(leftover_by.values()):.2f} USD**")
    if no_price:
        lines += ["", f"No usable estimated price, shares not shown: {', '.join(map(str, no_price))}"]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Re-print pending orders in whole shares (read-only).")
    ap.add_argument("--state", default=str(STATE_DEFAULT), help="state JSON to read")
    ap.add_argument("--out", default=None, help="also write the markdown to this path")
    args = ap.parse_args(argv)

    state_path = Path(args.state)
    if not state_path.exists():
        print(f"[reprint] no state at {state_path}")
        return 1
    pending, state = load_pending(state_path)
    text = render(pending, state, exec_date_from_sheet(state_path, pending[0].get("planned") if pending else None))
    print(text)
    if args.out:
        out = Path(args.out)
        refusal = refuse_out(out, state_path)
        if refusal:
            print(f"[reprint] refusing to write {out}: {refusal}")
            return 1
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"[reprint] -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
