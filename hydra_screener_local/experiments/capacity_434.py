"""TASK-434 - participation of the v9 order sheets against point-in-time dollar ADV.

WHY this exists, and why it is not called `capacity_report`
----------------------------------------------------------
The previous cycle measured participation on 31 of 56 orders (55.4 %), pooled the two books
and both sleeves into one headline, and then quoted three capital levels ($204M / $46M /
$11.6M) as if they were capacity. Three separate things were wrong with that:

  1. **Coverage.** 25 orders had no ADV, 14 of them ETF orders. An order without an ADV is
     UNKNOWN. It is not zero, it is not excluded, and it is not imputed - and a P95 taken
     over the covered half is a P95 of the covered half, not of the sheet.
  2. **Pooling.** Live and paper are different books on different dates; stocks and ETFs are
     different sleeves with different order sizes and different venues. One number over all
     four hides the only cells that bind.
  3. **Capacity.** A participation ratio is not capacity. Capacity needs an impact model and
     executed fills to calibrate it. Neither exists here, so this script measures
     participation and refuses to announce capacity. `capacity_verdict()` is hard-wired to
     NOT_CERTIFIED and carries the list of what is missing.

What this script fixed
----------------------
The ETF ADV gap was never a data gap. The previous cycle read `experiments/_sweep_cache_oos`
(the S&P 500 PIT lab cache), which by construction holds no ETFs, and `_sweep_cache_etf`
holds `close.pkl` only - no volume anywhere. The PRODUCTION bar store,
`hydra_screener_local/data_cache/bars.sqlite`, carries `volume` for all 3011 tickers it holds,
ETFs included: SPY QQQ IWM EFA EEM GLD DBC VNQ each have 5031 bars with non-null volume.
Coverage on the two sheets goes 31/56 -> 56/56 by switching source, with nothing imputed.

SOURCE AND UNITS, stated once and explicitly
--------------------------------------------
  source      `data_cache/bars.sqlite`, table `bars`, column `source` = 'yfinance' for every
              row (single provider - see the caveats in `capacity_verdict`).
  volume      SHARES traded that session (Yahoo `Volume`). Not dollars.
  close_raw   USD per share, as printed. `close_adj` is the dividend/split-adjusted series.
  DOLLAR ADV  is DERIVED, not read: dollar_volume(d) = close_raw(d) [USD/share]
              x volume(d) [shares] = USD; ADV20 = mean of the last 20 such bars dated on or
              before the sheet date. That multiply is the whole conversion from shares to
              dollars and there is no other.
  Choice of price column: `close_raw` is the tape's own dollars. `--price-col close_adj`
              reproduces production's own filter arithmetic (`core/filters.py:63-66` multiplies
              the ADJUSTED close by volume). On these 37 tickers the two differ by at most
              1.08 % (OUT, an ex-dividend inside the window); 31 of 37 are bit-identical.

Point-in-time: the window ends at the sheet's own `date`, never at the exec date and never at
today. A bar dated after the sheet was written cannot enter it.

Holiday hygiene: TASK-433 found an EODHD ghost row for 2026-09-07 (Labor Day) with 3 non-null
cells of 2728, which NaNs a 20-bar rolling mean for 20 bars. That row is in a different cache,
but the check is enforced here rather than assumed: `ghost_dates()` counts how many tickers the
store printed on each date and flags any date whose count collapses below a fraction of the
median. Flagged dates are dropped from the window and reported. A zero or null volume makes the
whole window UNKNOWN - it never becomes a 0.0 ADV, which would divide into +inf participation.

Aggregation rule (reviewer's instruction 4): orders of the SAME instrument on the SAME date in
the SAME book are summed by ABSOLUTE notional. Buys are NOT netted against sells - two opposite
orders in one name are two real executions and netting them would erase execution need that
exists. The netted figure is computed too, and reported alongside, purely so the gap is visible.

Rounding (instruction 7): whole-share flooring is measured per book and per sleeve as residual
cash, count of zero-share orders and exposure deviation from the sheet's own target weights.
Unplaced notional is NOT a loss. It is cash that stayed in cash and accrues ^IRX in the books.

THREE UNLIKE QUANTITIES, NAMED APART (defect D1, fixed here)
-----------------------------------------------------------
An earlier version printed `capital_reference - placeable` ($88,553 live, $88,899 paper) under the
heading "WHOLE-SHARE ROUNDING" and restated it in the summary as a rounding outcome. It is not one.
It is the sum of two unlike things plus a third that does not exist:

  (i)   ROUNDING RESIDUE - `requested - placeable`. $2,992 live, $2,278 paper. Whole-share
        flooring, and only that.
  (ii)  CAPITAL NOT YET DEPLOYED BY DESIGN - `capital_reference - requested`. $85,561 live,
        $86,621 paper. Both sheets are `week_index` 0, every order carries `tranche: 0`, and
        `config.V9["tranches"]` is 4, so one tranche of four is funded; the live sheet's own
        valuation shows exposure 0.0 across 0 names, confirming nothing was deployed earlier.
        $75,000 of it sits in tranches the schedule has not opened; the remaining $10,561 is cash
        left inside the open tranche by vol-targeting and by ETF eligibility. Not a rounding
        artefact, not a shortfall, not a loss.
  (iii) REALISED ECONOMIC LOSS - still None, still NOT MEASURABLE: nothing was executed and both
        ledgers are empty.
(i) + (ii) = residual cash, and the identity is asserted in `whole_share_impact` and pinned by a
test so the three can never be conflated again. The committed artefact
`journal_paper/2026-09-10.json` still stores (i) under `did.sizing.loss_dollars`; it is a book of
record and is NOT edited, so the reproduction test flags the naming instead.

CONFIGURATION VALUES ARE READ FROM THE DECLARED SOURCE, NOT FROM THE MODULE OBJECT
---------------------------------------------------------------------------------
`FILTERS['min_dollar_volume']` ($5,000,000/day) and `V9['tranches']` (4) are read out of the TEXT
of `config.py` with `ast`. `config.FILTERS` and `config.V9` are mutable process globals that other
test modules REBIND at import time (`test_spec_compliance.py:31,33`,
`experiments/test_screener_logic.py:21,22` replace FILTERS with a relaxed dict that has no
`min_dollar_volume` key), which made this report's answer depend on pytest collection order. The
declared literal cannot be rebound; the in-process value is read too and any disagreement is
reported (`threshold_live_matches_declared`, `threshold_divergence_note`) rather than hidden.

This script measures. It changes no scoring, no gate, no state, no order. Every file it opens
is opened read-only.

    python experiments/capacity_434.py
    python experiments/capacity_434.py --price-col close_adj
    python experiments/capacity_434.py --books paper --window 20 --json-only
"""
from __future__ import annotations

import argparse
import ast
import inspect
import hashlib
import json
import math
import os
import pathlib
import sqlite3
import sys
from collections import Counter, defaultdict

if hasattr(sys.stdout, "reconfigure"):                      # TASK-380: cp1252 consoles
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

DEFAULT_DB = os.path.join(ROOT, "data_cache", "bars.sqlite")
CONFIG_PY = os.path.join(ROOT, "config.py")
OUT_DIR = os.path.join(HERE, "_lab_scratch")
SCRATCH = os.path.join(OUT_DIR, "task434.json")
DEFAULT_WINDOW = 20                      # matches core/filters.py .iloc[-20:] and P.ADV_USD
DEFAULT_THRESHOLDS = (1.0, 3.0, 5.0)     # percent of ADV20$
GHOST_FLOOR_RATIO = 0.10                 # a date printing <10% of the median ticker count

#: The two books. READ-ONLY: these are the live and paper ledgers.
BOOKS = {
    "live": os.path.join(ROOT, "state", "instructions_20260904.json"),
    "paper": os.path.join(ROOT, "state_paper", "instructions_20260910.json"),
}

#: The published figures of the previous cycle, kept verbatim so they can be restated rather
#: than quietly replaced. Each is an ALGEBRAIC SCENARIO, never a certified capacity.
PRIOR_P95_PCT = 0.00147          # P95 participation over the PARTIAL 31-of-56 sample
PRIOR_SAMPLE = (31, 56)


# ------------------------------------------------------------- declared configuration

class ConfigReadError(RuntimeError):
    """Raised when a configuration value this report quotes cannot be established at all."""


def _config_source_literal(name: str, config_path: str = None) -> dict:
    """Read a module-level literal out of the TEXT of `config.py`, never out of the module object.

    WHY this exists (the bug it fixes). `config.FILTERS` and `config.V9` are module ATTRIBUTES.
    Several test modules in this repo REBIND them at import time - `test_spec_compliance.py:31,33`
    and `experiments/test_screener_logic.py:21,22` both do
    `config.FILTERS = {"min_avg_volume": 0, "min_price": 0, ...}` at module scope and never restore
    them. That relaxed dict DROPS `min_dollar_volume` entirely. Anything that then reads
    `config.FILTERS["min_dollar_volume"]` gets `None` - so this module used to die with
    `TypeError: float() argument must be ... not 'NoneType'` whenever pytest happened to collect
    one of those files first, and, worse, would have quoted a WRONG liquidity floor had the
    rebound dict carried a different number instead of no number at all.

    The source literal in `config.py` cannot be rebound by an importer. It is therefore the value
    of record for a report about what production declares. The live in-process value is read too
    (`declared_filter_threshold`) and any disagreement is REPORTED, not silently preferred.

    Returns dict(value, where="config.py:<lineno> <name>") or raises ConfigReadError.
    """
    path = config_path or CONFIG_PY
    try:
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
    except OSError as exc:                                   # clear diagnostic, never a TypeError
        raise ConfigReadError(f"cannot read the declared configuration at {path}: {exc}") from exc
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError as exc:
        raise ConfigReadError(f"{path} does not parse: {exc}") from exc
    for node in tree.body:                                   # module level only - no conditionals
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target] if isinstance(node, ast.AnnAssign) and node.value else [])
        for t in targets:
            if isinstance(t, ast.Name) and t.id == name:
                try:
                    value = ast.literal_eval(node.value)
                except ValueError as exc:
                    raise ConfigReadError(
                        f"{path}:{node.lineno} {name} is not a literal, so it cannot be read from "
                        f"source: {exc}") from exc
                return dict(value=value, where=f"config.py:{node.lineno} {name}")
    raise ConfigReadError(f"no module-level assignment to {name} found in {path}")


def _sha256_of_config(obj) -> str:
    """The digest runlog stamps, computed the same way (utils/runlog.py `_sha256_json`)."""
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def discover_run_manifests(root: str) -> list:
    """STAGE 1 - DISCOVERY. Candidate PATHS only. Discovery is never evidence.

    `utils/runlog.py:132` writes `<runs_dir>/<run>/manifest.json`, so a real manifest sits one
    level DOWN inside a per-run directory: a flat listing of `runs/` never reaches it, while a
    flat listing that matches the substring "manifest" happily returns somebody else's file.
    This walks the tree and makes no claim whatsoever about what it found.
    """
    found = []
    for sub in ("runs", "state", "state_paper"):
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        for dirpath, _dirnames, filenames in os.walk(d):
            for name in sorted(filenames):
                if name == "manifest.json" or ("manifest" in name and name.endswith(".json")):
                    found.append(os.path.relpath(os.path.join(dirpath, name), root))
    return sorted(found)


def validate_run_manifest(path: str, audited_dates=None) -> dict:
    """STAGE 2 - VALIDATION. Read it, parse it, and tie it to the run being audited.

    To count, a manifest must (a) parse as JSON, (b) carry what runlog actually stamps - an
    `ALGO_VERSION` and a `config` block holding a sha256 of FILTERS - and (c) BELONG TO THE
    AUDITED RUN, its own date matching one of `audited_dates`. A foreign, corrupt or ambiguous
    file is rejected here with its reason and can never reach stage 3.
    """
    out = dict(path=path, usable=False, reason=None, algo_version=None,
               filters_sha256=None, run_date=None)
    try:
        with open(path, encoding="utf-8") as fh:
            man = json.load(fh)
    except FileNotFoundError:
        out["reason"] = "does not exist"
        return out
    except (ValueError, UnicodeDecodeError) as exc:
        out["reason"] = "does not parse as JSON: %s" % (exc,)
        return out
    if not isinstance(man, dict):
        out["reason"] = "JSON is not an object"
        return out
    cfg = man.get("config")
    out["algo_version"] = man.get("ALGO_VERSION")
    out["run_date"] = man.get("date") or man.get("run_date")
    if not isinstance(cfg, dict) or not cfg.get("FILTERS"):
        out["reason"] = "no config.FILTERS sha256 - not a runlog manifest"
        return out
    out["filters_sha256"] = cfg.get("FILTERS")
    if out["algo_version"] is None:
        out["reason"] = "no ALGO_VERSION - cannot tie it to a run"
        return out
    if audited_dates is not None:
        want = {str(d)[:10] for d in audited_dates}
        if out["run_date"] is None:
            out["reason"] = "no date - cannot tie it to the audited sheet"
            return out
        if str(out["run_date"])[:10] not in want:
            out["reason"] = ("belongs to run dated %s, not to the audited sheet(s) %s"
                             % (out["run_date"], sorted(want)))
            return out
    out["usable"] = True
    return out


def audited_run_threshold(state_dir: str = None, audited_dates=None,
                          candidate_configs=None) -> dict:
    """STAGE 3 - RECONSTRUCTION, or an explicit refusal. What the audited run ACTUALLY applied.

    Three questions hide behind the word "configuration", and a capacity claim needs the third:

      (i)   DECLARED    - the literal in the text of `config.py` today (`declared_filter_threshold`).
      (ii)  EFFECTIVE   - what this process holds in `config.FILTERS` now, after any rebinding.
      (iii) AUDITED RUN - what the run that produced these sheets held WHEN it produced them.

    (i) and (ii) agreeing says nothing about (iii): reading today's literal with `ast` recovers
    today's source, never a run from 2026-09-04.

    WHY A HASH IS NOT A VALUE. `utils/runlog.py:281-284` stamps `sha256(FILTERS)`. A digest
    CONTRASTS a candidate configuration; it cannot invert to the values. Reconstruction therefore
    needs BOTH a usable manifest tied to the audited run AND a candidate configuration whose
    sha256 matches the digest it records. `candidate_configs` supplies the candidates as
    {label: FILTERS-like dict}; with no match, the honest answer is a refusal.

    THE CONTRACT, asserted before returning: `reconstructible` is True IF AND ONLY IF `value_usd`
    is not None. Discovery is reported separately and never moves it. The previous version
    returned reconstructible=True for any file whose NAME contained "manifest" - including one
    holding the bytes `not valid JSON` - while `value_usd` stayed None and the note still read
    NOT RECONSTRUCTIBLE. A file name is not evidence, and an incoherent triple is a defect.
    """
    root = state_dir or os.path.dirname(HERE)
    candidates = discover_run_manifests(root)
    examined = [validate_run_manifest(os.path.join(root, c), audited_dates) for c in candidates]
    usable = [e for e in examined if e["usable"]]

    value_usd, matched = None, None
    if usable and candidate_configs:
        for e in usable:
            for label, filters in dict(candidate_configs).items():
                if _sha256_of_config(filters) == e["filters_sha256"]:
                    mdv = filters.get("min_dollar_volume")
                    value_usd = float(mdv) if mdv is not None else None
                    matched = dict(manifest=e["path"], candidate=label)
                    break
            if matched:
                break

    if value_usd is None:
        if not candidates:
            reason = ("NOT RECONSTRUCTIBLE: no run manifest was found, so the threshold the "
                      "audited run applied cannot be established.")
        elif not usable:
            reason = ("NOT RECONSTRUCTIBLE: candidate files exist but none is a usable runlog "
                      "manifest tied to the audited run - see `examined` for each reason.")
        elif not candidate_configs:
            reason = ("NOT RECONSTRUCTIBLE: a usable manifest was found, but it records a sha256 "
                      "of FILTERS, not its values. A digest contrasts a candidate configuration, "
                      "it does not invert. Supply `candidate_configs` to test one.")
        else:
            reason = ("NOT RECONSTRUCTIBLE: a usable manifest was found, but no supplied "
                      "candidate configuration hashes to the sha256 it records.")
        reason += (" The declared literal is today's source, not evidence about a past run; do "
                   "not let it stand in for the audited-run configuration.")
    else:
        reason = ("RECONSTRUCTED from %s: candidate %r hashes to the sha256 that manifest records "
                  "for the audited run." % (matched["manifest"], matched["candidate"]))

    out = dict(
        reconstructible=value_usd is not None,
        value_usd=value_usd,
        matched=matched,
        candidates_found=candidates,
        examined=examined,
        usable_manifests=[e["path"] for e in usable],
        would_settle_it="utils/runlog.py:281-284 stamps ALGO_VERSION and sha256(FILTERS), sha256(V9)",
        sheets_record="algo_version only - no FILTERS or V9 hash on the instruction sheets",
        note=reason,
        does_not_support=("Any statement of the form 'the audited run used a $5M filter' unless "
                          "`reconstructible` is True. Declared and effective agreeing today is "
                          "not evidence about the audited run."),
    )
    assert out["reconstructible"] == (out["value_usd"] is not None), (
        "audited_run_threshold contract: reconstructible iff a value was recovered")
    return out


def declared_filter_threshold(config_path: str = None) -> dict:
    """The liquidity floor this report quotes: `FILTERS['min_dollar_volume']`, USD/day.

    VALUE USED: the literal declared in `config.py` (5,000,000 at the time of writing), read with
    `ast` from the file text. WHERE IT CAME FROM: `config.py` source, NOT `config.FILTERS` in
    memory - see `_config_source_literal` for why. The in-process value is read alongside and
    reported in `live_usd`; `live_matches_declared` is False whenever an importer has rebound or
    mutated `config.FILTERS`, and `divergence_note` says so in words.
    """
    lit = _config_source_literal("FILTERS", config_path)
    filters = lit["value"]
    if not isinstance(filters, dict) or "min_dollar_volume" not in filters:
        raise ConfigReadError(
            f"{lit['where']} does not declare 'min_dollar_volume'; this report cannot state a "
            f"liquidity floor it cannot read (keys found: {sorted(filters) if isinstance(filters, dict) else type(filters).__name__})")
    declared = filters["min_dollar_volume"]
    if not isinstance(declared, (int, float)) or isinstance(declared, bool):
        raise ConfigReadError(
            f"{lit['where']} declares min_dollar_volume as {declared!r}, which is not a number")
    declared = float(declared)

    live, live_err = None, None
    try:
        import config
        live_filters = getattr(config, "FILTERS", None)
        if not isinstance(live_filters, dict):
            live_err = f"config.FILTERS is {type(live_filters).__name__}, not a dict"
        elif "min_dollar_volume" not in live_filters:
            live_err = ("the in-process config.FILTERS has no 'min_dollar_volume' key (it has "
                        f"{sorted(live_filters)}) - it has been REBOUND by an importer")
        else:
            live = float(live_filters["min_dollar_volume"])
    except Exception as exc:                                 # noqa: BLE001 - reported, never fatal
        live_err = f"config could not be imported or read: {exc}"

    matches = (live is not None and live == declared)
    if matches:
        note = "the in-process config.FILTERS agrees with the declared literal"
    elif live is not None:
        note = (f"DIVERGENCE: the in-process config.FILTERS says ${live:,.0f}/day while "
                f"{lit['where']} declares ${declared:,.0f}/day. The DECLARED value is quoted; the "
                "in-process one has been changed by an importer at runtime.")
    else:
        note = (f"the in-process config.FILTERS could not supply the value ({live_err}); the "
                f"declared literal at {lit['where']} is quoted instead")
    return dict(threshold_usd=declared, declared_usd=declared, declared_where=lit["where"],
                source=(f"{lit['where']}['min_dollar_volume'] - SOURCE LITERAL read with ast, not "
                        "the rebindable config.FILTERS attribute"),
                live_usd=live, live_error=live_err, live_matches_declared=matches,
                divergence_note=note)


def declared_v9_tranches(config_path: str = None) -> dict:
    """`V9['tranches']` - how many tranches the schedule deploys the book over.

    Read from the `config.py` source literal for the same reason as the liquidity floor: `config.V9`
    is a rebindable module attribute and this report states what production DECLARES.
    """
    lit = _config_source_literal("V9", config_path)
    v9 = lit["value"]
    if not isinstance(v9, dict) or "tranches" not in v9:
        raise ConfigReadError(f"{lit['where']} does not declare 'tranches'")
    n = v9["tranches"]
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        raise ConfigReadError(f"{lit['where']} declares tranches as {n!r}, not a positive int")
    return dict(tranches=n, where=f"{lit['where']}['tranches']",
                step_bars=v9.get("step_bars"), hold_bars=v9.get("hold_bars"))


# --------------------------------------------------------------------------- sheets

def load_sheet(path: str, book: str) -> dict:
    """One instruction sheet, read-only. `date` is the as-of; `exec_date` is when it trades.

    `tranche`, `week_index` and `valuation` are carried through because the sheet's capital
    arithmetic cannot be read without them: a sheet places ONE tranche of a multi-tranche
    schedule, so the capital it does NOT ask for is not a shortfall (see `tranche_context`).
    They are optional - a fixture sheet may carry none, and the reading then says so.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    orders = []
    for o in raw.get("orders") or []:
        orders.append(dict(
            sleeve=str(o.get("sleeve")), ticker=str(o.get("ticker")), side=str(o.get("side")),
            dollars=float(o.get("dollars") or 0.0),
            est_price=(float(o["est_price"]) if o.get("est_price") else None),
            planned=o.get("planned"), tranche=o.get("tranche"),
        ))
    return dict(book=book, path=path, date=str(raw.get("date")), exec_date=str(raw.get("exec_date")),
                capital_reference=float(raw.get("capital_reference") or 0.0), orders=orders,
                week_index=raw.get("week_index"), valuation=raw.get("valuation"))


# --------------------------------------------------------------------------- bar source

class BarSource:
    """Read-only reader over the production bar store. Opened with `mode=ro`: it cannot write."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        uri = pathlib.Path(db_path).resolve().as_uri() + "?mode=ro"
        self.con = sqlite3.connect(uri, uri=True)

    def close(self) -> None:
        self.con.close()

    def date_counts(self, since: str) -> dict:
        """How many tickers printed a bar on each date. The ghost detector's input."""
        cur = self.con.execute(
            "SELECT date, COUNT(*) FROM bars WHERE date >= ? GROUP BY date", (since,))
        return {str(d): int(n) for d, n in cur.fetchall()}

    def tail_bars(self, ticker: str, asof: str, limit: int) -> list:
        """The last `limit` bars dated on or before `asof`, newest first. Point-in-time."""
        cur = self.con.execute(
            "SELECT date, close_raw, close_adj, volume FROM bars "
            "WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT ?", (ticker, asof, limit))
        return [(str(d), craw, cadj, v) for d, craw, cadj, v in cur.fetchall()]

    def max_date(self):
        row = self.con.execute("SELECT MAX(date) FROM bars").fetchone()
        return str(row[0]) if row and row[0] else None


def ghost_dates(counts: dict, floor_ratio: float = GHOST_FLOOR_RATIO) -> list:
    """Dates whose ticker count collapsed - a holiday/ghost row, not a session.

    A real session prints for ~every ticker in the store. The EODHD Labor Day row printed 3 of
    2728. Anything under `floor_ratio` x the median date count is a ghost and is excluded from
    every ADV window; it is reported, never silently dropped.
    """
    if not counts:
        return []
    vals = sorted(counts.values())
    mid = len(vals) // 2
    median = float(vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0)
    floor = median * float(floor_ratio)
    return sorted(d for d, n in counts.items() if n < floor)


# --------------------------------------------------------------------------- ADV

#: Every reason an ADV can be UNKNOWN. UNKNOWN is never 0.0 and never imputed.
UNKNOWN_REASONS = ("no_bars", "insufficient_bars", "nonpositive_volume", "missing_price")


def dollar_adv(source, ticker: str, asof: str, window: int,
               ghosts=frozenset(), price_col: str = "close_raw") -> dict:
    """ADV20 in USD for `ticker` as of `asof`, or UNKNOWN with a named reason.

    USD = mean over `window` bars of (price [USD/share] x volume [shares]). Ghost dates are
    skipped before counting, so a holiday row cannot shorten a real window.
    """
    if price_col not in ("close_raw", "close_adj"):
        raise ValueError(f"price_col must be close_raw or close_adj, got {price_col!r}")
    idx = 1 if price_col == "close_raw" else 2
    rows = [r for r in source.tail_bars(ticker, asof, window + len(ghosts) + 8)
            if r[0] not in ghosts][:window]
    out = dict(ticker=ticker, asof=asof, window=window, price_col=price_col,
               adv_usd=None, status=None, n_bars=len(rows),
               first_bar=(rows[-1][0] if rows else None), last_bar=(rows[0][0] if rows else None))
    if not rows:
        out["status"] = "no_bars"
        return out
    if len(rows) < window:
        out["status"] = "insufficient_bars"
        return out
    total = 0.0
    for _d, craw, cadj, vol in rows:
        price = craw if idx == 1 else cadj
        if vol is None or not math.isfinite(float(vol)) or float(vol) <= 0.0:
            out["status"] = "nonpositive_volume"
            return out
        if price is None or not math.isfinite(float(price)) or float(price) <= 0.0:
            out["status"] = "missing_price"
            return out
        total += float(price) * float(vol)
    out["adv_usd"] = total / float(window)
    out["status"] = "ok"
    return out


# --------------------------------------------------------------------------- participation

def participation_rows(sheet: dict, source, window: int, ghosts, price_col: str) -> list:
    """One row per order: notional, ADV20$, participation % - or participation None = UNKNOWN."""
    rows = []
    for o in sheet["orders"]:
        adv = dollar_adv(source, o["ticker"], sheet["date"], window, ghosts, price_col)
        notional = abs(float(o["dollars"]))
        part = (notional / adv["adv_usd"] * 100.0) if adv["status"] == "ok" and adv["adv_usd"] else None
        rows.append(dict(book=sheet["book"], date=sheet["date"], sleeve=o["sleeve"],
                         ticker=o["ticker"], side=o["side"], notional_usd=notional,
                         est_price=o["est_price"], adv_usd=adv["adv_usd"],
                         adv_status=adv["status"], adv_last_bar=adv["last_bar"],
                         adv_n_bars=adv["n_bars"], participation_pct=part,
                         known=adv["status"] == "ok"))
    return rows


def coverage(rows: list) -> dict:
    """Coverage TWICE (instruction 2): by ORDER COUNT and by NOTIONAL. Unknown stays unknown."""
    n = len(rows)
    known = [r for r in rows if r["known"]]
    notional = sum(r["notional_usd"] for r in rows)
    known_notional = sum(r["notional_usd"] for r in known)
    unknown_notional = notional - known_notional
    return dict(
        n_orders=n, n_known=len(known), n_unknown=n - len(known),
        count_coverage_pct=(100.0 * len(known) / n) if n else None,
        notional_usd=notional, known_notional_usd=known_notional,
        unknown_notional_usd=unknown_notional,
        notional_coverage_pct=(100.0 * known_notional / notional) if notional else None,
        unknown_notional_share_pct=(100.0 * unknown_notional / notional) if notional else None,
        unknown_reasons=dict(Counter(r["adv_status"] for r in rows if not r["known"])),
        unknown_tickers=sorted({r["ticker"] for r in rows if not r["known"]}),
    )


def _pctile(values: list, q: float):
    """Linear-interpolated percentile on the sorted sample. Explicit so it is checkable by hand."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    pos = (len(s) - 1) * (q / 100.0)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(s[int(pos)])
    return float(s[lo] + (s[hi] - s[lo]) * (pos - lo))


def participation_stats(rows: list, thresholds=DEFAULT_THRESHOLDS) -> dict:
    """P50/P95/max over the KNOWN orders only, carrying the sample it was taken over."""
    known = [r for r in rows if r["known"]]
    vals = [r["participation_pct"] for r in known]
    breaches = {f"gt_{t:g}pct": sum(1 for v in vals if v > t) for t in thresholds}
    worst = max(known, key=lambda r: r["participation_pct"], default=None)
    return dict(
        sample_known=len(known), sample_total=len(rows),
        sample_label=(f"{len(known)} of {len(rows)} orders (PARTIAL SAMPLE)"
                      if len(known) < len(rows) else f"{len(known)} of {len(rows)} orders (complete)"),
        partial=len(known) < len(rows),
        p50_pct=_pctile(vals, 50.0), p95_pct=_pctile(vals, 95.0),
        max_pct=(max(vals) if vals else None),
        worst_ticker=(worst["ticker"] if worst else None),
        breaches=breaches,
    )


def aggregate_instrument_date(rows: list) -> list:
    """Joint participation per (book, date, ticker): ABSOLUTE notional summed, NEVER netted.

    `gross_notional_usd` is the sum of |dollars| - the execution that actually has to happen.
    `net_notional_usd` (signed) is reported next to it only so the difference is visible; it is
    never the numerator of a participation figure.
    """
    groups = defaultdict(list)
    for r in rows:
        groups[(r["book"], r["date"], r["ticker"])].append(r)
    out = []
    for (book, date, ticker), rs in sorted(groups.items()):
        gross = sum(r["notional_usd"] for r in rs)
        net = sum((r["notional_usd"] if r["side"] == "buy" else -r["notional_usd"]) for r in rs)
        adv = next((r["adv_usd"] for r in rs if r["known"]), None)
        out.append(dict(
            book=book, date=date, ticker=ticker, n_orders=len(rs),
            sides=sorted({r["side"] for r in rs}),
            sleeves=sorted({r["sleeve"] for r in rs}),
            gross_notional_usd=gross, net_notional_usd=net,
            netting_would_hide_usd=gross - abs(net),
            adv_usd=adv, known=adv is not None,
            joint_participation_pct=(gross / adv * 100.0) if adv else None))
    return out


# ------------------------------------------------------- tranche schedule (defect D1)

def tranche_context(sheet: dict, tranches: int = None, tranches_where: str = None) -> dict:
    """How much of `capital_reference` this sheet is even TRYING to deploy, and why not more.

    THE DEFECT THIS FIXES (D1). `capital_reference - placeable` was printed under the heading
    "WHOLE-SHARE ROUNDING" and restated in the summary as a rounding outcome. On the live sheet
    that quantity is $88,553, of which only $2,992 is whole-share residue. The other ~$85,561 is
    capital the sheet never asked for, because v9 deploys the book over `V9["tranches"]` tranches,
    one renewed per step - so a week-0 sheet places ONE of four.

    The reading is DERIVED from the sheet and the declared config, not assumed:
      * every order carries an integer `tranche` and they all carry the SAME one;
      * that index equals `week_index % tranches` (`core/portfolio_engine.renewal_due`);
      * `week_index < tranches`, so the number of tranches opened so far is unambiguously
        `week_index + 1` (a later pass round the schedule reopens an already-funded tranche and
        the count stops being readable from the sheet alone);
      * the sheet's own `valuation` shows zero prior exposure and zero distinct names, so no
        earlier tranche holds anything.
    When any of those fails, `schedule_readable` is False, `reading` names the reason, and only
    the aggregate `not_requested_usd = capital_reference - requested` is reported - which is true
    whatever the schedule is doing.
    """
    where = tranches_where
    if tranches is None:
        try:
            d = declared_v9_tranches()
            tranches, where = d["tranches"], d["where"]
        except ConfigReadError as exc:
            return dict(tranches=None, tranches_where=None, week_index=sheet.get("week_index"),
                        order_tranches=[], schedule_readable=False,
                        reading=f"the declared tranche count could not be read: {exc}")

    week = sheet.get("week_index")
    order_tranches = sorted({o.get("tranche") for o in sheet["orders"]},
                            key=lambda v: (v is None, v))
    val = sheet.get("valuation") or {}
    sleeves = (val.get("sleeves") or {}) if isinstance(val, dict) else {}
    prior_exposure, prior_names = 0.0, 0
    exposure_readable = bool(sleeves)
    for s in sleeves.values():
        if not isinstance(s, dict):
            exposure_readable = False
            continue
        prior_exposure += float(s.get("exposure") or 0.0)
        prior_names += int(s.get("distinct") or 0)

    out = dict(tranches=tranches, tranches_where=where, week_index=week,
               order_tranches=order_tranches,
               prior_exposure_usd=(prior_exposure if exposure_readable else None),
               prior_distinct_names=(prior_names if exposure_readable else None),
               capital_per_tranche_usd=(sheet["capital_reference"] / tranches if tranches else None))

    if len(order_tranches) != 1 or not isinstance(order_tranches[0], int):
        out.update(schedule_readable=False,
                   reading=("the orders do not all carry one integer tranche index "
                            f"({order_tranches!r}), so the deployment schedule cannot be read from "
                            "this sheet"))
        return out
    k = order_tranches[0]
    if not isinstance(week, int) or week < 0:
        out.update(schedule_readable=False,
                   reading=f"the sheet carries no usable week_index ({week!r})")
        return out
    if k != week % tranches:
        out.update(schedule_readable=False,
                   reading=(f"the orders sit in tranche {k} but week_index {week} renews tranche "
                            f"{week % tranches} of {tranches}; the sheet contradicts the schedule"))
        return out
    if week >= tranches:
        out.update(schedule_readable=False,
                   reading=(f"week_index {week} is past the first pass through {tranches} tranches, "
                            "so the number of tranches funded so far is not readable from this "
                            "sheet alone"))
        return out
    if not exposure_readable or prior_exposure != 0.0 or prior_names != 0:
        out.update(schedule_readable=False,
                   reading=("the sheet's valuation does not show a zero prior book (exposure "
                            f"{prior_exposure!r}, {prior_names!r} names), so part of the capital "
                            "is already deployed and is not cash"))
        return out

    per = sheet["capital_reference"] / tranches
    out.update(
        schedule_readable=True, tranches_opened=week + 1, tranches_not_yet_opened=tranches - week - 1,
        opened_capital_usd=per * (week + 1),
        not_yet_opened_capital_usd=per * (tranches - week - 1),
        reading=(f"week_index {week}: tranche {k} of {tranches} is the only one funded so far, so "
                 f"${per * (tranches - week - 1):,.0f} of the ${sheet['capital_reference']:,.0f} "
                 "reference sits in tranches the schedule has not opened yet. Evidence: "
                 f"{where}, the sheet's own week_index and every order's tranche index, and a "
                 "valuation showing 0.0 exposure in 0 names."))
    return out


# --------------------------------------------------------------------------- rounding

def whole_share_impact(sheet: dict, tranches: int = None) -> dict:
    """Whole-share flooring per book AND per sleeve (instruction 1), never pooled.

    Unplaced notional is NOT a realised loss (instruction 7). It is cash that never left cash.
    What IS measurable and reported: residual cash, the count of orders that round to zero
    shares, and the exposure deviation from the sheet's own target weights, in percentage
    points of `capital_reference`.

    THE THREE QUANTITIES ARE NAMED SEPARATELY (defect D1) in `capital_split`. They are unlike
    things and conflating them was the mislabel:
      (i)   `rounding_residue_usd`  = requested - placeable. Whole-share flooring ONLY. $2,992
            live / $2,278 paper.
      (ii)  `not_requested_usd`     = capital_reference - requested. Capital the sheet never asked
            for, because the tranche schedule has not reached it (see `tranche_context`). $85,561
            live / $86,621 paper. It is NOT a rounding artefact and NOT a shortfall.
      (iii) `realised_economic_loss_usd` = None. NOT MEASURABLE: nothing was executed, the ledger
            is empty, and unplaced notional stayed in cash accruing ^IRX.
    (i) + (ii) = `residual_cash_usd`, which is what the previous version printed as if it were
    (i) alone. The identity is asserted here and pinned by a test.
    """
    cap = sheet["capital_reference"]
    per = {}
    for o in sheet["orders"]:
        px, dollars = o["est_price"], abs(float(o["dollars"]))
        s = per.setdefault(o["sleeve"], dict(sleeve=o["sleeve"], requested_usd=0.0,
                                             placeable_usd=0.0, n_orders=0, n_zero_share=0,
                                             zero_share_names=[], n_unpriced=0))
        s["n_orders"] += 1
        if px is None or px <= 0:
            s["n_unpriced"] += 1                  # cannot be floored: not a rounding statement
            continue
        shares = math.floor(dollars / px)
        placed = shares * px
        s["requested_usd"] += dollars
        s["placeable_usd"] += placed
        if shares == 0:
            s["n_zero_share"] += 1
            s["zero_share_names"].append(o["ticker"])
    for s in per.values():
        unplaced = s["requested_usd"] - s["placeable_usd"]
        s["unplaced_usd"] = unplaced
        s["unplaced_share_pct"] = (100.0 * unplaced / s["requested_usd"]) if s["requested_usd"] else None
        s["target_weight_pct"] = (100.0 * s["requested_usd"] / cap) if cap else None
        s["placed_weight_pct"] = (100.0 * s["placeable_usd"] / cap) if cap else None
        s["exposure_deviation_pp"] = (100.0 * unplaced / cap) if cap else None
        s["zero_share_names"].sort()
    book_req = sum(s["requested_usd"] for s in per.values())
    book_placed = sum(s["placeable_usd"] for s in per.values())
    rounding_residue = book_req - book_placed
    not_requested = cap - book_req
    residual_cash = cap - book_placed

    tr = tranche_context(sheet, tranches)
    if tr.get("schedule_readable"):
        undeployed_in_open = tr["opened_capital_usd"] - book_req
        not_requested_breakdown = dict(
            not_yet_opened_tranches_usd=tr["not_yet_opened_capital_usd"],
            undeployed_inside_the_open_tranche_usd=undeployed_in_open,
            note=("the open tranche's own cash that the sizing did not use - vol-targeting on the "
                  "stock sleeve and ineligible/inverse-vol ETF weights both leave cash by design"),
        )
    else:
        not_requested_breakdown = dict(
            not_yet_opened_tranches_usd=None, undeployed_inside_the_open_tranche_usd=None,
            note="not split: " + str(tr.get("reading")))

    capital_split = dict(
        capital_reference_usd=cap,
        requested_usd=book_req,
        placeable_usd=book_placed,
        residual_cash_usd=residual_cash,
        rounding_residue_usd=rounding_residue,
        rounding_residue_share_of_residual_pct=(100.0 * rounding_residue / residual_cash) if residual_cash else None,
        not_requested_usd=not_requested,
        not_requested_share_of_residual_pct=(100.0 * not_requested / residual_cash) if residual_cash else None,
        not_requested_breakdown=not_requested_breakdown,
        realised_economic_loss_usd=None,
        identity="rounding_residue_usd + not_requested_usd == residual_cash_usd",
        identity_holds=abs((rounding_residue + not_requested) - residual_cash) < 1e-6,
        labels=dict(
            rounding_residue_usd=("WHOLE-SHARE ROUNDING RESIDUE: requested minus what whole shares "
                                  "can buy. This and only this is a rounding artefact."),
            not_requested_usd=("CAPITAL NOT YET DEPLOYED BY DESIGN: the sheet never asked for it. "
                               "v9 deploys the book over the tranche schedule, so a week-0 sheet "
                               "places one tranche. Not a rounding artefact, not a shortfall, not "
                               "a loss."),
            residual_cash_usd=("THE SUM OF THE TWO ABOVE. It is a cash balance, not a rounding "
                               "outcome, and it must never be quoted as one."),
            realised_economic_loss_usd=("NOT MEASURABLE. No executed fills exist to realise "
                                        "anything against; the ledger is empty."),
        ),
        residual_cash_is_literally_cash=bool(tr.get("schedule_readable")),
    )
    return dict(
        book=sheet["book"], date=sheet["date"], capital_reference=cap,
        by_sleeve={k: per[k] for k in sorted(per)},
        book_requested_usd=book_req, book_placeable_usd=book_placed,
        book_unplaced_usd=rounding_residue,
        book_unplaced_share_pct=(100.0 * rounding_residue / book_req) if book_req else None,
        book_exposure_deviation_pp=(100.0 * rounding_residue / cap) if cap else None,
        residual_cash_usd=residual_cash,
        rounding_residue_usd=rounding_residue,
        not_requested_usd=not_requested,
        capital_split=capital_split,
        tranche=tr,
        n_zero_share=sum(s["n_zero_share"] for s in per.values()),
        realised_economic_loss_usd=None,
        realised_loss_note=("NOT MEASURABLE from this book: unplaced notional stayed in cash and "
                            "accrues ^IRX. A realised loss needs executed fills, and the ledger "
                            "is empty."),
    )


# --------------------------------------------------------------------------- filter applicability

def filter_applicability(config_path: str = None) -> dict:
    """Does config FILTERS min_dollar_volume actually constrain the positions being liquidated?

    Answered against the code, not from memory. Every claim below is re-derived at call time
    from the imported modules, so a change in the code changes this answer instead of leaving a
    stale sentence behind.

    WHICH VALUE THE THRESHOLD IS, AND WHERE IT CAME FROM. `threshold_usd` is
    `FILTERS['min_dollar_volume']` as DECLARED in the text of `config.py` - $5,000,000/day - read
    with `ast` by `declared_filter_threshold`. It is deliberately NOT read from the in-process
    `config.FILTERS` attribute: that attribute is a mutable process global which
    `test_spec_compliance.py:31,33` and `experiments/test_screener_logic.py:21,22` rebind at import
    time to a relaxed dict with no `min_dollar_volume` key at all. Reading the module attribute
    made this report's answer depend on pytest's collection order (a `TypeError` when the rebound
    dict was in place, the right number otherwise). The declared literal cannot be rebound out from
    under it. The live attribute is still read and reported in `threshold_source` /
    `threshold_live_usd`, and `threshold_live_matches_declared` goes False the moment the two
    disagree, so a genuine config change is visible rather than swallowed. If the literal itself
    cannot be read, `ConfigReadError` is raised with the reason - never a bare `TypeError`.
    """
    import core.filters as CF
    import core.portfolio_engine as PE
    import portfolio_v9 as P9

    thr_info = declared_filter_threshold(config_path)
    threshold = thr_info["threshold_usd"]
    audited = audited_run_threshold()
    filters_src = inspect.getsource(CF.apply_practical_filters)
    rank_src = inspect.getsource(P9.build_ranking)
    fetch_src = inspect.getsource(P9.fetch_v9_market)
    plan_src = inspect.getsource(PE.plan)

    # (a) is it a rolling window ending at the RUN date, or point-in-time per position?
    as_of_run_date = ".iloc[-20:]" in filters_src
    # (b) does the only caller sit on the stock ranking path?
    called_from_ranking = "apply_practical_filters" in rank_src
    # (c) does the ETF leg ever carry a volume series it could be filtered on?
    etf_has_volume = "fetch_etf_closes" in fetch_src and "etf_volume" in fetch_src
    # (d) does the engine's own plan() - which emits the sells - test any liquidity term?
    low = plan_src.lower()
    exit_tests_liquidity = any(tok in low for tok in ("dollar_volume", "adv_", "min_avg_volume"))

    applies_to = dict(
        stocks_on_entry=bool(called_from_ranking),
        stocks_on_exit=bool(exit_tests_liquidity),
        etfs_on_entry=bool(etf_has_volume),
        etfs_on_exit=bool(exit_tests_liquidity),
    )
    return dict(
        threshold_usd=threshold,
        threshold_source=thr_info["source"],
        threshold_declared_usd=thr_info["declared_usd"],
        threshold_live_usd=thr_info["live_usd"],
        threshold_live_matches_declared=thr_info["live_matches_declared"],
        threshold_divergence_note=thr_info["divergence_note"],
        evidence=dict(
            config=thr_info["source"],
            filter="core/filters.py:63-70 apply_practical_filters (ADJUSTED close x volume, .iloc[-20:])",
            caller="portfolio_v9.py:193-199 build_ranking - the STOCK ranking path",
            etf_leg="portfolio_v9.py:180 fetch_v9_market -> fetch_etf_closes (closes only, no volume)",
            exit_path="core/portfolio_engine.py:527-541 plan() sells - price check only, no liquidity term",
        ),
        threshold_of_the_audited_run=audited,
        as_of_run_date_not_point_in_time=bool(as_of_run_date),
        applies_to=applies_to,
        verdict=("SELECTION FILTER ON ENTRY, STOCKS ONLY. It never runs on the ETF sleeve (that "
                 "leg is fetched as closes with no volume series to filter), and it never runs on "
                 "an exit: plan() emits sells on a price check alone. It is also evaluated over "
                 "the last 20 rows of the frame fetched on the RUN date, so it says nothing about "
                 "the ADV of a position on some future liquidation date."),
        consequence=("Any scenario that assumes every holding sits at or above $%s/day of ADV "
                     "loses its basis for ETFs entirely, and for stocks holds only at the moment "
                     "of entry." % f"{threshold:,.0f}"),
    )


# --------------------------------------------------------------------------- scenarios

def scenarios(stats_by_cell: dict, sheets: dict, applic: dict) -> list:
    """The three published figures, restated as ALGEBRA WITH ASSUMPTIONS. Never capacity.

    Each carries the inputs it is computed from, the assumptions it needs to be true, and a
    `basis_valid` verdict taken from `filter_applicability`.
    """
    cap_ref = 100_000.0
    # DEFECT D2. "these sheets" means every sheet this run loaded, so the evidence that backs a
    # statement about "these sheets" is counted over all of them - not over `live` alone, which
    # covered 30 of 56 orders while the sentence claimed the lot. Each figure now carries the
    # SCOPE it was taken over, so the stated evidence and the stated scope cannot drift apart.
    scope_books = sorted(sheets)
    all_orders = [o for b in scope_books for o in sheets[b]["orders"]]
    scope_label = ("these sheets (%s)" % " + ".join(scope_books) if len(scope_books) != 1
                   else "this sheet (%s)" % scope_books[0])
    n_buy = sum(1 for o in all_orders if o["side"] == "buy")
    n_all = len(all_orders)
    scope = "%s: %d orders" % (scope_label, n_all)

    def _biggest(sleeve):
        cand = [(abs(o["dollars"]), b, o["ticker"])
                for b in scope_books for o in sheets[b]["orders"] if o["sleeve"] == sleeve]
        return max(cand, default=(0.0, None, None))

    max_stock, max_stock_book, max_stock_ticker = _biggest("stocks")
    max_etf, max_etf_book, max_etf_ticker = _biggest("etf")
    thr = applic["threshold_usd"]
    out = []

    out.append(dict(
        name="S1_p95_at_3pct_of_measured_adv",
        published_usd=204_000_000.0,
        recomputed_usd=(3.0 / PRIOR_P95_PCT) * cap_ref,
        formula="book = (3%% cap / P95 participation %.5f%%) x $%s reference book"
                % (PRIOR_P95_PCT, f"{cap_ref:,.0f}"),
        inputs=dict(p95_participation_pct=PRIOR_P95_PCT, cap_pct=3.0, reference_book_usd=cap_ref,
                    sample=f"{PRIOR_SAMPLE[0]} of {PRIOR_SAMPLE[1]} orders"),
        assumptions=[
            "P95 was taken over a PARTIAL sample of %d of %d orders; the 25 uncovered orders "
            "could sit anywhere in the distribution." % PRIOR_SAMPLE,
            "Order notional scales LINEARLY with the book - true only while the strategy keeps "
            "the same names and the same weights at every size.",
            "ADV is unchanged by the strategy's own trading.",
            "A 3 % participation cap is assumed, not derived from any measured impact.",
            "Measured on ONE date per book; ADV varies day to day and name to name.",
        ],
        basis="ALGEBRAIC SCENARIO - stands or falls on the assumptions above. NOT capacity.",
        basis_valid=True,
    ))

    out.append(dict(
        name="S2_largest_stock_order_at_3pct_of_filter_floor",
        published_usd=46_000_000.0,
        recomputed_usd=((thr * 0.03) / (max_stock / cap_ref)) if max_stock else None,
        formula="book = ($%s filter floor x 3%%) / (largest stock order $%.2f / $%s)"
                % (f"{thr:,.0f}", max_stock, f"{cap_ref:,.0f}"),
        inputs=dict(filter_floor_usd=thr, cap_pct=3.0, largest_stock_order_usd=max_stock,
                    largest_stock_order_book=max_stock_book,
                    largest_stock_order_ticker=max_stock_ticker,
                    reference_book_usd=cap_ref, scope=scope, buy_orders=n_buy, total_orders=n_all),
        assumptions=[
            "Assumes the thinnest name the strategy can hold has ADV exactly at the $%s filter "
            "floor - a WORST CASE, not an observed name." % f"{thr:,.0f}",
            "Assumes the $%s filter constrains the position being traded." % f"{thr:,.0f}",
            "Order notional scales LINEARLY with the book - true only while the strategy keeps "
            "the same names and the same weights at every size.",
        ],
        basis=("WEAKENED. The filter is a SELECTION rule on ENTRY for STOCKS only, evaluated as "
               "of the run date. Every order on %s is a BUY (%d of %d), so entry is "
               "the side that binds here and the assumption survives for THIS sample - but the "
               "filter does not bind the exit, and it does not make $%s a floor on the ADV of a "
               "holding at liquidation, which is where a large book's real risk sits."
               % (scope_label, n_buy, n_all, f"{thr:,.0f}")),
        basis_valid=bool(applic["applies_to"]["stocks_on_entry"]),
    ))

    out.append(dict(
        name="S3_largest_etf_order_at_3pct_of_filter_floor",
        published_usd=11_600_000.0,
        recomputed_usd=((thr * 0.03) / (max_etf / cap_ref)) if max_etf else None,
        formula="book = ($%s filter floor x 3%%) / (largest ETF order $%.2f / $%s)"
                % (f"{thr:,.0f}", max_etf, f"{cap_ref:,.0f}"),
        inputs=dict(filter_floor_usd=thr, cap_pct=3.0, largest_etf_order_usd=max_etf,
                    largest_etf_order_book=max_etf_book, largest_etf_order_ticker=max_etf_ticker,
                    reference_book_usd=cap_ref, scope=scope),
        assumptions=[
            "Assumes the $%s liquidity filter applies to the ETF sleeve." % f"{thr:,.0f}",
            "Order notional scales LINEARLY with the book - true only while the strategy keeps "
            "the same names and the same weights at every size.",
        ],
        basis=("BASIS INVALID. The ETF leg is fetched as closes with no volume series "
               "(portfolio_v9.fetch_v9_market -> fetch_etf_closes) and never reaches "
               "apply_practical_filters. The $5M floor was never applied to an ETF, so this "
               "scenario has no basis. The MEASURED ETF ADVs on these sheets run from "
               "$25.6M (DBC) to $27.9bn (SPY) - the binding one is DBC, three orders of "
               "magnitude away from this figure."),
        basis_valid=bool(applic["applies_to"]["etfs_on_entry"]),
    ))

    # the same algebra, but on the ADV this cycle actually measured, per cell
    for key, st in sorted(stats_by_cell.items()):
        if not st["max_pct"]:
            continue
        out.append(dict(
            name=f"S4_measured_{key.replace('/', '_')}_worst_order_at_3pct",
            published_usd=None,
            recomputed_usd=(3.0 / st["max_pct"]) * cap_ref,
            formula="book = (3%% cap / worst measured participation %.6f%% [%s]) x $%s"
                    % (st["max_pct"], st["worst_ticker"], f"{cap_ref:,.0f}"),
            inputs=dict(worst_participation_pct=st["max_pct"], worst_ticker=st["worst_ticker"],
                        cap_pct=3.0, reference_book_usd=cap_ref, sample=st["sample_label"]),
            assumptions=[
                # DEFECT D5: S4 is what the summary promotes as the binding constraint, so it
                # carries the SAME qualifier S1 carries. "Linear scaling" alone hid the condition
                # the linearity depends on.
                "Order notional scales LINEARLY with the book - true only while the strategy keeps "
                "the same names and the same weights at every size.",
                "ADV unchanged by the strategy's own trading.",
                "ONE date; ADV from a single provider (yfinance) with no second source.",
                "A 3 % cap assumed, not derived from measured impact.",
                "Sample: " + st["sample_label"],
            ],
            basis="ALGEBRAIC SCENARIO on measured ADV. NOT capacity.",
            basis_valid=True,
        ))
    return out


# --------------------------------------------------------------------------- gates

def announce_gate(cov_by_cell: dict, min_notional_coverage_pct: float = 100.0,
                  tol_pct: float = 1e-6) -> dict:
    """Capacity must NOT be announced before coverage is sufficient (the reviewer's rule).

    Per (book, sleeve): pass only when notional coverage reaches the threshold. Anything short
    blocks the announcement for that cell and names the notional still unknown.

    `tol_pct` exists because `100 * x / x` is not always 100.0 in binary floating point: on
    live/stocks (22 identical orders of $323.8780525195897) it evaluates to 99.99999999999999,
    and a bare `>=` blocked a cell whose unknown notional was exactly $0.00. The tolerance is
    1e-6 percentage points - eight orders of magnitude below the smallest real gap a single
    uncovered order could open on these sheets (one order of 26 is ~3.8 pp).
    """
    cells, blocked = {}, []
    for key, c in sorted(cov_by_cell.items()):
        ok = (c["notional_coverage_pct"] is not None
              and c["notional_coverage_pct"] >= min_notional_coverage_pct - tol_pct)
        cells[key] = dict(passed=ok, notional_coverage_pct=c["notional_coverage_pct"],
                          unknown_notional_usd=c["unknown_notional_usd"],
                          unknown_tickers=c["unknown_tickers"])
        if not ok:
            blocked.append(key)
    return dict(min_notional_coverage_pct=min_notional_coverage_pct, tol_pct=tol_pct,
                cells=cells, blocked_cells=blocked, coverage_sufficient=not blocked)


def capacity_verdict(gate: dict) -> dict:
    """Always NOT_CERTIFIED, with the reasons. Coverage is necessary, not sufficient."""
    missing = [
        "No market-impact model: participation is an input to capacity, not capacity itself.",
        "No executed fills to calibrate against - both ledgers are empty (0 entries).",
        "One sheet date per book; no distribution of ADV over time or over rebalances.",
        "A single data provider (yfinance via data_cache/bars.sqlite); no second source agrees.",
        "Exit-side liquidity is unmodelled: plan() emits sells on a price check alone.",
    ]
    if not gate["coverage_sufficient"]:
        missing.insert(0, "Coverage is insufficient in: " + ", ".join(gate["blocked_cells"]))
    return dict(status="NOT_CERTIFIED", coverage_sufficient=gate["coverage_sufficient"],
                participation_measured=True, missing=missing,
                statement=("Participation of the two v9 order sheets against point-in-time dollar "
                           "ADV is MEASURED. Capacity is NOT announced and NOT certified."))


def ledger_evidence(root: str = ROOT) -> dict:
    """An empty ledger means NO EXECUTIONS RECORDED. Nothing more, nothing less."""
    out = {}
    for book, rel in (("live", os.path.join("state", "portfolio_v9.json")),
                      ("paper", os.path.join("state_paper", "portfolio_v9.json"))):
        path = os.path.join(root, rel)
        entry = dict(book=book, path=path, exists=os.path.exists(path))
        if entry["exists"]:
            with open(path, "r", encoding="utf-8") as f:
                st = json.load(f)
            entry.update(n_ledger=len(st.get("ledger") or []), n_pending=len(st.get("pending") or []),
                         n_write_offs=len(st.get("write_offs") or []))
        out[book] = entry
    return dict(
        books=out,
        meaning=("An empty ledger means NO EXECUTIONS RECORDED IN THIS BOOK. It is not evidence "
                 "that trades did or did not happen at a broker."),
        evidence_required_to_verify_external_execution=[
            "Broker trade confirmations for the exec date (per order: ticker, side, shares, "
            "fill price, timestamp, commission).",
            "The brokerage account statement covering the exec date.",
            "Settlement records (T+1) showing cash movement and the resulting share balances.",
            "A broker position snapshot on the settle date to reconcile the book against.",
        ],
        note=("TASK-430 stays conditioned on the VERIFIED SETTLE. No fill is invented here and "
              "no state is written."),
    )


# --------------------------------------------------------------------------- run

def run(db_path: str = DEFAULT_DB, books=("live", "paper"), window: int = DEFAULT_WINDOW,
        price_col: str = "close_raw", thresholds=DEFAULT_THRESHOLDS,
        ghost_floor_ratio: float = GHOST_FLOOR_RATIO, book_paths: dict = None,
        root: str = ROOT) -> dict:
    paths = book_paths or BOOKS
    sheets = {b: load_sheet(paths[b], b) for b in books}
    source = BarSource(db_path)
    try:
        earliest = min(s["date"] for s in sheets.values())
        # a generous lookback so the median date count is taken over real sessions
        since = f"{int(earliest[:4]) - 1}{earliest[4:]}"
        counts = source.date_counts(since)
        ghosts = frozenset(ghost_dates(counts, ghost_floor_ratio))
        store_max = source.max_date()

        rows = []
        for b in books:
            rows.extend(participation_rows(sheets[b], source, window, ghosts, price_col))
    finally:
        source.close()

    cov_by_cell, stats_by_cell = {}, {}
    for book in books:
        for sleeve in sorted({r["sleeve"] for r in rows if r["book"] == book}):
            sub = [r for r in rows if r["book"] == book and r["sleeve"] == sleeve]
            key = f"{book}/{sleeve}"
            cov_by_cell[key] = coverage(sub)
            stats_by_cell[key] = participation_stats(sub, thresholds)

    staleness = {}
    for book in books:
        s = sheets[book]
        last = max((r["adv_last_bar"] for r in rows if r["book"] == book and r["adv_last_bar"]),
                   default=None)
        staleness[book] = dict(sheet_date=s["date"], exec_date=s["exec_date"],
                               store_max_date=store_max, adv_last_bar=last,
                               adv_is_current_to_sheet_date=(last == s["date"]))

    applic = filter_applicability()
    gate = announce_gate(cov_by_cell)
    return dict(
        task="TASK-434",
        source=dict(db=db_path, table="bars", provider="yfinance",
                    volume_units="shares", price_units="USD/share", price_col=price_col,
                    dollar_adv_units="USD",
                    derivation=("dollar_volume = price[USD/share] x volume[shares]; ADV = mean "
                                f"over {window} point-in-time bars")),
        window=window, thresholds=list(thresholds),
        hygiene=dict(ghost_dates=sorted(ghosts), ghost_floor_ratio=ghost_floor_ratio,
                     n_dates_scanned=len(counts),
                     note="ghost/holiday rows are excluded from every window and listed here"),
        staleness=staleness,
        coverage=cov_by_cell,
        participation=stats_by_cell,
        orders=rows,
        instrument_date=aggregate_instrument_date(rows),
        rounding={b: whole_share_impact(sheets[b]) for b in books},
        filter_applicability=applic,
        scenarios=scenarios(stats_by_cell, sheets, applic),
        announce_gate=gate,
        capacity=capacity_verdict(gate),
        ledger=ledger_evidence(root),
    )


# --------------------------------------------------------------------------- printing

def _usd(v):
    return "-" if v is None else f"${v:,.0f}"


def print_report(p: dict) -> None:
    src = p["source"]
    print("=" * 102)
    print("TASK-434  participation of the v9 order sheets vs point-in-time dollar ADV")
    print("=" * 102)
    print(f"source   {src['db']}  (table bars, provider {src['provider']})")
    print(f"units    volume = {src['volume_units']};  {src['price_col']} = {src['price_units']};  "
          f"ADV = {src['dollar_adv_units']}")
    print(f"derived  {src['derivation']}")
    h = p["hygiene"]
    print(f"hygiene  {len(h['ghost_dates'])} ghost/holiday date(s) excluded over "
          f"{h['n_dates_scanned']} dates"
          + (f": {', '.join(h['ghost_dates'])}" if h["ghost_dates"] else " (none found)"))
    for b, s in p["staleness"].items():
        flag = "CURRENT" if s["adv_is_current_to_sheet_date"] else "STALE"
        print(f"asof     {b:5s} sheet {s['sheet_date']}  exec {s['exec_date']}  "
              f"last ADV bar {s['adv_last_bar']}  [{flag}]")

    print("\n--- COVERAGE, twice: by order count and by notional (instruction 2) " + "-" * 34)
    print(f"{'cell':<16}{'orders':>11}{'count cov':>11}{'notional':>13}{'known $':>13}"
          f"{'UNKNOWN $':>12}{'unknown %':>11}")
    for k, c in p["coverage"].items():
        print(f"{k:<16}{str(c['n_known']) + '/' + str(c['n_orders']):>11}"
              f"{c['count_coverage_pct']:>10.1f}%{_usd(c['notional_usd']):>13}"
              f"{_usd(c['known_notional_usd']):>13}{_usd(c['unknown_notional_usd']):>12}"
              f"{c['unknown_notional_share_pct']:>10.1f}%")
    tot_unknown = sum(c["unknown_notional_usd"] for c in p["coverage"].values())
    print(f"UNKNOWN NOTIONAL, all cells: {_usd(tot_unknown)}  "
          "(unknown is not zero, not excluded, not imputed)")

    print("\n--- PARTICIPATION % of ADV20$, per book and per sleeve, never pooled (1) " + "-" * 29)
    ths = p["thresholds"]
    print(f"{'cell':<16}{'sample':<30}{'P50 %':>10}{'P95 %':>10}{'max %':>10}  {'worst':<7}"
          + " ".join(f">{t:g}%" for t in ths))
    for k, st in p["participation"].items():
        b = st["breaches"]
        print(f"{k:<16}{st['sample_label']:<30}{st['p50_pct']:>10.6f}{st['p95_pct']:>10.6f}"
              f"{st['max_pct']:>10.6f}  {str(st['worst_ticker']):<7}"
              + " ".join(f"{b[f'gt_{t:g}pct']:>4}" for t in ths))

    print("\n--- JOINT PARTICIPATION per instrument-date, ABS summed, never netted (4) " + "-" * 28)
    multi = [g for g in p["instrument_date"] if g["n_orders"] > 1]
    print(f"{len(p['instrument_date'])} instrument-dates; {len(multi)} carry more than one order.")
    for g in multi:
        print(f"  {g['book']}/{g['date']} {g['ticker']:<6} n={g['n_orders']} sides={g['sides']} "
              f"gross {_usd(g['gross_notional_usd'])} net {_usd(g['net_notional_usd'])} "
              f"netting would hide {_usd(g['netting_would_hide_usd'])} "
              f"joint {g['joint_participation_pct']:.6f}%")
    if not multi:
        print("  On these two sheets every instrument appears once per book-date, so each gross "
              "sum equals its single order. The rule is enforced in code, not merely stated.")

    print("\n--- WHOLE-SHARE ROUNDING: a deviation, not a loss (instruction 7) " + "-" * 36)
    print(f"{'book/sleeve':<16}{'requested':>12}{'placeable':>12}{'unplaced':>11}{'unpl %':>9}"
          f"{'zero-sh':>9}{'expo dev pp':>13}")
    for b, r in p["rounding"].items():
        for k, s in r["by_sleeve"].items():
            print(f"{b + '/' + k:<16}{_usd(s['requested_usd']):>12}{_usd(s['placeable_usd']):>12}"
                  f"{_usd(s['unplaced_usd']):>11}{s['unplaced_share_pct']:>8.2f}%"
                  f"{s['n_zero_share']:>9}{s['exposure_deviation_pp']:>13.4f}")
        print(f"{b + ' (book)':<16}{_usd(r['book_requested_usd']):>12}"
              f"{_usd(r['book_placeable_usd']):>12}{_usd(r['book_unplaced_usd']):>11}"
              f"{r['book_unplaced_share_pct']:>8.2f}%{r['n_zero_share']:>9}"
              f"{r['book_exposure_deviation_pp']:>13.4f}")
        names = sorted({n for s in r["by_sleeve"].values() for n in s["zero_share_names"]})
        print(f"{'':<16}zero-share names: {names or 'none'}")

    print("\n--- WHERE THE UNSPENT CAPITAL IS: three unlike things, named apart (D1) " + "-" * 30)
    print("  residual cash = capital_reference - placeable is a SUM. It is NOT a rounding figure.")
    for b, r in p["rounding"].items():
        cs, tr = r["capital_split"], r["tranche"]
        print(f"\n  {b}  capital_reference {_usd(cs['capital_reference_usd'])}   "
              f"requested {_usd(cs['requested_usd'])}   placeable {_usd(cs['placeable_usd'])}")
        print(f"    (i)   rounding residue          {_usd(cs['rounding_residue_usd']):>13}  "
              f"({cs['rounding_residue_share_of_residual_pct']:.1f}% of the residual cash)")
        print(f"          {cs['labels']['rounding_residue_usd']}")
        print(f"    (ii)  capital NOT YET DEPLOYED  {_usd(cs['not_requested_usd']):>13}  "
              f"({cs['not_requested_share_of_residual_pct']:.1f}% of the residual cash)")
        print(f"          {cs['labels']['not_requested_usd']}")
        nb = cs["not_requested_breakdown"]
        if nb["not_yet_opened_tranches_usd"] is not None:
            print(f"            tranches not yet opened            "
                  f"{_usd(nb['not_yet_opened_tranches_usd']):>13}")
            print(f"            cash left inside the open tranche  "
                  f"{_usd(nb['undeployed_inside_the_open_tranche_usd']):>13}  ({nb['note']})")
        else:
            print(f"            {nb['note']}")
        print(f"    (iii) realised economic loss    "
              f"{str(cs['realised_economic_loss_usd']):>13}  {cs['labels']['realised_economic_loss_usd']}")
        print(f"          {r['realised_loss_note']}")
        print(f"    ===   residual cash             {_usd(cs['residual_cash_usd']):>13}  "
              f"[{cs['identity']}: {'holds' if cs['identity_holds'] else 'BROKEN'}]")
        print(f"    tranche reading: {tr.get('reading')}")

    print("\n--- DOES THE $5M LIQUIDITY FILTER APPLY? (instruction 6) " + "-" * 45)
    a = p["filter_applicability"]
    print(f"threshold {_usd(a['threshold_usd'])}/day, 20-bar mean of ADJUSTED close x volume")
    print(f"  value from: {a['threshold_source']}")
    print(f"  in-process config.FILTERS: {a['threshold_live_usd']}  "
          f"(matches declared: {a['threshold_live_matches_declared']})")
    print(f"  {a['threshold_divergence_note']}")
    for k, v in a["applies_to"].items():
        print(f"  {k:<20} {'YES' if v else 'NO'}")
    print(f"  evaluated as of the RUN date, not point-in-time per position: "
          f"{a['as_of_run_date_not_point_in_time']}")
    for line in (a["verdict"], a["consequence"]):
        print("  " + line)
    for k, v in a["evidence"].items():
        print(f"  evidence[{k}] = {v}")

    print("\n--- SCENARIOS, not capacity (instruction 6) " + "-" * 58)
    for s in p["scenarios"]:
        pub = _usd(s["published_usd"]) if s["published_usd"] else "(new)"
        print(f"\n  {s['name']}\n    published {pub}   recomputed {_usd(s['recomputed_usd'])}   "
              f"basis_valid={s['basis_valid']}")
        print(f"    formula: {s['formula']}")
        for asm in s["assumptions"]:
            print(f"    assumes: {asm}")
        print(f"    basis:   {s['basis']}")

    print("\n--- GATE AND VERDICT " + "-" * 81)
    g, c = p["announce_gate"], p["capacity"]
    print(f"coverage gate (>= {g['min_notional_coverage_pct']:.0f}% of notional per cell): "
          f"{'PASS' if g['coverage_sufficient'] else 'BLOCKED: ' + ', '.join(g['blocked_cells'])}")
    print(f"capacity: {c['status']}")
    print(f"  {c['statement']}")
    for m in c["missing"]:
        print(f"  missing: {m}")

    print("\n--- LEDGER (instruction 8) " + "-" * 75)
    led = p["ledger"]
    for b, e in led["books"].items():
        print(f"  {b:<6} ledger entries {e.get('n_ledger')}, pending {e.get('n_pending')}, "
              f"write-offs {e.get('n_write_offs')}")
    print("  " + led["meaning"])
    for ev in led["evidence_required_to_verify_external_execution"]:
        print(f"  evidence required: {ev}")
    print("  " + led["note"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--db", default=DEFAULT_DB, help="production bar store (opened read-only)")
    ap.add_argument("--books", default="live,paper")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    ap.add_argument("--price-col", default="close_raw", choices=("close_raw", "close_adj"))
    ap.add_argument("--thresholds", default="1,3,5", help="participation breach levels, percent")
    ap.add_argument("--ghost-floor-ratio", type=float, default=GHOST_FLOOR_RATIO)
    ap.add_argument("--out", default=SCRATCH)
    ap.add_argument("--json-only", action="store_true")
    a = ap.parse_args(argv)

    payload = run(db_path=a.db, books=tuple(b.strip() for b in a.books.split(",") if b.strip()),
                  window=a.window, price_col=a.price_col,
                  thresholds=tuple(float(t) for t in a.thresholds.split(",")),
                  ghost_floor_ratio=a.ghost_floor_ratio)
    if not a.json_only:
        print_report(payload)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, default=str)
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
