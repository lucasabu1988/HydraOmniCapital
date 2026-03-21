# Auto-Recovery for Missed Trading Days — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When HYDRA restarts after missing 1–5 trading days, auto-replay each missed day using historical prices so cycle rotations, stops, and ML events are never lost.

**Architecture:** A new `_recover_missed_days()` method in `COMPASSLive` runs before `daily_open()`, detects gaps via `_recovery_gap_baseline` (raw `last_trading_date` preserved before state validator), and replays each missed day using yfinance historical closes with reconstructed regime scores.

**Tech Stack:** Python 3.14, yfinance, pandas, pytest

**Spec:** `docs/superpowers/specs/2026-03-21-auto-recovery-missed-days-design.md`

---

### Task 1: ML kwargs extension (DecisionLogger)

**Files:**
- Modify: `compass_ml_learning.py:515-536` (log_entry), `compass_ml_learning.py:602-628` (log_exit), `compass_ml_learning.py:905+` (log_daily_snapshot)
- Test: `tests/test_ml_kwargs.py` (new)

- [ ] **Step 1: Write failing test for log_entry with extra kwargs**

```python
# tests/test_ml_kwargs.py
import json, os, tempfile, pytest
from compass_ml_learning import DecisionLogger

@pytest.fixture
def logger(tmp_path):
    return DecisionLogger(str(tmp_path))

def test_log_entry_merges_kwargs(logger):
    dec_id = logger.log_entry(
        symbol='AAPL', sector='Technology', momentum_score=1.5,
        momentum_rank=0.9, entry_vol_ann=0.25, entry_daily_vol=0.016,
        adaptive_stop_pct=-0.08, trailing_stop_pct=-0.03,
        regime_score=0.6, max_positions_target=5, current_n_positions=3,
        portfolio_value=100000, portfolio_drawdown=0.0,
        current_leverage=1.0, crash_cooldown=0, trading_day=5,
        reconstructed=True, recovery_date='2026-03-21',
    )
    decisions_path = os.path.join(logger.data_dir, 'decisions.jsonl')
    with open(decisions_path) as f:
        lines = f.readlines()
    last = json.loads(lines[-1])
    assert last['reconstructed'] is True
    assert last['recovery_date'] == '2026-03-21'
    assert last['symbol'] == 'AAPL'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ml_kwargs.py::test_log_entry_merges_kwargs -v`
Expected: FAIL — `log_entry() got an unexpected keyword argument 'reconstructed'`

- [ ] **Step 3: Add `**kwargs` to DecisionLogger.log_entry**

In `compass_ml_learning.py`, add `**kwargs` to `log_entry` signature (after `source`), and merge into the record dict before appending:

```python
def log_entry(self, ..., source: str = "live", **kwargs) -> str:
    # ... existing code that builds record dict ...
    record_dict = record._asdict() if hasattr(record, '_asdict') else vars(record)
    # At the end, right before self._append_decision:
    record_dict.update(kwargs)
```

Apply the same pattern to `log_exit` and `log_daily_snapshot`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ml_kwargs.py -v`
Expected: PASS

- [ ] **Step 5: Write test for log_exit with kwargs**

```python
def test_log_exit_merges_kwargs(logger):
    logger.log_exit(
        symbol='AAPL', sector='Technology', exit_reason='hold_expired',
        entry_price=150.0, exit_price=155.0, pnl_usd=50.0,
        days_held=5, high_price=156.0, entry_vol_ann=0.25,
        entry_daily_vol=0.016, adaptive_stop_pct=-0.08,
        entry_momentum_score=1.5, entry_momentum_rank=0.9,
        regime_score=0.6, max_positions_target=5, current_n_positions=3,
        portfolio_value=100000, portfolio_drawdown=0.0,
        current_leverage=1.0, crash_cooldown=0, trading_day=10,
        reconstructed=True,
    )
    decisions_path = os.path.join(logger.data_dir, 'decisions.jsonl')
    with open(decisions_path) as f:
        lines = f.readlines()
    last = json.loads(lines[-1])
    assert last['reconstructed'] is True
    assert last['exit_reason'] == 'hold_expired'
```

- [ ] **Step 6: Run test, verify passes**

Run: `pytest tests/test_ml_kwargs.py -v`

- [ ] **Step 7: Commit**

```bash
git add compass_ml_learning.py tests/test_ml_kwargs.py
git commit -m "feat: add **kwargs to ML DecisionLogger for reconstructed flag support"
```

---

### Task 2: ML kwargs extension (COMPASSMLOrchestrator)

**Files:**
- Modify: `compass_ml_learning.py:1805-1826` (on_entry), `compass_ml_learning.py:1828-1860` (on_exit), `compass_ml_learning.py:1901+` (on_end_of_day)
- Test: `tests/test_ml_kwargs.py` (extend)

- [ ] **Step 1: Write failing test for orchestrator kwargs forwarding**

```python
def test_orchestrator_on_entry_forwards_kwargs(tmp_path):
    from compass_ml_learning import COMPASSMLOrchestrator
    ml = COMPASSMLOrchestrator(str(tmp_path))
    ml.on_entry(
        symbol='AAPL', sector='Technology', momentum_score=1.5,
        momentum_rank=0.9, entry_vol_ann=0.25, entry_daily_vol=0.016,
        adaptive_stop_pct=-0.08, trailing_stop_pct=-0.03,
        regime_score=0.6, max_positions_target=5, current_n_positions=3,
        portfolio_value=100000, portfolio_drawdown=0.0,
        current_leverage=1.0, crash_cooldown=0, trading_day=5,
        reconstructed=True, recovery_date='2026-03-21',
    )
    decisions_path = os.path.join(str(tmp_path), 'decisions.jsonl')
    with open(decisions_path) as f:
        last = json.loads(f.readlines()[-1])
    assert last['reconstructed'] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ml_kwargs.py::test_orchestrator_on_entry_forwards_kwargs -v`
Expected: FAIL — `on_entry() got an unexpected keyword argument 'reconstructed'`

- [ ] **Step 3: Add `**kwargs` to orchestrator methods, forward to logger**

In `on_entry`, `on_exit`, `on_end_of_day`: add `**kwargs` to signature and pass through to the logger call.

```python
def on_entry(self, ..., source: str = "live", **kwargs) -> str:
    try:
        return self.logger.log_entry(
            ..., source=source, **kwargs,
        )
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `pytest tests/test_ml_kwargs.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add compass_ml_learning.py tests/test_ml_kwargs.py
git commit -m "feat: forward **kwargs from ML orchestrator to DecisionLogger"
```

---

### Task 3: Helper functions (_trading_days_between, _recovery_price_dict)

**Files:**
- Modify: `omnicapital_live.py` (add two new methods to COMPASSLive)
- Test: `tests/test_auto_recovery.py` (new)

- [ ] **Step 1: Write failing tests for _trading_days_between**

```python
# tests/test_auto_recovery.py
import pytest
from datetime import date
from unittest.mock import MagicMock, patch
from omnicapital_live import COMPASSLive

@pytest.fixture
def trader(tmp_path):
    with patch.object(COMPASSLive, '__init__', lambda self, *a, **kw: None):
        t = object.__new__(COMPASSLive)
    return t

def test_trading_days_between_same_day(trader):
    assert trader._trading_days_between(date(2026, 3, 20), date(2026, 3, 20)) == 0

def test_trading_days_between_one_weekday(trader):
    # Thu → Fri = 1
    assert trader._trading_days_between(date(2026, 3, 19), date(2026, 3, 20)) == 1

def test_trading_days_between_over_weekend(trader):
    # Fri → Mon = 1 (weekend excluded)
    assert trader._trading_days_between(date(2026, 3, 20), date(2026, 3, 23)) == 1

def test_trading_days_between_full_week(trader):
    # Mon Mar 16 → Fri Mar 20 = 4
    assert trader._trading_days_between(date(2026, 3, 16), date(2026, 3, 20)) == 4

def test_trading_days_between_two_weeks(trader):
    # Fri Mar 6 → Fri Mar 20 = 10
    assert trader._trading_days_between(date(2026, 3, 6), date(2026, 3, 20)) == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auto_recovery.py -v -k trading_days`
Expected: FAIL — `AttributeError: _trading_days_between`

- [ ] **Step 3: Implement _trading_days_between**

```python
def _trading_days_between(self, start_date, end_date):
    """Count trading days (weekdays) between two dates, exclusive of start."""
    if start_date >= end_date:
        return 0
    count = 0
    current = start_date + timedelta(days=1)
    while current <= end_date:
        if current.weekday() < 5:  # Mon-Fri
            count += 1
        current += timedelta(days=1)
    return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_auto_recovery.py -v -k trading_days`
Expected: all PASS

- [ ] **Step 5: Write failing test for _recovery_price_dict**

```python
import pandas as pd, math

def test_recovery_price_dict_multiindex(trader):
    # Simulate yf.download with MultiIndex (multiple symbols)
    arrays = [['Close', 'Close', 'Volume'], ['AAPL', 'MSFT', 'AAPL']]
    cols = pd.MultiIndex.from_arrays(arrays)
    data = pd.DataFrame([[150.0, 300.0, 1000]], columns=cols)
    result = trader._recovery_price_dict(data, ['AAPL', 'MSFT'])
    assert result == {'AAPL': 150.0, 'MSFT': 300.0}

def test_recovery_price_dict_skips_nan(trader):
    arrays = [['Close', 'Close'], ['AAPL', 'MSFT']]
    cols = pd.MultiIndex.from_arrays(arrays)
    data = pd.DataFrame([[150.0, float('nan')]], columns=cols)
    result = trader._recovery_price_dict(data, ['AAPL', 'MSFT'])
    assert result == {'AAPL': 150.0}
    assert 'MSFT' not in result

def test_recovery_price_dict_skips_missing_symbol(trader):
    arrays = [['Close'], ['AAPL']]
    cols = pd.MultiIndex.from_arrays(arrays)
    data = pd.DataFrame([[150.0]], columns=cols)
    result = trader._recovery_price_dict(data, ['AAPL', 'GOOG'])
    assert result == {'AAPL': 150.0}
```

- [ ] **Step 6: Run test, verify fails**

Run: `pytest tests/test_auto_recovery.py -v -k recovery_price`

- [ ] **Step 7: Implement _recovery_price_dict**

```python
def _recovery_price_dict(self, data, symbols):
    """Convert yfinance DataFrame to {symbol: close_price} dict."""
    prices = {}
    is_multi = isinstance(data.columns, pd.MultiIndex)
    for sym in symbols:
        try:
            if is_multi:
                close = float(data['Close'][sym].iloc[-1])
            else:
                close = float(data['Close'].iloc[-1])
            if not math.isnan(close) and close > 0:
                prices[sym] = close
        except (KeyError, IndexError):
            continue
    return prices
```

- [ ] **Step 8: Run tests, verify all pass**

Run: `pytest tests/test_auto_recovery.py -v`

- [ ] **Step 9: Commit**

```bash
git add omnicapital_live.py tests/test_auto_recovery.py
git commit -m "feat: add _trading_days_between and _recovery_price_dict helpers"
```

---

### Task 4: Store _recovery_gap_baseline in load_state()

**Files:**
- Modify: `omnicapital_live.py:4448-4468` (load_state)
- Test: `tests/test_auto_recovery.py` (extend)

- [ ] **Step 1: Write failing test**

```python
def test_recovery_gap_baseline_preserved_before_validator(tmp_path):
    """Verify load_state stores raw last_trading_date before validator can reset it."""
    import json
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    # Write a state with a stale date (>7 days ago)
    state = {
        'version': '8.4', 'cash': 50000, 'peak_value': 100000,
        'portfolio_value': 50000, 'crash_cooldown': 0,
        'current_regime_score': 0.5, 'trading_day_counter': 10,
        'last_trading_date': '2026-03-10',  # stale by >7 days
        'positions': {}, 'position_meta': {},
        'portfolio_values_history': [],
    }
    with open(state_dir / 'compass_state_latest.json', 'w') as f:
        json.dump(state, f)

    with patch.object(COMPASSLive, '__init__', lambda self, *a, **kw: None):
        t = object.__new__(COMPASSLive)
    # Set minimal attrs needed by load_state
    t.state_dir = str(state_dir)
    t._last_persisted_trading_day_counter = None
    # ... (set other required attrs from __init__)

    t.load_state()
    assert t._recovery_gap_baseline == '2026-03-10'
```

Note: This test may need adjustment based on the exact attrs required by `load_state`. The key assertion is that `_recovery_gap_baseline` preserves the raw date even if the validator resets `last_trading_date`.

- [ ] **Step 2: Run test, verify fails**

Run: `pytest tests/test_auto_recovery.py::test_recovery_gap_baseline_preserved_before_validator -v`

- [ ] **Step 3: Add _recovery_gap_baseline to load_state**

In `omnicapital_live.py`, after line 4451 (`loaded_from = candidate; break`) and before `_validate_state()` at line 4468:

```python
        # Preserve raw last_trading_date for recovery gap detection
        # (validator may reset this if stale >7 days)
        self._recovery_gap_baseline = state.get('last_trading_date')
```

Also initialize `self._recovery_gap_baseline = None` in `__init__`.

- [ ] **Step 4: Run test, verify passes**

- [ ] **Step 5: Commit**

```bash
git add omnicapital_live.py tests/test_auto_recovery.py
git commit -m "feat: preserve raw last_trading_date as _recovery_gap_baseline in load_state"
```

---

### Task 5: Add _recovery_mode to execute_preclose_entries and _update_cycle_log_inner

**Files:**
- Modify: `omnicapital_live.py:2753+` (execute_preclose_entries), `omnicapital_live.py:3158+` (_update_cycle_log_inner)
- Test: `tests/test_auto_recovery.py` (extend)

- [ ] **Step 1: Add `_recovery_mode=False` param to execute_preclose_entries**

Add the parameter to the method signature. When `_recovery_mode=True`:
- Skip `_open_rattlesnake_positions()`, `_manage_catalyst_positions()`, `_manage_efa_position()` calls
- Set `self._recovery_mode = True` as instance flag before calling `_update_cycle_log`

```python
def execute_preclose_entries(self, prices=None, _recovery_mode=False):
    self._recovery_mode = _recovery_mode
    try:
        # ... existing exit/entry logic ...
        if _recovery_mode:
            pass  # skip Rattlesnake/Catalyst/EFA
        else:
            # existing HYDRA strategy calls
            ...
    finally:
        self._recovery_mode = False
```

- [ ] **Step 2: Modify _update_cycle_log_inner to use _recovery_spy_close**

In `_update_cycle_log_inner`, where `spy_close = self._get_spy_close()` is called:

```python
spy_close = getattr(self, '_recovery_spy_close', None) if getattr(self, '_recovery_mode', False) else self._get_spy_close()
```

Also add `reconstructed` and `recovery_date` fields to cycle log entry when in recovery mode.

- [ ] **Step 3: Write test verifying recovery mode skips Rattlesnake/Catalyst/EFA**

```python
def test_execute_preclose_recovery_mode_skips_hydra_strategies(trader):
    # Mock the strategy methods and verify they're NOT called in recovery mode
    trader._open_rattlesnake_positions = MagicMock()
    trader._manage_catalyst_positions = MagicMock()
    trader._manage_efa_position = MagicMock()
    # ... setup minimal state for execute_preclose_entries ...
    trader.execute_preclose_entries(prices={}, _recovery_mode=True)
    trader._open_rattlesnake_positions.assert_not_called()
    trader._manage_catalyst_positions.assert_not_called()
    trader._manage_efa_position.assert_not_called()
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_auto_recovery.py -v`

- [ ] **Step 5: Commit**

```bash
git add omnicapital_live.py tests/test_auto_recovery.py
git commit -m "feat: add _recovery_mode flag to execute_preclose_entries and _update_cycle_log_inner"
```

---

### Task 6: Implement _recover_missed_days()

**Files:**
- Modify: `omnicapital_live.py` (add method)
- Test: `tests/test_auto_recovery.py` (extend)

- [ ] **Step 1: Write failing test for gap detection — no gap**

```python
def test_recover_missed_days_no_gap(trader):
    """No recovery when last_trading_date is yesterday."""
    trader._recovery_gap_baseline = '2026-03-20'
    trader.trading_day_counter = 5
    trader.last_trading_date = date(2026, 3, 20)
    # Mock get_et_now to return Mar 21 (next trading day)
    trader.get_et_now = MagicMock(return_value=datetime(2026, 3, 21, 9, 30))

    result = trader._recover_missed_days()
    assert result == 0  # no days recovered
```

- [ ] **Step 2: Write failing test for gap detection — 3-day gap**

```python
@patch('omnicapital_live.yf')
def test_recover_missed_days_3day_gap(mock_yf, trader):
    """Should detect 3 missed days and attempt recovery."""
    trader._recovery_gap_baseline = '2026-03-17'  # Monday
    trader.trading_day_counter = 2
    trader.last_trading_date = date(2026, 3, 17)
    trader.get_et_now = MagicMock(return_value=datetime(2026, 3, 21, 9, 30))
    # ... setup mocks for yf.download, broker, etc.
    # Assert 3 days recovered (Tue 18, Wed 19, Thu 20)
```

- [ ] **Step 3: Write failing test for max 5-day cap**

```python
def test_recover_missed_days_exceeds_cap(trader, caplog):
    """Should log CRITICAL and skip when gap > 5 trading days."""
    trader._recovery_gap_baseline = '2026-03-06'
    trader.trading_day_counter = 1
    trader.get_et_now = MagicMock(return_value=datetime(2026, 3, 21, 9, 30))

    result = trader._recover_missed_days()
    assert result == 0
    assert 'Manual intervention required' in caplog.text
```

- [ ] **Step 4: Run tests, verify all fail**

Run: `pytest tests/test_auto_recovery.py -v -k recover_missed`

- [ ] **Step 5: Implement _recover_missed_days**

```python
def _recover_missed_days(self):
    """Detect and replay missed trading days using historical prices."""
    raw_date = self._recovery_gap_baseline
    if not raw_date:
        return 0

    try:
        last_date = date.fromisoformat(str(raw_date)[:10])
    except (ValueError, TypeError):
        return 0

    today = self.get_et_now().date()
    gap = self._trading_days_between(last_date, today)

    if gap <= 1:
        return 0

    if gap > 5:
        logger.critical(
            "Engine missed %d trading days (max 5 for auto-recovery). "
            "Manual intervention required.", gap
        )
        return 0

    logger.warning("[RECOVERY] Detected %d missed trading days (%s → %s)",
                   gap, last_date, today)

    recovered = 0
    current = last_date + timedelta(days=1)
    recovery_today = today.isoformat()

    while current < today:
        if current.weekday() >= 5:  # skip weekends
            current += timedelta(days=1)
            continue

        # Save engine state for restore
        saved = {
            '_spy_hist': self._spy_hist,
            '_hist_date': self._hist_date,
            '_preclose_entries_done': self._preclose_entries_done,
            '_daily_open_done': self._daily_open_done,
        }
        try:
            self._preclose_entries_done = False
            self._daily_open_done = False
            self._hist_date = None

            missed_str = current.isoformat()
            next_day = current + timedelta(days=1)

            # Step 1: Fetch historical closes
            symbols = list(self.broker.positions.keys()) + list(getattr(self, 'current_universe', []))
            symbols = list(set(symbols))
            data = yf.download(symbols, start=missed_str, end=next_day.isoformat(), progress=False)
            if data is None or len(data) == 0:
                logger.info("[RECOVERY] No data for %s (holiday?), skipping", missed_str)
                current += timedelta(days=1)
                continue

            prices = self._recovery_price_dict(data, symbols)
            if not prices:
                logger.info("[RECOVERY] No valid prices for %s, skipping", missed_str)
                current += timedelta(days=1)
                continue

            # Step 2: Reconstruct regime score
            spy_hist = yf.download('SPY', end=next_day.isoformat(), period='2y', progress=False)
            if isinstance(spy_hist.columns, pd.MultiIndex):
                spy_hist.columns = [c[0] for c in spy_hist.columns]
            if len(spy_hist) >= 252:
                self._spy_hist = spy_hist
                self.current_regime_score = self.compute_live_regime_score(spy_hist)

            # Step 3: Fetch ^GSPC close for cycle log
            gspc = yf.download('^GSPC', start=missed_str, end=next_day.isoformat(), progress=False)
            if isinstance(gspc.columns, pd.MultiIndex):
                gspc.columns = [c[0] for c in gspc.columns]
            if len(gspc) > 0:
                self._recovery_spy_close = float(gspc['Close'].iloc[-1])
            else:
                self._recovery_spy_close = None

            # Step 4: Run rotation or stops
            next_counter = self.trading_day_counter + 1
            is_rotation = (next_counter % self.CONFIG.get('HOLD_DAYS', 5) == 0)

            if is_rotation:
                self._preclose_entries_done = False
                self.execute_preclose_entries(prices, _recovery_mode=True)
            else:
                self.check_position_exits(prices)

            # Step 7: Increment state
            self.trading_day_counter += 1
            self.last_trading_date = current
            self.save_state()
            recovered += 1
            logger.info("[RECOVERY] Replayed %s (day %d, regime=%.3f%s)",
                        missed_str, self.trading_day_counter,
                        self.current_regime_score,
                        " ROTATION" if is_rotation else "")

        except Exception as e:
            logger.error("[RECOVERY] Failed on %s: %s", current, e, exc_info=True)
            break  # stop recovery, retry on next run_once
        finally:
            self._spy_hist = saved['_spy_hist']
            self._hist_date = saved['_hist_date']
            self._daily_open_done = saved['_daily_open_done']

        current += timedelta(days=1)

    if recovered:
        logger.info("[RECOVERY] Complete: %d days recovered", recovered)
    return recovered
```

- [ ] **Step 6: Run tests, verify they pass**

Run: `pytest tests/test_auto_recovery.py -v`

- [ ] **Step 7: Commit**

```bash
git add omnicapital_live.py tests/test_auto_recovery.py
git commit -m "feat: implement _recover_missed_days with historical replay"
```

---

### Task 7: Wire recovery into run_once()

**Files:**
- Modify: `omnicapital_live.py:4664-4675` (run_once)
- Test: `tests/test_auto_recovery.py` (extend)

- [ ] **Step 1: Write integration test**

```python
def test_run_once_calls_recovery_before_daily_open(trader):
    """Verify recovery runs before daily_open in run_once."""
    call_order = []
    trader._recover_missed_days = MagicMock(side_effect=lambda: call_order.append('recovery') or 0)
    original_daily_open = trader.daily_open
    trader.daily_open = MagicMock(side_effect=lambda: call_order.append('daily_open'))
    trader.is_new_trading_day = MagicMock(return_value=True)
    trader.is_market_open = MagicMock(return_value=False)
    trader.get_et_now = MagicMock(return_value=datetime(2026, 3, 21, 9, 30))

    trader.run_once()
    assert call_order == ['recovery', 'daily_open']
```

- [ ] **Step 2: Run test, verify fails**

Run: `pytest tests/test_auto_recovery.py::test_run_once_calls_recovery_before_daily_open -v`

- [ ] **Step 3: Modify run_once to call _recover_missed_days before daily_open**

In `run_once()`, change lines 4670-4674:

```python
            if self.is_new_trading_day():
                if self.is_market_open() or self.get_et_now().weekday() < 5:
                    self._recover_missed_days()  # ← NEW: before daily_open
                    self.daily_open()
                    self.save_state()
```

- [ ] **Step 4: Run test, verify passes**

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -v --timeout=60 -x`
Expected: no new failures from our changes

- [ ] **Step 6: Commit**

```bash
git add omnicapital_live.py tests/test_auto_recovery.py
git commit -m "feat: wire _recover_missed_days into run_once before daily_open"
```

---

### Task 8: End-to-end integration test

**Files:**
- Test: `tests/test_auto_recovery.py` (extend)

- [ ] **Step 1: Write idempotency test**

```python
@patch('omnicapital_live.yf')
def test_recovery_is_idempotent(mock_yf, trader):
    """Running recovery twice produces the same state."""
    # Setup: 2-day gap, mock yf.download
    # Run recovery once → save state
    # Run recovery again → should detect no gap (last_trading_date updated)
    # Assert trading_day_counter is same after both runs
```

- [ ] **Step 2: Write yfinance failure test**

```python
@patch('omnicapital_live.yf')
def test_recovery_skips_day_on_yf_failure(mock_yf, trader):
    """If yfinance returns empty DataFrame, skip that day gracefully."""
    mock_yf.download.return_value = pd.DataFrame()
    # Assert recovery returns 0, no crash, logs info about skipping
```

- [ ] **Step 3: Run all tests**

Run: `pytest tests/test_auto_recovery.py -v`
Expected: all PASS

- [ ] **Step 4: Run full test suite to check for regressions**

Run: `pytest tests/ -v --timeout=60`
Expected: no new failures

- [ ] **Step 5: Commit**

```bash
git add tests/test_auto_recovery.py
git commit -m "test: add idempotency and failure handling tests for auto-recovery"
```

---

### Task 9: Final push

- [ ] **Step 1: Push all commits**

```bash
git push
```

- [ ] **Step 2: Verify cloud deploy**

Wait ~60s for Render auto-deploy, then check:

```bash
curl -s https://omnicapital.onrender.com/api/health | python -m json.tool
```
