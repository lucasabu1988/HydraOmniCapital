"""HYDRA v9 daily CLI: state, engine, instruction sheet.

Manual operation. No broker. After the close of bar t this writes orders to execute
MOC at t+1. Fills are presumed on the next run. ALGO_VERSION stays v8.4; this CLI is
opt-in (`python portfolio_v9.py` or `daily.py --v9`).

Usage:
    python portfolio_v9.py --capital 100000          # first run
    python portfolio_v9.py                           # subsequent runs
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from config import (  # noqa: E402
    ALGO_VERSION,
    FILTERS,
    SECTOR_FETCH_BUDGET_SECONDS,
    UNIVERSE,
    V9,
)
from core import portfolio_engine as E  # noqa: E402
from core.filters import (  # noqa: E402
    apply_data_quality_filter,
    apply_practical_filters,
    remove_zombie_tickers,
)
from core.signals import generate_daily_candidates  # noqa: E402
from data.fetch import fetch_etf_closes, fetch_prices_and_volume, fetch_spy, fetch_tbill  # noqa: E402
from data.sectors import resolve_sectors, sector_degraded_message  # noqa: E402
from core.dividends import apply_dividends, summarize_dividends, tickers_from_state  # noqa: E402
from dashboard_v9 import summarize_interest  # noqa: E402
from data.dividends import fetch_dividends  # noqa: E402
from core.state_migrations import SchemaError, migrate  # noqa: E402
from data.universe import get_universe, universe_report  # noqa: E402
from core.portfolios import resolve as resolve_portfolio  # noqa: E402
import preflight as PF  # noqa: E402

STATE_NAME = "portfolio_v9.json"
DEFAULT_STATE_DIR = ROOT / "state"
_OFFDISK_WARNED = False


def _json_ready(obj):
    if isinstance(obj, dict):
        return {str(k): _json_ready(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_ready(v) for v in obj]
    if isinstance(obj, (pd.Timestamp, datetime)):
        return str(obj)[:10] if hasattr(obj, "date") else str(obj)
    try:
        if pd.isna(obj):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(obj, "item"):
        try:
            return obj.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(obj, (float, int, str, bool)) or obj is None:
        return obj
    return str(obj)


def load_state(path: Path) -> dict | None:
    """Read + migrate (TASK-360). An unknown schema_version refuses to run."""
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        state = json.load(f)
    try:
        return migrate(state)
    except SchemaError as e:
        raise SystemExit(f"state {path}: {e} - refusing to run on an unknown schema") from e


def copy_state_off_disk(today: str, files: list[Path], silent: bool = False,
                        subdir: str = "state_v9") -> Path | None:
    """Copy state + instruction files to HYDRA_BACKUP_DIR/state_v9/<date>/ when the env is set."""
    global _OFFDISK_WARNED
    dest_root = os.environ.get("HYDRA_BACKUP_DIR")
    if not dest_root:
        if not _OFFDISK_WARNED and not silent:
            print("[v9] AVISO: HYDRA_BACKUP_DIR no esta definido; el backup de state/ queda en el mismo disco")
            _OFFDISK_WARNED = True
        return None
    dest = Path(dest_root) / subdir / today.replace("-", "")
    dest.mkdir(parents=True, exist_ok=True)
    for p in files:
        p = Path(p)
        if p.exists():
            shutil.copy2(p, dest / p.name)
    # PIT snapshots (TASK-362) and run manifests (TASK-359) travel with the state.
    for sub, src in (("pit", ROOT / "data_cache" / "pit"), ("runs", ROOT / "runs")):
        if src.exists():
            try:
                shutil.copytree(src, Path(dest_root) / sub, dirs_exist_ok=True)
            except Exception as e:  # never let a backup mirror stop the run
                if not silent:
                    print(f"[v9] AVISO: backup de {sub}/ fallo: {e}")
    if not silent:
        print(f"[v9] off-disk backup -> {dest}")
    return dest


def save_state(path: Path, state: dict) -> Path | None:
    """Backup the previous file (if any), then write. Returns the backup path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = None
    if path.exists():
        bdir = path.parent / "backup"
        bdir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = bdir / f"{ts}.json"
        shutil.copy2(path, backup_path)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(_json_ready(state), f, indent=2, ensure_ascii=False)
    tmp.replace(path)
    return backup_path


def fetch_v9_market(universe: str = None, cfg: dict | None = None) -> dict:
    """Prices for the engine. Stocks/ETFs use cfg['price_period']; T-bill stays percent until /100."""
    cfg = cfg or V9
    period = cfg["price_period"]
    uni = universe or os.environ.get("UNIVERSE") or UNIVERSE
    tickers = get_universe(universe=uni)
    try:
        ureport = universe_report(uni)          # cached resolve; WARN in preflight when on the fallback list
    except Exception:
        ureport = None
    stock_report, etf_report, irx_report = {}, {}, {}
    prices, volumes = fetch_prices_and_volume(tickers, period=period, report=stock_report)
    spy = fetch_spy(period=period)
    etf = fetch_etf_closes(list(cfg["etf_universe"]), period=period, report=etf_report)
    irx = fetch_tbill(period=period, report=irx_report)
    return dict(prices=prices, volumes=volumes, spy=spy, etf=etf, irx=irx,
                stock_report=stock_report, etf_report=etf_report, irx_report=irx_report,
                universe_report=ureport)


def build_ranking(prices: pd.DataFrame, spy: pd.Series, volumes: pd.DataFrame,
                  cfg: dict | None = None) -> pd.DataFrame:
    prices, _ = apply_practical_filters(
        prices, volumes=volumes,
        min_avg_volume=FILTERS.get("min_avg_volume", 1_000_000),
        min_price=FILTERS.get("min_price", 5.0),
        max_price=FILTERS.get("max_price"),
        min_dollar_volume=FILTERS.get("min_dollar_volume"),
    )
    prices = apply_data_quality_filter(prices, max_abs_daily_return=1.0, lookback=252)
    prices = remove_zombie_tickers(prices)
    if volumes is not None and not volumes.empty:
        volumes = volumes[volumes.columns.intersection(prices.columns)]
    spy = spy.reindex(prices.index).ffill()
    sector_map = resolve_sectors(list(prices.columns), budget_seconds=SECTOR_FETCH_BUDGET_SECONDS)
    return generate_daily_candidates(
        prices, spy, volumes=volumes, sector_map=sector_map,
        momentum_window=(cfg or V9)["stock_momentum_window"],
    )


def _last_date(frame) -> str:
    ts = pd.Timestamp(frame.index[-1])
    return str(ts.date())


def next_session_date(index, today: str) -> str:
    """First bar on the price calendar strictly after `today`, else the next NYSE session.

    A Friday run has no later bar in the downloaded index, so the fallback used to be
    BDay(1) and printed Labor Day 2026-09-07 on the first sheet (TASK-357).
    """
    from utils.trading_calendar import next_nyse_session
    idx = pd.DatetimeIndex(index).normalize()
    later = idx[idx > pd.Timestamp(today).normalize()]
    if len(later):
        return str(pd.Timestamp(later[0]).date())
    return next_nyse_session(today)


def _row(frame, date: str) -> pd.Series:
    idx = pd.DatetimeIndex(frame.index).normalize()
    target = pd.Timestamp(date).normalize()
    hits = frame.index[idx == target]
    if len(hits):
        return frame.loc[hits[-1]]
    return frame.iloc[-1]


def whole_share_display(order: dict) -> dict | None:
    """Display-only: floor(dollars / est_price). Engine orders stay fractional."""
    if order.get("side") not in ("buy", "sell"):
        return None
    dollars = float(order.get("dollars") or 0.0)
    price = order.get("est_price")
    try:
        price = float(price) if price is not None else None
    except (TypeError, ValueError):
        price = None
    if price is None or price <= 0 or dollars <= 0:
        return None
    shares = int(math.floor(dollars / price))
    at = shares * price
    return {"shares": shares, "at_est": round(at, 4), "leftover": round(dollars - at, 4)}


def write_instructions(state_dir: Path, date: str, orders: list, fills: list, summary: dict,
                       state: dict, exec_date: str, sector_warning: str | None = None) -> tuple[Path, Path]:
    payload = {
        "date": date,
        "algo_version": "v9",
        "production_flag": ALGO_VERSION,
        "no_trades": len(orders) == 0,
        "orders": _json_ready(orders),
        "fills_settled_today": _json_ready(fills),
        "valuation": _json_ready(summary),
        "pending": _json_ready(state.get("pending") or []),
        "week_index": state.get("week_index"),
        "capital_reference": state.get("capital_reference"),
        "exec_date": exec_date,
        "execute": f"ejecutar al cierre del {exec_date} (MOC t+1). Fills presumidos hasta que corrijas el estado.",
        "sector_degraded": sector_warning,
        "interest": _json_ready(summarize_interest(state)),
        "dividends": _json_ready(summarize_dividends(state)),
        "whole_shares": "display-only; orders and presumed fills stay in dollars/fractional",
    }
    md_path = state_dir / f"instructions_{date.replace('-', '')}.md"
    json_path = state_dir / f"instructions_{date.replace('-', '')}.json"
    lines = [
        f"# HYDRA v9 instructions — {date}",
        "",
    ]
    if sector_warning:
        lines += [f"**DEGRADED** {sector_warning}", ""]
    lines += [
        payload["execute"],
        "",
        f"Capital reference: {state.get('capital_reference'):,.2f} USD"
        if state.get("capital_reference") else "",
        f"Week index: {state.get('week_index')}  |  last renewal: {state.get('last_renewal_date')}",
        "",
    ]
    ix = summarize_interest(state)
    sl = ix.get("since_last_by_sleeve") or {}
    sl_txt = ", ".join(f"{k} {v:,.2f}" for k, v in sl.items()) or "—"
    lines += [
        "## Interest (T-bill on idle cash)",
        "",
        f"Since previous run ({ix.get('since_from') or '—'} -> {ix.get('last_date') or '—'}): "
        f"**{ix['since_last_run']:,.2f}** USD ({sl_txt})",
        f"Cumulative: **{ix['cumulative']:,.2f}** USD",
        "",
    ]
    dv = summarize_dividends(state)
    dsl = dv.get("since_last_by_sleeve") or {}
    dsl_txt = ", ".join(f"{k} {v:,.2f}" for k, v in dsl.items()) or "—"
    lines += [
        "## Dividends (cash, ex-date)",
        "",
        f"Since previous run ({dv.get('since_from') or '—'} -> {dv.get('last_date') or '—'}): "
        f"**{dv['since_last_run']:,.2f}** USD ({dsl_txt})",
        f"Cumulative: **{dv['cumulative']:,.2f}** USD",
        "Broker pays on pay-date, later than ex-date — reconcile.py lists that gap.",
        "",
        "## Orders",
        "",
    ]
    if not orders:
        lines.append("**No trades today** (non-renewal day, or this date was already planned).")
    else:
        lines.append("| sleeve | tranche | side | ticker | $ | est. units | est. price | shares | $ at est | leftover |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        leftover_by = {}
        for o in orders:
            units = o.get("est_units")
            price = o.get("est_price")
            ws = whole_share_display(o)
            sh = "" if ws is None else str(ws["shares"])
            at = "" if ws is None else f"{ws['at_est']:.2f}"
            left = "" if ws is None else f"{ws['leftover']:.2f}"
            if ws is not None and o.get("side") == "buy":
                key = (o.get("sleeve"), o.get("tranche"))
                leftover_by[key] = leftover_by.get(key, 0.0) + ws["leftover"]
            lines.append(
                f"| {o.get('sleeve')} | {o.get('tranche')} | {o.get('side')} | {o.get('ticker')} | "
                f"{o.get('dollars', 0):.2f} | "
                f"{'' if units is None else f'{units:.4f}'} | "
                f"{'' if price is None else f'{price:.4f}'} | "
                f"{sh} | {at} | {left} |"
            )
        if leftover_by:
            lines += ["", "Cash left over by rounding (buys, display-only; engine still books dollars):", ""]
            for (sleeve, k), amt in leftover_by.items():
                lines.append(f"- {sleeve} tranche {k}: **{amt:.2f}** USD stays unspent if you buy whole shares")
    lines += ["", "## Valuation (last close)", ""]
    if summary:
        tot = summary.get("total") or 0.0
        lines.append(f"Book: **{tot:,.2f}**")
        for name, sl in (summary.get("sleeves") or {}).items():
            lines.append(
                f"- {name}: {sl.get('value', 0):,.2f} ({100 * sl.get('share', 0):.1f}%)  "
                f"cash {sl.get('cash', 0):,.2f}  expo {sl.get('exposure', 0):.2f}  "
                f"n={sl.get('distinct', 0)}  {', '.join(sl.get('names') or [])}"
            )
    if fills:
        lines += ["", "## Fills settled this run", ""]
        for f in fills:
            lines.append(f"- {f.get('status')} {f.get('side')} {f.get('ticker')} "
                         f"{f.get('sleeve')} ${f.get('dollars', 0):.2f}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return md_path, json_path


def run(state_dir: Path = DEFAULT_STATE_DIR, capital: float | None = None,
        anchor: str | None = None, universe: str | None = None, *,
        fetch_fn=None, rank_fn=None, engine=E, silent: bool = False,
        force: bool = False, dividend_fn=None, runlog=None,
        cfg: dict | None = None, portfolio: str | None = None,
        allow_disabled: bool = False) -> dict:
    """One daily step. fetch_fn / rank_fn are injectable so tests never hit the network.
    `runlog` is an optional `utils.runlog.RunContext` (TASK-359): data fingerprints and the
    files written land in its manifest. None = today's behaviour."""
    # TASK-365: a named book brings its own state dir, cfg and capital; no name = today's behaviour.
    book = None                       # `pf` below is the preflight result; the portfolio is `book`
    if portfolio is not None:
        book = resolve_portfolio(portfolio, allow_disabled=allow_disabled)
        if Path(state_dir).resolve() == DEFAULT_STATE_DIR.resolve():
            state_dir = book.state_dir
        if cfg is None:
            cfg = book.cfg
        if capital is None:
            capital = book.capital
    cfg = cfg or V9
    backup_subdir = book.backup_subdir if book is not None else "state_v9"
    state_dir = Path(state_dir)
    state_path = state_dir / STATE_NAME
    state = load_state(state_path)

    data = fetch_fn(universe) if fetch_fn is not None else fetch_v9_market(universe, cfg=cfg)
    prices, volumes, spy, etf, irx = data["prices"], data["volumes"], data["spy"], data["etf"], data["irx"]
    if prices is None or len(prices) == 0 or etf is None or len(etf) == 0:
        raise RuntimeError("v9 fetch returned no stock or ETF prices")
    today = _last_date(prices)
    if runlog is not None:
        for name, frame in (("stocks", prices), ("etf", etf), ("^IRX", irx)):
            try:
                runlog.fingerprint(name, frame)
            except Exception:
                pass
    tbill_rate = 0.0
    if irx is not None and len(irx) and irx.dropna().size:
        # full history, percent -> decimal: plan() builds the trailing 252-bar T-bill hurdle from it
        # (a single last print made the ETF signal compare 12m returns with today's rate, not with
        # the accumulated T-bill return the lab measured; TASK-347 review)
        tbill_rate = pd.to_numeric(irx, errors="coerce").astype(float) / 100.0

    if state is None:
        cap = 100000.0 if capital is None else float(capital)
        if cap <= 0:
            raise SystemExit("First run needs a positive --capital USD.")
        wd = pd.Timestamp(today).weekday()          # 0=Mon ... 4=Fri
        if wd != 4 and not silent:
            print(f"[v9] AVISO: primera corrida en {today} (weekday={wd}, no es viernes). "
                  f"Ancla = ultimo cierre igual. Lucas pidio ancla viernes -> primera "
                  f"ejecucion lunes; renovaciones siguen siendo cada {cfg['step_bars']} barras, "
                  f"no cada lunes calendario.")
        state = engine.new_state(cap, anchor or today, cfg)
        if not silent:
            print(f"[v9] new state capital={cap:.2f} anchor={state['anchor_date']}")

    ranking = None
    if not state.get("pending"):
        ranking = rank_fn(prices, spy, volumes) if rank_fn is not None else build_ranking(prices, spy, volumes, cfg=cfg)
    # Injected fetch (tests) uses the fixture's last bar as the session so the suite
    # does not depend on the wall clock. Live fetch compares to the last weekday.
    pf = PF.evaluate(
        prices, etf, irx, state=state, ranking=ranking,
        asof=today if fetch_fn is not None else pd.Timestamp.now(),
        last_session=today if fetch_fn is not None else None,
        backup_dir=os.environ.get("HYDRA_BACKUP_DIR"),
        universe_report=data.get("universe_report"),
    )
    if not silent:
        print(PF.format_table(pf))
    PF.raise_if_hard(pf, force=force)

    fills = []
    if state.get("pending"):
        planned = state["pending"][0].get("planned")
        if planned and pd.Timestamp(today) > pd.Timestamp(planned):
            # Fills are booked at the close of the FIRST bar after the plan (t+1, the MOC the sheet
            # asked for), not at whatever close the CLI happens to run on (integration review 340).
            exec_date = next_session_date(prices.index, planned)
            if pd.Timestamp(exec_date) > pd.Timestamp(today):
                exec_date = today
            fills = engine.settle(state, exec_date, _row(prices, exec_date), _row(etf, exec_date), cfg)
            if not silent:
                print(f"[v9] settled {len(fills)} fill(s) at {exec_date} (planned {planned}, run {today})")
        elif not silent:
            print(f"[v9] pending orders from {planned} still waiting for t+1 (today={today})")

    # Cash dividends (TASK-349): after settle, before plan. Tests with fetch_fn skip the network.
    if state.get("last_run_date"):
        if dividend_fn is not None:
            table = dividend_fn(tickers_from_state(state))
        elif fetch_fn is not None:
            table = []
        else:
            table = fetch_dividends(tickers_from_state(state))
        credited = apply_dividends(state, table, today)
        if credited and not silent:
            total_dv = sum(float(r.get("dollars") or 0) for r in credited)
            print(f"[v9] dividends {len(credited)} credit(s) {total_dv:.2f} USD")

    orders = []
    if not state.get("pending"):
        if ranking is None:
            ranking = rank_fn(prices, spy, volumes) if rank_fn is not None else build_ranking(prices, spy, volumes, cfg=cfg)
        state, orders = engine.plan(state, today, ranking, prices, etf, tbill_rate, cfg)
        if not silent:
            print(f"[v9] plan {today}: {len(orders)} order(s)")
    elif not silent:
        print("[v9] skip plan — pending not settled")
    sector_warning = sector_degraded_message(ranking) if ranking is not None else None
    if sector_warning and not silent:
        print(f"[v9] DEGRADED {sector_warning}")

    backup = save_state(state_path, state)
    summary = engine.summary_table(state, prices.iloc[-1], etf.iloc[-1], cfg)
    exec_date = next_session_date(prices.index, today)
    # A same-day rerun must not overwrite today's sheet with "No trades": the pending orders planned
    # today ARE the instructions still to execute (integration review 340).
    sheet_orders = orders
    if not orders and state.get("pending") and state["pending"][0].get("planned") == today:
        sheet_orders = list(state["pending"])
    md_path, json_path = write_instructions(
        state_dir, today, sheet_orders, fills, summary, state, exec_date,
        sector_warning=sector_warning,
    )
    if runlog is not None:
        for art in (state_path, md_path, json_path, backup):
            if art:
                try:
                    runlog.artifact(art)
                except Exception:
                    pass
    copy_state_off_disk(today, [state_path, md_path, json_path], silent=silent, subdir=backup_subdir)
    if not silent:
        if backup:
            print(f"[v9] backed up previous state -> {backup}")
        print(f"[v9] state -> {state_path}")
        print(f"[v9] instructions -> {md_path}")
        ix = summarize_interest(state)
        print(f"[v9] interest since last run {ix['since_last_run']:.2f}  cumulative {ix['cumulative']:.2f}")
        dv = summarize_dividends(state)
        print(f"[v9] dividends since last run {dv['since_last_run']:.2f}  cumulative {dv['cumulative']:.2f}")
        if not orders:
            print("[v9] no trades today")
    return dict(
        today=today, orders=orders, fills=fills, state_path=str(state_path),
        instructions_md=str(md_path), no_trades=len(orders) == 0,
        # pieces for the journal builder (TASK-355); no journal logic here
        state=state, ranking=ranking, summary=summary, preflight=pf,
        sheet_orders=sheet_orders, sector_warning=sector_warning,
        last_bars={"stocks": today, "etf": _last_date(etf), "^IRX": _last_date(irx) if irx is not None and len(irx) else None},
        prices=prices, etf=etf, irx=irx,
        manifest_path=str(runlog.directory / "manifest.json") if runlog is not None else None,
        portfolio=book.name if book is not None else "default",
        journal_dir=str(book.journal_dir) if book is not None else None,
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="HYDRA v9 instruction CLI (50/50 T20+ETF)")
    p.add_argument("--capital", type=float, default=None,
                   help="USD on first run (default 100000, or the portfolio's capital_reference). "
                        "Ignored once state exists.")
    p.add_argument("--portfolio", default=None,
                   help="Book from portfolios.toml (TASK-365). Default = the live book, identical to no flag.")
    p.add_argument("--allow-disabled", action="store_true",
                   help="Run a portfolio marked enabled = false in portfolios.toml.")
    p.add_argument("--anchor", type=str, default=None, help="YYYY-MM-DD; default = last close")
    p.add_argument("--state-dir", type=str, default=str(DEFAULT_STATE_DIR))
    p.add_argument("--universe", type=str, default=None)
    p.add_argument("--force", action="store_true",
                   help="Plan even if preflight hard-fails (stale bars, missing ETFs, unknown schema).")
    args = p.parse_args(argv)
    from utils.runlog import start_run
    ctx = start_run("portfolio_v9", argv=list(argv) if argv is not None else None)
    rc = 0
    try:
        with ctx:
            run(Path(args.state_dir), capital=args.capital, anchor=args.anchor, universe=args.universe,
                force=args.force, runlog=ctx, portfolio=args.portfolio, allow_disabled=args.allow_disabled)
    except SystemExit as e:
        print(f"[v9] {e}")
        rc = 1
    except Exception as e:
        print(f"[v9] ERROR: {e}")
        rc = 1
    if rc:
        ctx.finish(exit_status=rc)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
