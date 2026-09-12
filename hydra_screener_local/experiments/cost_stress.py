"""TASK-433 - cost stress as a table, measured in deltas against the base case.

Production models 10 bp/side on stocks and 5 bp/side on ETFs. On the Russell 2000 half of the
universe that may be optimistic; the reviewer of 2026-09-11 said so and Lucas asked for it to be
measured, not argued. Four declared scenarios, the same frozen engine, the same two panels the
prereg used (Russell PIT on the holiday-cleaned calendar, S&P 500 PIT on the same grid and start),
and for every scenario the three deltas that matter - dCAGR, dSharpe (excess), dmaxDD - because the
question is sensitivity, not level.

    python experiments/cost_stress.py            # drive what is not cached, print the table
    python experiments/cost_stress.py --dry-run  # scenarios and cache status only

Nothing here is a threshold: `COST_BP_PER_SIDE`, `stock_cost_bp` and `etf_cost_bp` are overridden
inside the run and restored after it. The base row for each panel IS the TASK-431 book (same
config), so the table is anchored to the number already on the board. Books are cached per
scenario under `_lab_scratch/cost_stress/`; a re-run only drives what is missing.

The risk-free leg enters through `load_annual_rate`, which takes the unit of the file as a
required argument: `irx.pkl` is a PERCENT series and `metrics.step_risk_free` wants a decimal
one. The first run of this script read the file raw and published a 342 % T-bill, so the rows
carry full-precision statistics and `table` rounds only for the console.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # TASK-380: cp1252 consoles

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import engine_backtest as EB  # noqa: E402
import holdout as HO  # noqa: E402
import metrics as M  # noqa: E402
import calendar_spec as CSPEC  # noqa: E402
import provenance as PV  # noqa: E402
import redesign_lab as L  # noqa: E402
import run_russell_prereg as R  # noqa: E402

OUT_DIR = os.path.join(HERE, "_lab_scratch", "cost_stress")
SCRATCH = os.path.join(HERE, "_lab_scratch", "task433.json")

#: (label, stock bp/side, etf bp/side) - declared before any number was looked at (Lucas 2026-09-11).
SCENARIOS = (
    ("base", 10.0, 5.0),
    ("conservative", 20.0, 8.0),
    ("stress", 35.0, 10.0),
    ("smallcap_crisis", 50.0, 15.0),
)
PANELS = ("russell", "sp500")
#: The TASK-431 books are the base rows: same engine, same config, already on the board.
BASE_BOOKS = {
    "russell": os.path.join(HERE, "_lab_scratch", "engine_book_russell.pkl"),
    "sp500": os.path.join(HERE, "_lab_scratch", "engine_book_sp_samegrid.pkl"),
}

#: The unit of every rate-like or scale-bearing quantity this script reads or publishes, recorded
#: in each manifest and compared as an exact dict. This is the block that would have refused the
#: 342 % T-bill: nothing in a float64 series distinguishes 0.0151 from 1.51, and a book carries no
#: record of the divisor it was measured under. `reindexed` is a third, independent way to get the
#: same file wrong - the published rows were computed on the native ^IRX calendar, which differs
#: from the price-calendar convention by 1.8e-05 per step.
UNITS = {
    "irx": {"on_disk": "annual_percent", "consumed": "annual_decimal", "divisor": 100.0,
            "reindexed": "native_irx_calendar"},
    "costs": {"on_disk": "basis_points_per_side", "consumed": "fraction_per_side",
              "divisor": 10000.0},
    "step_returns": "decimal_per_step",
    "ann_net": "percent_per_year",
    "maxdd_net": "percent_negative",
    "rf_ann_pct": "percent_per_year",
    "sharpe_excess": "dimensionless_annualised",
    "turnover": "percent_of_book_per_step",
}

#: Said once, here, because the trap is structural. The per-sleeve turnover quoted in the previous
#: cycle (10.87 % stocks + 1.22 % ETF per step) was BACK-SOLVED from the cost deltas of these same
#: eight books under an assumed 50/50 blend. It is an arithmetic restatement of those deltas and
#: nothing else. Once `_LedgerTap` measures the sleeves directly, agreement between the two is
#: arithmetic, not confirmation, and disagreement is a bug in one of them, not a finding.
#: `task431.json` already carries a third, different quantity - the engine's own
#: `counts['turnover']` of 12.7 %/step, mean PLANNED buy+sell dollars over the book total, rounded
#: to 1 dp - against the 12.09 % the back-solve gives for the same book.
INFERENCE_RULE = (
    "algebraically-inferred turnover is a restatement of the cost deltas it was derived from; "
    "it is never independent evidence about the same returns, and agreement with the direct "
    "measurement is arithmetic rather than confirmation"
)


#: How an annualised rate is written on disk, as the divisor that brings it to the decimal
#: contract `metrics.step_risk_free` and `core.portfolio_engine.accrue_interest` both document.
#: The caller declares which one the file holds; nothing here looks at the numbers. On
#: `_sweep_cache_oos/irx.pkl` the 25th percentile is 0.085 and the minimum is -0.105, so neither
#: magnitude nor sign can tell percent from decimal on this series - a sniffing rule would be
#: right on today's file and silently wrong on a ZIRP-era slice.
ANNUAL_RATE_UNITS = {"decimal": 1.0, "percent": 100.0}


def book_path(panel: str, label: str) -> str:
    return os.path.join(OUT_DIR, f"{panel}_{label}.pkl")


def as_annual_decimal(rate, *, unit: str) -> pd.Series:
    """An annualised rate series in the decimal contract, converted from a declared unit.

    Pure: no file, no global, no magnitude test. `unit` is keyword-only and required so that a
    caller cannot pass a series whose unit it never thought about.
    """
    if unit not in ANNUAL_RATE_UNITS:
        raise ValueError(f"unknown rate unit {unit!r}: declare one of {sorted(ANNUAL_RATE_UNITS)}")
    out = pd.Series(rate).astype(float) / ANNUAL_RATE_UNITS[unit]
    out.index = pd.DatetimeIndex(out.index)
    return out.sort_index()


def load_annual_rate(path, *, unit: str, calendar=None) -> pd.Series:
    """Read an annualised rate pickle and hand back the decimal series every consumer expects.

    `_sweep_cache_oos/irx.pkl` is the 13-week T-bill in PERCENT - `data/fetch.py:fetch_tbill`
    says so in as many words - and three scripts (`redesign_lab` for `P.IRX`, `reference_rows`,
    `portfolio_v9`) each wrote their own inline `/ 100.0` on the way in. This script was the
    fourth reader of the same file and forgot, which is how TASK-433 first published a T-bill of
    342 % a year and stamped `below_tbill` on all eight rows. The conversion lives behind one
    named seam with a required unit so the next reader has to state what is on disk instead of
    inferring it from the values.

    `calendar` is the optional price calendar: reindex + ffill + fillna(0.0), exactly the shape
    `redesign_lab` gives `P.IRX`. Left out, the series keeps its own ^IRX calendar - which is
    what the published TASK-433 rows were computed on (the two differ by 1.8e-05 per step).
    """
    out = as_annual_decimal(pd.read_pickle(path), unit=unit)
    if calendar is not None:
        out = out.reindex(pd.DatetimeIndex(calendar)).ffill().fillna(0.0)
    return out


def data_inputs(panel: str) -> dict:
    """Every input FILE a drive of `panel` opens, by logical name.

    A file this panel does not read is recorded as `None`, never left out: an absent key would
    let a panel swap look like a shorter manifest instead of a different one. The names are the
    contract - a rejection reads `[data:membership]` or `[data:etf_close]`, which is a diagnosis,
    where a bare `[data]` would not be. Injectable, so a test never hashes the 264 MB caches.
    """
    etf = os.path.join(R.S.ETF_CACHE, "close.pkl")
    irx = os.path.join(R.OOS_CACHE, "irx.pkl")
    if panel == "russell":
        cache = R.TRADING_CACHE
        return dict(price_close=os.path.join(cache, "close.pkl"),
                    price_close_raw=os.path.join(cache, "close_raw.pkl"),
                    price_open=os.path.join(cache, "open.pkl"),
                    volume=os.path.join(cache, "volume.pkl"),
                    spy=os.path.join(cache, "spy.pkl"),
                    membership=os.path.join(cache, "membership.pkl"),
                    coverage=os.path.join(cache, "coverage.json"),
                    sp500_pit_payload=None, etf_close=etf, irx=irx)
    if panel == "sp500":
        cache = R.OOS_CACHE
        return dict(price_close=os.path.join(cache, "close.pkl"),
                    price_close_raw=os.path.join(cache, "close_raw.pkl"),
                    price_open=os.path.join(cache, "open.pkl"),
                    volume=os.path.join(cache, "volume.pkl"),
                    spy=os.path.join(cache, "spy.pkl"),
                    membership=None, coverage=None,
                    sp500_pit_payload=os.path.join(ROOT, "data_cache", "sp500_pit.json"),
                    etf_close=etf, irx=irx)
    raise ValueError(f"unknown panel {panel!r}")


def _verdict_rule() -> dict:
    """The rule as written before anything was looked at - hashed, so a moved goalpost shows."""
    return dict(SURVIVE_D=R.SURVIVE_D, FAIL_D=R.FAIL_D,
                MAXDD_WORSE_PP=R.MAXDD_WORSE_PP, MIN_CYCLES=R.MIN_CYCLES)


def request(panel: str, label: str, stock_bp: float, etf_bp: float, *,
            calendar: dict | None = None, with_data: bool = True,
            declared: str = "research+validation") -> dict:
    """What is being ASKED FOR, in the manifest's own shape - the other half of the comparison.

    Every value is read out of the live objects, not out of the defaults as written in source:
    `v9_effective` is V9 with the scenario's costs already applied, exactly as `_CostOverride`
    leaves it, so 20/8 and 15/13 stay distinguishable where the 14.0 bp blend `run_russell_prereg`
    computes would not. `calendar` is the grid the answer must land on - the anchor book's, which
    is what makes the 814-mark identity a refusal instead of a note - and is left out only for the
    first book of a run, which has nothing to be anchored to yet.

    That one exception used to be SILENT: `provenance` skipped any field the request omitted, so
    the first book of every run was accredited with its window unchecked, and a 604-mark
    2014-2026 base with a valid manifest passed, became the anchor and set the start date for the
    S&P drive. `calendar=None` therefore no longer means "say nothing"; it means declaring
    `calendar_anchor` in words, which makes `accredit` record `calendar` as UNCOMPARED and print
    `CACHE DEGRADED [calendar]`. The hole is not closed by the declaration - nothing constrains
    the anchor's own window - but it is no longer invisible.

    `with_data=False` drops the `data` block, which `provenance` treats as an identity field and
    refuses. It is kept only for building a request that is deliberately incomplete, and such a
    request cannot accredit anything.
    """
    v9 = dict(EB.V9)
    v9["stock_cost_bp"], v9["etf_cost_bp"] = float(stock_bp), float(etf_bp)
    lab = dict(L.BASE)
    lab.update(L.CONFIGS["T20"])
    rule = _verdict_rule()
    req = dict(
        code=PV.code_identity(),
        config=dict(v9_effective=v9, v9_effective_sha256=PV.sha256_json(v9),
                    lab_config=lab, lab_config_sha256=PV.sha256_json(lab),
                    algo_version=R.ALGO_VERSION, step_bars=int(R.STEP),
                    capital=1.0, whole_shares=False),
        costs=dict(stock_bp_per_side=float(stock_bp), etf_bp_per_side=float(etf_bp),
                   scenario_label=label, source="EB.V9 under _CostOverride"),
        sectors=dict(requested_mode="fixed"),
        units=dict(UNITS),
        period=dict(declared=declared, holdout_sha256=HO.load_holdout()["sha256"]),
        protocol=dict(prereg_sha256=(PV.sha256_lf(R.PREREG_PATH)
                                     if os.path.exists(R.PREREG_PATH) else None),
                      board_task="TASK-433", verdict_rule=rule,
                      verdict_rule_sha256=PV.sha256_json(rule)),
    )
    if calendar is not None:
        req["calendar"] = dict(calendar)
    else:
        # No anchor declaration. It used to go here, and it was an EXEMPTION: the first book
        # declared that nothing constrained its window and `accredit` recorded `calendar` as
        # UNCOMPARED. The grid is derivable from the rules without any book (calendar_spec), so
        # "there is no earlier book" was never a reason to skip the check - only a reason not to
        # use another BOOK as the reference. A request with no calendar is now simply a request
        # with no calendar, and `accredit` refuses it as an undeclared identity block.
        pass
    if with_data:
        req["data"] = PV.data_identity(data_inputs(panel))
    return req


class _LedgerTap:
    """Measure what a drive actually traded, per sleeve, by wrapping `settle` for its duration.

    The engine already carries every number the previous cycle inferred: each fill records its
    `sleeve`, `dollars`, `cost` and `cost_bp` (`core/portfolio_engine.py`), `settle` returns them
    and `state['ledger']` keeps them. `run_russell_prereg._patch_settle_cost` already wraps this
    exact seam for a single total. Wrapping it here keeps the measurement additive - no engine
    file is touched - and it works for BOTH panels, including `drive_sp_same_grid`, which throws
    its counts away at `book, _counts = EB.drive_engine(...)`.

    What comes out is FILLED dollars. That is deliberately a different quantity from the engine's
    `counts['turnover']` (mean PLANNED buy+sell dollars over the book total, rounded to 1 dp) and
    from the algebraic back-solve; see `INFERENCE_RULE` before quoting any two of them together.
    """

    def __init__(self):
        self.by_step: dict = {}
        self._orig = None

    def __enter__(self):
        self._orig = EB.E.settle

        def wrapped(state, exec_date, *a, **kw):
            fills = self._orig(state, exec_date, *a, **kw)
            self._record(exec_date, fills)
            return fills
        EB.E.settle = wrapped
        return self

    def __exit__(self, *exc):
        if self._orig is not None:
            EB.E.settle = self._orig
        return False

    def _record(self, exec_date, fills) -> None:
        for f in fills or []:
            sleeve = str(f.get("sleeve") or "?")
            key = f"{f.get('side')}:{f.get('status')}"
            rec = self.by_step.setdefault(str(exec_date), {}).setdefault(
                sleeve, dict(filled_dollars=0.0, cost_dollars=0.0, n={}))
            rec["n"][key] = rec["n"].get(key, 0) + 1
            if str(f.get("status")) == "filled":
                rec["filled_dollars"] += float(f.get("dollars") or 0.0)
                rec["cost_dollars"] += float(f.get("cost") or 0.0)

    def summary(self, book: pd.Series | None = None) -> dict:
        """Aggregate and per-step, at full precision - the engine rounds `turnover` to 1 dp.

        `cost_bp_effective_by_sleeve` is a free self-check: it must equal the configured bp to
        ~1e-9, so a broken cost override shows up as a number instead of a silently wrong table.
        """
        by_sleeve: dict = {}
        for _date, sleeves in self.by_step.items():
            for sleeve, rec in sleeves.items():
                agg = by_sleeve.setdefault(
                    sleeve, dict(filled_dollars=0.0, cost_dollars=0.0, events={}))
                agg["filled_dollars"] += rec["filled_dollars"]
                agg["cost_dollars"] += rec["cost_dollars"]
                for k, v in rec["n"].items():
                    agg["events"][k] = agg["events"].get(k, 0) + v
        out = dict(
            by_sleeve=by_sleeve,
            by_step=self.by_step,
            cost_bp_effective_by_sleeve={
                s: (a["cost_dollars"] / a["filled_dollars"] * 10000.0) if a["filled_dollars"]
                else None for s, a in by_sleeve.items()},
            settles=len(self.by_step),
            measured=("filled dollars from the ledger; NOT the engine's planned-dollar turnover "
                      "and NOT the algebraic back-solve - see INFERENCE_RULE"),
        )
        if book is not None and len(book) > 1:
            marks = pd.DatetimeIndex(pd.Series(book).index)
            values = pd.Series(book).astype(float)
            shares: dict = {}
            for date, sleeves in self.by_step.items():
                pos = int(marks.searchsorted(pd.Timestamp(date), side="right")) - 1
                if pos < 0:
                    continue
                total = float(values.iloc[pos])
                if not total:
                    continue
                for sleeve, rec in sleeves.items():
                    shares.setdefault(sleeve, []).append(rec["filled_dollars"] / total)
            out["turnover_filled_pct_by_sleeve"] = {
                s: float(sum(v) / len(v) * 100.0) for s, v in shares.items() if v}
            out["turnover_filled_pct_total"] = float(
                sum(out["turnover_filled_pct_by_sleeve"].values()))
        return out


class _CostOverride:
    """Set V9 costs for one drive and put them back whatever happens."""

    def __init__(self, stock_bp: float, etf_bp: float):
        self.stock_bp, self.etf_bp = float(stock_bp), float(etf_bp)
        self._old = {}

    def __enter__(self):
        self._old = {k: EB.V9[k] for k in ("stock_cost_bp", "etf_cost_bp")}
        EB.V9["stock_cost_bp"] = self.stock_bp
        EB.V9["etf_cost_bp"] = self.etf_bp
        return self

    def __exit__(self, *exc):
        EB.V9.update(self._old)
        return False


def load_russell_panel():
    """The prereg's Russell panel: holiday-cleaned cache, membership overlay, START at first membership."""
    P = L.load_panel(oos=False, cache_dir=R.TRADING_CACHE)
    restore = R.attach_russell_membership(P, os.path.join(R.TRADING_CACHE, "membership.pkl"))
    P.ETF = R.S.load_etfs(P.close.index)
    return P, restore, R.start_bar(P)


def _universe_block(P) -> dict:
    """Recorded, not compared: the columns come out of `price_close`, whose bytes ARE compared."""
    cols = sorted(str(c) for c in P.close.columns)
    return dict(n_columns=len(cols), columns_sha256=PV.sha256_json(cols))


def _sectors_block(P, requested_mode: str = "fixed") -> dict:
    """`requested_mode` is the half a caller can know without loading a 264 MB panel, so it is the
    half that gets compared; the mapper's own `info` is recorded beside it.

    The lab's default is a FIXED map, which `redesign_lab`'s docstring says must not be quoted as
    PIT evidence on sectors. A book driven under 'fixed' and one under 'pit' are different
    experiments and must never share a cache slot.
    """
    info = dict(getattr(P, "SECTOR_SOURCE", None) or {})
    smap = getattr(P, "SECTOR", None) or {}
    out = dict(requested_mode=requested_mode, mode=info.get("mode"),
               pit_valid=info.get("pit_valid"), snapshot_date=str(info.get("snapshot_date")),
               n_mapped=info.get("n_mapped"), n_fallback=info.get("n_fallback"))
    if smap:
        out["map_sha256"] = PV.sha256_json({str(k): str(v) for k, v in sorted(smap.items())})
    return out


def drive(panel: str, stock_bp: float, etf_bp: float, *, start_date: str | None = None,
          progress_every: int = 100, drive_fn=None) -> tuple[pd.Series, dict]:
    """One engine run for one panel under one cost scenario, with what it traded MEASURED.

    Returns `(book, measured)`. The counts are no longer dropped at `book, _ = drive_fn(...)`:
    `_LedgerTap` reads the fills the engine already produces, per sleeve and at full precision,
    and the engine's own `counts` come back too whenever the panel's driver hands them over
    (`run_russell_prereg.drive_sp_same_grid` does not - the tap covers it anyway, which is why
    the tap and not a return-value change is the seam). `drive_fn` is the test seam.
    """
    drive_fn = drive_fn or EB.drive_engine
    measured: dict = {}
    with _LedgerTap() as tap, _CostOverride(stock_bp, etf_bp):
        if panel == "russell":
            P, restore, start = load_russell_panel()
            old = EB.START
            try:
                EB.START = start
                book, counts = drive_fn(P, progress_every=progress_every)
            finally:
                EB.START = old
                restore()
            measured.update(engine_counts=counts, start_bar=int(start),
                            universe=_universe_block(P), sectors=_sectors_block(P))
        elif panel == "sp500":
            if start_date is None:
                raise ValueError("sp500 needs the Russell start date to land on the same grid")
            book = R.drive_sp_same_grid(start_date, progress_every=progress_every)
            measured.update(engine_counts=None, start_date=str(start_date),
                            note="drive_sp_same_grid discards the engine counts; the tap does not")
        else:
            raise ValueError(f"unknown panel {panel!r}")
        measured["ledger"] = tap.summary(book)
    return book, measured


def stats_row(book: pd.Series, irx: pd.Series, label: str) -> dict:
    """One row of the table. `irx` is the annualised DECIMAL rate - see `load_annual_rate`.

    `metrics.stats` rounds for display (2 dp, and 1 dp on the drawdown), but the three numbers
    this task publishes are differences of a tenth: a delta taken from rounded inputs has thrown
    away exactly the digits it is made of. So the published metrics are recomputed here at full
    precision and `table` does the rounding.
    """
    net = book.pct_change().dropna()
    rf = M.step_risk_free(irx, book.index)
    row = M.stats(net, label, R.STEP, rf=rf)
    rate = pd.Series(rf).astype(float).dropna()
    rate.index = pd.DatetimeIndex(rate.index)
    common = pd.DatetimeIndex(net.index).intersection(rate.index)
    row.update(ann_net=M.annualised_return(net, R.STEP),
               sharpe_excess=M.sharpe_excess(net, rf, R.STEP),
               maxdd_net=M.max_drawdown(net),
               rf_ann_pct=M.annualised_risk_free(rate.loc[common], R.STEP))
    row["wealth"] = round(float(book.iloc[-1] / book.iloc[0]), 4) if len(book) > 1 else None
    return row


def deltas(row: dict, base: dict) -> dict:
    """The three numbers the task is about, scenario minus base, at full precision.

    Rounding before subtracting throws away the answer: taken from the display values, the
    Russell d_sharpe_excess printed -0.07 where it is -0.0629 and d_maxdd -1.2 where it is
    -1.1554. `table` rounds for the console; the JSON keeps the digits.
    """
    def d(k):
        a, b = row.get(k), base.get(k)
        return float(a) - float(b) if a is not None and b is not None else None
    return dict(d_ann_net=d("ann_net"), d_sharpe_excess=d("sharpe_excess"), d_maxdd=d("maxdd_net"))


#: Display precision only - the rows themselves stay unrounded (see `deltas`).
DISPLAY_DP = {"ann_net": 2, "sharpe_excess": 2, "maxdd_net": 1, "rf_ann_pct": 2,
              "d_ann_net": 4, "d_sharpe_excess": 4, "d_maxdd": 4}


def table(rows: list[dict]) -> pd.DataFrame:
    cols = ["panel", "scenario", "stock_bp", "etf_bp", "ann_net", "sharpe_excess", "maxdd_net",
            "d_ann_net", "d_sharpe_excess", "d_maxdd", "below_tbill", "rf_ann_pct", "provenance"]
    out = pd.DataFrame(rows)[[c for c in cols if c in rows[0]]]
    for col, dp in DISPLAY_DP.items():
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").round(dp)
    return out


def same_marks(books: dict) -> dict:
    """Element-wise index identity across every book in the table - automatic, not a footnote.

    The eight published books are all 814 marks on the same dates, and every delta in the table
    is a subtraction between two of them, so a pair on different grids is not a delta at all.
    This runs whatever route the books came in by, including the historical one where there is no
    manifest to compare a calendar against.
    """
    items = list(books.items())
    if not items:
        return dict(n_books=0, identical=None)
    ref_key, ref = items[0]
    ref_idx = pd.DatetimeIndex(pd.Series(ref).index)
    for key, b in items[1:]:
        idx = pd.DatetimeIndex(pd.Series(b).index)
        if len(idx) != len(ref_idx) or not bool((idx == ref_idx).all()):
            raise SystemExit(
                f"MARK GRID MISMATCH: {key} is {len(idx)} marks "
                f"{idx[0].date() if len(idx) else None}..{idx[-1].date() if len(idx) else None} "
                f"but {ref_key} is {len(ref_idx)} marks {ref_idx[0].date()}..{ref_idx[-1].date()}. "
                "Every delta in this table is a subtraction between two books; on different grids "
                "it is not a delta. Refusing to publish.")
    return dict(n_books=len(items), identical=True, n_marks=int(len(ref_idx)),
                first=str(ref_idx[0].date()), last=str(ref_idx[-1].date()),
                sha256=PV.calendar_sha256(ref_idx))


def cache_state(panel: str, label: str) -> str:
    """`absent` | `accredited` | `historical_incomplete`. Never a bare boolean.

    The old status line printed `os.path.exists`, which is the defect itself written down: it
    reports that a file with that name is there, which is not a statement about the book.
    """
    path = BASE_BOOKS[panel] if label == "base" else book_path(panel, label)
    return "absent" if not os.path.exists(path) else PV.classify(path)



#: An identity block that was NOT compared leaves the book short of full accreditation, however
#: loudly stdout said so. `provenance.IDENTITY_BLOCKS` is the list; `calendar` reaches this path
#: through the anchor declaration, which is legitimate for the book that DEFINES the grid and is
#: still a contract nobody verified.
DEGRADED = "accredited_with_limitations"



def derived_grid(panel: str) -> dict:
    """The expected mark grid for `panel`, from the identified inputs and the engine's rules.

    Takes no book. `calendar_spec.expected_grid` refuses an empty or too-short calendar and a
    membership record that is not on that calendar, so a grid that comes back here is one the
    rules actually produce rather than one shaped by whatever was cached.
    """
    if panel == "russell":
        P = L.load_panel(oos=False, cache_dir=R.TRADING_CACHE)
        restore = R.attach_russell_membership(P, os.path.join(R.TRADING_CACHE, "membership.pkl"))
        try:
            return CSPEC.expected_grid(P.close.index, P.MEMBERSHIP,
                                       calendar_source=f"{R.TRADING_CACHE} close index")
        finally:
            restore()
    P = L.load_panel(oos=True)
    return CSPEC.expected_grid(P.close.index, calendar_source="OOS panel close index")


def check_grid(book, spec: dict, art: str):
    """Validate one book's marks against the derived grid. Returns a limitation, or None.

    Applies to EVERY book - the first one included. The anchor was the one that mattered: it was
    the book nothing checked, and it set `start_date` for the other panel.
    """
    if spec is None or spec.get("unavailable"):
        return dict(
            identity_blocks_not_compared=["calendar"],
            why={"calendar": "expected grid unavailable: " + str((spec or {}).get("unavailable"))},
            recorded_not_compared=[],
            note=("The mark grid could not be derived from the inputs, so this book's calendar "
                  "was not validated against anything."))
    r = CSPEC.validate_marks(book.index, spec)
    if r["ok"]:
        return None
    return dict(
        identity_blocks_not_compared=["calendar"],
        why={"calendar": "; ".join(r["problems"])},
        recorded_not_compared=[],
        note=("The book's marks do not match the grid derived from the rules (%d expected, %d "
              "present). Validated against calendar_spec, not against another book."
              % (r["n_expected"], r["n_got"])),
        grid_check=r, rules=spec.get("rules"))


def classify_accreditation(man: dict):
    """Turn one book's accreditation record into (class, limitation) for the published payload.

    The defect this closes: `accredit` returns a record naming every block it could not compare,
    the call site bound it to `_man` and dropped it, every book that did not RAISE was stamped
    ACCREDITED, and `fully_accredited` was computed as "no historical rows". A book accepted
    under `calendar_anchor` - its window compared against nothing - therefore landed inside
    `fully_accredited=true`. The warning existed only on stdout, which no artifact preserves.

    A console warning is not a contract. Returns `PV.ACCREDITED` only when no identity block went
    uncompared; otherwise `DEGRADED` plus the record of what was missed, which travels into the
    row and forces the aggregate down.
    """
    acc = (man or {}).get("_accreditation")
    if not isinstance(acc, dict) or "compared" not in acc:
        # POSITIVE EVIDENCE REQUIRED. A missing or shapeless record is not a clean bill: it is
        # the absence of the only statement of what was checked. `or {}` here used to turn "no
        # record" into "nothing uncompared" into ACCREDITED - the same absence-reads-as-success
        # defect this function was written to close, one level up.
        return DEGRADED, dict(
            identity_blocks_not_compared=sorted(PV.IDENTITY_BLOCKS),
            why={"_accreditation": "absent or malformed: no record of what was compared"},
            recorded_not_compared=[],
            note=("No accreditation record accompanies this book, so NOTHING is known to have "
                  "been verified. An absent record is not a passing one."))
    compared = list(acc.get("compared") or [])
    uncompared = list(acc.get("uncompared") or [])
    # a mandatory block is satisfied only by appearing in `compared`; silence is not agreement
    identity_missed = sorted(f for f in PV.IDENTITY_BLOCKS if f not in compared)
    if not identity_missed:
        return PV.ACCREDITED, None
    why = acc.get("uncompared_why") or {}
    for f in identity_missed:
        why.setdefault(f, "not listed in `compared`: no evidence this contract was checked"
                       if f not in uncompared else why.get(f))
    return DEGRADED, dict(
        identity_blocks_not_compared=sorted(identity_missed),
        why={k: why.get(k) for k in sorted(identity_missed)},
        recorded_not_compared=sorted(acc.get("uncompared_keys") or []),
        note=("Mandatory identity contract(s) were not verified for this book. It is NOT fully "
              "accredited; a stdout warning does not discharge the contract."),
    )


def run(*, dry_run: bool = False, drive_fn=None, irx: pd.Series | None = None,
        panels=PANELS, scenarios=SCENARIOS, allow_historical: bool = False) -> dict:
    """Drive (or accredit) every scenario on every panel and publish the delta table.

    A cached book is consumed only when its manifest answers for what is being asked - costs,
    code, config, the input bytes, the mark grid, the units, the holdout partition and the
    protocol - and every mismatch stops the run with the field named. Existence is not a cache
    hit; that was the defect.

    The eight books already on disk predate the manifest and cannot be accredited retroactively,
    so they are refused by default. `allow_historical` consumes them anyway, prints the
    `CACHE UNACCREDITED` line for each and stamps every row and the payload, so nothing from such
    a run can be quoted as accredited. It takes a human saying so; it is never the default.

    `irx` is the test seam for the risk-free leg and must already be the annualised DECIMAL rate;
    left out, it is read from `_sweep_cache_oos/irx.pkl` through `load_annual_rate`, which is
    where the percent-to-decimal conversion is declared.
    """
    os.makedirs(OUT_DIR, exist_ok=True)
    status = {p: {lab: cache_state(p, lab) for lab, _, _ in scenarios} for p in panels}
    print("scenarios (stock bp / etf bp per side):", [(a, b, c) for a, b, c in scenarios], flush=True)
    print("cache:", json.dumps(status), flush=True)
    if dry_run:
        return dict(task="TASK-433", scenarios=list(scenarios), cached=status, dry_run=True)

    if irx is None:
        # the file is PERCENT; everything downstream of this line is the annualised decimal
        # contract, and an injected `irx` is expected to be decimal already.
        irx = load_annual_rate(os.path.join(R.OOS_CACHE, "irx.pkl"), unit="percent")
    rows, books, engine_measured = [], {}, {}
    limitations = []   # per-book identity contracts that went uncompared; gates fully_accredited
    start_date, anchor = None, None
    # Derived from the input data and the engine's rules, never from a candidate book, and
    # computed BEFORE the first book is opened so nothing it contains can influence it.
    spec_by_panel = {}
    for _panel in panels:
        try:
            spec_by_panel[_panel] = derived_grid(_panel)
        except Exception as exc:                       # noqa: BLE001 - reported, never swallowed
            spec_by_panel[_panel] = dict(unavailable=str(exc))
            print(f"[{_panel}] expected grid UNAVAILABLE: {exc}", flush=True)

    def grid_as_calendar(panel):
        """The DERIVED grid in the manifest's calendar shape - the first book's reference.

        This is what removes the anchor exemption: the first book is no longer compared against
        nothing, it is compared against the grid the rules produce. Returns None only when the
        grid could not be derived, and `accredit` then refuses the undeclared calendar.
        """
        sp = spec_by_panel.get(panel) or {}
        if sp.get("unavailable") or sp.get("marks") is None:
            return None
        return PV.calendar_block(pd.Series(1.0, index=pd.DatetimeIndex(sp["marks"])))
    for panel in panels:
        base_row = None
        for label, s_bp, e_bp in scenarios:
            path = BASE_BOOKS[panel] if label == "base" else book_path(panel, label)
            book, provenance_cls, limitation = None, None, None
            if os.path.exists(path):
                req = request(panel, label, s_bp, e_bp, calendar=anchor or grid_as_calendar(panel))
                try:
                    book, _man = PV.accredit(path, req)
                    provenance_cls, limitation = classify_accreditation(_man)
                    grid_lim = check_grid(book, spec_by_panel.get(panel), f"{panel}/{label}")
                    if grid_lim is not None:
                        provenance_cls, limitation = DEGRADED, grid_lim
                        print(f"[{panel}/{label}] CACHE DEGRADED [calendar]: "
                              f"{grid_lim['why']['calendar']}", flush=True)
                    print(f"[{panel}/{label}] accredited {len(book)} marks from "
                          f"{os.path.basename(path)}", flush=True)
                except PV.CacheRejected as exc:
                    print(str(exc), flush=True)
                    if exc.tag != PV.UNACCREDITED:
                        raise SystemExit(
                            f"{exc}\nThe cached file is left exactly as it is. Drive the scenario "
                            "to a new accredited name, or point at the book that answers.")
                    if not allow_historical:
                        raise SystemExit(
                            f"{exc}\nRe-run with --allow-historical to report it as history; "
                            "every row of such a run is stamped historical_incomplete.")
                    book = pd.read_pickle(path)
                    provenance_cls = PV.HISTORICAL
            if book is None:
                if panel == "sp500" and start_date is None:
                    rb = books.get(("russell", "base")) or pd.read_pickle(BASE_BOOKS["russell"])
                    start_date = str(pd.Timestamp(rb.index[0]).date())
                print(f"[{panel}/{label}] driving stock {s_bp} bp / etf {e_bp} bp ...", flush=True)
                out = drive(panel, s_bp, e_bp, start_date=start_date, drive_fn=drive_fn)
                book, measured = out if isinstance(out, tuple) else (out, {})
                pd.to_pickle(book, path)
                req = request(panel, label, s_bp, e_bp, calendar=anchor or grid_as_calendar(panel))
                for key in ("universe", "sectors"):
                    if measured.get(key):
                        req[key] = {**(req.get(key) or {}), **measured[key]}
                if measured.get("start_bar") is not None:
                    req["config"]["start_bar"] = int(measured["start_bar"])
                PV.write_manifest(book, path, req, engine=measured)
                engine_measured[f"{panel}/{label}"] = measured
                provenance_cls = PV.ACCREDITED
                # Writing a manifest is not validating the result against what was asked, so the
                # book just driven is checked against the derived grid exactly like a cached one.
                grid_lim = check_grid(book, spec_by_panel.get(panel), f"{panel}/{label}")
                if grid_lim is not None:
                    provenance_cls, limitation = DEGRADED, grid_lim
                    print(f"[{panel}/{label}] DRIVEN BOOK DEGRADED [calendar]: "
                          f"{grid_lim['why']['calendar']}", flush=True)
                print(f"[{panel}/{label}] wrote {os.path.basename(PV.manifest_path(path))}",
                      flush=True)
            if anchor is None:
                anchor = PV.calendar_block(book)
            if limitation is not None:
                limitations.append(dict(panel=panel, scenario=label, **limitation))
            if panel == "russell" and label == "base":
                start_date = str(pd.Timestamp(book.index[0]).date())
            books[(panel, label)] = book
            row = stats_row(book, irx, f"{panel}/{label}")
            row.update(panel=panel, scenario=label, stock_bp=s_bp, etf_bp=e_bp,
                       provenance=provenance_cls)
            if base_row is None:
                base_row = row
            row.update(deltas(row, base_row))
            rf = row.get("rf_ann_pct")
            row["below_tbill"] = bool(rf is not None and row.get("ann_net") is not None
                                      and float(row["ann_net"]) < float(rf))
            rows.append(row)

    marks = same_marks({f"{p}/{lab}": b for (p, lab), b in books.items()})
    tbl = table(rows)
    print("\n--- cost stress (deltas vs base, same engine, same panels as TASK-431) ---", flush=True)
    print(tbl.to_string(index=False), flush=True)
    print(f"\nmark grid: {marks.get('n_marks')} marks {marks.get('first')}..{marks.get('last')} "
          f"identical across all {marks.get('n_books')} books", flush=True)
    worst = [r for r in rows if r["below_tbill"]]
    if worst:
        print("\nBELOW T-BILL:", ", ".join(f"{r['panel']}/{r['scenario']}" for r in worst), flush=True)
    else:
        print("\nno scenario takes ann_net below the T-bill", flush=True)

    historical = [f"{r['panel']}/{r['scenario']}" for r in rows
                  if r.get("provenance") == PV.HISTORICAL]
    if historical:
        print(f"\n{PV.UNACCREDITED}: {', '.join(historical)} - historical artifacts with "
              "incomplete provenance. This table may be reported as history; it is not an "
              "accredited result and TASK-433 stays open on that ground.", flush=True)

    first = min(str(b.index[0].date()) for b in books.values())
    last = max(str(b.index[-1].date()) for b in books.values())
    payload = dict(task="TASK-433", scenarios=list(scenarios), rows=rows,
                   below_tbill=[f"{r['panel']}/{r['scenario']}" for r in worst],
                   marks=marks, engine=engine_measured, inference_rule=INFERENCE_RULE,
                   provenance=dict(accredited=[f"{r['panel']}/{r['scenario']}" for r in rows
                                               if r.get("provenance") == PV.ACCREDITED],
                                   accredited_with_limitations=[f"{l['panel']}/{l['scenario']}"
                                                                for l in limitations],
                                   limitations=limitations,
                                   historical_incomplete=historical,
                                   fully_accredited=(not historical) and not limitations,
                                   fully_accredited_requires=("every book accredited AND every "
                                                              "mandatory identity contract compared "
                                                              "on every book, the calendar included"),
                                   calendar_validated_against=(
                                       "calendar_spec.expected_grid - derived from the input data "
                                       "and the engine's rules before any candidate book was "
                                       "opened; no book validates its own grid and no book is "
                                       "exempt"),
                                   rules=({k: v.get("rules") for k, v in spec_by_panel.items()})),
                   note="frozen v9; only stock_cost_bp / etf_cost_bp vary; base rows are the TASK-431 books")
    payload = HO.stamp(payload, first=first, last=last, declared="research+validation")
    with open(SCRATCH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    print("wrote", SCRATCH, flush=True)
    return payload


#: What is actually on disk for the pre-manifest books, each item with what it supports and what
#: it does not. Nothing here is retrospective metadata about how those runs were made: every item
#: is a file that exists, dated by its own mtime, and the run that produced the books left no log.
HISTORICAL_EVIDENCE = (
    dict(kind="artifact", path="experiments/_lab_scratch/task431.json",
         supports="the config (FROZEN_V9 incl. stock_cost_bp 10.0 / etf_cost_bp 5.0), the frozen "
                  "scoring surface, the period 2010-06-28..2026-08-26, start_bar, coverage, and "
                  "the Russell base's own engine counts",
         does_not_support="that engine_book_russell.pkl on disk IS that run's output - no result "
                          "hash was recorded - nor anything about the S&P same-grid book beyond a "
                          "stats row, nor anything about the six scenario books; and the file was "
                          "itself re-stamped in place at 11:29:51, 53 minutes after the books"),
    dict(kind="run_log", path="experiments/_lab_scratch/task431_run.log",
         supports="that a run happened that morning",
         does_not_support="the books: its tail is the SUPERSEDED run-1 ffill pairing "
                          "(d_sharpe -0.1886), whose output was renamed task431_run1_misaligned.json. "
                          "There is no run log at all for the 10:36:58 books or for any cost_stress run"),
    dict(kind="inputs", path="experiments/_lab_scratch/russell_prereg_cache/",
         supports="one panel, materialised once at 10:28:39-10:28:48 and unchanged since, "
                  "predating BOTH the base books (10:36:58) and all six scenario books (14:34-14:53)",
         does_not_support="which of those bytes any particular book actually read"),
    dict(kind="inputs", path="experiments/_sweep_cache_oos/irx.pkl",
         supports="the risk-free input has not moved since 2026-09-05 17:00:40",
         does_not_support="the unit it was consumed under, which is exactly the defect that "
                          "published a 342 % T-bill on all eight rows"),
    dict(kind="code_mtimes",
         path="experiments/{engine_backtest,run_russell_prereg,redesign_lab}.py, config.py",
         supports="nothing about the books",
         does_not_support="code identity between the bases and the scenarios - it BREAKS it: the "
                          "base books are 10:36:58, the scenario books 14:34-14:53, and "
                          "config.py/engine_backtest.py (11:20:25), run_russell_prereg.py "
                          "(11:29:07) and redesign_lab.py (11:29:24) all sit between them"),
    dict(kind="protocol", path="GROKBOARD.md:1362",
         supports="that the four cost scenarios (10/5, 20/8, 35/10, 50/15) were declared in prose "
                  "before any number was looked at",
         does_not_support="anything about which book answers for which scenario"),
    dict(kind="absent", path="hydra_screener_local/runs/",
         supports="nothing - the directory does not exist",
         does_not_support="there are ZERO runlog manifests for any lab run; the machinery built in "
                          "TASK-359 (utils/runlog.py) was never wired into experiments/, and "
                          "_lab_scratch/ is gitignored so no version history of these JSONs exists"),
)


def historical_books() -> list[str]:
    """The eight books TASK-433 published, base rows first."""
    return [BASE_BOOKS[p] for p in PANELS] + [
        book_path(p, lab) for p in PANELS for lab, _, _ in SCENARIOS if lab != "base"]


def classify_existing_books(paths=None) -> dict:
    """Write `<book>.provenance.json` beside every pre-manifest book. Never a manifest.

    Two classes exist and there is no third: `accredited`, which means a manifest is there and
    verifies, and `historical_incomplete`, which means it is not. All eight of the published
    books are in the second class, the two base books included - matching the TASK-431 row on
    three rounded statistics is corroboration of the config and the period, not proof of
    provenance, and no hash of any of these books was recorded by anything at any time.

    Nothing is overwritten and nothing is invented: `observed` is recomputed now from the
    artifact, `contemporaneous_evidence` is the list of files that actually exist, and `absent`
    names the manifest fields for which there is no evidence at all.
    """
    out = {}
    for path in (paths if paths is not None else historical_books()):
        if not os.path.exists(path):
            print(f"[classify] absent, nothing to classify: {path}", flush=True)
            continue
        if PV.classify(path) == PV.ACCREDITED:
            print(f"[classify] already accredited, left alone: {os.path.basename(path)}", flush=True)
            continue
        rec = PV.classify_historical(
            path, evidence=HISTORICAL_EVIDENCE,
            note="TASK-433 scenario/base book, published 2026-09-11 before any manifest existed. "
                 "It may be reported as history and must never be consumed as a cache hit.")
        out[PV._rel(path)] = rec
        print(f"[classify] {PV.HISTORICAL}: {os.path.basename(path)} "
              f"n={rec['observed']['n']} {rec['observed']['first']}..{rec['observed']['last']} "
              f"sha {rec['observed']['sha256'][:12]} -> "
              f"{os.path.basename(PV.provenance_path(path))}", flush=True)
    print(f"[classify] {len(out)} book(s) classified {PV.HISTORICAL}; none accredited, none "
          "modified, none deleted.", flush=True)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="TASK-433: cost stress in deltas")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-historical", action="store_true",
                    help="consume the pre-manifest books and stamp every row historical_incomplete")
    ap.add_argument("--classify-historical", action="store_true",
                    help="write <book>.provenance.json beside each pre-manifest book and stop")
    args = ap.parse_args(argv)
    if args.classify_historical:
        classify_existing_books()
        return 0
    run(dry_run=args.dry_run, allow_historical=args.allow_historical)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
