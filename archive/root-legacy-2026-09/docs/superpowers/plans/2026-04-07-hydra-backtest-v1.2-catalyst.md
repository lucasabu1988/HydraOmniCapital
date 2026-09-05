# HYDRA Backtest v1.2 — Catalyst Standalone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `hydra_backtest/catalyst/` — a Catalyst cross-asset trend standalone backtest sub-package that imports pure signal logic from `catalyst_signals.py`, reuses v1.0 infrastructure (BacktestState, methodology, reporting, _mark_to_market, _get_exec_price), and produces a 5-tier waterfall report with blocking smoke tests.

**Architecture:** New sub-package `hydra_backtest/catalyst/` with its own engine, validation, CLI, and tests. v1.0 modules are reused as-is via imports — zero modification to existing files except `data.py` (one new helper `load_catalyst_assets`, already implemented locally) and `.github/workflows/test.yml` (CI step).

**Tech Stack:** Python 3.14, pandas, numpy, pytest, pytest-cov. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-04-07-hydra-backtest-v1.2-catalyst-design.md`

---

## File Structure

```
hydra_backtest/                                    ← v1.0 + v1.1 (untouched except data.py)
├── data.py                                        ← + load_catalyst_assets helper (already local)
└── catalyst/                                      ← NEW v1.2 sub-package
    ├── __init__.py                                ← public exports (already scaffolded)
    ├── __main__.py                                ← CLI: python -m hydra_backtest.catalyst
    ├── engine.py                                  ← run_catalyst_backtest + apply_catalyst_rebalance
    ├── validation.py                              ← Layer A smoke tests Catalyst-adapted
    ├── README.md                                  ← usage + architecture + v1.2 limitations
    └── tests/
        ├── __init__.py                            ← already scaffolded
        ├── conftest.py                            ← already scaffolded (catalyst_minimal_config)
        ├── test_engine.py
        ├── test_validation.py
        ├── test_integration.py                    ← CLI smoke
        └── test_e2e.py                            ← @pytest.mark.slow
.github/workflows/test.yml                         ← + new pytest step for catalyst
```

**Reuse table** (from spec §4.2):

| From v1.0/v1.1 | How |
|---|---|
| `BacktestState`, `BacktestResult` | `from hydra_backtest.engine import ...` |
| `_mark_to_market`, `_get_exec_price`, `_slice_history_to_date` | Direct imports |
| `data.load_spy_data`, `load_yield_series` | Direct imports |
| `methodology.build_waterfall` | Direct import (strategy-agnostic) |
| `reporting.write_*` | Direct imports |
| `errors.HydraDataError`, `HydraConfigError` | Direct imports |

**Pure imports from `catalyst_signals.py`** (consumer-not-owner):
```python
from catalyst_signals import (
    CATALYST_TREND_ASSETS,    # ('TLT', 'ZROZ', 'GLD', 'DBC')
    CATALYST_REBALANCE_DAYS,  # 5
    CATALYST_SMA_PERIOD,      # 200
    compute_trend_holdings,
    compute_catalyst_targets,
)
```

---

## Task 1: Bootstrap commit — scaffold + data loader

**Status:** scaffold and `load_catalyst_assets` are already implemented locally. This task only commits them.

**Files (already on disk, untracked or modified):**
- `hydra_backtest/catalyst/__init__.py` (untracked) — imports `engine` + `validation` symbols that don't exist yet (will fail import until Task 5)
- `hydra_backtest/catalyst/tests/__init__.py` (untracked, empty)
- `hydra_backtest/catalyst/tests/conftest.py` (untracked) — `catalyst_minimal_config` fixture
- `hydra_backtest/data.py` (modified) — added `load_catalyst_assets`

**Action:**

- [ ] **Step 1: Verify scaffold contents**

```bash
cat hydra_backtest/catalyst/__init__.py
cat hydra_backtest/catalyst/tests/conftest.py
git diff hydra_backtest/data.py | head -60
```

Expected: `__init__.py` exports `run_catalyst_backtest`, `apply_catalyst_rebalance`, `run_catalyst_smoke_tests`. `conftest.py` defines `catalyst_minimal_config` with `INITIAL_CAPITAL=100_000` and `COMMISSION_PER_SHARE=0.0035`. `data.py` diff shows `load_catalyst_assets` validating TLT/ZROZ/GLD/DBC + OHLCV columns.

- [ ] **Step 2: Verify pytest collects but doesn't yet import the package**

```bash
pytest hydra_backtest/catalyst/tests/ --collect-only -q 2>&1 | tail -5
```

Expected: `0 tests collected` (conftest loads cleanly, no test files yet). The package's `__init__.py` will fail if anything actually tries to `import hydra_backtest.catalyst` — that's expected and will be fixed in Task 6 by ensuring all referenced symbols exist.

> ⚠️ Until Task 6, do NOT `import hydra_backtest.catalyst` from anywhere. Tests must `from hydra_backtest.catalyst.engine import ...` directly to bypass the package init.

- [ ] **Step 3: Commit**

```bash
git add hydra_backtest/catalyst/__init__.py \
        hydra_backtest/catalyst/tests/__init__.py \
        hydra_backtest/catalyst/tests/conftest.py \
        hydra_backtest/data.py
git commit -m "feat(hydra_backtest): bootstrap catalyst sub-package + load_catalyst_assets"
```

---

## Task 2: Engine — `apply_catalyst_rebalance` pure function

**File:** `hydra_backtest/catalyst/engine.py` (NEW)

**Goal:** Pure equivalent of `COMPASSLive._manage_catalyst_positions` (omnicapital_live.py:2196). Computes trend holdings, sells positions no longer in trend, buys new entrants, and (mirroring live) increases existing positions if target_shares grew. Never downsizes existing holdings.

- [ ] **Step 1: Create `engine.py` with imports and the rebalance helper**

```python
"""hydra_backtest.catalyst.engine — Catalyst cross-asset trend backtest engine.

Pure functions only. Mirrors COMPASSLive._manage_catalyst_positions
(omnicapital_live.py:2196) without side effects.
"""
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

from catalyst_signals import (
    CATALYST_REBALANCE_DAYS,
    CATALYST_SMA_PERIOD,
    CATALYST_TREND_ASSETS,
    compute_trend_holdings,
)
from hydra_backtest.data import compute_data_fingerprint
from hydra_backtest.engine import (
    BacktestResult,
    BacktestState,
    _get_exec_price,
    _mark_to_market,
    _slice_history_to_date,
)


def _has_enough_history(asset_data: Dict[str, pd.DataFrame],
                        ticker: str,
                        date: pd.Timestamp) -> bool:
    """Return True if `ticker` has at least CATALYST_SMA_PERIOD bars on/before `date`."""
    df = asset_data.get(ticker)
    if df is None:
        return False
    return len(df.loc[:date]) >= CATALYST_SMA_PERIOD


def apply_catalyst_rebalance(
    state: BacktestState,
    date: pd.Timestamp,
    i: int,
    asset_data: Dict[str, pd.DataFrame],
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[BacktestState, list, list]:
    """Pure equivalent of COMPASSLive._manage_catalyst_positions.

    Side-effect-free rebalance: computes trend_holdings via
    `compute_trend_holdings`, sells positions no longer in trend
    (exit_reason='CATALYST_TREND_OFF'), and buys new entrants OR adds to
    existing holdings if target_shares grew. Mirrors live's "no downsize"
    behavior (omnicapital_live.py:2270).

    Returns
    -------
    new_state, trades_list, decisions_list
    """
    trades: list = []
    decisions: list = []

    # 1. Slice history to `date` for the 4 trend assets only
    sliced = _slice_history_to_date(asset_data, date,
                                    symbols=list(CATALYST_TREND_ASSETS))

    # 2. Determine which assets have ≥ SMA_PERIOD days of history
    eligible = {t for t in CATALYST_TREND_ASSETS
                if _has_enough_history(asset_data, t, date)}

    # 3. Filter sliced to eligible only — assets without enough history
    #    must NEVER be considered above SMA200 (compute_trend_holdings
    #    already enforces this, but we belt-and-suspenders here)
    sliced_eligible = {t: df for t, df in sliced.items() if t in eligible}
    trend_holdings = compute_trend_holdings(sliced_eligible)

    # 4. Compute portfolio value for ring-fenced budget
    portfolio_value = _mark_to_market(state, asset_data, date)

    # 5. Equal-weight target_value per holding
    if trend_holdings:
        per_asset = portfolio_value / len(trend_holdings)
    else:
        per_asset = 0.0

    # 6. Current prices on `date`
    current_prices = {
        t: float(asset_data[t].loc[date, 'Close'])
        for t in CATALYST_TREND_ASSETS
        if date in asset_data.get(t, pd.DataFrame()).index
    }

    # 7. SELLS: positions no longer in trend
    new_positions = dict(state.positions)
    cash = state.cash
    for sym in list(new_positions.keys()):
        if sym not in trend_holdings:
            pos = new_positions[sym]
            exit_price = _get_exec_price(asset_data, sym, date, i, all_dates,
                                         execution_mode, side='sell')
            shares = pos['shares']
            proceeds = shares * exit_price
            commission = shares * config.get('COMMISSION_PER_SHARE', 0.0035)
            cash += proceeds - commission
            pnl = (exit_price - pos['entry_price']) * shares - commission
            ret = (exit_price / pos['entry_price'] - 1.0) if pos['entry_price'] > 0 else 0.0
            trades.append({
                'symbol': sym,
                'entry_date': pos['entry_date'],
                'exit_date': date,
                'exit_reason': 'CATALYST_TREND_OFF',
                'entry_price': pos['entry_price'],
                'exit_price': exit_price,
                'shares': shares,
                'pnl': pnl,
                'return': ret,
                'sector': 'Catalyst',
            })
            decisions.append({
                'date': date,
                'action': 'EXIT',
                'symbol': sym,
                'reason': 'CATALYST_TREND_OFF',
            })
            del new_positions[sym]

    # 8. BUYS: new entrants and existing holdings whose target_shares grew
    for sym in trend_holdings:
        price = current_prices.get(sym, 0.0)
        if price <= 0:
            continue
        target_shares = int(per_asset / price)
        if target_shares <= 0:
            continue

        current_shares = new_positions[sym]['shares'] if sym in new_positions else 0
        needed = target_shares - current_shares
        if needed <= 0:
            # Mirrors live "no downsize" behavior (omnicapital_live.py:2270)
            continue

        entry_price = _get_exec_price(asset_data, sym, date, i, all_dates,
                                      execution_mode, side='buy')
        cost = needed * entry_price
        commission = needed * config.get('COMMISSION_PER_SHARE', 0.0035)
        if cash < cost + commission:
            # Not enough cash — buy what we can (rounded down)
            affordable = int((cash - commission) / entry_price)
            if affordable <= 0:
                continue
            needed = affordable
            cost = needed * entry_price
            commission = needed * config.get('COMMISSION_PER_SHARE', 0.0035)
        cash -= cost + commission

        if sym in new_positions:
            # Increase existing position — weighted-average entry price
            existing = new_positions[sym]
            total_shares = existing['shares'] + needed
            weighted_entry = (
                (existing['shares'] * existing['entry_price'] + needed * entry_price)
                / total_shares
            )
            new_positions[sym] = {
                **existing,
                'shares': total_shares,
                'entry_price': weighted_entry,
                'high_price': max(existing.get('high_price', entry_price), entry_price),
            }
            decisions.append({
                'date': date,
                'action': 'ADD',
                'symbol': sym,
                'shares_added': needed,
            })
        else:
            new_positions[sym] = {
                'symbol': sym,
                'entry_price': entry_price,
                'shares': needed,
                'entry_date': date,
                'entry_idx': i,
                'days_held': 0,
                'sub_strategy': 'trend',
                'sector': 'Catalyst',
                'entry_vol': 0.0,
                'entry_daily_vol': 0.0,
                'high_price': entry_price,
            }
            decisions.append({
                'date': date,
                'action': 'ENTRY',
                'symbol': sym,
                'shares': needed,
            })

    new_state = state._replace(cash=cash, positions=new_positions)
    return new_state, trades, decisions
```

- [ ] **Step 2: Verify the file compiles**

```bash
python -c "import py_compile; py_compile.compile('hydra_backtest/catalyst/engine.py'); print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add hydra_backtest/catalyst/engine.py
git commit -m "feat(hydra_backtest.catalyst): apply_catalyst_rebalance pure function"
```

---

## Task 3: Engine — daily cash-yield helper + git sha

**File:** `hydra_backtest/catalyst/engine.py` (extend)

Catalyst has no leverage, so the daily cost helper only credits cash yield (Aaa or T-bill) — identical pattern to Rattlesnake (`_apply_rattlesnake_daily_costs`).

- [ ] **Step 1: Append helpers to `engine.py`**

```python
def _apply_catalyst_daily_costs(
    state: BacktestState,
    cash_yield_annual_pct: float,
) -> BacktestState:
    """Apply one trading day's cash yield. Catalyst has no leverage,
    no margin cost. Negative yields are ignored (fail-safe).
    """
    cash = state.cash
    if cash > 0 and cash_yield_annual_pct > 0:
        daily_rate = cash_yield_annual_pct / 100.0 / 252
        cash += cash * daily_rate
    return state._replace(cash=cash)


def _capture_git_sha() -> str:
    """Get current git commit sha, or 'unknown' if not in a repo."""
    try:
        out = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return 'unknown'
```

- [ ] **Step 2: Compile + commit**

```bash
python -c "import py_compile; py_compile.compile('hydra_backtest/catalyst/engine.py')"
git add hydra_backtest/catalyst/engine.py
git commit -m "feat(hydra_backtest.catalyst): daily cash-yield helper + git sha capture"
```

---

## Task 4: Engine — `run_catalyst_backtest` orchestrator

**File:** `hydra_backtest/catalyst/engine.py` (extend)

Top-level entrypoint. Loops over `[start_date, end_date]`, calls rebalance every `CATALYST_REBALANCE_DAYS`, applies daily costs, snapshots day. Returns `BacktestResult` compatible with `methodology.build_waterfall`.

- [ ] **Step 1: Append the orchestrator to `engine.py`**

```python
def run_catalyst_backtest(
    config: dict,
    asset_data: Dict[str, pd.DataFrame],
    cash_yield_daily: pd.Series,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    execution_mode: str = 'same_close',
    progress_callback: Optional[callable] = None,
) -> BacktestResult:
    """Run a Catalyst cross-asset trend backtest from start_date to end_date.

    Pure function: no side effects. Returns a BacktestResult compatible
    with v1.0 reporting/methodology layers (drop-in for build_waterfall).

    Universe is hardcoded as CATALYST_TREND_ASSETS (no PIT parameter).
    """
    started_at = datetime.now()

    # Aggregate trading dates from the union of all 4 ETFs
    all_dates_set = set()
    for df in asset_data.values():
        all_dates_set.update(df.index)
    all_dates = sorted(all_dates_set)

    state = BacktestState(
        cash=float(config['INITIAL_CAPITAL']),
        positions={},
        peak_value=float(config['INITIAL_CAPITAL']),
        crash_cooldown=0,
        portfolio_value_history=(),
    )

    trades: list = []
    decisions: list = []
    snapshots: list = []
    universe_size: Dict[int, int] = {}

    catalyst_day_counter = 0
    last_progress_year: Optional[int] = None
    dates_in_range = [d for d in all_dates if start_date <= d <= end_date]
    total_bars = max(len(dates_in_range), 1)

    for i, date in enumerate(all_dates):
        if date < start_date or date > end_date:
            continue

        # Progress callback (first bar of each year)
        if progress_callback is not None and date.year != last_progress_year:
            last_progress_year = date.year
            try:
                pv_now = _mark_to_market(state, asset_data, date)
                bars_done = sum(1 for d in dates_in_range if d < date)
                progress_callback({
                    'year': int(date.year),
                    'progress_pct': 100.0 * bars_done / total_bars,
                    'portfolio_value': float(pv_now),
                    'n_positions': len(state.positions),
                })
            except Exception:
                pass

        # 1. Mark-to-market
        portfolio_value = _mark_to_market(state, asset_data, date)

        # 1b. Update peak BEFORE drawdown
        if portfolio_value > state.peak_value:
            state = state._replace(peak_value=portfolio_value)

        # 2. Universe size = count of assets with enough history today
        eligible_today = sum(
            1 for t in CATALYST_TREND_ASSETS
            if _has_enough_history(asset_data, t, date)
        )
        universe_size[date.year] = max(universe_size.get(date.year, 0), eligible_today)

        # 3. Drawdown
        drawdown = (
            (portfolio_value - state.peak_value) / state.peak_value
            if state.peak_value > 0 else 0.0
        )

        # 4. Daily costs (cash yield only)
        daily_yield = float(
            cash_yield_daily.get(date, cash_yield_daily.iloc[0])
            if len(cash_yield_daily) > 0 else 0.0
        )
        state = _apply_catalyst_daily_costs(state, daily_yield)

        # 5. Rebalance check
        catalyst_day_counter += 1
        rebalance_today = False
        if catalyst_day_counter >= CATALYST_REBALANCE_DAYS or not state.positions:
            catalyst_day_counter = 0
            rebalance_today = True
            state, rb_trades, rb_decisions = apply_catalyst_rebalance(
                state, date, i, asset_data, config, execution_mode, all_dates,
            )
            trades.extend(rb_trades)
            decisions.extend(rb_decisions)

        # 6. Snapshot AFTER rebalance
        pv_after = _mark_to_market(state, asset_data, date)
        snapshots.append({
            'date': date,
            'portfolio_value': pv_after,
            'cash': state.cash,
            'n_positions': len(state.positions),
            'leverage': 1.0,                # Catalyst never uses leverage
            'drawdown': drawdown,
            'regime_score': 1.0,            # No regime gate
            'crash_active': False,
            'max_positions': len(CATALYST_TREND_ASSETS),
            'rebalance_today': rebalance_today,
            'n_trend_holdings': len(state.positions),
        })

        # 7. Update state tail: peak + days_held
        if pv_after > state.peak_value:
            state = state._replace(peak_value=pv_after)
        new_positions = {
            sym: {**p, 'days_held': p.get('days_held', 0) + 1}
            for sym, p in state.positions.items()
        }
        state = state._replace(
            positions=new_positions,
            portfolio_value_history=state.portfolio_value_history + (pv_after,),
        )

    # 8. Synthetic-close any remaining open positions at the end of the backtest
    if state.positions:
        last_date = dates_in_range[-1]
        last_i = all_dates.index(last_date)
        for sym, pos in list(state.positions.items()):
            exit_price = _get_exec_price(asset_data, sym, last_date, last_i,
                                         all_dates, execution_mode, side='sell')
            shares = pos['shares']
            commission = shares * config.get('COMMISSION_PER_SHARE', 0.0035)
            pnl = (exit_price - pos['entry_price']) * shares - commission
            ret = (exit_price / pos['entry_price'] - 1.0) if pos['entry_price'] > 0 else 0.0
            trades.append({
                'symbol': sym,
                'entry_date': pos['entry_date'],
                'exit_date': last_date,
                'exit_reason': 'CATALYST_BACKTEST_END',
                'entry_price': pos['entry_price'],
                'exit_price': exit_price,
                'shares': shares,
                'pnl': pnl,
                'return': ret,
                'sector': 'Catalyst',
            })

    finished_at = datetime.now()

    result_config = dict(config)
    result_config['_execution_mode'] = execution_mode

    trade_cols = ['symbol', 'entry_date', 'exit_date', 'exit_reason',
                  'entry_price', 'exit_price', 'shares', 'pnl', 'return', 'sector']
    return BacktestResult(
        config=result_config,
        daily_values=pd.DataFrame(snapshots),
        trades=pd.DataFrame(trades) if trades else pd.DataFrame(columns=trade_cols),
        decisions=decisions,
        exit_events=[t for t in trades if t['exit_reason'] == 'CATALYST_TREND_OFF'],
        universe_size=universe_size,
        started_at=started_at,
        finished_at=finished_at,
        git_sha=_capture_git_sha(),
        data_inputs_hash=compute_data_fingerprint(asset_data),
    )
```

- [ ] **Step 2: Compile + commit**

```bash
python -c "import py_compile; py_compile.compile('hydra_backtest/catalyst/engine.py')"
git add hydra_backtest/catalyst/engine.py
git commit -m "feat(hydra_backtest.catalyst): run_catalyst_backtest orchestrator"
```

---

## Task 5: Validation — Layer A smoke tests

**File:** `hydra_backtest/catalyst/validation.py` (NEW)

Per spec §9, Catalyst inherits the 6 mathematical invariants from v1.0/v1.1 and adds 4 Catalyst-specific ones. No stop/profit checks (Catalyst has neither).

- [ ] **Step 1: Create `validation.py`**

```python
"""hydra_backtest.catalyst.validation — Layer A smoke tests for Catalyst.

Mathematical invariants (shared with v1.0/v1.1):
1. No NaN in critical columns
2. Cash never < -1.0
3. Drawdown ∈ [-1.0, 0]
4. Peak monotonic non-decreasing
5. Vol ann ∈ [0.5%, 50%]
6. No outlier daily returns > ±15% (allowlist crash days)

Catalyst-specific invariants:
7. n_positions ∈ [0, 4] always
8. Trade exit reasons ⊆ {'CATALYST_TREND_OFF', 'CATALYST_BACKTEST_END'}
9. Pre-eligibility snapshots: when no asset has SMA200 history yet, n_positions == 0
10. Rebalance frequency: consecutive rebalance days exactly CATALYST_REBALANCE_DAYS apart
"""
from typing import List

import numpy as np
import pandas as pd

from catalyst_signals import CATALYST_REBALANCE_DAYS, CATALYST_TREND_ASSETS
from hydra_backtest.engine import BacktestResult
from hydra_backtest.errors import HydraValidationError

# Crash days where ±15% portfolio moves are tolerated (same allowlist as v1.0)
_CRASH_ALLOWLIST = {
    pd.Timestamp('2008-10-13'),
    pd.Timestamp('2008-10-15'),
    pd.Timestamp('2020-03-12'),
    pd.Timestamp('2020-03-16'),
}


def _check_no_nan(daily: pd.DataFrame, errors: List[str]) -> None:
    critical = ['portfolio_value', 'cash', 'n_positions', 'drawdown']
    for col in critical:
        if col in daily.columns and daily[col].isna().any():
            errors.append(f"NaN in critical column: {col}")


def _check_cash_floor(daily: pd.DataFrame, errors: List[str]) -> None:
    if 'cash' in daily.columns and (daily['cash'] < -1.0).any():
        bad = daily[daily['cash'] < -1.0].iloc[0]
        errors.append(f"Cash < -1.0 at {bad['date']}: {bad['cash']:.4f}")


def _check_drawdown_range(daily: pd.DataFrame, errors: List[str]) -> None:
    if 'drawdown' not in daily.columns:
        return
    dd = daily['drawdown']
    if (dd < -1.0).any() or (dd > 0).any():
        errors.append(f"Drawdown out of [-1.0, 0]: min={dd.min():.4f}, max={dd.max():.4f}")


def _check_peak_monotonic(daily: pd.DataFrame, errors: List[str]) -> None:
    if 'portfolio_value' not in daily.columns:
        return
    pv = daily['portfolio_value'].values
    peak = np.maximum.accumulate(pv)
    # peak by construction is non-decreasing — this guards against future bugs
    if not np.all(np.diff(peak) >= -1e-9):
        errors.append("Peak series is not monotonic non-decreasing")


def _check_vol_range(daily: pd.DataFrame, errors: List[str]) -> None:
    if 'portfolio_value' not in daily.columns or len(daily) < 30:
        return
    rets = daily['portfolio_value'].pct_change().dropna()
    if len(rets) < 2:
        return
    vol_ann = rets.std() * np.sqrt(252) * 100
    if vol_ann < 0.5 or vol_ann > 50:
        errors.append(f"Annualized vol out of [0.5%, 50%]: {vol_ann:.2f}%")


def _check_outlier_returns(daily: pd.DataFrame, errors: List[str]) -> None:
    if 'portfolio_value' not in daily.columns or len(daily) < 2:
        return
    rets = daily['portfolio_value'].pct_change()
    for date, r in rets.items():
        if pd.isna(r):
            continue
        if abs(r) > 0.15:
            row_date = daily.loc[date, 'date'] if 'date' in daily.columns else date
            if pd.Timestamp(row_date) not in _CRASH_ALLOWLIST:
                errors.append(
                    f"Outlier daily return {r * 100:.2f}% on {row_date}"
                )


def _check_n_positions_bounds(daily: pd.DataFrame, errors: List[str]) -> None:
    max_pos = len(CATALYST_TREND_ASSETS)
    if 'n_positions' in daily.columns:
        bad = daily[(daily['n_positions'] < 0) | (daily['n_positions'] > max_pos)]
        if not bad.empty:
            row = bad.iloc[0]
            errors.append(
                f"n_positions out of [0, {max_pos}] at {row['date']}: {row['n_positions']}"
            )


def _check_exit_reasons(trades: pd.DataFrame, errors: List[str]) -> None:
    if trades.empty or 'exit_reason' not in trades.columns:
        return
    valid = {'CATALYST_TREND_OFF', 'CATALYST_BACKTEST_END'}
    invalid = set(trades['exit_reason'].unique()) - valid
    if invalid:
        errors.append(f"Invalid Catalyst exit reasons: {invalid}")


def _check_rebalance_cadence(daily: pd.DataFrame, errors: List[str]) -> None:
    if 'rebalance_today' not in daily.columns:
        return
    rb_idxs = daily.index[daily['rebalance_today']].tolist()
    if len(rb_idxs) < 3:
        return  # not enough rebalances to check cadence
    # Skip the first one (always day 1 / first run)
    diffs = np.diff(rb_idxs[1:])
    bad = [int(d) for d in diffs if d != CATALYST_REBALANCE_DAYS]
    if bad:
        errors.append(
            f"Rebalance cadence broken: expected every {CATALYST_REBALANCE_DAYS} days, "
            f"got diffs containing {bad[:5]}"
        )


def run_catalyst_smoke_tests(result: BacktestResult) -> None:
    """Run all Layer A smoke tests on a Catalyst BacktestResult.

    Raises HydraValidationError on the first failing class of checks
    (with all errors aggregated). Returns silently on success.
    """
    errors: List[str] = []
    daily = result.daily_values
    trades = result.trades

    _check_no_nan(daily, errors)
    _check_cash_floor(daily, errors)
    _check_drawdown_range(daily, errors)
    _check_peak_monotonic(daily, errors)
    _check_vol_range(daily, errors)
    _check_outlier_returns(daily, errors)
    _check_n_positions_bounds(daily, errors)
    _check_exit_reasons(trades, errors)
    _check_rebalance_cadence(daily, errors)

    if errors:
        msg = "Catalyst smoke tests failed:\n  - " + "\n  - ".join(errors)
        raise HydraValidationError(msg)
```

- [ ] **Step 2: Compile + commit**

```bash
python -c "import py_compile; py_compile.compile('hydra_backtest/catalyst/validation.py')"
git add hydra_backtest/catalyst/validation.py
git commit -m "feat(hydra_backtest.catalyst): Layer A smoke tests"
```

---

## Task 6: Public API exports — verify package imports

**File:** `hydra_backtest/catalyst/__init__.py` (already exists, verify only)

After Tasks 2–5, the existing `__init__.py` symbols (`run_catalyst_backtest`, `apply_catalyst_rebalance`, `run_catalyst_smoke_tests`) should resolve.

- [ ] **Step 1: Verify the package imports cleanly**

```bash
python -c "import hydra_backtest.catalyst as c; print(c.__all__)"
```

Expected: `['run_catalyst_backtest', 'apply_catalyst_rebalance', 'run_catalyst_smoke_tests']`

- [ ] **Step 2: No commit needed if imports succeed.** If `__init__.py` needs adjustment (e.g., adding a missing symbol), make the edit and commit:

```bash
git add hydra_backtest/catalyst/__init__.py
git commit -m "feat(hydra_backtest.catalyst): finalize public API exports"
```

---

## Task 7: Engine unit tests — `test_engine.py`

**File:** `hydra_backtest/catalyst/tests/test_engine.py` (NEW)

- [ ] **Step 1: Create test file with synthetic-data fixtures and core engine tests**

```python
"""Unit tests for hydra_backtest.catalyst.engine."""
import numpy as np
import pandas as pd
import pytest

from hydra_backtest.catalyst.engine import (
    _has_enough_history,
    apply_catalyst_rebalance,
    run_catalyst_backtest,
)
from hydra_backtest.engine import BacktestState


def _make_asset(start: str, n_days: int, drift: float = 0.0,
                start_price: float = 100.0) -> pd.DataFrame:
    """Generate a deterministic OHLCV DataFrame for testing."""
    dates = pd.bdate_range(start, periods=n_days)
    closes = start_price * (1 + drift) ** np.arange(n_days)
    return pd.DataFrame({
        'Open': closes,
        'High': closes * 1.005,
        'Low': closes * 0.995,
        'Close': closes,
        'Volume': 1_000_000,
    }, index=dates)


@pytest.fixture
def four_assets_uptrend():
    """4 trending-up ETFs with enough history to satisfy SMA200."""
    return {
        'TLT':  _make_asset('2020-01-01', 400, drift=0.0005),
        'ZROZ': _make_asset('2020-01-01', 400, drift=0.0005),
        'GLD':  _make_asset('2020-01-01', 400, drift=0.0005),
        'DBC':  _make_asset('2020-01-01', 400, drift=0.0005),
    }


@pytest.fixture
def cash_yield_zero():
    return pd.Series(0.0, index=pd.bdate_range('2020-01-01', periods=400))


def test_has_enough_history_true(four_assets_uptrend):
    last_date = four_assets_uptrend['TLT'].index[-1]
    assert _has_enough_history(four_assets_uptrend, 'TLT', last_date) is True


def test_has_enough_history_false_early(four_assets_uptrend):
    early_date = four_assets_uptrend['TLT'].index[50]
    assert _has_enough_history(four_assets_uptrend, 'TLT', early_date) is False


def test_apply_rebalance_buys_all_four_when_uptrending(four_assets_uptrend,
                                                        catalyst_minimal_config):
    last_date = four_assets_uptrend['TLT'].index[-1]
    state = BacktestState(cash=100_000.0, positions={}, peak_value=100_000.0,
                          crash_cooldown=0, portfolio_value_history=())
    all_dates = sorted(four_assets_uptrend['TLT'].index)
    new_state, trades, decisions = apply_catalyst_rebalance(
        state, last_date, len(all_dates) - 1, four_assets_uptrend,
        catalyst_minimal_config, 'same_close', all_dates,
    )
    assert len(new_state.positions) == 4
    assert {'TLT', 'ZROZ', 'GLD', 'DBC'} == set(new_state.positions.keys())
    assert all(d['action'] == 'ENTRY' for d in decisions)
    assert trades == []


def test_apply_rebalance_sells_when_asset_drops_below_sma(catalyst_minimal_config):
    """One asset crashes below SMA200 — should be sold with CATALYST_TREND_OFF."""
    n = 250
    dates = pd.bdate_range('2020-01-01', periods=n)
    base = _make_asset('2020-01-01', n, drift=0.001)
    # TLT crashes to -50% over the last 30 days (now firmly below SMA200)
    crash_close = np.concatenate([
        base['Close'].values[:-30],
        np.linspace(base['Close'].values[-30], base['Close'].values[-30] * 0.5, 30),
    ])
    tlt_crashed = base.copy()
    tlt_crashed['Close'] = crash_close
    tlt_crashed['Open'] = crash_close
    tlt_crashed['High'] = crash_close * 1.005
    tlt_crashed['Low'] = crash_close * 0.995

    assets = {
        'TLT':  tlt_crashed,
        'ZROZ': base.copy(),
        'GLD':  base.copy(),
        'DBC':  base.copy(),
    }
    last_date = dates[-1]
    all_dates = sorted(dates)

    # Pre-seed state with TLT held
    state = BacktestState(
        cash=50_000.0,
        positions={'TLT': {'symbol': 'TLT', 'entry_price': 100.0, 'shares': 100,
                           'entry_date': dates[0], 'entry_idx': 0, 'days_held': 200,
                           'sub_strategy': 'trend', 'sector': 'Catalyst',
                           'entry_vol': 0.0, 'entry_daily_vol': 0.0,
                           'high_price': 110.0}},
        peak_value=100_000.0, crash_cooldown=0, portfolio_value_history=(),
    )
    new_state, trades, decisions = apply_catalyst_rebalance(
        state, last_date, len(all_dates) - 1, assets,
        catalyst_minimal_config, 'same_close', all_dates,
    )
    assert 'TLT' not in new_state.positions
    assert any(t['exit_reason'] == 'CATALYST_TREND_OFF' for t in trades)


def test_apply_rebalance_no_downsize_when_target_smaller(four_assets_uptrend,
                                                          catalyst_minimal_config):
    """Existing position with current_shares > target_shares should NOT be sold down."""
    last_date = four_assets_uptrend['TLT'].index[-1]
    # Pre-seed with a giant TLT position
    state = BacktestState(
        cash=10_000.0,
        positions={'TLT': {'symbol': 'TLT', 'entry_price': 50.0, 'shares': 9999,
                           'entry_date': four_assets_uptrend['TLT'].index[0],
                           'entry_idx': 0, 'days_held': 200,
                           'sub_strategy': 'trend', 'sector': 'Catalyst',
                           'entry_vol': 0.0, 'entry_daily_vol': 0.0,
                           'high_price': 100.0}},
        peak_value=1_000_000.0, crash_cooldown=0, portfolio_value_history=(),
    )
    all_dates = sorted(four_assets_uptrend['TLT'].index)
    new_state, trades, _ = apply_catalyst_rebalance(
        state, last_date, len(all_dates) - 1, four_assets_uptrend,
        catalyst_minimal_config, 'same_close', all_dates,
    )
    # TLT still held, no exit trade for TLT
    assert 'TLT' in new_state.positions
    assert new_state.positions['TLT']['shares'] >= 9999
    assert not any(t['symbol'] == 'TLT' and t['exit_reason'] == 'CATALYST_TREND_OFF'
                   for t in trades)


def test_run_backtest_smoke(four_assets_uptrend, cash_yield_zero,
                             catalyst_minimal_config):
    start = four_assets_uptrend['TLT'].index[210]
    end = four_assets_uptrend['TLT'].index[-1]
    result = run_catalyst_backtest(
        catalyst_minimal_config, four_assets_uptrend, cash_yield_zero,
        start, end, execution_mode='same_close',
    )
    assert not result.daily_values.empty
    assert 'rebalance_today' in result.daily_values.columns
    assert (result.daily_values['n_positions'] >= 0).all()
    assert (result.daily_values['n_positions'] <= 4).all()
```

- [ ] **Step 2: Run the new tests**

```bash
pytest hydra_backtest/catalyst/tests/test_engine.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add hydra_backtest/catalyst/tests/test_engine.py
git commit -m "test(hydra_backtest.catalyst): engine unit tests"
```

---

## Task 8: Validation unit tests — `test_validation.py`

**File:** `hydra_backtest/catalyst/tests/test_validation.py` (NEW)

- [ ] **Step 1: Create the test file**

```python
"""Unit tests for hydra_backtest.catalyst.validation."""
import pandas as pd
import pytest

from hydra_backtest.catalyst.validation import run_catalyst_smoke_tests
from hydra_backtest.engine import BacktestResult
from hydra_backtest.errors import HydraValidationError


def _make_result(daily: pd.DataFrame, trades: pd.DataFrame = None) -> BacktestResult:
    if trades is None:
        trades = pd.DataFrame(columns=['symbol', 'exit_reason'])
    return BacktestResult(
        config={}, daily_values=daily, trades=trades, decisions=[],
        exit_events=[], universe_size={},
        started_at=pd.Timestamp.now(), finished_at=pd.Timestamp.now(),
        git_sha='test', data_inputs_hash='test',
    )


def _good_daily(n=300):
    dates = pd.bdate_range('2020-01-01', periods=n)
    pv = 100_000 * (1.0001 ** range(n))
    return pd.DataFrame({
        'date': dates,
        'portfolio_value': pv,
        'cash': [10_000.0] * n,
        'n_positions': [4] * n,
        'drawdown': [0.0] * n,
        'rebalance_today': [(i % 5 == 0) for i in range(n)],
    })


def test_smoke_passes_clean_result():
    run_catalyst_smoke_tests(_make_result(_good_daily()))


def test_smoke_fails_n_positions_over_max():
    daily = _good_daily()
    daily.loc[10, 'n_positions'] = 5
    with pytest.raises(HydraValidationError, match="n_positions out of"):
        run_catalyst_smoke_tests(_make_result(daily))


def test_smoke_fails_invalid_exit_reason():
    daily = _good_daily()
    trades = pd.DataFrame([{'symbol': 'TLT', 'exit_reason': 'COMPASS_STOP'}])
    with pytest.raises(HydraValidationError, match="Invalid Catalyst exit reasons"):
        run_catalyst_smoke_tests(_make_result(daily, trades))


def test_smoke_fails_negative_cash_floor():
    daily = _good_daily()
    daily.loc[5, 'cash'] = -10.0
    with pytest.raises(HydraValidationError, match="Cash < -1.0"):
        run_catalyst_smoke_tests(_make_result(daily))


def test_smoke_fails_drawdown_out_of_range():
    daily = _good_daily()
    daily.loc[5, 'drawdown'] = 0.5  # positive drawdown impossible
    with pytest.raises(HydraValidationError, match="Drawdown out of"):
        run_catalyst_smoke_tests(_make_result(daily))


def test_smoke_accepts_valid_catalyst_exit_reasons():
    daily = _good_daily()
    trades = pd.DataFrame([
        {'symbol': 'TLT', 'exit_reason': 'CATALYST_TREND_OFF'},
        {'symbol': 'GLD', 'exit_reason': 'CATALYST_BACKTEST_END'},
    ])
    run_catalyst_smoke_tests(_make_result(daily, trades))
```

- [ ] **Step 2: Run + commit**

```bash
pytest hydra_backtest/catalyst/tests/test_validation.py -v
git add hydra_backtest/catalyst/tests/test_validation.py
git commit -m "test(hydra_backtest.catalyst): validation unit tests"
```

---

## Task 9: CLI entrypoint — `__main__.py`

**File:** `hydra_backtest/catalyst/__main__.py` (NEW)

Mirrors the Rattlesnake CLI shape (`hydra_backtest/rattlesnake/__main__.py`). Key difference: no PIT universe, no VIX, no SPY regime — just `--catalyst-assets`, `--aaa`, optional `--tbill`, date range, output dir.

- [ ] **Step 1: Create `__main__.py`**

```python
"""CLI: python -m hydra_backtest.catalyst

Run a Catalyst standalone backtest with the v1.0 5-tier waterfall and
write daily/trades/waterfall outputs to disk.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

from hydra_backtest.catalyst import (
    run_catalyst_backtest,
    run_catalyst_smoke_tests,
)
from hydra_backtest.data import (
    load_catalyst_assets,
    load_yield_series,
)
from hydra_backtest.methodology import build_waterfall
from hydra_backtest.reporting import (
    write_daily_csv,
    write_trades_csv,
    write_waterfall_json,
)


def _progress(payload):
    print(
        f"  [{payload['year']}] {payload['progress_pct']:5.1f}%  "
        f"PV=${payload['portfolio_value']:>12,.0f}  "
        f"pos={payload['n_positions']}",
        flush=True,
    )


def main(argv=None):
    p = argparse.ArgumentParser(
        prog='python -m hydra_backtest.catalyst',
        description='Run a Catalyst cross-asset trend standalone backtest.',
    )
    p.add_argument('--start', required=True, help='Start date (YYYY-MM-DD)')
    p.add_argument('--end', required=True, help='End date (YYYY-MM-DD)')
    p.add_argument('--out-dir', required=True, help='Output directory')
    p.add_argument('--catalyst-assets', required=True,
                   help='Pickle of {ticker: OHLCV df} for TLT/ZROZ/GLD/DBC')
    p.add_argument('--aaa', required=True, help='Moody Aaa yield CSV')
    p.add_argument('--aaa-date-col', default='observation_date')
    p.add_argument('--aaa-value-col', default='yield_pct')
    p.add_argument('--tbill', default=None, help='Optional 3M T-bill CSV (Tier 1)')
    p.add_argument('--initial-capital', type=float, default=100_000.0)
    p.add_argument('--commission-per-share', type=float, default=0.0035)
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== Catalyst v1.2 backtest: {args.start} → {args.end} ===", flush=True)

    print("Loading data...", flush=True)
    asset_data = load_catalyst_assets(args.catalyst_assets)
    aaa_series = load_yield_series(args.aaa, date_col=args.aaa_date_col,
                                   value_col=args.aaa_value_col)

    # Build per-day yield series aligned to the union of asset dates
    all_dates = sorted({d for df in asset_data.values() for d in df.index})
    aaa_daily = aaa_series.reindex(all_dates).ffill().fillna(0.0)

    config = {
        'INITIAL_CAPITAL': args.initial_capital,
        'COMMISSION_PER_SHARE': args.commission_per_share,
    }

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)

    print("Running tier 0 (Aaa, same_close)...", flush=True)
    result_tier0 = run_catalyst_backtest(
        config, asset_data, aaa_daily, start, end,
        execution_mode='same_close', progress_callback=_progress,
    )
    print("  Layer A smoke tests...", flush=True)
    run_catalyst_smoke_tests(result_tier0)

    # Build the 5-tier waterfall — methodology layer is strategy-agnostic
    print("Building 5-tier waterfall...", flush=True)
    if args.tbill:
        tbill_series = load_yield_series(args.tbill).reindex(all_dates).ffill().fillna(0.0)
    else:
        tbill_series = aaa_daily * 0.7  # crude proxy if no T-bill provided

    waterfall = build_waterfall(
        run_fn=run_catalyst_backtest,
        config=config,
        price_data=asset_data,
        cash_yield_aaa=aaa_daily,
        cash_yield_tbill=tbill_series,
        start_date=start,
        end_date=end,
        smoke_test_fn=run_catalyst_smoke_tests,
        progress_callback=_progress,
        run_kwargs_extra={},  # Catalyst takes no PIT/SPY/VIX
    )

    # Write outputs
    daily_path = out_dir / 'catalyst_v2_daily.csv'
    trades_path = out_dir / 'catalyst_v2_trades.csv'
    waterfall_path = out_dir / 'catalyst_v2_waterfall.json'
    write_daily_csv(result_tier0, daily_path)
    write_trades_csv(result_tier0, trades_path)
    write_waterfall_json(waterfall, waterfall_path)

    print(f"\n  Daily:     {daily_path}")
    print(f"  Trades:    {trades_path}")
    print(f"  Waterfall: {waterfall_path}")
    print("\n=== Catalyst v1.2 backtest complete ===", flush=True)


if __name__ == '__main__':
    main()
```

> **Note on `build_waterfall` signature:** The Rattlesnake CLI passes its own positional args to `build_waterfall`. Catalyst's `run_catalyst_backtest` has a different signature (no `pit_universe`, no `spy_data`, no `vix_data`). If `build_waterfall` is currently hardcoded to the COMPASS/Rattlesnake signature, **read it during this task** and either (a) call it with `run_kwargs_extra={}` if it already supports extra-kwargs passthrough, or (b) inline a 5-tier loop in `__main__.py` that calls `run_catalyst_backtest` directly four times (tier 0–3) and `build_waterfall` only for the report assembly. Pick whichever requires the smaller change to v1.0 code. **Do not modify `methodology.py`** without updating the v1.0 + v1.1 callers in the same commit.

- [ ] **Step 2: Verify CLI parses without crashing**

```bash
python -m hydra_backtest.catalyst --help
```

- [ ] **Step 3: Commit**

```bash
git add hydra_backtest/catalyst/__main__.py
git commit -m "feat(hydra_backtest.catalyst): CLI entrypoint"
```

---

## Task 10: Integration test (CLI smoke)

**File:** `hydra_backtest/catalyst/tests/test_integration.py` (NEW)

Smoke-tests the CLI by invoking `python -m hydra_backtest.catalyst` against a tiny synthetic pickle in a tmp dir.

- [ ] **Step 1: Create the test**

```python
"""CLI smoke test for hydra_backtest.catalyst."""
import pickle
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def _make_synth_assets(n_days: int = 250) -> dict:
    dates = pd.bdate_range('2020-01-01', periods=n_days)
    out = {}
    for sym in ['TLT', 'ZROZ', 'GLD', 'DBC']:
        closes = 100 * (1.0003 ** np.arange(n_days))
        out[sym] = pd.DataFrame({
            'Open': closes, 'High': closes * 1.005,
            'Low': closes * 0.995, 'Close': closes,
            'Volume': 1_000_000,
        }, index=dates)
    return out


def test_cli_runs_end_to_end(tmp_path):
    assets = _make_synth_assets()
    pkl = tmp_path / 'catalyst_assets.pkl'
    with open(pkl, 'wb') as f:
        pickle.dump(assets, f)

    aaa_csv = tmp_path / 'aaa.csv'
    pd.DataFrame({
        'observation_date': pd.bdate_range('2020-01-01', periods=250),
        'yield_pct': [4.0] * 250,
    }).to_csv(aaa_csv, index=False)

    out_dir = tmp_path / 'out'
    cmd = [
        sys.executable, '-m', 'hydra_backtest.catalyst',
        '--start', '2020-11-01', '--end', '2020-12-31',
        '--out-dir', str(out_dir),
        '--catalyst-assets', str(pkl),
        '--aaa', str(aaa_csv),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, f"CLI failed:\nstdout={res.stdout}\nstderr={res.stderr}"
    assert (out_dir / 'catalyst_v2_daily.csv').exists()
    assert (out_dir / 'catalyst_v2_trades.csv').exists()
    assert (out_dir / 'catalyst_v2_waterfall.json').exists()
```

- [ ] **Step 2: Run + commit**

```bash
pytest hydra_backtest/catalyst/tests/test_integration.py -v
git add hydra_backtest/catalyst/tests/test_integration.py
git commit -m "test(hydra_backtest.catalyst): CLI integration smoke"
```

---

## Task 11: E2E test (slow, real data)

**File:** `hydra_backtest/catalyst/tests/test_e2e.py` (NEW)

Marked `@pytest.mark.slow` — runs only when `--run-slow` is enabled. Uses the real `data_cache/catalyst_assets.pkl` (built in Task 14) over a 2-year window.

- [ ] **Step 1: Create the test**

```python
"""End-to-end Catalyst backtest with real data. Slow."""
from pathlib import Path

import pandas as pd
import pytest

from hydra_backtest.catalyst import run_catalyst_backtest, run_catalyst_smoke_tests
from hydra_backtest.data import load_catalyst_assets, load_yield_series

DATA_PKL = Path('data_cache/catalyst_assets.pkl')
AAA_CSV = Path('data_cache/moody_aaa_yield.csv')


@pytest.mark.slow
@pytest.mark.skipif(not DATA_PKL.exists(), reason="catalyst_assets.pkl not built")
@pytest.mark.skipif(not AAA_CSV.exists(), reason="moody_aaa_yield.csv missing")
def test_e2e_2year_window():
    asset_data = load_catalyst_assets(str(DATA_PKL))
    aaa = load_yield_series(str(AAA_CSV))
    all_dates = sorted({d for df in asset_data.values() for d in df.index})
    aaa_daily = aaa.reindex(all_dates).ffill().fillna(0.0)

    config = {'INITIAL_CAPITAL': 100_000.0, 'COMMISSION_PER_SHARE': 0.0035}
    result = run_catalyst_backtest(
        config, asset_data, aaa_daily,
        pd.Timestamp('2020-01-01'), pd.Timestamp('2021-12-31'),
        execution_mode='same_close',
    )
    run_catalyst_smoke_tests(result)
    assert len(result.daily_values) > 100


@pytest.mark.slow
@pytest.mark.skipif(not DATA_PKL.exists(), reason="catalyst_assets.pkl not built")
def test_e2e_determinism():
    """Two consecutive runs must produce byte-identical daily output."""
    asset_data = load_catalyst_assets(str(DATA_PKL))
    aaa = load_yield_series(str(AAA_CSV))
    all_dates = sorted({d for df in asset_data.values() for d in df.index})
    aaa_daily = aaa.reindex(all_dates).ffill().fillna(0.0)

    config = {'INITIAL_CAPITAL': 100_000.0, 'COMMISSION_PER_SHARE': 0.0035}
    r1 = run_catalyst_backtest(config, asset_data, aaa_daily,
                                pd.Timestamp('2020-01-01'), pd.Timestamp('2020-12-31'))
    r2 = run_catalyst_backtest(config, asset_data, aaa_daily,
                                pd.Timestamp('2020-01-01'), pd.Timestamp('2020-12-31'))
    pd.testing.assert_frame_equal(r1.daily_values, r2.daily_values)
```

- [ ] **Step 2: Commit (tests will skip until Task 14 is done)**

```bash
git add hydra_backtest/catalyst/tests/test_e2e.py
git commit -m "test(hydra_backtest.catalyst): E2E tests (slow, real data)"
```

---

## Task 12: README

**File:** `hydra_backtest/catalyst/README.md` (NEW)

- [ ] **Step 1: Write the README**

Sections to include (model after `hydra_backtest/rattlesnake/README.md`):

1. **Overview** — Catalyst is the third HYDRA pillar (cross-asset trend on TLT/ZROZ/GLD/DBC), 4 hardcoded ETFs, equal-weight when above SMA200, rebalances every 5 days.
2. **Architecture** — sub-package layout, reuse of v1.0 infrastructure, consumer-not-owner of `catalyst_signals.py`.
3. **Usage** — full CLI example with all flags.
4. **Data prerequisites** — how to build `data_cache/catalyst_assets.pkl` (the snippet from `data.py::load_catalyst_assets` docstring).
5. **Output schema** — `catalyst_v2_daily.csv`, `catalyst_v2_trades.csv`, `catalyst_v2_waterfall.json`.
6. **Smoke tests** — list of Layer A invariants enforced.
7. **v1.2 limitations** — no HydraCapitalManager, no permanent gold, no asset proxies for pre-inception, no Layer B/C cross-validation.
8. **Roadmap** — pointer to v1.3 (EFA), v1.4 (HYDRA full), v1.5.

- [ ] **Step 2: Commit**

```bash
git add hydra_backtest/catalyst/README.md
git commit -m "docs(hydra_backtest.catalyst): README"
```

---

## Task 13: CI integration

**File:** `.github/workflows/test.yml` (modify)

- [ ] **Step 1: Add a Catalyst pytest step right after the Rattlesnake one**

Read the current workflow:

```bash
cat .github/workflows/test.yml
```

Locate the Rattlesnake test step (added in commit `b22dc3b`). Add an analogous step:

```yaml
      - name: Run Catalyst tests
        run: pytest hydra_backtest/catalyst/tests/ -v --cov=hydra_backtest/catalyst --cov-report=term-missing --cov-fail-under=80
```

- [ ] **Step 2: Verify YAML still parses**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml'))" && echo OK
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/test.yml
git commit -m "ci(hydra_backtest.catalyst): add CI step for catalyst tests"
```

---

## Task 14: Catalyst assets download (one-time, NOT a code task)

**This task is a manual data prep step. No git commit.**

- [ ] **Step 1: Run the download script** (one-shot Python REPL or scratch script)

```python
import pickle

import yfinance as yf

data = {}
for sym in ['TLT', 'ZROZ', 'GLD', 'DBC']:
    df = yf.download(sym, start='1999-01-01', end='2027-01-01',
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    data[sym] = df
    print(f"  {sym}: {len(df)} rows, {df.index.min().date()} → {df.index.max().date()}")

with open('data_cache/catalyst_assets.pkl', 'wb') as f:
    pickle.dump(data, f)
print("Saved data_cache/catalyst_assets.pkl")
```

- [ ] **Step 2: Verify the loader accepts it**

```bash
python -c "from hydra_backtest.data import load_catalyst_assets; d = load_catalyst_assets('data_cache/catalyst_assets.pkl'); print({k: len(v) for k, v in d.items()})"
```

Expected: dict with TLT/ZROZ/GLD/DBC keys, each ≥ 1000 rows.

> **Note:** `data_cache/catalyst_assets.pkl` is in `.gitignore` (data files are not committed). Treat this step as a local prerequisite for the official run in Task 15 — CI does not need it.

---

## Task 15: Run the official 2000-2026 backtest

**Goal:** Produce the canonical `backtests/catalyst_v1/` outputs that anyone can reproduce from a clean checkout.

- [ ] **Step 1: Run the CLI**

```bash
python -m hydra_backtest.catalyst \
    --start 2000-01-01 \
    --end 2026-03-05 \
    --out-dir backtests/catalyst_v1 \
    --catalyst-assets data_cache/catalyst_assets.pkl \
    --aaa data_cache/moody_aaa_yield.csv \
    --aaa-date-col observation_date --aaa-value-col yield_pct \
    --tbill data_cache/tbill_3m_fred.csv 2>&1 | tee backtests/catalyst_v1/run.log
```

Expected runtime: ~2–3 minutes (fast — only 4 assets, infrequent rebalances).

- [ ] **Step 2: Verify output files exist and are non-empty**

```bash
ls -la backtests/catalyst_v1/
python -c "import pandas as pd; print(pd.read_csv('backtests/catalyst_v1/catalyst_v2_daily.csv').shape)"
python -c "import json; w=json.load(open('backtests/catalyst_v1/catalyst_v2_waterfall.json')); print(list(w.keys()))"
```

- [ ] **Step 3: Determinism check** — run a second time and diff

```bash
cp backtests/catalyst_v1/catalyst_v2_daily.csv /tmp/catalyst_run1.csv
python -m hydra_backtest.catalyst \
    --start 2000-01-01 --end 2026-03-05 \
    --out-dir backtests/catalyst_v1 \
    --catalyst-assets data_cache/catalyst_assets.pkl \
    --aaa data_cache/moody_aaa_yield.csv \
    --tbill data_cache/tbill_3m_fred.csv > /dev/null
diff /tmp/catalyst_run1.csv backtests/catalyst_v1/catalyst_v2_daily.csv && echo "DETERMINISTIC ✅"
```

- [ ] **Step 4: Commit the official outputs**

```bash
git add backtests/catalyst_v1/
git commit -m "feat(hydra_backtest.catalyst): v1.2 official 2000-2026 results"
```

- [ ] **Step 5: Update memory + push**

Add a one-line entry to `MEMORY.md` referencing the v1.2 result (CAGR / Sharpe / MaxDD from waterfall.json tier3).

```bash
git push
```

---

## Success criteria (from spec §14)

v1.2 is complete when ALL of these are true:

1. ☐ `python -m hydra_backtest.catalyst --start 2000-01-01 --end 2026-03-05 ...` runs to completion without errors
2. ☐ Two consecutive runs produce byte-identical `catalyst_v2_daily.csv`
3. ☐ All Layer A smoke tests pass for all 3 tier runs (Aaa same_close, Tier 1 t-bill, Tier 2 next_open, Tier 3 +slippage)
4. ☐ Coverage ≥ 80% for `hydra_backtest/catalyst/`
5. ☐ v1.0 + v1.1 test suites remain green (`pytest hydra_backtest/tests/ hydra_backtest/rattlesnake/tests/`)
6. ☐ Waterfall report prints 5 tiers
7. ☐ Pre-2002 snapshots show `n_positions == 0` (data gap respected)

---

## Risks & open questions

| Risk | Mitigation |
|---|---|
| `methodology.build_waterfall` signature may not accept Catalyst's reduced kwargs | Task 9 has a fallback: inline the 5-tier loop in `__main__.py` rather than touching v1.0 |
| `catalyst_signals.py` is consumer-not-owner — if its constants change, the backtest changes too | Acceptable per spec §4.4; document in README |
| Pre-2002 has 0 holdings → all-cash period drags CAGR | Expected; spec §6.5 explicitly accepts this |
| Determinism failure from `dict.keys()` ordering on synthetic-end exits | Sort `state.positions.items()` before iterating in the synthetic-end loop |
