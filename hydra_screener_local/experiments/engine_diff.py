"""Differential driver: two engine versions on the same OOS panel, stop at the first divergence.

    python experiments/engine_diff.py --other C:/path/to/other/hydra_screener_local --steps 200

`--other` is another checkout of hydra_screener_local; its core/portfolio_engine.py is loaded under
a private module name (tranche_book, config and the lab stay THIS tree's). Read-only.

Audit phase 8.9/8.10. Before this the driver compared **orders and fills only**, and
returned 0 as soon as those matched. Two engines could agree on every order and
disagree on cash, on units, on tranche layout, on fees or on the ledger, and the
command reported "IDENTICAL". It now compares, after every plan and every settlement:

    orders, fills, cash, positions, tranches, fees, the full normalized state, errors

and any divergence — including one visible only in cash — exits non-zero.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import pandas as pd  # noqa: E402

import engine_backtest as EB  # noqa: E402
import redesign_lab as L  # noqa: E402
import sleeve_lab as S  # noqa: E402
import core.portfolio_engine as E_MAIN  # noqa: E402
from config import V9  # noqa: E402

TOL = 1e-9
#: keys whose value is bookkeeping about the run, not the book itself
VOLATILE_STATE_KEYS = ("config", "config_sha256", "sleeve_registry", "registry_sha256")


def load_other_engine(other_root: str):
    path = os.path.join(other_root, "core", "portfolio_engine.py")
    spec = importlib.util.spec_from_file_location("other_portfolio_engine", path)
    mod = importlib.util.module_from_spec(spec)
    # the other tree's sleeves package (registry/adapters) must resolve to ITS files when the engine
    # imports `sleeves.registry`; give it priority on sys.path while loading and running
    sys.path.insert(0, other_root)
    for name in [m for m in list(sys.modules) if m == "sleeves" or m.startswith("sleeves.")]:
        del sys.modules[name]
    spec.loader.exec_module(mod)
    return mod


def slim(o):
    keep = ("sleeve", "tranche", "ticker", "side", "dollars", "est_units", "est_price", "close",
            "units", "price", "cost", "status", "exec_date", "planned", "reason", "note")
    return {k: (round(o[k], 9) if isinstance(o.get(k), float) else o.get(k)) for k in keep if k in o}


# --------------------------------------------------------------------------- projections
def _round(x, nd=9):
    try:
        return round(float(x), nd)
    except (TypeError, ValueError):
        return x


def cash_view(state: dict) -> dict:
    """{sleeve: [tranche cash, ...]} plus the total. Phase 8.9: cash is compared."""
    out: dict = {}
    total = 0.0
    for sleeve, block in sorted((state.get("sleeves") or {}).items()):
        row = [_round(t.get("cash")) for t in (block.get("tranches") or [])]
        out[sleeve] = row
        total += sum(v for v in row if isinstance(v, float))
    out["_total"] = _round(total)
    return out


def positions_view(state: dict) -> dict:
    """{sleeve: {ticker: units}} aggregated across tranches."""
    out: dict = {}
    for sleeve, block in sorted((state.get("sleeves") or {}).items()):
        acc: dict = {}
        for tr in block.get("tranches") or []:
            for tk, u in (tr.get("units") or {}).items():
                acc[str(tk)] = _round(acc.get(str(tk), 0.0) + float(u))
        out[sleeve] = {k: v for k, v in sorted(acc.items()) if abs(v) > 1e-12}
    return out


def tranches_view(state: dict) -> dict:
    """The per-tranche layout: cash, units, marks and staleness."""
    out: dict = {}
    for sleeve, block in sorted((state.get("sleeves") or {}).items()):
        rows = []
        for tr in block.get("tranches") or []:
            rows.append({
                "k": tr.get("k"),
                "opened": tr.get("opened"),
                "cash": _round(tr.get("cash")),
                "units": {str(k): _round(v) for k, v in sorted((tr.get("units") or {}).items())},
                "last_px": {str(k): _round(v) for k, v in sorted((tr.get("last_px") or {}).items())},
                "stale": {str(k): int(v) for k, v in sorted((tr.get("stale") or {}).items())},
            })
        out[sleeve] = rows
    return out


def fees_view(state: dict) -> dict:
    """Cumulative fees per sleeve, from the canonical ledger projection."""
    from core.ledger import moves_book
    out: dict = {}
    for f in state.get("ledger") or []:
        if not moves_book(f.get("status")):
            continue
        sleeve = str(f.get("sleeve") or "?")
        try:
            out[sleeve] = _round(out.get(sleeve, 0.0) + float(f.get("cost") or 0.0))
        except (TypeError, ValueError):
            out[sleeve] = "unparseable"
    return dict(sorted(out.items()))


def normalized_state(state: dict) -> dict:
    """The whole state, minus the bookkeeping that legitimately differs between trees.

    Phase 8.9: "estado completo normalizado". The config hash of two checkouts differs
    by construction, so those keys are dropped; everything that describes the *book*
    is compared.
    """
    out = json.loads(json.dumps(state, sort_keys=True, default=str))
    for key in VOLATILE_STATE_KEYS:
        out.pop(key, None)
    return out


PROJECTIONS = (
    ("cash", cash_view),
    ("positions", positions_view),
    ("tranches", tranches_view),
    ("fees", fees_view),
    ("state", normalized_state),
)


def first_difference(a, b, path="$") -> str | None:
    """A human-readable path to the first divergence, or None."""
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a:
                return f"{path}.{key}: missing on main"
            if key not in b:
                return f"{path}.{key}: missing on other"
            hit = first_difference(a[key], b[key], f"{path}.{key}")
            if hit:
                return hit
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}: length {len(a)} vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            hit = first_difference(x, y, f"{path}[{i}]")
            if hit:
                return hit
        return None
    if isinstance(a, float) and isinstance(b, float):
        if abs(a - b) > TOL:
            return f"{path}: {a!r} vs {b!r}  (delta {a - b:.3e})"
        return None
    if a != b:
        return f"{path}: {a!r} vs {b!r}"
    return None


def compare_states(sa: dict, sb: dict, *, where: str) -> list[str]:
    """Every projection that diverges, most specific first. Empty list = identical."""
    problems = []
    for label, view in PROJECTIONS:
        hit = first_difference(view(sa), view(sb), f"{label}")
        if hit:
            problems.append(f"{where}: {label} differs at {hit}")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--other", required=True)
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--sectors", default="live")
    ap.add_argument("--json", default=None, help="write the divergence report here")
    args = ap.parse_args(argv)

    E_OTHER = load_other_engine(os.path.abspath(args.other))
    print("main engine :", E_MAIN.__file__)
    print("other engine:", E_OTHER.__file__)
    P = L.load_panel(oos=True, sectors=args.sectors)
    P.ETF = S.load_etfs(P.close.index)
    idx = P.close.index
    cfg = dict(V9)
    c = dict(L.BASE)
    c.update(L.CONFIGS["T20"])
    sa = E_MAIN.new_state(1.0, str(idx[EB.START].date()), cfg)
    sb = E_OTHER.new_state(1.0, str(idx[EB.START].date()), cfg)

    report: dict = {"steps_compared": 0, "problems": [], "errors": []}

    def fail(problems: list[str]) -> int:
        report["problems"] = problems
        for msg in problems[:12]:
            print("  DIFF", msg)
        print(f"DIVERGED after {report['steps_compared']} step(s): {len(problems)} projection(s)")
        if args.json:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, default=str)
        return 1

    problems = compare_states(sa, sb, where="new_state")
    if problems:
        return fail(problems)

    prev_t = None
    i = -1
    for i, t in enumerate(range(EB.START, len(idx) - 6, EB.STEP)):
        if i >= args.steps:
            break
        today = str(idx[t].date())

        if sa.get("pending") and prev_t is not None:
            e = prev_t + 1
            try:
                fa = E_MAIN.settle(sa, str(idx[e].date()), P.close.iloc[e], P.ETF.iloc[e], cfg)
            except Exception as exc:                     # phase 8.9: errors are compared too
                fa, err_a = None, f"{type(exc).__name__}: {exc}"
            else:
                err_a = None
            try:
                fb = E_OTHER.settle(sb, str(idx[e].date()), P.close.iloc[e], P.ETF.iloc[e], cfg)
            except Exception as exc:
                fb, err_b = None, f"{type(exc).__name__}: {exc}"
            else:
                err_b = None
            if err_a != err_b:
                report["errors"].append({"step": i, "phase": "settle", "main": err_a, "other": err_b})
                return fail([f"settle step {i}: errors differ — main {err_a!r} other {err_b!r}"])
            if err_a is None:
                if [slim(x) for x in fa] != [slim(x) for x in fb]:
                    hit = first_difference([slim(x) for x in fa], [slim(x) for x in fb], "fills")
                    return fail([f"settle step {i} exec {idx[e].date()}: fills differ at {hit}"])
                # and the book the fills produced, not only the fills
                problems = compare_states(sa, sb, where=f"after settle {idx[e].date()}")
                if problems:
                    return fail(problems)

        rk = EB._ranking(P, t, c)
        if rk is None:
            prev_t = t
            continue

        try:
            sa, oa = E_MAIN.plan(sa, today, rk, P.close.iloc[: t + 1], P.ETF.iloc[: t + 1], P.IRX, cfg)
        except Exception as exc:
            oa, err_a = None, f"{type(exc).__name__}: {exc}"
        else:
            err_a = None
        try:
            sb, ob = E_OTHER.plan(sb, today, rk, P.close.iloc[: t + 1], P.ETF.iloc[: t + 1], P.IRX, cfg)
        except Exception as exc:
            ob, err_b = None, f"{type(exc).__name__}: {exc}"
        else:
            err_b = None
        if err_a != err_b:
            report["errors"].append({"step": i, "phase": "plan", "main": err_a, "other": err_b})
            return fail([f"plan step {i} ({today}): errors differ — main {err_a!r} other {err_b!r}"])
        if err_a is None:
            if [slim(x) for x in oa] != [slim(x) for x in ob]:
                hit = first_difference([slim(x) for x in oa], [slim(x) for x in ob], "orders")
                return fail([f"plan step {i} ({today}): orders differ at {hit} "
                             f"(main {len(oa)} orders, other {len(ob)})"])
            problems = compare_states(sa, sb, where=f"after plan {today}")
            if problems:
                return fail(problems)

        prev_t = t
        report["steps_compared"] = i + 1
        if (i + 1) % 50 == 0:
            print(f"  identical through step {i + 1} ({today})", flush=True)

    n = min(args.steps, i + 1) if i >= 0 else 0
    print(f"IDENTICAL for {n} step(s): orders, fills, cash, positions, tranches, fees, "
          f"full state and errors")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
