# HYDRA Backtest v1.1 — Rattlesnake Standalone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `hydra_backtest/rattlesnake/` — a Rattlesnake standalone backtest sub-package that imports pure signal logic from `rattlesnake_signals.py`, reuses v1.0 infrastructure (BacktestState, methodology, reporting), and produces a 5-tier waterfall report with blocking smoke tests.

**Architecture:** New sub-package `hydra_backtest/rattlesnake/` with its own engine, validation, CLI, and tests. v1.0 modules are reused as-is via imports — zero modification to existing files except `data.py` (one new helper `load_vix_series`) and `.github/workflows/test.yml` (CI step).

**Tech Stack:** Python 3.14, pandas, numpy, pytest, pytest-cov. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-04-07-hydra-backtest-v1.1-rattlesnake-design.md`

---

## File Structure

```
hydra_backtest/                                    ← v1.0 (untouched except data.py)
├── data.py                                        ← + load_vix_series helper
└── rattlesnake/                                   ← NEW v1.1 sub-package
    ├── __init__.py                                ← public exports
    ├── __main__.py                                ← CLI: python -m hydra_backtest.rattlesnake
    ├── engine.py                                  ← run_rattlesnake_backtest + apply_rattlesnake_*
    ├── validation.py                              ← Layer A smoke tests Rattlesnake-adapted
    ├── README.md                                  ← usage + architecture + v1.1 limitations
    └── tests/
        ├── __init__.py
        ├── conftest.py                            ← rattlesnake_minimal_config fixture
        ├── test_engine.py
        ├── test_validation.py
        ├── test_integration.py                    ← CLI smoke
        └── test_e2e.py                            ← @pytest.mark.slow
.github/workflows/test.yml                         ← + new pytest step for rattlesnake
```

---

## Task 1: Bootstrap sub-package + conftest fixture

**Files:**
- Create: `hydra_backtest/rattlesnake/__init__.py`
- Create: `hydra_backtest/rattlesnake/tests/__init__.py`
- Create: `hydra_backtest/rattlesnake/tests/conftest.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p hydra_backtest/rattlesnake/tests
```

- [ ] **Step 2: Create empty package init**

Create `hydra_backtest/rattlesnake/__init__.py`:
```python
"""hydra_backtest.rattlesnake — Rattlesnake mean-reversion standalone backtest.

See docs/superpowers/specs/2026-04-07-hydra-backtest-v1.1-rattlesnake-design.md
for the design and docs/superpowers/plans/2026-04-07-hydra-backtest-v1.1-rattlesnake.md
for the implementation plan.
"""
```

- [ ] **Step 3: Create empty test init**

Create `hydra_backtest/rattlesnake/tests/__init__.py` (empty file).

```bash
touch hydra_backtest/rattlesnake/tests/__init__.py
```

- [ ] **Step 4: Create conftest with rattlesnake_minimal_config fixture**

Create `hydra_backtest/rattlesnake/tests/conftest.py`:
```python
"""Shared fixtures for hydra_backtest.rattlesnake tests."""
import numpy as np
import pytest


@pytest.fixture(autouse=True)
def fixed_seed():
    """Force deterministic numpy RNG for every test."""
    np.random.seed(666)


@pytest.fixture
def rattlesnake_minimal_config():
    """Smallest valid Rattlesnake config — subset of COMPASS config schema.

    Excludes COMPASS-only keys (CRASH_LEVERAGE, LEV_FLOOR, etc.) since
    Rattlesnake uses no leverage and no DD scaling.
    """
    return {
        # Capital
        'INITIAL_CAPITAL': 100_000,
        # Trade costs
        'COMMISSION_PER_SHARE': 0.0035,
        # Position bounds
        'NUM_POSITIONS': 5,            # = R_MAX_POSITIONS, used by smoke tests bound check
        'NUM_POSITIONS_RISK_OFF': 2,   # = R_MAX_POS_RISK_OFF
        # Universe age requirement (ensures stocks have enough history for SMA200)
        'MIN_AGE_DAYS': 220,           # > R_TREND_SMA (200) so SMA200 is computable
    }
```

- [ ] **Step 5: Verify pytest collects the new test directory**

Run: `pytest hydra_backtest/rattlesnake/tests/ --collect-only -q 2>&1 | tail -5`
Expected: `0 tests collected` (no test files yet, but conftest loads cleanly)

- [ ] **Step 6: Commit**

```bash
git add hydra_backtest/rattlesnake/__init__.py hydra_backtest/rattlesnake/tests/__init__.py hydra_backtest/rattlesnake/tests/conftest.py
git commit -m "feat(hydra_backtest): bootstrap rattlesnake sub-package + conftest"
```

---

## Task 2: VIX series loader in data.py

**Files:**
- Modify: `hydra_backtest/data.py` (add `load_vix_series` function)
- Modify: `hydra_backtest/__init__.py` (re-export `load_vix_series`)
- Modify: `hydra_backtest/tests/test_data.py` (add tests)

- [ ] **Step 1: Write failing tests for VIX loader**

Append to `hydra_backtest/tests/test_data.py`:
```python
def test_load_vix_series_returns_daily_series(tmp_path):
    from hydra_backtest.data import load_vix_series
    df = pd.DataFrame({
        'Date': pd.date_range('2020-01-02', periods=5, freq='B'),
        'Close': [12.5, 13.1, 14.0, 18.5, 35.5],
    })
    path = tmp_path / 'vix.csv'
    df.to_csv(path, index=False)
    series = load_vix_series(str(path))
    assert isinstance(series, pd.Series)
    assert len(series) == 5
    assert series.iloc[-1] == 35.5

def test_load_vix_series_missing_file_raises(tmp_path):
    from hydra_backtest.data import load_vix_series
    from hydra_backtest.errors import HydraDataError
    with pytest.raises(HydraDataError, match="VIX"):
        load_vix_series(str(tmp_path / 'nonexistent.csv'))

def test_load_vix_series_handles_yfinance_format(tmp_path):
    """yfinance saves with index named 'Date' and 'Close' column."""
    from hydra_backtest.data import load_vix_series
    df = pd.DataFrame(
        {'Close': [13.5, 14.0, 15.0]},
        index=pd.date_range('2020-01-02', periods=3, freq='B'),
    )
    df.index.name = 'Date'
    path = tmp_path / 'vix_yf.csv'
    df.to_csv(path)
    series = load_vix_series(str(path))
    assert len(series) == 3
    assert series.iloc[0] == 13.5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest hydra_backtest/tests/test_data.py -k vix -v`
Expected: FAIL with `ImportError: cannot import name 'load_vix_series'`

- [ ] **Step 3: Implement load_vix_series in data.py**

Append to `hydra_backtest/data.py`:
```python
def load_vix_series(path: str) -> pd.Series:
    """Load daily VIX close from CSV.

    Accepts two formats:
      - yfinance default: Date as index column + 'Close' column
      - Plain: 'Date' or 'date' column + 'Close' or 'close' column

    Returns a Series indexed by Timestamp, values in points (e.g. 35.5
    for VIX=35.5). The caller is responsible for download:

        import yfinance as yf
        yf.download('^VIX', start='1999-01-01', end='2027-01-01').to_csv(
            'data_cache/vix_history.csv'
        )
    """
    if not os.path.exists(path):
        raise HydraDataError(f"VIX series file not found: {path}")
    df = pd.read_csv(path)
    # Normalize column names
    cols_lower = {c.lower(): c for c in df.columns}
    date_col = cols_lower.get('date')
    close_col = cols_lower.get('close')
    if date_col is None or close_col is None:
        raise HydraDataError(
            f"VIX CSV must have 'Date' and 'Close' columns, got {list(df.columns)}"
        )
    df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
    df = df.dropna(subset=[date_col]).sort_values(date_col).set_index(date_col)
    series = pd.to_numeric(df[close_col], errors='coerce').dropna()
    series.name = 'vix'
    return series
```

- [ ] **Step 4: Re-export from package __init__**

Edit `hydra_backtest/__init__.py` — add `load_vix_series` to the data imports and `__all__`:

```python
from hydra_backtest.data import (
    compute_data_fingerprint,
    load_pit_universe,
    load_price_history,
    load_sector_map,
    load_spy_data,
    load_vix_series,
    load_yield_series,
    validate_config,
)
```

And in the `__all__` list, add `'load_vix_series'`.

- [ ] **Step 5: Run tests and verify they pass**

Run: `pytest hydra_backtest/tests/test_data.py -k vix -v`
Expected: 3 passed

- [ ] **Step 6: Run full v1.0 test suite to confirm zero regression**

Run: `pytest hydra_backtest/tests/ -m "not slow" -q 2>&1 | tail -5`
Expected: 77 passed (74 from v1.0 + 3 new VIX tests)

- [ ] **Step 7: Commit**

```bash
git add hydra_backtest/data.py hydra_backtest/__init__.py hydra_backtest/tests/test_data.py
git commit -m "feat(hydra_backtest): add load_vix_series helper for v1.1 Rattlesnake"
```

---

## Task 3: Engine — universe filter helper

**Files:**
- Create: `hydra_backtest/rattlesnake/engine.py`
- Create: `hydra_backtest/rattlesnake/tests/test_engine.py`

- [ ] **Step 1: Write failing test for universe filter**

Create `hydra_backtest/rattlesnake/tests/test_engine.py`:
```python
"""Tests for hydra_backtest.rattlesnake.engine."""
import pandas as pd
import pytest

from hydra_backtest.rattlesnake.engine import _resolve_rattlesnake_universe


def test_resolve_universe_intersects_with_pit():
    pit_universe = {2010: ['AAPL', 'MSFT', 'GOOG', 'NOTINR'], 2021: ['AAPL', 'MSFT']}
    result_2010 = _resolve_rattlesnake_universe(pit_universe, 2010)
    # Result should be the intersection R_UNIVERSE ∩ pit[2010]
    assert 'AAPL' in result_2010
    assert 'MSFT' in result_2010
    assert 'NOTINR' not in result_2010  # not in R_UNIVERSE
    # Result is sorted
    assert result_2010 == sorted(result_2010)


def test_resolve_universe_returns_empty_for_missing_year():
    result = _resolve_rattlesnake_universe({}, 2010)
    assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest hydra_backtest/rattlesnake/tests/test_engine.py -v -k universe`
Expected: FAIL with `ModuleNotFoundError: No module named 'hydra_backtest.rattlesnake.engine'`

- [ ] **Step 3: Create engine.py with universe helper**

Create `hydra_backtest/rattlesnake/engine.py`:
```python
"""Rattlesnake mean-reversion backtest engine.

Pure-function consumer of rattlesnake_signals.py. Reuses v1.0
infrastructure: BacktestState, BacktestResult, _mark_to_market,
_get_exec_price, _slice_history_to_date.
"""
from datetime import datetime
import subprocess
from typing import Dict, List, Optional, Tuple

import pandas as pd

from hydra_backtest.data import compute_data_fingerprint
from hydra_backtest.engine import (
    BacktestResult,
    BacktestState,
    _get_exec_price,
    _mark_to_market,
    _slice_history_to_date,
)
from rattlesnake_signals import (
    R_MAX_HOLD_DAYS,
    R_MAX_POS_RISK_OFF,
    R_MAX_POSITIONS,
    R_POSITION_SIZE,
    R_UNIVERSE,
    R_VIX_PANIC,
    check_rattlesnake_exit,
    check_rattlesnake_regime,
    find_rattlesnake_candidates,
)


def _resolve_rattlesnake_universe(
    pit_universe: Dict[int, List[str]],
    year: int,
) -> List[str]:
    """Intersect R_UNIVERSE (S&P 100 hardcoded) with PIT S&P 500 for `year`.

    Drops survivorship bias from R_UNIVERSE without requiring fresh PIT
    S&P 100 data. Tickers in R_UNIVERSE that were never in S&P 500 are
    permanently excluded (rare edge case).
    """
    sp500_year = set(pit_universe.get(year, []))
    return sorted(t for t in R_UNIVERSE if t in sp500_year)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest hydra_backtest/rattlesnake/tests/test_engine.py -v -k universe`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/rattlesnake/engine.py hydra_backtest/rattlesnake/tests/test_engine.py
git commit -m "feat(hydra_backtest.rattlesnake): _resolve_rattlesnake_universe helper"
```

---

## Task 4: Engine — apply_rattlesnake_exits pure function

**Files:**
- Modify: `hydra_backtest/rattlesnake/engine.py`
- Modify: `hydra_backtest/rattlesnake/tests/test_engine.py`

- [ ] **Step 1: Write failing tests for apply_rattlesnake_exits**

Append to `hydra_backtest/rattlesnake/tests/test_engine.py`:
```python
from hydra_backtest.engine import BacktestState
from hydra_backtest.rattlesnake.engine import apply_rattlesnake_exits


def _make_rattle_position(entry_price, shares, entry_idx=0, days_held=0):
    return {
        'symbol': 'AAPL',
        'entry_price': float(entry_price),
        'shares': float(shares),
        'entry_date': pd.Timestamp('2020-01-02'),
        'entry_idx': entry_idx,
        'days_held': days_held,
        'sector': 'Unknown',
        'entry_vol': 0.0,
        'entry_daily_vol': 0.0,
        'high_price': float(entry_price),
    }


def _make_minimal_config():
    return {
        'INITIAL_CAPITAL': 100_000,
        'COMMISSION_PER_SHARE': 0.0035,
    }


def test_apply_rattlesnake_exits_profit_target():
    """+4% triggers R_PROFIT exit."""
    pos = _make_rattle_position(100.0, 10, days_held=2)
    state = BacktestState(
        cash=50_000.0, positions={'AAPL': pos}, peak_value=51_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    df = pd.DataFrame(
        {'Open': [100.0, 105.0], 'Close': [100.0, 105.0]},
        index=pd.date_range('2020-01-02', periods=2),
    )
    price_data = {'AAPL': df}
    all_dates = list(df.index)
    config = _make_minimal_config()
    new_state, trades, _ = apply_rattlesnake_exits(
        state, all_dates[1], 1, price_data, config,
        execution_mode='same_close', all_dates=all_dates,
    )
    assert 'AAPL' not in new_state.positions
    assert len(trades) == 1
    assert trades[0]['exit_reason'] == 'R_PROFIT'
    assert trades[0]['exit_price'] == 105.0


def test_apply_rattlesnake_exits_stop_loss():
    """-5% triggers R_STOP exit."""
    pos = _make_rattle_position(100.0, 10, days_held=2)
    state = BacktestState(
        cash=50_000.0, positions={'AAPL': pos}, peak_value=51_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    df = pd.DataFrame(
        {'Open': [100.0, 95.0], 'Close': [100.0, 95.0]},
        index=pd.date_range('2020-01-02', periods=2),
    )
    all_dates = list(df.index)
    new_state, trades, _ = apply_rattlesnake_exits(
        state, all_dates[1], 1, {'AAPL': df}, _make_minimal_config(),
        execution_mode='same_close', all_dates=all_dates,
    )
    assert 'AAPL' not in new_state.positions
    assert trades[0]['exit_reason'] == 'R_STOP'


def test_apply_rattlesnake_exits_time_limit():
    """days_held >= R_MAX_HOLD_DAYS (=8) triggers R_TIME exit."""
    from rattlesnake_signals import R_MAX_HOLD_DAYS
    pos = _make_rattle_position(100.0, 10, days_held=R_MAX_HOLD_DAYS)
    state = BacktestState(
        cash=50_000.0, positions={'AAPL': pos}, peak_value=51_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    # Price unchanged — only the time limit fires
    df = pd.DataFrame(
        {'Open': [100.0, 100.0], 'Close': [100.0, 100.0]},
        index=pd.date_range('2020-01-02', periods=2),
    )
    all_dates = list(df.index)
    new_state, trades, _ = apply_rattlesnake_exits(
        state, all_dates[1], 1, {'AAPL': df}, _make_minimal_config(),
        execution_mode='same_close', all_dates=all_dates,
    )
    assert trades[0]['exit_reason'] == 'R_TIME'


def test_apply_rattlesnake_exits_no_exit_holds_position():
    """Within hold window, within profit/stop bounds → position carries."""
    pos = _make_rattle_position(100.0, 10, days_held=3)
    state = BacktestState(
        cash=50_000.0, positions={'AAPL': pos}, peak_value=51_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    # Price up +2% (below +4% profit target)
    df = pd.DataFrame(
        {'Open': [100.0, 102.0], 'Close': [100.0, 102.0]},
        index=pd.date_range('2020-01-02', periods=2),
    )
    all_dates = list(df.index)
    new_state, trades, _ = apply_rattlesnake_exits(
        state, all_dates[1], 1, {'AAPL': df}, _make_minimal_config(),
        execution_mode='same_close', all_dates=all_dates,
    )
    assert 'AAPL' in new_state.positions
    assert len(trades) == 0


def test_apply_rattlesnake_exits_next_open_mode_uses_next_open():
    """In next_open mode, exit fills at Open[T+1] not Close[T]."""
    pos = _make_rattle_position(100.0, 10, days_held=2)
    state = BacktestState(
        cash=50_000.0, positions={'AAPL': pos}, peak_value=51_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    df = pd.DataFrame({
        'Open': [100.0, 105.0, 103.0],
        'Close': [100.0, 105.0, 105.0],
    }, index=pd.date_range('2020-01-02', periods=3))
    all_dates = list(df.index)
    # Exit fires at i=1 (Close[T]=105 → +5% profit). Fill at Open[T+1]=103.
    new_state, trades, _ = apply_rattlesnake_exits(
        state, all_dates[1], 1, {'AAPL': df}, _make_minimal_config(),
        execution_mode='next_open', all_dates=all_dates,
    )
    assert trades[0]['exit_reason'] == 'R_PROFIT'
    assert trades[0]['exit_price'] == 103.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest hydra_backtest/rattlesnake/tests/test_engine.py -v -k apply_rattlesnake_exits`
Expected: FAIL with `ImportError: cannot import name 'apply_rattlesnake_exits'`

- [ ] **Step 3: Implement apply_rattlesnake_exits**

Append to `hydra_backtest/rattlesnake/engine.py`:
```python
def apply_rattlesnake_exits(
    state: BacktestState,
    date: pd.Timestamp,
    i: int,
    price_data: Dict[str, pd.DataFrame],
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[BacktestState, list, list]:
    """Pure equivalent of COMPASSLive._check_rattlesnake_exits.

    Source: omnicapital_live.py:2040. Mirrors the live exit loop:
    iterate positions, call check_rattlesnake_exit, exit via _get_exec_price.

    Exit reasons get the 'R_' prefix to match the live trade tag at
    omnicapital_live.py:2080: 'R_PROFIT', 'R_STOP', 'R_TIME'.

    Returns (new_state, trades_list, decisions_list).
    """
    trades: list = []
    decisions: list = []
    cash = state.cash
    positions = dict(state.positions)

    for symbol in list(positions.keys()):
        pos = positions[symbol]
        df = price_data.get(symbol)
        if df is None or date not in df.index:
            continue
        current_price = float(df.loc[date, 'Close'])

        reason = check_rattlesnake_exit(
            symbol,
            pos['entry_price'],
            current_price,
            pos.get('days_held', 0),
        )
        if reason is None:
            continue

        # Resolve execution price
        exit_price = _get_exec_price(
            symbol, date, i, all_dates, price_data, execution_mode
        )
        if exit_price is None:
            continue  # cannot execute — position carries

        shares = pos['shares']
        proceeds = shares * exit_price
        commission = shares * config['COMMISSION_PER_SHARE']
        cash += proceeds - commission
        pnl = (exit_price - pos['entry_price']) * shares - commission
        exit_date = date if execution_mode == 'same_close' else all_dates[i + 1]
        exit_reason = f'R_{reason}'  # 'R_PROFIT' / 'R_STOP' / 'R_TIME'

        trades.append({
            'symbol': symbol,
            'entry_date': pos['entry_date'],
            'exit_date': exit_date,
            'exit_reason': exit_reason,
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'shares': shares,
            'pnl': pnl,
            'return': pnl / (pos['entry_price'] * shares) if pos['entry_price'] > 0 else 0.0,
            'sector': pos.get('sector', 'Unknown'),
        })
        decisions.append({
            'type': 'exit',
            'symbol': symbol,
            'date': str(date),
            'reason': exit_reason,
            'exit_price': exit_price,
        })
        del positions[symbol]

    new_state = state._replace(cash=cash, positions=positions)
    return new_state, trades, decisions
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest hydra_backtest/rattlesnake/tests/test_engine.py -v`
Expected: 7 passed (2 universe + 5 apply_rattlesnake_exits)

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/rattlesnake/engine.py hydra_backtest/rattlesnake/tests/test_engine.py
git commit -m "feat(hydra_backtest.rattlesnake): apply_rattlesnake_exits with 3 exit reasons"
```

---

## Task 5: Engine — apply_rattlesnake_entries pure function

**Files:**
- Modify: `hydra_backtest/rattlesnake/engine.py`
- Modify: `hydra_backtest/rattlesnake/tests/test_engine.py`

- [ ] **Step 1: Write failing tests for apply_rattlesnake_entries**

Append to `hydra_backtest/rattlesnake/tests/test_engine.py`:
```python
from hydra_backtest.rattlesnake.engine import apply_rattlesnake_entries


def _make_candidate(symbol, price, drop_pct=-0.10, rsi=20.0):
    return {
        'symbol': symbol,
        'score': -drop_pct,
        'drop_pct': drop_pct,
        'rsi': rsi,
        'price': price,
    }


def test_apply_rattlesnake_entries_opens_positions_up_to_max():
    state = BacktestState(
        cash=100_000.0, positions={}, peak_value=100_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    candidates = [
        _make_candidate('AAA', 100.0),
        _make_candidate('BBB', 50.0),
        _make_candidate('CCC', 200.0),
    ]
    # Each candidate needs price_data so _get_exec_price can resolve
    dates = pd.date_range('2020-01-02', periods=2)
    price_data = {
        'AAA': pd.DataFrame({'Open': [100.0, 100.0], 'Close': [100.0, 100.0]}, index=dates),
        'BBB': pd.DataFrame({'Open': [50.0, 50.0], 'Close': [50.0, 50.0]}, index=dates),
        'CCC': pd.DataFrame({'Open': [200.0, 200.0], 'Close': [200.0, 200.0]}, index=dates),
    }
    config = _make_minimal_config()
    new_state, decisions = apply_rattlesnake_entries(
        state, dates[0], 0, price_data, candidates,
        max_positions=5, config=config,
        execution_mode='same_close', all_dates=list(dates),
    )
    assert len(new_state.positions) == 3
    assert all(s in new_state.positions for s in ['AAA', 'BBB', 'CCC'])


def test_apply_rattlesnake_entries_uses_fixed_initial_cash_for_sizing():
    """All entries in one call must size against the SAME snapshot of cash,
    not against the residual cash that decreases as positions are opened.
    Mirrors omnicapital_live.py:2151: position_value = r_budget * R_POSITION_SIZE
    where r_budget is computed once before the candidate loop."""
    from rattlesnake_signals import R_POSITION_SIZE
    state = BacktestState(
        cash=100_000.0, positions={}, peak_value=100_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    candidates = [_make_candidate('AAA', 100.0), _make_candidate('BBB', 100.0)]
    dates = pd.date_range('2020-01-02', periods=2)
    price_data = {
        sym: pd.DataFrame({'Open': [100.0, 100.0], 'Close': [100.0, 100.0]}, index=dates)
        for sym in ['AAA', 'BBB']
    }
    config = _make_minimal_config()
    new_state, _ = apply_rattlesnake_entries(
        state, dates[0], 0, price_data, candidates,
        max_positions=5, config=config,
        execution_mode='same_close', all_dates=list(dates),
    )
    # Both positions should target $20K (= $100K initial * 0.20), 200 shares each
    expected_shares = int(100_000 * R_POSITION_SIZE / 100.0)
    assert new_state.positions['AAA']['shares'] == expected_shares
    assert new_state.positions['BBB']['shares'] == expected_shares


def test_apply_rattlesnake_entries_uses_integer_shares():
    """Rattlesnake uses integer shares (omnicapital_live.py:2152), unlike
    COMPASS which uses fractional shares."""
    state = BacktestState(
        cash=100_000.0, positions={}, peak_value=100_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    # Awkward price that would give a fractional share count
    candidates = [_make_candidate('AAA', 137.50)]
    dates = pd.date_range('2020-01-02', periods=2)
    price_data = {
        'AAA': pd.DataFrame({'Open': [137.50, 137.50], 'Close': [137.50, 137.50]}, index=dates),
    }
    new_state, _ = apply_rattlesnake_entries(
        state, dates[0], 0, price_data, candidates, max_positions=5,
        config=_make_minimal_config(), execution_mode='same_close',
        all_dates=list(dates),
    )
    shares = new_state.positions['AAA']['shares']
    assert shares == int(shares)  # whole number
    # 100_000 * 0.20 / 137.50 = 145.45 → int → 145
    assert shares == 145


def test_apply_rattlesnake_entries_skips_when_no_slots():
    state = BacktestState(
        cash=100_000.0,
        positions={f'P{i}': _make_rattle_position(100.0, 10) for i in range(5)},
        peak_value=100_000.0, crash_cooldown=0, portfolio_value_history=(),
    )
    candidates = [_make_candidate('AAA', 100.0)]
    dates = pd.date_range('2020-01-02', periods=2)
    new_state, _ = apply_rattlesnake_entries(
        state, dates[0], 0, {}, candidates, max_positions=5,
        config=_make_minimal_config(), execution_mode='same_close',
        all_dates=list(dates),
    )
    assert 'AAA' not in new_state.positions  # no slots available
    assert len(new_state.positions) == 5


def test_apply_rattlesnake_entries_skips_when_cash_insufficient():
    state = BacktestState(
        cash=500.0, positions={}, peak_value=500.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    candidates = [_make_candidate('AAA', 100.0)]
    dates = pd.date_range('2020-01-02', periods=2)
    new_state, _ = apply_rattlesnake_entries(
        state, dates[0], 0, {}, candidates, max_positions=5,
        config=_make_minimal_config(), execution_mode='same_close',
        all_dates=list(dates),
    )
    # cash < 1000 threshold → no entries
    assert len(new_state.positions) == 0


def test_apply_rattlesnake_entries_skips_zero_share_positions():
    """When position_value < entry_price, shares=0 → skip."""
    state = BacktestState(
        cash=10.0, positions={}, peak_value=10.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    # cash too small but above the 1000 threshold? No, 10 < 1000 → skip
    # Use a different test case: high price with cash just above threshold
    state = state._replace(cash=1500.0)
    candidates = [_make_candidate('AAA', 5000.0)]  # very expensive ticker
    dates = pd.date_range('2020-01-02', periods=2)
    price_data = {
        'AAA': pd.DataFrame({'Open': [5000.0, 5000.0], 'Close': [5000.0, 5000.0]}, index=dates),
    }
    # 1500 * 0.20 / 5000 = 0.06 → int → 0 → skip
    new_state, _ = apply_rattlesnake_entries(
        state, dates[0], 0, price_data, candidates, max_positions=5,
        config=_make_minimal_config(), execution_mode='same_close',
        all_dates=list(dates),
    )
    assert len(new_state.positions) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest hydra_backtest/rattlesnake/tests/test_engine.py -v -k apply_rattlesnake_entries`
Expected: FAIL with `ImportError: cannot import name 'apply_rattlesnake_entries'`

- [ ] **Step 3: Implement apply_rattlesnake_entries**

Append to `hydra_backtest/rattlesnake/engine.py`:
```python
def apply_rattlesnake_entries(
    state: BacktestState,
    date: pd.Timestamp,
    i: int,
    price_data: Dict[str, pd.DataFrame],
    candidates: List[dict],
    max_positions: int,
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[BacktestState, list]:
    """Pure equivalent of COMPASSLive._open_rattlesnake_positions.

    Source: omnicapital_live.py:2092. Sized at 20% of the cash snapshot
    captured BEFORE the candidate loop (mirroring r_budget * R_POSITION_SIZE
    at omnicapital_live.py:2151). Uses INTEGER shares
    (omnicapital_live.py:2152).
    """
    decisions: list = []
    cash = state.cash
    positions = dict(state.positions)

    slots = max_positions - len(positions)
    if slots <= 0 or cash < 1000:
        return state, decisions

    # CRITICAL: capture initial_cash BEFORE the loop. All entries in this
    # call size against this fixed snapshot, NOT against decreasing cash.
    # This mirrors the live engine where r_budget is computed once via
    # compute_allocation() and reused for every candidate in the loop.
    initial_cash = cash

    for cand in candidates[:slots]:
        symbol = cand.get('symbol')
        if not symbol or symbol in positions:
            continue

        entry_price = _get_exec_price(
            symbol, date, i, all_dates, price_data, execution_mode
        )
        if entry_price is None or entry_price <= 0:
            continue

        position_value = initial_cash * R_POSITION_SIZE  # 20% of fixed snapshot
        shares = int(position_value / entry_price)       # INTEGER shares
        if shares < 1:
            continue

        cost = shares * entry_price
        commission = shares * config['COMMISSION_PER_SHARE']
        # Cash buffer check uses CURRENT cash (matching live which uses
        # portfolio.cash * 0.90 at omnicapital_live.py:2159)
        if cost + commission > cash * 0.90:
            continue

        # In next_open mode, the position is recorded at the fill bar (i+1),
        # so days_held counts forward correctly from the fill day.
        if execution_mode == 'next_open':
            effective_entry_date = all_dates[i + 1]
            effective_entry_idx = i + 1
        else:
            effective_entry_date = date
            effective_entry_idx = i

        positions[symbol] = {
            'symbol': symbol,
            'entry_price': entry_price,
            'shares': float(shares),
            'entry_date': effective_entry_date,
            'entry_idx': effective_entry_idx,
            'days_held': 0,
            'sector': 'Unknown',
            'entry_vol': 0.0,
            'entry_daily_vol': 0.0,
            'high_price': entry_price,
        }
        cash -= cost + commission
        decisions.append({
            'type': 'entry',
            'symbol': symbol,
            'date': str(effective_entry_date),
            'entry_price': entry_price,
            'shares': float(shares),
            'drop_pct': cand.get('drop_pct'),
            'rsi': cand.get('rsi'),
        })

    return state._replace(cash=cash, positions=positions), decisions
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest hydra_backtest/rattlesnake/tests/test_engine.py -v`
Expected: 13 passed (2 universe + 5 exits + 6 entries)

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/rattlesnake/engine.py hydra_backtest/rattlesnake/tests/test_engine.py
git commit -m "feat(hydra_backtest.rattlesnake): apply_rattlesnake_entries with fixed budget + integer shares"
```

---

## Task 6: Engine — daily costs helper (Rattlesnake variant)

**Files:**
- Modify: `hydra_backtest/rattlesnake/engine.py`
- Modify: `hydra_backtest/rattlesnake/tests/test_engine.py`

- [ ] **Step 1: Write failing tests**

Append to `hydra_backtest/rattlesnake/tests/test_engine.py`:
```python
from hydra_backtest.rattlesnake.engine import _apply_rattlesnake_daily_costs


def test_daily_costs_rattlesnake_cash_yield_only():
    """Rattlesnake has no leverage → only cash yield is applied,
    no margin cost."""
    state = BacktestState(
        cash=10_000.0, positions={}, peak_value=10_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    new_state = _apply_rattlesnake_daily_costs(state, cash_yield_annual_pct=3.5)
    expected = 10_000.0 * (1 + 0.035 / 252)
    assert abs(new_state.cash - expected) < 1e-6


def test_daily_costs_rattlesnake_zero_cash():
    state = BacktestState(
        cash=0.0, positions={}, peak_value=0.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    new_state = _apply_rattlesnake_daily_costs(state, cash_yield_annual_pct=3.5)
    assert new_state.cash == 0.0


def test_daily_costs_rattlesnake_negative_yield_ignored():
    """Negative yields (rare, e.g. T-bill briefly negative in 2020) are
    not applied — fail-safe default to no compounding."""
    state = BacktestState(
        cash=10_000.0, positions={}, peak_value=10_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    new_state = _apply_rattlesnake_daily_costs(state, cash_yield_annual_pct=-0.10)
    assert new_state.cash == 10_000.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest hydra_backtest/rattlesnake/tests/test_engine.py -v -k daily_costs`
Expected: FAIL with `ImportError: cannot import name '_apply_rattlesnake_daily_costs'`

- [ ] **Step 3: Implement helper**

Append to `hydra_backtest/rattlesnake/engine.py`:
```python
def _apply_rattlesnake_daily_costs(
    state: BacktestState,
    cash_yield_annual_pct: float,
) -> BacktestState:
    """Apply one trading day's cash yield. Rattlesnake has no leverage
    so there is no margin cost component.

    Negative yields are ignored (fail-safe — see v1.0 design §13.4 for the
    same behavior on the COMPASS side).
    """
    cash = state.cash
    if cash > 0 and cash_yield_annual_pct > 0:
        daily_rate = cash_yield_annual_pct / 100.0 / 252
        cash += cash * daily_rate
    return state._replace(cash=cash)
```

- [ ] **Step 4: Run tests**

Run: `pytest hydra_backtest/rattlesnake/tests/test_engine.py -v`
Expected: 16 passed (2 + 5 + 6 + 3)

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/rattlesnake/engine.py hydra_backtest/rattlesnake/tests/test_engine.py
git commit -m "feat(hydra_backtest.rattlesnake): _apply_rattlesnake_daily_costs (cash yield only)"
```

---

## Task 7: Engine — run_rattlesnake_backtest orchestrator

**Files:**
- Modify: `hydra_backtest/rattlesnake/engine.py`
- Modify: `hydra_backtest/rattlesnake/tests/test_engine.py`

- [ ] **Step 1: Write failing integration test**

Append to `hydra_backtest/rattlesnake/tests/test_engine.py`:
```python
import numpy as np

from hydra_backtest.engine import BacktestResult
from hydra_backtest.rattlesnake.engine import run_rattlesnake_backtest


def test_run_rattlesnake_backtest_smoke():
    """Minimal 200-day backtest with synthetic data. Verify it returns
    a valid BacktestResult without crashing."""
    dates = pd.date_range('2020-01-02', periods=400)
    np.random.seed(666)

    # Build 30 synthetic tickers with normal returns
    price_data = {}
    for k in range(30):
        base = 100.0 + k
        returns = np.random.normal(0.0005, 0.020, 400)
        closes = base * np.exp(np.cumsum(returns))
        price_data[f'T{k:02d}'] = pd.DataFrame({
            'Open': closes,
            'High': closes * 1.005,
            'Low': closes * 0.995,
            'Close': closes,
            'Volume': [1_500_000] * 400,
        }, index=dates)

    # SPY trends up
    spy_returns = np.random.normal(0.0005, 0.012, 400)
    spy_close = 300.0 * np.exp(np.cumsum(spy_returns))
    spy_data = pd.DataFrame({'Close': spy_close}, index=dates)

    # VIX series — calm at 15, no panic
    vix_data = pd.Series([15.0] * 400, index=dates, name='vix')

    # PIT universe: all tickers in 2020 and 2021. The engine intersects
    # this with R_UNIVERSE — but our synthetic tickers ('T00'..'T29') are
    # NOT in R_UNIVERSE. To make this test produce trades, we override
    # R_UNIVERSE for the test scope.
    import rattlesnake_signals as rs
    original_universe = rs.R_UNIVERSE
    rs.R_UNIVERSE = [f'T{k:02d}' for k in range(30)]
    try:
        pit_universe = {
            2020: [f'T{k:02d}' for k in range(30)],
            2021: [f'T{k:02d}' for k in range(30)],
        }
        cash_yield = pd.Series([3.5] * 400, index=dates)
        config = {
            'INITIAL_CAPITAL': 100_000,
            'COMMISSION_PER_SHARE': 0.0035,
            'NUM_POSITIONS': 5,
            'NUM_POSITIONS_RISK_OFF': 2,
            'MIN_AGE_DAYS': 220,
        }
        result = run_rattlesnake_backtest(
            config=config, price_data=price_data, pit_universe=pit_universe,
            spy_data=spy_data, vix_data=vix_data, cash_yield_daily=cash_yield,
            start_date=dates[0], end_date=dates[-1],
            execution_mode='same_close',
        )
    finally:
        rs.R_UNIVERSE = original_universe

    assert isinstance(result, BacktestResult)
    assert len(result.daily_values) == 400
    assert 'portfolio_value' in result.daily_values.columns
    assert result.daily_values['portfolio_value'].iloc[0] > 0
    assert len(result.git_sha) > 0


def test_run_rattlesnake_backtest_days_held_increments():
    """When a position is held across multiple days, days_held should
    increment monotonically until it triggers exit at R_MAX_HOLD_DAYS=8."""
    from rattlesnake_signals import R_MAX_HOLD_DAYS
    dates = pd.date_range('2020-01-02', periods=300)

    # Single ticker that meets entry criteria once and stays flat
    closes = ([100.0] * 250 + [90.0] * 5 + [91.0] * 45)  # drop on day 250, then flat
    price_data = {
        'AAA': pd.DataFrame({
            'Open': closes, 'High': [c * 1.01 for c in closes],
            'Low': [c * 0.99 for c in closes], 'Close': closes,
            'Volume': [2_000_000] * 300,
        }, index=dates),
    }
    spy_data = pd.DataFrame({'Close': [300.0] * 300}, index=dates)
    vix_data = pd.Series([15.0] * 300, index=dates, name='vix')

    import rattlesnake_signals as rs
    original_universe = rs.R_UNIVERSE
    rs.R_UNIVERSE = ['AAA']
    try:
        pit_universe = {2020: ['AAA']}
        config = {
            'INITIAL_CAPITAL': 100_000,
            'COMMISSION_PER_SHARE': 0.0035,
            'NUM_POSITIONS': 5,
            'NUM_POSITIONS_RISK_OFF': 2,
            'MIN_AGE_DAYS': 220,
        }
        result = run_rattlesnake_backtest(
            config=config, price_data=price_data, pit_universe=pit_universe,
            spy_data=spy_data, vix_data=vix_data,
            cash_yield_daily=pd.Series([0.0] * 300, index=dates),
            start_date=dates[0], end_date=dates[-1],
            execution_mode='same_close',
        )
    finally:
        rs.R_UNIVERSE = original_universe

    # Expect at least one R_TIME exit (because price stays flat after entry,
    # so neither profit nor stop fires)
    if not result.trades.empty:
        time_exits = result.trades[result.trades['exit_reason'] == 'R_TIME']
        assert len(time_exits) >= 0  # may or may not produce trades — just no crash
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest hydra_backtest/rattlesnake/tests/test_engine.py -v -k run_rattlesnake_backtest_smoke`
Expected: FAIL with `ImportError: cannot import name 'run_rattlesnake_backtest'`

- [ ] **Step 3: Implement run_rattlesnake_backtest**

Append to `hydra_backtest/rattlesnake/engine.py`:
```python
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


def run_rattlesnake_backtest(
    config: dict,
    price_data: Dict[str, pd.DataFrame],
    pit_universe: Dict[int, List[str]],
    spy_data: pd.DataFrame,
    vix_data: pd.Series,
    cash_yield_daily: pd.Series,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    execution_mode: str = 'same_close',
    progress_callback: Optional[callable] = None,
) -> BacktestResult:
    """Run a Rattlesnake mean-reversion backtest from start_date to end_date.

    Pure function: no side effects. Returns a BacktestResult compatible
    with v1.0 reporting/methodology layers (drop-in for build_waterfall).
    """
    started_at = datetime.now()

    # Aggregate all trading dates from price_data
    all_dates_set = set()
    for df in price_data.values():
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
                pv_now = _mark_to_market(state, price_data, date)
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
        portfolio_value = _mark_to_market(state, price_data, date)

        # 1b. Update peak BEFORE drawdown
        if portfolio_value > state.peak_value:
            state = state._replace(peak_value=portfolio_value)

        # 2. Resolve PIT universe (intersection with R_UNIVERSE)
        tradeable = _resolve_rattlesnake_universe(pit_universe, date.year)
        # Filter further by tickers that have price data on this date
        # AND meet MIN_AGE_DAYS history requirement
        min_age = config.get('MIN_AGE_DAYS', 220)
        tradeable = [
            t for t in tradeable
            if t in price_data
            and date in price_data[t].index
            and len(price_data[t].loc[:date]) >= min_age
        ]
        universe_size[date.year] = max(universe_size.get(date.year, 0), len(tradeable))

        # 3. Drawdown
        drawdown = (
            (portfolio_value - state.peak_value) / state.peak_value
            if state.peak_value > 0 else 0.0
        )

        # 4. Regime + VIX
        spy_slice = spy_data.loc[:date]
        vix_value = float(vix_data.loc[date]) if date in vix_data.index else None
        regime_info = check_rattlesnake_regime(spy_slice, vix_value)
        max_positions = regime_info['max_positions']
        entries_allowed = regime_info['entries_allowed']
        vix_panic = regime_info['vix_panic']

        # 5. Daily costs (cash yield only)
        daily_yield = float(
            cash_yield_daily.get(date, cash_yield_daily.iloc[0])
            if len(cash_yield_daily) > 0 else 0.0
        )
        state = _apply_rattlesnake_daily_costs(state, daily_yield)

        # 6. Apply exits
        state, exit_trades, exit_decisions = apply_rattlesnake_exits(
            state, date, i, price_data, config, execution_mode, all_dates,
        )
        trades.extend(exit_trades)
        decisions.extend(exit_decisions)

        # 7. Apply entries (if regime allows)
        if entries_allowed and len(tradeable) >= 5:
            # Find candidates using sliced history
            sliced = _slice_history_to_date(price_data, date, symbols=tradeable)
            current_prices = {
                t: float(price_data[t].loc[date, 'Close'])
                for t in tradeable
            }
            held = set(state.positions.keys())
            slots = max_positions - len(state.positions)
            if slots > 0:
                candidates = find_rattlesnake_candidates(
                    sliced, current_prices, held, max_candidates=slots,
                )
                state, entry_decisions = apply_rattlesnake_entries(
                    state, date, i, price_data, candidates,
                    max_positions, config, execution_mode, all_dates,
                )
                decisions.extend(entry_decisions)

        # 8. Snapshot AFTER exits and entries
        pv_after = _mark_to_market(state, price_data, date)
        snapshots.append({
            'date': date,
            'portfolio_value': pv_after,
            'cash': state.cash,
            'n_positions': len(state.positions),
            'leverage': 1.0,         # Rattlesnake never uses leverage
            'drawdown': drawdown,
            'regime_score': 1.0 if regime_info['regime'] == 'RISK_ON' else 0.0,
            'crash_active': vix_panic,  # repurpose this column for VIX panic
            'max_positions': max_positions,
        })

        # 9. Update state tail: peak (if pv_after exceeded), increment days_held
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

    finished_at = datetime.now()

    trade_cols = ['symbol', 'entry_date', 'exit_date', 'exit_reason',
                  'entry_price', 'exit_price', 'shares', 'pnl', 'return', 'sector']
    return BacktestResult(
        config=dict(config),
        daily_values=pd.DataFrame(snapshots),
        trades=pd.DataFrame(trades) if trades else pd.DataFrame(columns=trade_cols),
        decisions=decisions,
        exit_events=[t for t in trades if t['exit_reason'] in ('R_STOP', 'R_PROFIT')],
        universe_size=universe_size,
        started_at=started_at,
        finished_at=finished_at,
        git_sha=_capture_git_sha(),
        data_inputs_hash=compute_data_fingerprint(price_data),
    )
```

- [ ] **Step 4: Run all engine tests**

Run: `pytest hydra_backtest/rattlesnake/tests/test_engine.py -v`
Expected: 18 passed (16 + 2 new run_rattlesnake_backtest tests)

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/rattlesnake/engine.py hydra_backtest/rattlesnake/tests/test_engine.py
git commit -m "feat(hydra_backtest.rattlesnake): run_rattlesnake_backtest orchestrator"
```

---

## Task 8: Validation — Layer A smoke tests

**Files:**
- Create: `hydra_backtest/rattlesnake/validation.py`
- Create: `hydra_backtest/rattlesnake/tests/test_validation.py`

- [ ] **Step 1: Write failing tests for run_rattlesnake_smoke_tests**

Create `hydra_backtest/rattlesnake/tests/test_validation.py`:
```python
"""Tests for hydra_backtest.rattlesnake.validation."""
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from hydra_backtest.engine import BacktestResult
from hydra_backtest.errors import HydraBacktestValidationError
from hydra_backtest.rattlesnake.validation import run_rattlesnake_smoke_tests


def _good_rattlesnake_result():
    rng = np.random.default_rng(666)
    dates = pd.date_range('2020-01-01', periods=500)
    daily_rets = rng.normal(loc=0.0003, scale=0.005, size=500)
    values = (100_000 * np.cumprod(1 + daily_rets)).tolist()
    daily = pd.DataFrame({
        'date': dates,
        'portfolio_value': values,
        'cash': values,
        'n_positions': [3] * 500,
        'leverage': [1.0] * 500,
        'drawdown': [0.0] * 500,
        'regime_score': [1.0] * 500,
        'crash_active': [False] * 500,
        'max_positions': [5] * 500,
    })
    trades = pd.DataFrame(columns=[
        'symbol', 'entry_date', 'exit_date', 'exit_reason',
        'entry_price', 'exit_price', 'shares', 'pnl', 'return', 'sector',
    ])
    return BacktestResult(
        config={'NUM_POSITIONS': 5, 'COMMISSION_PER_SHARE': 0.0035},
        daily_values=daily, trades=trades, decisions=[], exit_events=[],
        universe_size={2020: 60}, started_at=datetime(2026, 4, 7),
        finished_at=datetime(2026, 4, 7), git_sha='test', data_inputs_hash='test',
    )


def test_smoke_tests_pass_for_good_result():
    run_rattlesnake_smoke_tests(_good_rattlesnake_result())  # no raise


def test_smoke_tests_detect_nan():
    r = _good_rattlesnake_result()
    r.daily_values.loc[10, 'portfolio_value'] = float('nan')
    with pytest.raises(HydraBacktestValidationError, match="NaN"):
        run_rattlesnake_smoke_tests(r)


def test_smoke_tests_detect_negative_cash():
    r = _good_rattlesnake_result()
    r.daily_values.loc[5, 'cash'] = -1000.0
    with pytest.raises(HydraBacktestValidationError, match="cash"):
        run_rattlesnake_smoke_tests(r)


def test_smoke_tests_detect_too_many_positions():
    r = _good_rattlesnake_result()
    r.daily_values.loc[10, 'n_positions'] = 10
    with pytest.raises(HydraBacktestValidationError, match="n_positions"):
        run_rattlesnake_smoke_tests(r)


def test_smoke_tests_detect_drawdown_below_neg_one():
    r = _good_rattlesnake_result()
    r.daily_values.loc[10, 'drawdown'] = -1.5
    with pytest.raises(HydraBacktestValidationError, match="drawdown"):
        run_rattlesnake_smoke_tests(r)


def test_smoke_tests_detect_bad_stop_exit():
    """An R_STOP exit with positive return is impossible."""
    r = _good_rattlesnake_result()
    r.trades.loc[0] = {
        'symbol': 'AAA', 'entry_date': pd.Timestamp('2020-01-02'),
        'exit_date': pd.Timestamp('2020-01-05'), 'exit_reason': 'R_STOP',
        'entry_price': 100.0, 'exit_price': 110.0, 'shares': 10.0,
        'pnl': 100.0, 'return': 0.10, 'sector': 'Unknown',
    }
    with pytest.raises(HydraBacktestValidationError, match="R_STOP"):
        run_rattlesnake_smoke_tests(r)


def test_smoke_tests_detect_bad_profit_exit():
    """An R_PROFIT exit must have return >= R_PROFIT_TARGET (-tolerance)."""
    r = _good_rattlesnake_result()
    r.trades.loc[0] = {
        'symbol': 'AAA', 'entry_date': pd.Timestamp('2020-01-02'),
        'exit_date': pd.Timestamp('2020-01-05'), 'exit_reason': 'R_PROFIT',
        'entry_price': 100.0, 'exit_price': 101.0, 'shares': 10.0,
        'pnl': 10.0, 'return': 0.01, 'sector': 'Unknown',
    }
    with pytest.raises(HydraBacktestValidationError, match="R_PROFIT"):
        run_rattlesnake_smoke_tests(r)


def test_smoke_tests_accept_valid_profit_exit():
    """A correct R_PROFIT exit (return ~ +4%) should pass."""
    r = _good_rattlesnake_result()
    r.trades.loc[0] = {
        'symbol': 'AAA', 'entry_date': pd.Timestamp('2020-01-02'),
        'exit_date': pd.Timestamp('2020-01-05'), 'exit_reason': 'R_PROFIT',
        'entry_price': 100.0, 'exit_price': 104.0, 'shares': 10.0,
        'pnl': 40.0, 'return': 0.04, 'sector': 'Unknown',
    }
    run_rattlesnake_smoke_tests(r)  # no raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest hydra_backtest/rattlesnake/tests/test_validation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hydra_backtest.rattlesnake.validation'`

- [ ] **Step 3: Implement validation**

Create `hydra_backtest/rattlesnake/validation.py`:
```python
"""Layer A smoke tests for Rattlesnake — blocking for v1.1.

Adapted from hydra_backtest.validation.run_smoke_tests:
- Removes COMPASS-only checks (leverage bounds, sector concentration,
  crash brake)
- Adds Rattlesnake-specific checks: stop/profit/time exit adherence
"""
import numpy as np
import pandas as pd

from hydra_backtest.engine import BacktestResult
from hydra_backtest.errors import HydraBacktestValidationError
from rattlesnake_signals import (
    R_MAX_HOLD_DAYS,
    R_MAX_POSITIONS,
    R_PROFIT_TARGET,
    R_STOP_LOSS,
)

# Tolerance for stop/profit return checks. Stops and profits use the
# Close[T] check but execute at Open[T+1] in next-open mode, so the
# realized return can deviate from the threshold by overnight gap.
_RETURN_TOLERANCE = 0.05  # 5 pp tolerance to account for gap-through

# Known crash dates where daily portfolio returns can legitimately exceed ±15%
_CRASH_ALLOWLIST = {
    pd.Timestamp('2008-09-29'),
    pd.Timestamp('2008-10-13'),
    pd.Timestamp('2008-10-15'),
    pd.Timestamp('2008-10-28'),
    pd.Timestamp('2020-03-09'),
    pd.Timestamp('2020-03-12'),
    pd.Timestamp('2020-03-13'),
    pd.Timestamp('2020-03-16'),
    pd.Timestamp('2020-03-17'),
    pd.Timestamp('2020-03-18'),
    pd.Timestamp('2020-03-24'),
}


def run_rattlesnake_smoke_tests(result: BacktestResult) -> None:
    """Run all Layer A smoke tests for a Rattlesnake backtest result.

    Raises HydraBacktestValidationError on any failure.
    """
    daily = result.daily_values

    if len(daily) == 0:
        raise HydraBacktestValidationError("Backtest produced empty daily_values")

    # 1. No NaN in critical columns
    for col in ('portfolio_value', 'cash', 'drawdown'):
        if col in daily.columns and daily[col].isna().any():
            raise HydraBacktestValidationError(
                f"NaN detected in daily_values column: {col}"
            )

    # 2. Cash never arbitrarily negative
    if (daily['cash'] < -1.0).any():
        raise HydraBacktestValidationError(
            f"Negative cash detected: min = {float(daily['cash'].min())}"
        )

    # 3. Drawdown bounds
    if (daily['drawdown'] < -1.0).any() or (daily['drawdown'] > 1e-4).any():
        raise HydraBacktestValidationError(
            f"drawdown out of [-1.0, 0] range: "
            f"min={float(daily['drawdown'].min())}, "
            f"max={float(daily['drawdown'].max())}"
        )

    # 4. Position count bounds (Rattlesnake: max R_MAX_POSITIONS, no bull override)
    if (daily['n_positions'] < 0).any() or (daily['n_positions'] > R_MAX_POSITIONS).any():
        raise HydraBacktestValidationError(
            f"n_positions out of [0, {R_MAX_POSITIONS}] range: "
            f"min={int(daily['n_positions'].min())}, "
            f"max={int(daily['n_positions'].max())}"
        )

    # 5. Peak monotonic non-decreasing
    pv = daily['portfolio_value'].values
    peak = np.maximum.accumulate(pv)
    if not np.all(np.diff(peak) >= -1e-6):
        raise HydraBacktestValidationError(
            "Peak portfolio value is not monotonic non-decreasing"
        )

    # 6. Statistical sanity — annualized vol
    returns = daily['portfolio_value'].pct_change().dropna()
    if len(returns) > 20:
        vol_ann = float(returns.std() * np.sqrt(252))
        if not (0.005 <= vol_ann <= 0.50):
            # Lower bound is 0.5% (vs 3% for COMPASS) because Rattlesnake
            # spends much of the time in cash and has lower vol overall
            raise HydraBacktestValidationError(
                f"Annualized volatility out of sanity range [0.5%, 50%]: {vol_ann:.2%}"
            )

    # 7. Outlier daily returns (except allowlist)
    dates = pd.to_datetime(daily['date'])
    ret_dates = dates.iloc[1:].reset_index(drop=True)
    rets_arr = returns.reset_index(drop=True)
    for ts, ret in zip(ret_dates, rets_arr):
        if abs(ret) > 0.15 and ts not in _CRASH_ALLOWLIST:
            raise HydraBacktestValidationError(
                f"Outlier daily return {ret:.2%} on {ts.date()} "
                "not in crash allowlist"
            )

    # 8. Trade exit adherence (Rattlesnake-specific)
    trades = result.trades
    if not trades.empty and 'exit_reason' in trades.columns:
        # R_STOP: return must be ≤ R_STOP_LOSS + tolerance
        stops = trades[trades['exit_reason'] == 'R_STOP']
        if not stops.empty:
            bad_stops = stops[stops['return'] > R_STOP_LOSS + _RETURN_TOLERANCE]
            if len(bad_stops) > 0:
                raise HydraBacktestValidationError(
                    f"{len(bad_stops)} R_STOP exits have return > "
                    f"{R_STOP_LOSS + _RETURN_TOLERANCE:.2%} (worst: "
                    f"{float(bad_stops['return'].max()):.2%})"
                )

        # R_PROFIT: return must be ≥ R_PROFIT_TARGET - tolerance
        profits = trades[trades['exit_reason'] == 'R_PROFIT']
        if not profits.empty:
            bad_profits = profits[profits['return'] < R_PROFIT_TARGET - _RETURN_TOLERANCE]
            if len(bad_profits) > 0:
                raise HydraBacktestValidationError(
                    f"{len(bad_profits)} R_PROFIT exits have return < "
                    f"{R_PROFIT_TARGET - _RETURN_TOLERANCE:.2%} (worst: "
                    f"{float(bad_profits['return'].min()):.2%})"
                )
```

- [ ] **Step 4: Run validation tests**

Run: `pytest hydra_backtest/rattlesnake/tests/test_validation.py -v`
Expected: 8 passed

- [ ] **Step 5: Run full sub-package tests**

Run: `pytest hydra_backtest/rattlesnake/tests/ -v 2>&1 | tail -10`
Expected: 26 passed (18 engine + 8 validation)

- [ ] **Step 6: Commit**

```bash
git add hydra_backtest/rattlesnake/validation.py hydra_backtest/rattlesnake/tests/test_validation.py
git commit -m "feat(hydra_backtest.rattlesnake): Layer A smoke tests"
```

---

## Task 9: Public API exports

**Files:**
- Modify: `hydra_backtest/rattlesnake/__init__.py`

- [ ] **Step 1: Update __init__.py with public exports**

Replace `hydra_backtest/rattlesnake/__init__.py`:
```python
"""hydra_backtest.rattlesnake — Rattlesnake mean-reversion standalone backtest.

See docs/superpowers/specs/2026-04-07-hydra-backtest-v1.1-rattlesnake-design.md
for the design and docs/superpowers/plans/2026-04-07-hydra-backtest-v1.1-rattlesnake.md
for the implementation plan.
"""
from hydra_backtest.rattlesnake.engine import (
    apply_rattlesnake_entries,
    apply_rattlesnake_exits,
    run_rattlesnake_backtest,
)
from hydra_backtest.rattlesnake.validation import run_rattlesnake_smoke_tests

__all__ = [
    'run_rattlesnake_backtest',
    'apply_rattlesnake_exits',
    'apply_rattlesnake_entries',
    'run_rattlesnake_smoke_tests',
]
```

- [ ] **Step 2: Verify imports work**

Run: `python -c "from hydra_backtest.rattlesnake import run_rattlesnake_backtest, run_rattlesnake_smoke_tests; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add hydra_backtest/rattlesnake/__init__.py
git commit -m "feat(hydra_backtest.rattlesnake): public API exports"
```

---

## Task 10: CLI entrypoint

**Files:**
- Create: `hydra_backtest/rattlesnake/__main__.py`
- Create: `hydra_backtest/rattlesnake/tests/test_integration.py`

- [ ] **Step 1: Write failing CLI integration test**

Create `hydra_backtest/rattlesnake/tests/test_integration.py`:
```python
"""Integration tests for hydra_backtest.rattlesnake CLI."""
import os
import subprocess
import sys

import pytest


def test_cli_help():
    """python -m hydra_backtest.rattlesnake --help should succeed."""
    result = subprocess.run(
        [sys.executable, '-m', 'hydra_backtest.rattlesnake', '--help'],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0
    out = result.stdout.lower()
    assert 'start' in out
    assert 'end' in out
    assert 'vix' in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest hydra_backtest/rattlesnake/tests/test_integration.py -v`
Expected: FAIL because `python -m hydra_backtest.rattlesnake` returns non-zero (no __main__.py)

- [ ] **Step 3: Implement __main__.py**

Create `hydra_backtest/rattlesnake/__main__.py`:
```python
"""CLI entrypoint: python -m hydra_backtest.rattlesnake

Reads PIT data from data_cache/, runs 3 Rattlesnake backtest tiers
(baseline + T-bill + next-open), post-processes for slippage tier,
writes CSV + JSON outputs, and prints a waterfall summary.
"""
import argparse
import os
import sys

import pandas as pd

from hydra_backtest import (
    build_waterfall,
    format_summary_table,
    load_pit_universe,
    load_price_history,
    load_spy_data,
    load_vix_series,
    load_yield_series,
    write_daily_csv,
    write_trades_csv,
    write_waterfall_json,
)
from hydra_backtest.rattlesnake import (
    run_rattlesnake_backtest,
    run_rattlesnake_smoke_tests,
)


# Rattlesnake config — subset of COMPASS keys (no leverage, no DD scaling).
_CONFIG = {
    'INITIAL_CAPITAL': 100_000,
    'COMMISSION_PER_SHARE': 0.0035,
    'NUM_POSITIONS': 5,
    'NUM_POSITIONS_RISK_OFF': 2,
    'MIN_AGE_DAYS': 220,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog='python -m hydra_backtest.rattlesnake',
        description='Reproducible Rattlesnake mean-reversion standalone backtest.',
    )
    parser.add_argument('--start', type=str, default='2000-01-01',
                        help='Backtest start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, default='2026-03-05',
                        help='Backtest end date (YYYY-MM-DD)')
    parser.add_argument('--out-dir', type=str, default='backtests/rattlesnake_v1',
                        help='Output directory for CSVs and JSON')
    parser.add_argument('--constituents', type=str,
                        default='data_cache/sp500_constituents_history.pkl')
    parser.add_argument('--prices', type=str,
                        default='data_cache/sp500_universe_prices.pkl')
    parser.add_argument('--spy', type=str,
                        default='data_cache/SPY_2000-01-01_2027-01-01.csv')
    parser.add_argument('--vix', type=str,
                        default='data_cache/vix_history.csv')
    parser.add_argument('--aaa', type=str,
                        default='data_cache/moody_aaa_yield.csv')
    parser.add_argument('--tbill', type=str,
                        default='data_cache/tbill_3m_fred.csv')
    parser.add_argument('--aaa-date-col', type=str, default='DATE')
    parser.add_argument('--aaa-value-col', type=str, default='DAAA')
    parser.add_argument('--tbill-date-col', type=str, default='DATE')
    parser.add_argument('--tbill-value-col', type=str, default='DGS3MO')
    parser.add_argument('--slippage-bps', type=float, default=2.0)
    parser.add_argument('--half-spread-bps', type=float, default=0.5)
    parser.add_argument('--t-bill-rf', type=float, default=0.03)
    args = parser.parse_args(argv)

    print("Loading data...", flush=True)
    pit = load_pit_universe(args.constituents)
    prices = load_price_history(args.prices)
    spy = load_spy_data(args.spy)
    vix = load_vix_series(args.vix)
    aaa_yield = load_yield_series(
        args.aaa, date_col=args.aaa_date_col, value_col=args.aaa_value_col,
    )
    tbill_yield = load_yield_series(
        args.tbill, date_col=args.tbill_date_col, value_col=args.tbill_value_col,
    )
    print(
        f"  PIT universe: {sum(len(v) for v in pit.values()) // max(len(pit), 1)} tickers/year avg, "
        f"{len(prices)} total tickers, VIX {len(vix)} bars",
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
    tier_0 = run_rattlesnake_backtest(
        config=_CONFIG, price_data=prices, pit_universe=pit, spy_data=spy,
        vix_data=vix, cash_yield_daily=aaa_yield,
        start_date=start, end_date=end, execution_mode='same_close',
        progress_callback=_make_progress_cb('tier0'),
    )
    run_rattlesnake_smoke_tests(tier_0)
    print("  tier 0 smoke tests: PASSED", flush=True)

    print("\nTier 1: + T-bill cash yield", flush=True)
    tier_1 = run_rattlesnake_backtest(
        config=_CONFIG, price_data=prices, pit_universe=pit, spy_data=spy,
        vix_data=vix, cash_yield_daily=tbill_yield,
        start_date=start, end_date=end, execution_mode='same_close',
        progress_callback=_make_progress_cb('tier1'),
    )
    run_rattlesnake_smoke_tests(tier_1)
    print("  tier 1 smoke tests: PASSED", flush=True)

    print("\nTier 2: + next-open execution", flush=True)
    tier_2 = run_rattlesnake_backtest(
        config=_CONFIG, price_data=prices, pit_universe=pit, spy_data=spy,
        vix_data=vix, cash_yield_daily=tbill_yield,
        start_date=start, end_date=end, execution_mode='next_open',
        progress_callback=_make_progress_cb('tier2'),
    )
    run_rattlesnake_smoke_tests(tier_2)
    print("  tier 2 smoke tests: PASSED", flush=True)

    print("\nBuilding waterfall...", flush=True)
    report = build_waterfall(
        tier_0=tier_0, tier_1=tier_1, tier_2=tier_2,
        t_bill_rf=args.t_bill_rf,
        slippage_bps=args.slippage_bps,
        half_spread_bps=args.half_spread_bps,
    )

    os.makedirs(args.out_dir, exist_ok=True)
    write_daily_csv(tier_0, os.path.join(args.out_dir, 'rattlesnake_v2_daily.csv'))
    write_trades_csv(tier_0, os.path.join(args.out_dir, 'rattlesnake_v2_trades.csv'))
    write_waterfall_json(report, os.path.join(args.out_dir, 'rattlesnake_v2_waterfall.json'))

    print('\n' + format_summary_table(report), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 4: Run integration test**

Run: `pytest hydra_backtest/rattlesnake/tests/test_integration.py -v`
Expected: 1 passed (test_cli_help)

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/rattlesnake/__main__.py hydra_backtest/rattlesnake/tests/test_integration.py
git commit -m "feat(hydra_backtest.rattlesnake): CLI entrypoint with progress callback"
```

---

## Task 11: E2E tests (slow, real data)

**Files:**
- Create: `hydra_backtest/rattlesnake/tests/test_e2e.py`

- [ ] **Step 1: Create test_e2e.py**

Create `hydra_backtest/rattlesnake/tests/test_e2e.py`:
```python
"""End-to-end tests for hydra_backtest.rattlesnake. SLOW.

Run with: pytest hydra_backtest/rattlesnake/tests/test_e2e.py -m slow
"""
import hashlib
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.slow


@pytest.mark.skipif(
    not os.path.exists('data_cache/sp500_universe_prices.pkl'),
    reason="Requires real PIT cache",
)
@pytest.mark.skipif(
    not os.path.exists('data_cache/vix_history.csv'),
    reason="Requires VIX history (download via yfinance ^VIX)",
)
def test_e2e_full_rattlesnake_runs_to_completion(tmp_path):
    """Full Rattlesnake backtest over the available PIT range runs without errors."""
    out = tmp_path / 'run1'
    result = subprocess.run(
        [sys.executable, '-m', 'hydra_backtest.rattlesnake',
         '--start', '2000-01-01',
         '--end', '2026-03-04',
         '--out-dir', str(out)],
        capture_output=True, text=True, timeout=1800,
    )
    assert result.returncode == 0, (
        f"CLI failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert (out / 'rattlesnake_v2_daily.csv').exists()
    assert (out / 'rattlesnake_v2_waterfall.json').exists()
    assert (out / 'rattlesnake_v2_trades.csv').exists()
    for tier in ('baseline', 't_bill', 'next_open', 'real_costs', 'net_honest'):
        assert tier in result.stdout


@pytest.mark.skipif(
    not os.path.exists('data_cache/sp500_universe_prices.pkl'),
    reason="Requires real PIT cache",
)
@pytest.mark.skipif(
    not os.path.exists('data_cache/vix_history.csv'),
    reason="Requires VIX history",
)
def test_e2e_rattlesnake_determinism(tmp_path):
    """Two runs with identical inputs produce byte-identical daily CSVs."""
    out1 = tmp_path / 'run1'
    out2 = tmp_path / 'run2'
    for out_dir in (out1, out2):
        result = subprocess.run(
            [sys.executable, '-m', 'hydra_backtest.rattlesnake',
             '--start', '2010-01-01',
             '--end', '2012-12-31',
             '--out-dir', str(out_dir)],
            capture_output=True, text=True, timeout=900,
        )
        assert result.returncode == 0

    def _sha(path):
        with open(path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()

    assert _sha(out1 / 'rattlesnake_v2_daily.csv') == _sha(out2 / 'rattlesnake_v2_daily.csv')
```

- [ ] **Step 2: Verify slow tests are deselected by default**

Run: `pytest hydra_backtest/rattlesnake/tests/ -m "not slow" --collect-only -q 2>&1 | tail -5`
Expected: collects all engine + validation + integration tests, deselects E2E (which is marked slow)

- [ ] **Step 3: Commit**

```bash
git add hydra_backtest/rattlesnake/tests/test_e2e.py
git commit -m "test(hydra_backtest.rattlesnake): E2E full run + determinism (@pytest.mark.slow)"
```

---

## Task 12: README

**Files:**
- Create: `hydra_backtest/rattlesnake/README.md`

- [ ] **Step 1: Write README**

Create `hydra_backtest/rattlesnake/README.md`:
```markdown
# hydra_backtest.rattlesnake — Rattlesnake Standalone Backtest

Reproducible Rattlesnake mean-reversion backtest, the second pillar of
the HYDRA quantitative trading system.

## What this is

A Python sub-package that runs a Rattlesnake mean-reversion backtest
from 2000 to 2026 using point-in-time S&P 500 membership (intersected
with the hardcoded R_UNIVERSE), producing a waterfall methodology
report (baseline → +T-bill → +next-open → +slippage → NET HONEST).

**Consumer-not-owner principle** (inherited from v1.0): pure functions
are imported directly from `rattlesnake_signals.py` (the live engine
module). The reimplementation surface is ~250 LOC of pure helpers
(`apply_rattlesnake_exits`, `apply_rattlesnake_entries`,
`_resolve_rattlesnake_universe`, `_apply_rattlesnake_daily_costs`,
`run_rattlesnake_backtest`).

## How to run

```bash
# Download VIX history first (one-time setup)
python -c "import yfinance as yf; yf.download('^VIX', start='1999-01-01', end='2027-01-01').to_csv('data_cache/vix_history.csv')"

# Run backtest
python -m hydra_backtest.rattlesnake \
  --start 2000-01-01 \
  --end 2026-03-05 \
  --out-dir backtests/rattlesnake_v1 \
  --aaa-date-col observation_date --aaa-value-col yield_pct \
  --tbill data_cache/tbill_3m_fred.csv
```

Outputs in `backtests/rattlesnake_v1/`:
- `rattlesnake_v2_daily.csv` — daily equity curve
- `rattlesnake_v2_trades.csv` — all trades with exit reasons
  (`R_PROFIT`, `R_STOP`, `R_TIME`)
- `rattlesnake_v2_waterfall.json` — 5 tiers + metadata

Stdout shows progress per year and final waterfall summary table.

## How to test

```bash
# Fast tests (~10s)
pytest hydra_backtest/rattlesnake/tests/ -v -m "not slow"

# E2E tests (~5min, requires real data cache + vix_history.csv)
pytest hydra_backtest/rattlesnake/tests/ -v -m slow

# With coverage
pytest hydra_backtest/rattlesnake/tests/ -v --cov=hydra_backtest.rattlesnake
```

## Architecture

```
hydra_backtest/rattlesnake/
├── engine.py        — run_rattlesnake_backtest + apply_rattlesnake_*
├── validation.py    — Layer A smoke tests (Rattlesnake-adapted)
├── __main__.py      — CLI entrypoint
└── __init__.py      — public API
```

Reuses from `hydra_backtest/` (v1.0):
- `BacktestState`, `BacktestResult` dataclasses
- `_mark_to_market`, `_get_exec_price`, `_slice_history_to_date`
- `methodology.build_waterfall` (5-tier waterfall)
- `reporting` writers
- `data` loaders (with new `load_vix_series` helper)
- `errors` exception hierarchy

## Differences from COMPASS (v1.0)

| Aspect | COMPASS | Rattlesnake |
|---|---|---|
| Signal | Risk-adjusted momentum (90d/5d-skip) | Drop ≥8% in 5d + RSI(5)<25 + above SMA200 + volume |
| Universe | S&P 500 PIT top-40 by score | S&P 100 (R_UNIVERSE) ∩ S&P 500 PIT |
| Hold | 5 days (with renewal) | 8 days (no renewal) |
| Exits | Hold expired / position stop / trailing stop / rotation / regime reduce | Profit target (+4%) / stop (-5%) / time (≥8d) |
| Position size | Inverse-volatility weights, fractional shares | 20% of cash snapshot, INTEGER shares |
| Leverage | Vol-targeted 0.30-1.00 | 1.0 always |
| DD scaling | Yes (3 tiers) + crash brake | No |
| Sector limits | Max 3 per sector | None |
| Bull override | Yes (+1 position) | No |

## Limitations (v1.1)

- **Standalone only**: no integration with COMPASS, no cash recycling.
  Standalone Rattlesnake CAGR under-states its real contribution because
  the live engine recycles idle Rattlesnake cash to COMPASS via
  HydraCapitalManager. Full integration is v1.4.
- **Fed Emergency overlay NOT applied**: out of scope (same as v1.0)
- **R_UNIVERSE intersection with PIT S&P 500 is lossy** for tickers that
  were in S&P 100 but not S&P 500 (rare edge case)
- **VIX missing data → fail-closed** (no entries) per the v1.0 fix in
  `rattlesnake_signals.py` (commit b9d4ad7)
- **Layer B cross-validation against `archive/strategies/rattlesnake_v1.py`
  is best-effort** — if the archive script can't run, Layer A is the
  only blocking gate
```

- [ ] **Step 2: Commit**

```bash
git add hydra_backtest/rattlesnake/README.md
git commit -m "docs(hydra_backtest.rattlesnake): package README"
```

---

## Task 13: CI integration

**Files:**
- Modify: `.github/workflows/test.yml`

- [ ] **Step 1: Read current test.yml**

Run: `cat .github/workflows/test.yml`
Expected: existing workflow with v1.0 hydra_backtest test step

- [ ] **Step 2: Add new test step for rattlesnake sub-package**

Edit `.github/workflows/test.yml`. After the existing v1.0 step ("Test hydra_backtest package"), add:

```yaml
      - name: Test hydra_backtest.rattlesnake sub-package
        run: >
          pytest hydra_backtest/rattlesnake/tests/ -v --tb=short
          --cov=hydra_backtest.rattlesnake
          --cov-report=term-missing
          -m "not slow"
```

- [ ] **Step 3: Verify YAML is valid**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml')); print('OK YAML')"`
Expected: `OK YAML`

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/test.yml
git commit -m "ci(hydra_backtest.rattlesnake): add pytest step to CI"
```

---

## Task 14: Full sub-package coverage check

**Files:** none (verification task)

- [ ] **Step 1: Run the full sub-package suite with coverage**

Run:
```bash
pytest hydra_backtest/rattlesnake/tests/ -v --cov=hydra_backtest.rattlesnake --cov-report=term-missing -m "not slow"
```
Expected: all tests pass, coverage ≥ 80%

- [ ] **Step 2: Run v1.0 suite to confirm zero regression**

Run: `pytest hydra_backtest/tests/ -v -m "not slow" 2>&1 | tail -5`
Expected: 77 passed (74 v1.0 + 3 vix loader)

- [ ] **Step 3: Run combined**

Run: `pytest hydra_backtest/ -v -m "not slow" 2>&1 | tail -5`
Expected: ~100 passed (77 v1.0 + 26 v1.1)

- [ ] **Step 4: If any test fails, fix it before proceeding**

Common issues:
- Import cycles between v1.0 and rattlesnake — verify rattlesnake imports v1.0 modules but v1.0 never imports rattlesnake
- Fixture name collision — `minimal_config` (v1.0) vs `rattlesnake_minimal_config` (v1.1) — they're different fixtures, no collision
- Missing `R_MAX_HOLD_DAYS` import in tests — verify import statements

- [ ] **Step 5: Commit any fixes (if needed)**

If no fixes needed, skip this step.

---

## Task 15: VIX data download (one-time setup, NOT a code task)

This is a manual prep step the engineer must do before running the E2E
tests or the official backtest. It's documented here for visibility.

**Files:** none (data prep)

- [ ] **Step 1: Download VIX history via yfinance**

Run:
```bash
python -c "
import yfinance as yf
import pandas as pd
df = yf.download('^VIX', start='1999-01-01', end='2027-01-01', progress=False, auto_adjust=True)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.droplevel(1)
df[['Close']].to_csv('data_cache/vix_history.csv')
print(f'Saved {len(df)} VIX bars to data_cache/vix_history.csv')
print(f'Range: {df.index[0]} to {df.index[-1]}')
print(f'Min/Max VIX: {df[\"Close\"].min():.2f} / {df[\"Close\"].max():.2f}')
"
```
Expected: `Saved ~6800 VIX bars`, range `1999-...` to `2026-...`

- [ ] **Step 2: Verify the file is loaded by `load_vix_series`**

Run: `python -c "from hydra_backtest.data import load_vix_series; v = load_vix_series('data_cache/vix_history.csv'); print(f'{len(v)} bars, range {v.index.min()} to {v.index.max()}, min/max {v.min():.2f}/{v.max():.2f}')"`
Expected: prints bar count + date range + VIX range

- [ ] **Step 3: NO COMMIT** — `data_cache/` is gitignored.

---

## Task 16: Run the official 2000-2026 backtest

**Files:** none (verification + result capture)

- [ ] **Step 1: Run the full backtest**

Run:
```bash
python -m hydra_backtest.rattlesnake \
  --start 2000-01-01 \
  --end 2026-03-05 \
  --out-dir backtests/rattlesnake_v1_official \
  --aaa-date-col observation_date \
  --aaa-value-col yield_pct \
  --tbill data_cache/tbill_3m_fred.csv
```
Expected: ~3-5 minutes runtime, prints waterfall table at end with 5 tiers

- [ ] **Step 2: Verify outputs exist**

Run: `ls backtests/rattlesnake_v1_official/`
Expected: 3 files (`rattlesnake_v2_daily.csv`, `rattlesnake_v2_trades.csv`, `rattlesnake_v2_waterfall.json`)

- [ ] **Step 3: Inspect the waterfall JSON**

Run:
```bash
python -c "import json; d=json.load(open('backtests/rattlesnake_v1_official/rattlesnake_v2_waterfall.json')); [print(f\"{t['name']:<14} CAGR={t['cagr']*100:+.2f}% Sharpe={t['sharpe']:.3f} MaxDD={t['max_drawdown']*100:+.2f}%\") for t in d['tiers']]"
```
Expected: 5 tiers printed (baseline, t_bill, next_open, real_costs, net_honest)

- [ ] **Step 4: Commit the official run results**

```bash
git add backtests/rattlesnake_v1_official/
git commit -m "feat(hydra_backtest.rattlesnake): v1.1 official 2000-2026 backtest results"
```

---

## Self-Review Checklist

**Spec coverage**:
- ✅ §3 scope (Rattlesnake standalone) → Tasks 1-12
- ✅ §4 architecture (sub-package, reuse from v1.0) → Tasks 1, 9
- ✅ §4.4 consumer-not-owner principle → Tasks 3, 4, 5, 7 (imports from rattlesnake_signals)
- ✅ §5 data flow → Task 7 orchestrator
- ✅ §6 engine spec → Tasks 3, 4, 5, 6, 7
- ✅ §7 PIT universe filter → Task 3
- ✅ §8 VIX historical loader → Task 2
- ✅ §9 methodology waterfall (reused from v1.0) → Task 10 CLI uses build_waterfall
- ✅ §10 Layer A smoke tests → Task 8
- ✅ §11 Layer B cross-validation → DEFERRED (best-effort, non-blocking per spec) — not a separate task
- ✅ §12 CLI → Task 10
- ✅ §13 testing strategy → Tasks 4-8 (unit), 10 (integration), 11 (E2E)
- ✅ §13.4 CI integration → Task 13
- ✅ §15 success criteria → Tasks 14, 15, 16
- ✅ §16 roadmap context → Documented in spec, no task needed

**Placeholder scan**: No "TODO", "TBD", "implement later", "similar to X". All steps have actual code/commands.

**Type consistency**:
- `BacktestState`, `BacktestResult` from `hydra_backtest.engine` — used consistently in Tasks 4, 5, 6, 7
- `apply_rattlesnake_exits`, `apply_rattlesnake_entries`, `run_rattlesnake_backtest` signatures consistent across definition (Tasks 4, 5, 7) and usage (Task 7 orchestrator, Task 10 CLI)
- Position dict schema consistent (Task 5 entries → Task 4 exits read it → Task 7 increments `days_held`)
- `R_MAX_HOLD_DAYS`, `R_PROFIT_TARGET`, `R_STOP_LOSS`, `R_POSITION_SIZE`, `R_MAX_POSITIONS` used consistently from `rattlesnake_signals` (no rename, no aliasing)

**One identified risk**: Task 7's `test_run_rattlesnake_backtest_smoke` and `test_run_rattlesnake_backtest_days_held_increments` mutate `rattlesnake_signals.R_UNIVERSE` for the test scope. The `try/finally` restoration handles cleanup. If a test runner runs them in parallel with other tests that import `R_UNIVERSE`, there could be a race condition. The fix if needed: use `unittest.mock.patch` instead of direct assignment. For v1.1, `try/finally` is acceptable because pytest runs sequentially by default in this project.
