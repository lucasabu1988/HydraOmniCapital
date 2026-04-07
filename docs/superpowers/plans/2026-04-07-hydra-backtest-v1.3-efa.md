# HYDRA Backtest v1.3 — EFA Standalone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `hydra_backtest/efa/` — a single-asset EFA passive trend backtest sub-package implementing the SMA200 regime gate inline (no live pure functions exist to import), reusing v1.0 infrastructure (BacktestState, methodology, reporting), and producing a 5-tier waterfall report with blocking smoke tests.

**Architecture:** New sub-package `hydra_backtest/efa/` with its own engine, validation, CLI, and tests. v1.0/v1.1/v1.2 modules are reused as-is via imports — zero modification to existing files except `data.py` (one new helper `load_efa_series`) and `.github/workflows/test.yml` (CI step).

**Tech Stack:** Python 3.14, pandas, numpy, pytest, pytest-cov. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-04-07-hydra-backtest-v1.3-efa-design.md`

---

## File Structure

```
hydra_backtest/                                    ← v1.0+v1.1+v1.2 (untouched except data.py)
├── data.py                                        ← + load_efa_series helper
└── efa/                                           ← NEW v1.3 sub-package
    ├── __init__.py                                ← public exports
    ├── __main__.py                                ← CLI: python -m hydra_backtest.efa
    ├── engine.py                                  ← run_efa_backtest + apply_efa_decision
    ├── validation.py                              ← Layer A smoke tests EFA-adapted
    ├── README.md                                  ← usage + architecture + v1.3 limitations
    └── tests/
        ├── __init__.py
        ├── conftest.py                            ← efa_minimal_config fixture
        ├── test_engine.py
        ├── test_validation.py
        ├── test_integration.py                    ← CLI smoke
        └── test_e2e.py                            ← @pytest.mark.slow
.github/workflows/test.yml                         ← + new pytest step for efa
```

**Reuse table** (from spec §4.2):

| From v1.0 | How |
|---|---|
| `BacktestState`, `BacktestResult` | `from hydra_backtest.engine import ...` |
| `_mark_to_market`, `_get_exec_price` | Direct imports |
| `data.load_yield_series` | Direct import |
| `methodology.build_waterfall` | Direct import (strategy-agnostic) |
| `reporting.write_*`, `format_summary_table` | Direct imports |
| `errors.HydraDataError`, `HydraBacktestValidationError` | Direct imports |

**Inline constants** (from `omnicapital_live.py`, no module to import them from cleanly — duplicate as module-level constants in `efa/engine.py` to avoid coupling on the live module's heavy import surface):

```python
EFA_SYMBOL = 'EFA'
EFA_SMA_PERIOD = 200
```

These two values match `omnicapital_live.py:264-266`. If they ever change in live, this duplication is the only contract surface to keep in sync (documented in the README's "v1.3 limitations" section).

---

## Task 1: Bootstrap sub-package + conftest fixture

**Files:**
- Create: `hydra_backtest/efa/__init__.py` (initially empty docstring only — public API wired in Task 6)
- Create: `hydra_backtest/efa/tests/__init__.py` (empty)
- Create: `hydra_backtest/efa/tests/conftest.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p hydra_backtest/efa/tests
```

- [ ] **Step 2: Create empty package init**

`hydra_backtest/efa/__init__.py`:
```python
"""hydra_backtest.efa — EFA passive international trend standalone backtest.

Single-asset (EFA, iShares MSCI EAFE), long when above SMA200, cash
otherwise. No rebalance cadence, no PIT, no other-strategy interaction.

See:
- docs/superpowers/specs/2026-04-07-hydra-backtest-v1.3-efa-design.md
- docs/superpowers/plans/2026-04-07-hydra-backtest-v1.3-efa.md

Public API symbols are wired in Task 6 once engine and validation exist.
"""
```

- [ ] **Step 3: Empty tests init**

```bash
touch hydra_backtest/efa/tests/__init__.py
```

- [ ] **Step 4: conftest.py with `efa_minimal_config` fixture**

```python
"""Shared fixtures for hydra_backtest.efa tests."""
import numpy as np
import pytest


@pytest.fixture(autouse=True)
def fixed_seed():
    """Force deterministic numpy RNG for every test."""
    np.random.seed(666)


@pytest.fixture
def efa_minimal_config():
    """Smallest valid EFA config — even simpler than Catalyst.

    No leverage, no DD scaling, no rebalance cadence, no position
    bounds (max is 1 by definition since the universe is 1 ticker).
    """
    return {
        'INITIAL_CAPITAL': 100_000,
        'COMMISSION_PER_SHARE': 0.0035,
    }
```

- [ ] **Step 5: Verify pytest collects empty cleanly**

```bash
pytest hydra_backtest/efa/tests/ --collect-only -q 2>&1 | tail -5
```

Expected: `0 tests collected` (conftest loads cleanly, no test files yet, no broken imports).

- [ ] **Step 6: Commit**

```bash
git add hydra_backtest/efa/__init__.py \
        hydra_backtest/efa/tests/__init__.py \
        hydra_backtest/efa/tests/conftest.py
git commit -m "feat(hydra_backtest): bootstrap efa sub-package + conftest"
```

---

## Task 2: data.py — `load_efa_series` helper

**File:** `hydra_backtest/data.py` (modify) + `hydra_backtest/__init__.py` (re-export)

- [ ] **Step 1: Add `load_efa_series` to `data.py`**

Append after `load_catalyst_assets`:

```python
def load_efa_series(path: str) -> pd.DataFrame:
    """Load EFA OHLCV from pickle.

    Format: pickle of a single pd.DataFrame with Open/High/Low/Close/Volume
    columns indexed by date. Caller is responsible for download:

        import yfinance as yf
        import pickle
        df = yf.download('EFA', start='1999-01-01', end='2027-01-01',
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        with open('data_cache/efa_history.pkl', 'wb') as f:
            pickle.dump(df, f)
    """
    if not os.path.exists(path):
        raise HydraDataError(f"EFA history file not found: {path}")
    with open(path, 'rb') as f:
        df = pickle.load(f)
    if not isinstance(df, pd.DataFrame):
        raise HydraDataError(
            f"EFA history must be a DataFrame, got {type(df).__name__}"
        )
    if df.empty:
        raise HydraDataError("EFA history DataFrame is empty")
    required_cols = {'Open', 'High', 'Low', 'Close', 'Volume'}
    missing_cols = required_cols - set(df.columns)
    if missing_cols:
        raise HydraDataError(
            f"EFA history missing columns: {missing_cols}"
        )
    return df
```

- [ ] **Step 2: Re-export from `hydra_backtest/__init__.py`**

Add `load_efa_series` to the imports from `hydra_backtest.data` and to `__all__`.

- [ ] **Step 3: Smoke test**

```bash
python -c "
import pandas as pd
import pickle
import tempfile
from hydra_backtest.data import load_efa_series
df = pd.DataFrame({'Open':[1.0],'High':[1.0],'Low':[1.0],'Close':[1.0],'Volume':[1]}, index=[pd.Timestamp('2020-01-01')])
with tempfile.NamedTemporaryFile(suffix='.pkl', delete=False) as f:
    pickle.dump(df, f)
    path = f.name
loaded = load_efa_series(path)
print('OK', loaded.shape)
"
```

- [ ] **Step 4: Verify v1.0/v1.1/v1.2 still import cleanly**

```bash
python -c "import hydra_backtest; print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/data.py hydra_backtest/__init__.py
git commit -m "feat(hydra_backtest): add load_efa_series data loader"
```

---

## Task 3: Engine — `apply_efa_decision` pure function

**File:** `hydra_backtest/efa/engine.py` (NEW)

- [ ] **Step 1: Create `engine.py` with imports, constants, and the decision helper**

```python
"""hydra_backtest.efa.engine — EFA passive trend backtest engine.

Pure functions only. Implements the regime gate inline (no pure
function exists in omnicapital_live.py to import — the logic lives
embedded in _manage_efa_position at omnicapital_live.py:2409).
"""
import subprocess
from datetime import datetime
from typing import Optional, Tuple

import pandas as pd

from hydra_backtest.data import compute_data_fingerprint
from hydra_backtest.engine import (
    BacktestResult,
    BacktestState,
    _get_exec_price,
    _mark_to_market,
)


# These two constants mirror omnicapital_live.py:264-266. If live ever
# changes them, this duplication is the only contract surface to update.
EFA_SYMBOL = 'EFA'
EFA_SMA_PERIOD = 200


def _efa_close_on(efa_data: pd.DataFrame, date: pd.Timestamp) -> Optional[float]:
    """Return EFA Close on `date`, or None if data unavailable."""
    if date not in efa_data.index:
        return None
    return float(efa_data.loc[date, 'Close'])


def _efa_above_sma200(
    efa_data: pd.DataFrame,
    date: pd.Timestamp,
) -> bool:
    """True if EFA closed above its 200-day SMA on `date`.

    Returns False when there is insufficient history (so the engine
    treats EFA as 'not held' before there are enough bars to compute
    the SMA — matches the live behavior in COMPASSLive._efa_above_sma200).
    """
    sliced = efa_data.loc[:date]
    if len(sliced) < EFA_SMA_PERIOD:
        return False
    close = float(sliced['Close'].iloc[-1])
    sma = float(sliced['Close'].iloc[-EFA_SMA_PERIOD:].mean())
    return close > sma


def apply_efa_decision(
    state: BacktestState,
    date: pd.Timestamp,
    i: int,
    efa_data: pd.DataFrame,
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[BacktestState, list, list]:
    """Pure equivalent of COMPASSLive._manage_efa_position for the
    standalone case (no recycling, no min-buy threshold, no 90% cap).

    Decision matrix:
        above_sma200 | held | action
        -------------+------+--------------------------------
        True         | no   | BUY 100% of cash
        True         | yes  | no-op
        False        | no   | no-op
        False        | yes  | SELL all (EFA_BELOW_SMA200)
    """
    trades: list = []
    decisions: list = []

    above = _efa_above_sma200(efa_data, date)
    held = EFA_SYMBOL in state.positions
    commission_per_share = config.get('COMMISSION_PER_SHARE', 0.0035)

    new_positions = dict(state.positions)
    cash = state.cash

    # Case 1: above SMA200 and NOT held → BUY
    if above and not held:
        entry_price = _get_exec_price(
            EFA_SYMBOL, date, i, all_dates, {EFA_SYMBOL: efa_data}, execution_mode,
        )
        if entry_price is not None and entry_price > 0:
            # Deploy 100% of cash (integer shares, account for commission)
            affordable_after_comm = cash - (cash / entry_price) * commission_per_share
            shares = int(affordable_after_comm / entry_price)
            if shares > 0:
                cost = shares * entry_price
                commission = shares * commission_per_share
                if cost + commission <= cash:
                    cash -= cost + commission
                    new_positions[EFA_SYMBOL] = {
                        'symbol': EFA_SYMBOL,
                        'entry_price': entry_price,
                        'shares': shares,
                        'entry_date': date,
                        'entry_idx': i,
                        'days_held': 0,
                        'sub_strategy': 'passive_intl',
                        'sector': 'International Equity',
                        'entry_vol': 0.0,
                        'entry_daily_vol': 0.0,
                        'high_price': entry_price,
                    }
                    decisions.append({
                        'date': date,
                        'action': 'ENTRY',
                        'symbol': EFA_SYMBOL,
                        'shares': shares,
                    })

    # Case 2: NOT above SMA200 and held → SELL
    elif not above and held:
        pos = new_positions[EFA_SYMBOL]
        exit_price = _get_exec_price(
            EFA_SYMBOL, date, i, all_dates, {EFA_SYMBOL: efa_data}, execution_mode,
        )
        if exit_price is not None:
            shares = pos['shares']
            commission = shares * commission_per_share
            cash += shares * exit_price - commission
            pnl = (exit_price - pos['entry_price']) * shares - commission
            ret = (
                (exit_price / pos['entry_price'] - 1.0)
                if pos['entry_price'] > 0 else 0.0
            )
            trades.append({
                'symbol': EFA_SYMBOL,
                'entry_date': pos['entry_date'],
                'exit_date': date,
                'exit_reason': 'EFA_BELOW_SMA200',
                'entry_price': pos['entry_price'],
                'exit_price': exit_price,
                'shares': shares,
                'pnl': pnl,
                'return': ret,
                'sector': 'International Equity',
            })
            decisions.append({
                'date': date,
                'action': 'EXIT',
                'symbol': EFA_SYMBOL,
                'reason': 'EFA_BELOW_SMA200',
            })
            del new_positions[EFA_SYMBOL]

    # Cases 3 & 4: above+held or not-above+not-held → no-op

    new_state = state._replace(cash=cash, positions=new_positions)
    return new_state, trades, decisions
```

- [ ] **Step 2: Compile + commit**

```bash
python -c "import py_compile; py_compile.compile('hydra_backtest/efa/engine.py', doraise=True); print('OK')"
git add hydra_backtest/efa/engine.py
git commit -m "feat(hydra_backtest.efa): apply_efa_decision pure function + SMA200 helpers"
```

---

## Task 4: Engine — daily cash-yield helper + git sha

**File:** `hydra_backtest/efa/engine.py` (extend)

EFA has no leverage, so the daily cost helper only credits cash yield — identical pattern to Catalyst (`_apply_catalyst_daily_costs`) and Rattlesnake (`_apply_rattlesnake_daily_costs`).

- [ ] **Step 1: Append helpers**

```python
def _apply_efa_daily_costs(
    state: BacktestState,
    cash_yield_annual_pct: float,
) -> BacktestState:
    """Apply one trading day's cash yield. EFA has no leverage,
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
python -c "import py_compile; py_compile.compile('hydra_backtest/efa/engine.py')"
git add hydra_backtest/efa/engine.py
git commit -m "feat(hydra_backtest.efa): daily cash-yield helper + git sha"
```

---

## Task 5: Engine — `run_efa_backtest` orchestrator

**File:** `hydra_backtest/efa/engine.py` (extend)

- [ ] **Step 1: Append orchestrator**

```python
def run_efa_backtest(
    config: dict,
    efa_data: pd.DataFrame,
    cash_yield_daily: pd.Series,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    execution_mode: str = 'same_close',
    progress_callback: Optional[callable] = None,
) -> BacktestResult:
    """Run an EFA passive trend backtest from start_date to end_date.

    Pure function: no side effects. Returns a BacktestResult compatible
    with v1.0 reporting/methodology layers (drop-in for build_waterfall).

    Universe is the single hardcoded ticker EFA_SYMBOL.
    """
    started_at = datetime.now()

    all_dates = sorted(efa_data.index)
    asset_dict = {EFA_SYMBOL: efa_data}  # for _mark_to_market interface

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
    universe_size: dict = {}

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
                pv_now = _mark_to_market(state, asset_dict, date)
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
        portfolio_value = _mark_to_market(state, asset_dict, date)

        # 1b. Update peak BEFORE drawdown
        if portfolio_value > state.peak_value:
            state = state._replace(peak_value=portfolio_value)

        # 2. Universe size = 1 once we have ≥SMA_PERIOD bars; 0 before
        eligible = 1 if len(efa_data.loc[:date]) >= EFA_SMA_PERIOD else 0
        universe_size[date.year] = max(universe_size.get(date.year, 0), eligible)

        # 3. Drawdown
        drawdown = (
            (portfolio_value - state.peak_value) / state.peak_value
            if state.peak_value > 0 else 0.0
        )

        # 4. Daily cash yield (no leverage, no margin)
        if len(cash_yield_daily) > 0:
            daily_yield = float(
                cash_yield_daily.get(date, cash_yield_daily.iloc[0])
            )
        else:
            daily_yield = 0.0
        state = _apply_efa_daily_costs(state, daily_yield)

        # 5. Apply EFA decision (state-driven, daily, no cadence)
        above_sma_today = _efa_above_sma200(efa_data, date)
        state, day_trades, day_decisions = apply_efa_decision(
            state, date, i, efa_data, config, execution_mode, all_dates,
        )
        trades.extend(day_trades)
        decisions.extend(day_decisions)

        # 6. Snapshot AFTER decision
        pv_after = _mark_to_market(state, asset_dict, date)
        snapshots.append({
            'date': date,
            'portfolio_value': pv_after,
            'cash': state.cash,
            'n_positions': len(state.positions),
            'leverage': 1.0,           # EFA never uses leverage
            'drawdown': drawdown,
            'regime_score': 1.0 if above_sma_today else 0.0,
            'crash_active': False,
            'max_positions': 1,
            'above_sma_today': above_sma_today,
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

    # 8. Synthetic-close any remaining open position at backtest end
    if EFA_SYMBOL in state.positions and dates_in_range:
        last_date = dates_in_range[-1]
        last_i = all_dates.index(last_date)
        pos = state.positions[EFA_SYMBOL]
        exit_price = _get_exec_price(
            EFA_SYMBOL, last_date, last_i, all_dates, asset_dict, execution_mode,
        )
        if exit_price is None:
            exit_price = float(pos['entry_price'])
        shares = pos['shares']
        commission = shares * config.get('COMMISSION_PER_SHARE', 0.0035)
        pnl = (exit_price - pos['entry_price']) * shares - commission
        ret = (
            (exit_price / pos['entry_price'] - 1.0)
            if pos['entry_price'] > 0 else 0.0
        )
        trades.append({
            'symbol': EFA_SYMBOL,
            'entry_date': pos['entry_date'],
            'exit_date': last_date,
            'exit_reason': 'EFA_BACKTEST_END',
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'shares': shares,
            'pnl': pnl,
            'return': ret,
            'sector': 'International Equity',
        })

    finished_at = datetime.now()

    result_config = dict(config)
    result_config['_execution_mode'] = execution_mode

    trade_cols = [
        'symbol', 'entry_date', 'exit_date', 'exit_reason',
        'entry_price', 'exit_price', 'shares', 'pnl', 'return', 'sector',
    ]
    return BacktestResult(
        config=result_config,
        daily_values=pd.DataFrame(snapshots),
        trades=pd.DataFrame(trades) if trades else pd.DataFrame(columns=trade_cols),
        decisions=decisions,
        exit_events=[t for t in trades if t['exit_reason'] == 'EFA_BELOW_SMA200'],
        universe_size=universe_size,
        started_at=started_at,
        finished_at=finished_at,
        git_sha=_capture_git_sha(),
        data_inputs_hash=compute_data_fingerprint(asset_dict),
    )
```

- [ ] **Step 2: Smoke test orchestrator with synthetic data**

```bash
python -c "
import numpy as np, pandas as pd
from hydra_backtest.efa.engine import run_efa_backtest
np.random.seed(666)
dates = pd.bdate_range('2020-01-01', periods=400)
rets = 0.0005 + np.random.normal(0, 0.01, 400)
closes = 50.0 * np.cumprod(1 + rets)
efa = pd.DataFrame({'Open':closes,'High':closes*1.005,'Low':closes*0.995,'Close':closes,'Volume':1e6}, index=dates)
yld = pd.Series(0.0, index=dates)
cfg = {'INITIAL_CAPITAL':100_000.0,'COMMISSION_PER_SHARE':0.0035}
r = run_efa_backtest(cfg, efa, yld, dates[210], dates[-1])
print(f'Days: {len(r.daily_values)}, n_pos range: [{r.daily_values[\"n_positions\"].min()}, {r.daily_values[\"n_positions\"].max()}]')
print(f'Trades: {len(r.trades)}, final PV: \${r.daily_values[\"portfolio_value\"].iloc[-1]:,.0f}')
"
```

- [ ] **Step 3: Commit**

```bash
git add hydra_backtest/efa/engine.py
git commit -m "feat(hydra_backtest.efa): run_efa_backtest orchestrator"
```

---

## Task 6: Validation — Layer A smoke tests

**File:** `hydra_backtest/efa/validation.py` (NEW)

- [ ] **Step 1: Create `validation.py`**

```python
"""hydra_backtest.efa.validation — Layer A smoke tests for EFA.

Mathematical invariants (shared with v1.0/v1.1/v1.2):
1. No NaN in critical columns
2. Cash never < -1.0
3. Drawdown ∈ [-1.0, 0]
4. Peak monotonic non-decreasing
5. Vol ann ∈ [0.5%, 50%]
6. No outlier daily returns > ±15% (allowlist crash days)

EFA-specific invariants:
7. n_positions ∈ [0, 1] always (single-asset universe)
8. Trade exit reasons ⊆ {'EFA_BELOW_SMA200', 'EFA_BACKTEST_END'}
"""
from typing import List

import numpy as np
import pandas as pd

from hydra_backtest.engine import BacktestResult
from hydra_backtest.errors import HydraBacktestValidationError

_CRASH_ALLOWLIST = {
    pd.Timestamp('2008-10-13'),
    pd.Timestamp('2008-10-15'),
    pd.Timestamp('2020-03-12'),
    pd.Timestamp('2020-03-16'),
}


def _check_no_nan(daily, errors):
    critical = ['portfolio_value', 'cash', 'n_positions', 'drawdown']
    for col in critical:
        if col in daily.columns and daily[col].isna().any():
            errors.append(f"NaN in critical column: {col}")


def _check_cash_floor(daily, errors):
    if 'cash' in daily.columns and (daily['cash'] < -1.0).any():
        bad = daily[daily['cash'] < -1.0].iloc[0]
        errors.append(f"Cash < -1.0 at {bad['date']}: {bad['cash']:.4f}")


def _check_drawdown_range(daily, errors):
    if 'drawdown' not in daily.columns:
        return
    dd = daily['drawdown']
    if (dd < -1.0).any() or (dd > 0).any():
        errors.append(
            f"Drawdown out of [-1.0, 0]: min={dd.min():.4f}, max={dd.max():.4f}"
        )


def _check_peak_monotonic(daily, errors):
    if 'portfolio_value' not in daily.columns:
        return
    pv = daily['portfolio_value'].values
    peak = np.maximum.accumulate(pv)
    if not np.all(np.diff(peak) >= -1e-9):
        errors.append("Peak series is not monotonic non-decreasing")


def _check_vol_range(daily, errors):
    if 'portfolio_value' not in daily.columns or len(daily) < 30:
        return
    rets = daily['portfolio_value'].pct_change().dropna()
    if len(rets) < 2:
        return
    vol_ann = rets.std() * np.sqrt(252) * 100
    if vol_ann < 0.5 or vol_ann > 50:
        errors.append(f"Annualized vol out of [0.5%, 50%]: {vol_ann:.2f}%")


def _check_outlier_returns(daily, errors):
    if 'portfolio_value' not in daily.columns or len(daily) < 2:
        return
    rets = daily['portfolio_value'].pct_change()
    for idx, r in rets.items():
        if pd.isna(r):
            continue
        if abs(r) > 0.15:
            row_date = daily.loc[idx, 'date'] if 'date' in daily.columns else idx
            if pd.Timestamp(row_date) not in _CRASH_ALLOWLIST:
                errors.append(f"Outlier daily return {r * 100:.2f}% on {row_date}")


def _check_n_positions_bounds(daily, errors):
    if 'n_positions' not in daily.columns:
        return
    bad = daily[(daily['n_positions'] < 0) | (daily['n_positions'] > 1)]
    if not bad.empty:
        row = bad.iloc[0]
        errors.append(
            f"n_positions out of [0, 1] at {row.get('date', '?')}: {row['n_positions']}"
        )


def _check_exit_reasons(trades, errors):
    if trades.empty or 'exit_reason' not in trades.columns:
        return
    valid = {'EFA_BELOW_SMA200', 'EFA_BACKTEST_END'}
    invalid = set(trades['exit_reason'].unique()) - valid
    if invalid:
        errors.append(f"Invalid EFA exit reasons: {invalid}")


def run_efa_smoke_tests(result: BacktestResult) -> None:
    """Run all Layer A smoke tests on an EFA BacktestResult.

    Raises HydraBacktestValidationError with all errors aggregated.
    """
    errors: List[str] = []
    daily = result.daily_values
    trades = result.trades

    if daily.empty:
        raise HydraBacktestValidationError("EFA backtest produced empty daily_values")

    _check_no_nan(daily, errors)
    _check_cash_floor(daily, errors)
    _check_drawdown_range(daily, errors)
    _check_peak_monotonic(daily, errors)
    _check_vol_range(daily, errors)
    _check_outlier_returns(daily, errors)
    _check_n_positions_bounds(daily, errors)
    _check_exit_reasons(trades, errors)

    if errors:
        msg = "EFA smoke tests failed:\n  - " + "\n  - ".join(errors)
        raise HydraBacktestValidationError(msg)
```

- [ ] **Step 2: Compile + commit**

```bash
python -c "import py_compile; py_compile.compile('hydra_backtest/efa/validation.py')"
git add hydra_backtest/efa/validation.py
git commit -m "feat(hydra_backtest.efa): Layer A smoke tests"
```

---

## Task 7: Wire public API exports

**File:** `hydra_backtest/efa/__init__.py` (modify)

- [ ] **Step 1: Replace placeholder with real exports**

```python
"""hydra_backtest.efa — EFA passive international trend standalone backtest.

Single-asset (EFA, iShares MSCI EAFE), long when above SMA200, cash
otherwise. No rebalance cadence, no PIT, no other-strategy interaction.

See:
- docs/superpowers/specs/2026-04-07-hydra-backtest-v1.3-efa-design.md
- docs/superpowers/plans/2026-04-07-hydra-backtest-v1.3-efa.md
"""
from hydra_backtest.efa.engine import (
    EFA_SMA_PERIOD,
    EFA_SYMBOL,
    apply_efa_decision,
    run_efa_backtest,
)
from hydra_backtest.efa.validation import run_efa_smoke_tests

__all__ = [
    'EFA_SYMBOL',
    'EFA_SMA_PERIOD',
    'apply_efa_decision',
    'run_efa_backtest',
    'run_efa_smoke_tests',
]
```

- [ ] **Step 2: Verify imports**

```bash
python -c "import hydra_backtest.efa as e; print(e.__all__); print('All resolve:', all(hasattr(e, s) for s in e.__all__))"
pytest hydra_backtest/efa/tests/ --collect-only -q 2>&1 | tail -3
pytest hydra_backtest/tests/ hydra_backtest/rattlesnake/tests/ hydra_backtest/catalyst/tests/ --collect-only -q 2>&1 | tail -3
```

Expected: efa imports clean, v1.0+v1.1+v1.2 still collect 124 tests (108 prior + 16 catalyst).

- [ ] **Step 3: Commit**

```bash
git add hydra_backtest/efa/__init__.py
git commit -m "feat(hydra_backtest.efa): wire public API exports"
```

---

## Task 8: Engine unit tests

**File:** `hydra_backtest/efa/tests/test_engine.py` (NEW)

- [ ] **Step 1: Create test file**

```python
"""Unit tests for hydra_backtest.efa.engine."""
import numpy as np
import pandas as pd
import pytest

from hydra_backtest.efa.engine import (
    EFA_SMA_PERIOD,
    EFA_SYMBOL,
    _efa_above_sma200,
    apply_efa_decision,
    run_efa_backtest,
)
from hydra_backtest.engine import BacktestState


def _make_efa(start: str = '2020-01-01', n_days: int = 400,
              drift: float = 0.0005, start_price: float = 50.0) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=n_days)
    closes = start_price * (1.0 + drift) ** np.arange(n_days)
    return pd.DataFrame(
        {'Open': closes, 'High': closes * 1.005, 'Low': closes * 0.995,
         'Close': closes, 'Volume': 1_000_000},
        index=dates,
    )


def _empty_state(cash: float = 100_000.0) -> BacktestState:
    return BacktestState(
        cash=cash, positions={}, peak_value=cash,
        crash_cooldown=0, portfolio_value_history=(),
    )


def _held_state(cash: float = 0.0, shares: int = 1000,
                entry_price: float = 50.0) -> BacktestState:
    return BacktestState(
        cash=cash,
        positions={EFA_SYMBOL: {
            'symbol': EFA_SYMBOL, 'entry_price': entry_price, 'shares': shares,
            'entry_date': pd.Timestamp('2020-01-01'), 'entry_idx': 0,
            'days_held': 100, 'sub_strategy': 'passive_intl',
            'sector': 'International Equity', 'entry_vol': 0.0,
            'entry_daily_vol': 0.0, 'high_price': entry_price,
        }},
        peak_value=cash + shares * entry_price,
        crash_cooldown=0, portfolio_value_history=(),
    )


def test_above_sma_uptrend():
    efa = _make_efa(drift=0.001)
    assert _efa_above_sma200(efa, efa.index[-1]) is True


def test_below_sma_downtrend():
    efa = _make_efa(drift=-0.001)
    assert _efa_above_sma200(efa, efa.index[-1]) is False


def test_sma_insufficient_history():
    efa = _make_efa()
    # Day 50 has < 200 bars
    assert _efa_above_sma200(efa, efa.index[50]) is False


def test_apply_decision_buys_when_above_and_not_held(efa_minimal_config):
    efa = _make_efa(drift=0.001)
    state = _empty_state()
    last_date = efa.index[-1]
    new_state, trades, decisions = apply_efa_decision(
        state, last_date, len(efa) - 1, efa,
        efa_minimal_config, 'same_close', list(efa.index),
    )
    assert EFA_SYMBOL in new_state.positions
    assert trades == []  # entries are not trade records
    assert any(d['action'] == 'ENTRY' for d in decisions)
    assert new_state.cash < state.cash  # cash deployed


def test_apply_decision_sells_when_below_and_held(efa_minimal_config):
    # Create EFA series that ends below its SMA200
    efa = _make_efa(drift=0.001, n_days=300)
    # Crash the last 30 bars to drive Close below SMA200
    crash_tail = np.linspace(
        efa['Close'].iloc[-31], efa['Close'].iloc[-31] * 0.4, 31
    )
    efa.iloc[-31:, efa.columns.get_loc('Close')] = crash_tail
    efa['Open'] = efa['Close']
    efa['High'] = efa['Close'] * 1.005
    efa['Low'] = efa['Close'] * 0.995

    state = _held_state(shares=500, entry_price=float(efa['Close'].iloc[-200]))
    last_date = efa.index[-1]
    new_state, trades, _ = apply_efa_decision(
        state, last_date, len(efa) - 1, efa,
        efa_minimal_config, 'same_close', list(efa.index),
    )
    assert EFA_SYMBOL not in new_state.positions
    assert any(t['exit_reason'] == 'EFA_BELOW_SMA200' for t in trades)


def test_apply_decision_no_op_above_and_held(efa_minimal_config):
    efa = _make_efa(drift=0.001)
    state = _held_state(shares=1000, entry_price=50.0)
    last_date = efa.index[-1]
    new_state, trades, decisions = apply_efa_decision(
        state, last_date, len(efa) - 1, efa,
        efa_minimal_config, 'same_close', list(efa.index),
    )
    assert EFA_SYMBOL in new_state.positions
    assert trades == []
    assert decisions == []


def test_apply_decision_no_op_below_and_not_held(efa_minimal_config):
    efa = _make_efa(drift=-0.001)
    state = _empty_state()
    last_date = efa.index[-1]
    new_state, trades, decisions = apply_efa_decision(
        state, last_date, len(efa) - 1, efa,
        efa_minimal_config, 'same_close', list(efa.index),
    )
    assert EFA_SYMBOL not in new_state.positions
    assert trades == []
    assert decisions == []


def test_run_backtest_buy_and_hold_in_continuous_uptrend(efa_minimal_config):
    """Always-uptrend run should produce a single ENTRY + a synthetic-end exit."""
    efa = _make_efa(drift=0.001, n_days=500)
    yld = pd.Series(0.0, index=efa.index)
    start = efa.index[210]   # after SMA200 settles
    end = efa.index[-1]
    result = run_efa_backtest(efa_minimal_config, efa, yld, start, end)
    # Exactly one trade record (the synthetic-end exit)
    assert len(result.trades) == 1
    assert result.trades.iloc[0]['exit_reason'] == 'EFA_BACKTEST_END'
    # Final PV > initial (uptrend)
    assert result.daily_values['portfolio_value'].iloc[-1] > 100_000.0
    # n_positions stable at 1 throughout
    assert (result.daily_values['n_positions'] == 1).all()


def test_run_backtest_handles_pre_inception(efa_minimal_config):
    """Bars before SMA200 has data must show n_positions == 0."""
    efa = _make_efa(n_days=400)
    yld = pd.Series(0.0, index=efa.index)
    # Range that starts BEFORE SMA200 has settled
    result = run_efa_backtest(
        efa_minimal_config, efa, yld, efa.index[0], efa.index[250]
    )
    early_snaps = result.daily_values.iloc[:100]
    assert (early_snaps['n_positions'] == 0).all()
```

- [ ] **Step 2: Run + commit**

```bash
pytest hydra_backtest/efa/tests/test_engine.py -v
git add hydra_backtest/efa/tests/test_engine.py
git commit -m "test(hydra_backtest.efa): engine unit tests"
```

---

## Task 9: Validation unit tests

**File:** `hydra_backtest/efa/tests/test_validation.py` (NEW)

- [ ] **Step 1: Create test file**

```python
"""Unit tests for hydra_backtest.efa.validation."""
import numpy as np
import pandas as pd
import pytest

from hydra_backtest.efa.validation import run_efa_smoke_tests
from hydra_backtest.engine import BacktestResult
from hydra_backtest.errors import HydraBacktestValidationError


def _make_result(daily, trades=None) -> BacktestResult:
    if trades is None:
        trades = pd.DataFrame(columns=['symbol', 'exit_reason'])
    return BacktestResult(
        config={}, daily_values=daily, trades=trades, decisions=[],
        exit_events=[], universe_size={},
        started_at=pd.Timestamp.now(), finished_at=pd.Timestamp.now(),
        git_sha='test', data_inputs_hash='test',
    )


def _good_daily(n: int = 300) -> pd.DataFrame:
    np.random.seed(666)
    dates = pd.bdate_range('2020-01-01', periods=n)
    rets = 0.0003 + np.random.normal(0, 0.008, n)
    pv = 100_000.0 * np.cumprod(1 + rets)
    peak = np.maximum.accumulate(pv)
    drawdown = (pv - peak) / peak
    return pd.DataFrame({
        'date': dates,
        'portfolio_value': pv,
        'cash': [10_000.0] * n,
        'n_positions': [1] * n,
        'drawdown': drawdown,
    })


def test_smoke_passes_clean_result():
    run_efa_smoke_tests(_make_result(_good_daily()))


def test_smoke_fails_n_positions_over_max():
    daily = _good_daily()
    daily.loc[10, 'n_positions'] = 2
    with pytest.raises(HydraBacktestValidationError, match="n_positions out of"):
        run_efa_smoke_tests(_make_result(daily))


def test_smoke_fails_invalid_exit_reason():
    daily = _good_daily()
    trades = pd.DataFrame([{'symbol': 'EFA', 'exit_reason': 'COMPASS_STOP'}])
    with pytest.raises(HydraBacktestValidationError, match="Invalid EFA exit reasons"):
        run_efa_smoke_tests(_make_result(daily, trades))


def test_smoke_accepts_valid_exit_reasons():
    daily = _good_daily()
    trades = pd.DataFrame([
        {'symbol': 'EFA', 'exit_reason': 'EFA_BELOW_SMA200'},
        {'symbol': 'EFA', 'exit_reason': 'EFA_BACKTEST_END'},
    ])
    run_efa_smoke_tests(_make_result(daily, trades))


def test_smoke_fails_negative_cash():
    daily = _good_daily()
    daily.loc[5, 'cash'] = -10.0
    with pytest.raises(HydraBacktestValidationError, match="Cash < -1.0"):
        run_efa_smoke_tests(_make_result(daily))


def test_smoke_fails_drawdown_out_of_range():
    daily = _good_daily()
    daily.loc[5, 'drawdown'] = 0.5
    with pytest.raises(HydraBacktestValidationError, match="Drawdown out of"):
        run_efa_smoke_tests(_make_result(daily))


def test_smoke_fails_empty_daily():
    empty = pd.DataFrame(columns=['date', 'portfolio_value', 'cash',
                                   'n_positions', 'drawdown'])
    with pytest.raises(HydraBacktestValidationError, match="empty daily_values"):
        run_efa_smoke_tests(_make_result(empty))


def test_smoke_fails_outlier_return():
    daily = _good_daily()
    daily.loc[50, 'portfolio_value'] = daily.loc[49, 'portfolio_value'] * 1.20
    with pytest.raises(HydraBacktestValidationError, match="Outlier daily return"):
        run_efa_smoke_tests(_make_result(daily))
```

- [ ] **Step 2: Run + commit**

```bash
pytest hydra_backtest/efa/tests/test_validation.py -v
git add hydra_backtest/efa/tests/test_validation.py
git commit -m "test(hydra_backtest.efa): validation unit tests"
```

---

## Task 10: CLI entrypoint

**File:** `hydra_backtest/efa/__main__.py` (NEW)

- [ ] **Step 1: Create the CLI**

Mirrors Catalyst's `__main__.py` shape but with the simpler EFA signature (one pickle, no PIT, no SPY, no VIX).

```python
"""CLI entrypoint: python -m hydra_backtest.efa

Loads EFA OHLCV pickle, runs 3 EFA backtest tiers (baseline + T-bill +
next-open), post-processes for slippage tier, writes CSV + JSON outputs,
and prints a waterfall summary.
"""
import argparse
import os
import sys

import pandas as pd

from hydra_backtest import (
    build_waterfall,
    format_summary_table,
    load_efa_series,
    load_yield_series,
    write_daily_csv,
    write_trades_csv,
    write_waterfall_json,
)
from hydra_backtest.efa import (
    run_efa_backtest,
    run_efa_smoke_tests,
)


_CONFIG = {
    'INITIAL_CAPITAL': 100_000,
    'COMMISSION_PER_SHARE': 0.0035,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog='python -m hydra_backtest.efa',
        description='Reproducible EFA passive international trend standalone backtest.',
    )
    parser.add_argument('--start', type=str, default='2000-01-01')
    parser.add_argument('--end', type=str, default='2026-03-05')
    parser.add_argument('--out-dir', type=str, default='backtests/efa_v1')
    parser.add_argument('--efa', type=str, default='data_cache/efa_history.pkl')
    parser.add_argument('--aaa', type=str, default='data_cache/moody_aaa_yield.csv')
    parser.add_argument('--tbill', type=str, default='data_cache/tbill_3m_fred.csv')
    parser.add_argument('--aaa-date-col', type=str, default='observation_date')
    parser.add_argument('--aaa-value-col', type=str, default='yield_pct')
    parser.add_argument('--tbill-date-col', type=str, default='DATE')
    parser.add_argument('--tbill-value-col', type=str, default='DGS3MO')
    parser.add_argument('--slippage-bps', type=float, default=2.0)
    parser.add_argument('--half-spread-bps', type=float, default=0.5)
    parser.add_argument('--t-bill-rf', type=float, default=0.03)
    args = parser.parse_args(argv)

    print("Loading data...", flush=True)
    efa_data = load_efa_series(args.efa)
    aaa_yield = load_yield_series(
        args.aaa, date_col=args.aaa_date_col, value_col=args.aaa_value_col,
    )
    tbill_yield = load_yield_series(
        args.tbill, date_col=args.tbill_date_col, value_col=args.tbill_value_col,
    )
    print(
        f"  EFA: {len(efa_data)} rows ({efa_data.index.min().date()} → "
        f"{efa_data.index.max().date()})",
        flush=True,
    )

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)

    def _make_progress_cb(tier_name):
        def _cb(info):
            print(
                f"  [{tier_name}] {info['year']}: {info['progress_pct']:5.1f}% | "
                f"portfolio ${info['portfolio_value']:>12,.0f} | "
                f"{info['n_positions']} positions",
                flush=True,
            )
        return _cb

    print("\nTier 0: baseline (Aaa cash, same-close exec)", flush=True)
    tier_0 = run_efa_backtest(
        config=_CONFIG, efa_data=efa_data, cash_yield_daily=aaa_yield,
        start_date=start, end_date=end, execution_mode='same_close',
        progress_callback=_make_progress_cb('tier0'),
    )
    run_efa_smoke_tests(tier_0)
    print("  tier 0 smoke tests: PASSED", flush=True)

    print("\nTier 1: + T-bill cash yield", flush=True)
    tier_1 = run_efa_backtest(
        config=_CONFIG, efa_data=efa_data, cash_yield_daily=tbill_yield,
        start_date=start, end_date=end, execution_mode='same_close',
        progress_callback=_make_progress_cb('tier1'),
    )
    run_efa_smoke_tests(tier_1)
    print("  tier 1 smoke tests: PASSED", flush=True)

    print("\nTier 2: + next-open execution", flush=True)
    tier_2 = run_efa_backtest(
        config=_CONFIG, efa_data=efa_data, cash_yield_daily=tbill_yield,
        start_date=start, end_date=end, execution_mode='next_open',
        progress_callback=_make_progress_cb('tier2'),
    )
    run_efa_smoke_tests(tier_2)
    print("  tier 2 smoke tests: PASSED", flush=True)

    print("\nBuilding waterfall...", flush=True)
    report = build_waterfall(
        tier_0=tier_0, tier_1=tier_1, tier_2=tier_2,
        t_bill_rf=args.t_bill_rf,
        slippage_bps=args.slippage_bps,
        half_spread_bps=args.half_spread_bps,
    )

    os.makedirs(args.out_dir, exist_ok=True)
    write_daily_csv(tier_0, os.path.join(args.out_dir, 'efa_v2_daily.csv'))
    write_trades_csv(tier_0, os.path.join(args.out_dir, 'efa_v2_trades.csv'))
    write_waterfall_json(report, os.path.join(args.out_dir, 'efa_v2_waterfall.json'))

    print('\n' + format_summary_table(report), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: `--help` smoke test**

```bash
python -m hydra_backtest.efa --help
```

- [ ] **Step 3: Commit**

```bash
git add hydra_backtest/efa/__main__.py
git commit -m "feat(hydra_backtest.efa): CLI entrypoint"
```

---

## Task 11: Integration test (CLI smoke)

**File:** `hydra_backtest/efa/tests/test_integration.py` (NEW)

- [ ] **Step 1: Create test**

```python
"""CLI smoke test for hydra_backtest.efa."""
import json
import pickle
import subprocess
import sys

import numpy as np
import pandas as pd


def _make_synth_efa(n_days: int = 300) -> pd.DataFrame:
    np.random.seed(666)
    dates = pd.bdate_range('2020-01-01', periods=n_days)
    rets = 0.0004 + np.random.normal(0, 0.008, n_days)
    closes = 50.0 * np.cumprod(1 + rets)
    return pd.DataFrame(
        {'Open': closes, 'High': closes * 1.005, 'Low': closes * 0.995,
         'Close': closes, 'Volume': 1_000_000},
        index=dates,
    )


def test_cli_runs_end_to_end(tmp_path):
    efa = _make_synth_efa()
    pkl = tmp_path / 'efa_history.pkl'
    with open(pkl, 'wb') as f:
        pickle.dump(efa, f)

    dates = pd.bdate_range('2020-01-01', periods=300)
    aaa_csv = tmp_path / 'aaa.csv'
    pd.DataFrame(
        {'observation_date': dates, 'yield_pct': [4.5] * len(dates)}
    ).to_csv(aaa_csv, index=False)
    tbill_csv = tmp_path / 'tbill.csv'
    pd.DataFrame(
        {'DATE': dates, 'DGS3MO': [3.5] * len(dates)}
    ).to_csv(tbill_csv, index=False)

    out_dir = tmp_path / 'out'
    cmd = [
        sys.executable, '-m', 'hydra_backtest.efa',
        '--start', '2020-12-01',
        '--end', '2021-02-26',
        '--out-dir', str(out_dir),
        '--efa', str(pkl),
        '--aaa', str(aaa_csv),
        '--tbill', str(tbill_csv),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, (
        f"CLI failed:\nstdout=\n{res.stdout}\nstderr=\n{res.stderr}"
    )

    assert (out_dir / 'efa_v2_daily.csv').exists()
    assert (out_dir / 'efa_v2_trades.csv').exists()
    assert (out_dir / 'efa_v2_waterfall.json').exists()

    with open(out_dir / 'efa_v2_waterfall.json') as f:
        wf = json.load(f)
    tier_names = [t['name'] for t in wf['tiers']]
    assert 'baseline' in tier_names
    assert 'net_honest' in tier_names
```

- [ ] **Step 2: Run + commit**

```bash
pytest hydra_backtest/efa/tests/test_integration.py -v
git add hydra_backtest/efa/tests/test_integration.py
git commit -m "test(hydra_backtest.efa): CLI integration smoke"
```

---

## Task 12: E2E tests (slow, real data)

**File:** `hydra_backtest/efa/tests/test_e2e.py` (NEW)

- [ ] **Step 1: Create test**

```python
"""End-to-end EFA backtest with real data. Slow, requires data_cache/."""
from pathlib import Path

import pandas as pd
import pytest

from hydra_backtest.efa import run_efa_backtest, run_efa_smoke_tests
from hydra_backtest.data import load_efa_series, load_yield_series

DATA_PKL = Path('data_cache/efa_history.pkl')
AAA_CSV = Path('data_cache/moody_aaa_yield.csv')


def _load_inputs():
    efa_data = load_efa_series(str(DATA_PKL))
    aaa = load_yield_series(
        str(AAA_CSV), date_col='observation_date', value_col='yield_pct'
    )
    aaa_daily = aaa.reindex(efa_data.index).ffill().fillna(0.0)
    return efa_data, aaa_daily


@pytest.mark.slow
@pytest.mark.skipif(not DATA_PKL.exists(),
                    reason="data_cache/efa_history.pkl not built (Task 14)")
@pytest.mark.skipif(not AAA_CSV.exists(),
                    reason="data_cache/moody_aaa_yield.csv missing")
def test_e2e_2year_window():
    efa_data, aaa_daily = _load_inputs()
    config = {'INITIAL_CAPITAL': 100_000.0, 'COMMISSION_PER_SHARE': 0.0035}
    result = run_efa_backtest(
        config, efa_data, aaa_daily,
        pd.Timestamp('2020-01-01'), pd.Timestamp('2021-12-31'),
        execution_mode='same_close',
    )
    run_efa_smoke_tests(result)
    assert len(result.daily_values) > 100
    assert (result.daily_values['n_positions'] >= 0).all()
    assert (result.daily_values['n_positions'] <= 1).all()


@pytest.mark.slow
@pytest.mark.skipif(not DATA_PKL.exists(),
                    reason="data_cache/efa_history.pkl not built (Task 14)")
@pytest.mark.skipif(not AAA_CSV.exists(),
                    reason="data_cache/moody_aaa_yield.csv missing")
def test_e2e_determinism():
    efa_data, aaa_daily = _load_inputs()
    config = {'INITIAL_CAPITAL': 100_000.0, 'COMMISSION_PER_SHARE': 0.0035}
    r1 = run_efa_backtest(
        config, efa_data, aaa_daily,
        pd.Timestamp('2020-01-01'), pd.Timestamp('2020-12-31'),
    )
    r2 = run_efa_backtest(
        config, efa_data, aaa_daily,
        pd.Timestamp('2020-01-01'), pd.Timestamp('2020-12-31'),
    )
    pd.testing.assert_frame_equal(r1.daily_values, r2.daily_values)
    pd.testing.assert_frame_equal(r1.trades, r2.trades)
```

- [ ] **Step 2: Commit (will skip until Task 14)**

```bash
git add hydra_backtest/efa/tests/test_e2e.py
git commit -m "test(hydra_backtest.efa): E2E tests (slow, real data)"
```

---

## Task 13: README

**File:** `hydra_backtest/efa/README.md` (NEW)

Sections to include (model after `hydra_backtest/catalyst/README.md`):

1. **Overview** — fourth and last standalone pillar; single-asset (EFA); SMA200 regime gate; no rebalance cadence.
2. **Strategy in one paragraph** — long when above SMA200, cash otherwise; never partial.
3. **How to run** — full CLI example.
4. **Data prerequisites** — yfinance one-shot download snippet.
5. **Architecture** — sub-package layout, reuse table.
6. **Layer A invariants** — list of 8 checks.
7. **v1.3 limitations** — no HCM, no reverse-flow liquidation, no min-buy threshold, no 90% cap, no asset proxy for pre-inception, no Layer B/C.
8. **Inline strategy note** — explains why EFA does NOT import from a live module (no pure function exists; constants duplicated as the only contract surface).
9. **Roadmap** — pointer to v1.4 / v1.5.

- [ ] **Step 1: Write the README**
- [ ] **Step 2: Commit**

```bash
git add hydra_backtest/efa/README.md
git commit -m "docs(hydra_backtest.efa): README"
```

---

## Task 14: CI integration

**File:** `.github/workflows/test.yml` (modify)

- [ ] **Step 1: Add EFA pytest step right after the Catalyst one**

```yaml
      - name: Test hydra_backtest.efa sub-package
        run: >
          pytest hydra_backtest/efa/tests/ -v --tb=short
          --cov=hydra_backtest.efa
          --cov-report=term-missing
          -m "not slow"
```

- [ ] **Step 2: YAML lint + commit**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml'))" && echo OK
git add .github/workflows/test.yml
git commit -m "ci(hydra_backtest.efa): add CI step for efa tests"
```

---

## Task 15: EFA history download (one-time, NOT a code task)

**Manual data prep step. No git commit.**

- [ ] **Step 1: Run the download**

```python
import pickle
import pandas as pd
import yfinance as yf

df = yf.download('EFA', start='1999-01-01', end='2027-01-01',
                 auto_adjust=True, progress=False)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.droplevel(1)
print(f'EFA: {len(df)} rows, {df.index.min().date()} → {df.index.max().date()}')

with open('data_cache/efa_history.pkl', 'wb') as f:
    pickle.dump(df, f)
print('Saved data_cache/efa_history.pkl')
```

- [ ] **Step 2: Verify loader accepts it**

```bash
python -c "from hydra_backtest.data import load_efa_series; df = load_efa_series('data_cache/efa_history.pkl'); print(df.shape, df.index.min().date(), '→', df.index.max().date())"
```

- [ ] **Step 3: Run the now-unblocked E2E tests**

```bash
pytest hydra_backtest/efa/tests/test_e2e.py -v -m "slow"
```

> **Note:** `data_cache/efa_history.pkl` is gitignored. Treat this as a local prerequisite for the official run in Task 16 — CI does not need it.

---

## Task 16: Run the official 2000-2026 backtest

- [ ] **Step 1: Run the CLI**

```bash
mkdir -p backtests/efa_v1
python -m hydra_backtest.efa \
    --start 2000-01-01 \
    --end 2026-03-05 \
    --out-dir backtests/efa_v1 2>&1 | tee backtests/efa_v1/run.log
```

Expected runtime: ~30-60 seconds (fastest pillar).

- [ ] **Step 2: Verify outputs**

```bash
ls -la backtests/efa_v1/
python -c "
import pandas as pd, json
d = pd.read_csv('backtests/efa_v1/efa_v2_daily.csv')
t = pd.read_csv('backtests/efa_v1/efa_v2_trades.csv')
w = json.load(open('backtests/efa_v1/efa_v2_waterfall.json'))
print(f'daily: {d.shape}, trades: {t.shape}')
print(f'tiers: {[tt[\"name\"] for tt in w[\"tiers\"]]}')
"
```

- [ ] **Step 3: Determinism check**

```bash
cp backtests/efa_v1/efa_v2_daily.csv /tmp/efa_run1.csv
python -m hydra_backtest.efa --start 2000-01-01 --end 2026-03-05 --out-dir backtests/efa_v1 > /dev/null 2>&1
diff -q /tmp/efa_run1.csv backtests/efa_v1/efa_v2_daily.csv && echo "DETERMINISTIC ✅"
```

- [ ] **Step 4: Commit official outputs + push**

```bash
git add backtests/efa_v1/
git commit -m "feat(hydra_backtest.efa): v1.3 official 2000-2026 results"
git push
```

- [ ] **Step 5: Update memory** with final NET HONEST CAGR/Sharpe/MaxDD from waterfall.

---

## Success criteria (from spec §14)

v1.3 is complete when ALL of these are true:

1. ☐ `python -m hydra_backtest.efa --start 2000-01-01 --end 2026-03-05 ...` runs to completion
2. ☐ Two consecutive runs produce byte-identical `efa_v2_daily.csv`
3. ☐ All Layer A smoke tests pass for all 3 tier runs
4. ☐ Coverage ≥ 80% for `hydra_backtest/efa/`
5. ☐ v1.0 + v1.1 + v1.2 test suites remain green
6. ☐ Waterfall report prints 5 tiers
7. ☐ Pre-inception (before 2001-08-17) snapshots show `n_positions == 0`
8. ☐ Buy-and-hold sanity test: always-uptrend run produces a single trade
   record (the synthetic-end exit)

---

## Risks & open questions

| Risk | Mitigation |
|---|---|
| EFA inception 2001-08-17 means 2000-2002 is all-cash → drags reported CAGR | Expected; spec §6.5 explicitly accepts this. The waterfall metric is computed on daily PV including cash periods. |
| Buying with 100% of cash on a single ticker causes commission rounding edge cases (e.g. cash insufficient by $0.01 after commission) | Engine recomputes affordable shares with `int(...)` and checks `cost + commission ≤ cash` before deploying. Smoke test verifies cash floor never < -1.0. |
| Constant duplication (`EFA_SYMBOL`, `EFA_SMA_PERIOD`) drifts from live | README documents the duplication. v1.4 (HYDRA full integration) will resolve this when it imports from live modules wholesale. |
| Determinism failure from synthetic-end exit when `EFA_SYMBOL` not in `state.positions` | The if-guard `if EFA_SYMBOL in state.positions and dates_in_range:` covers it; same pattern as Catalyst T15. |
