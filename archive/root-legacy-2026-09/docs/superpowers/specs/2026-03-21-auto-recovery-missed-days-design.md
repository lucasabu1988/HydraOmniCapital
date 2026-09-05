# Auto-Recovery for Missed Trading Days

**Date**: 2026-03-21
**Status**: Approved (rev 2 — post spec review)
**Author**: Lucas + Claude Opus 4.6

## Problem

When the HYDRA engine is down during a trading day, cycle rotations are missed. The Mar 20, 2026 incident required manual state editing (commit `2e264d6`) which introduced a corrupted SPY benchmark value, left the ML system with gaps, and required multiple follow-up fixes.

The engine's existing catch-up logic (`_missed_preclose`) only handles the case where the engine restarts *during* the same trading day. If an entire day is missed, the cycle log goes stale, positions don't rotate, and ML hooks never fire.

## Solution

A new `_recover_missed_days()` method in `omnicapital_live.py` that detects missed trading days on startup and replays each one sequentially using historical close prices, reconstructing the regime score, position exits/entries, cycle log updates, and ML events that would have occurred.

## Detection Logic

**CRITICAL**: Recovery runs BEFORE `daily_open()`, not after. `daily_open()` overwrites `last_trading_date` and increments `trading_day_counter` for today, which would destroy the gap signal.

The detection reads `last_trading_date` from the raw persisted state before `_validate_and_repair_state()` runs (the validator resets `last_trading_date` to `None` if stale by >7 calendar days, which could erase the gap baseline for 5-day recoveries spanning weekends).

```python
# In run_once(), BEFORE daily_open():
def run_once(self):
    if self.is_new_trading_day():
        recovered = self._recover_missed_days()  # ← runs first
        self.daily_open()                         # ← only after recovery

    if self.is_market_open():
        # ... normal trading logic
```

Gap detection:
```
raw_last_date = read last_trading_date from compass_state_latest.json directly
gap_days = trading_days_between(raw_last_date, today)

if gap_days <= 1:
    no recovery needed
elif gap_days <= 5:
    enter recovery mode
elif gap_days > 5:
    log CRITICAL, skip auto-recovery, require manual intervention
```

**Trading days calculation**: Exclude weekends (Saturday/Sunday). Holidays are not tracked — if the exchange was closed and yfinance returns no data for that date, the recovery skips that day gracefully.

## Recovery Sequence

For each missed trading day, in chronological order:

### Step 0: Save and Override Engine State

Before each missed day replay, save and temporarily override internal engine state:

```python
saved_spy_hist = self._spy_hist
saved_hist_date = self._hist_date
saved_preclose_done = self._preclose_entries_done
saved_daily_open_done = self._daily_open_done

try:
    self._preclose_entries_done = False
    self._daily_open_done = False
    self._hist_date = None  # force refresh_daily_data to re-fetch
    # ... Steps 1-7 ...
finally:
    self._spy_hist = saved_spy_hist
    self._hist_date = saved_hist_date
    self._daily_open_done = saved_daily_open_done
    # _preclose_entries_done stays as-is (set by Step 4)
```

This prevents stale internal state from contaminating the replay, and ensures mid-recovery crashes leave the engine in a recoverable state.

### Step 1: Fetch Historical Closes

```python
symbols = list(self.broker.positions.keys()) + self.current_universe
data = yf.download(symbols, start=missed_date, end=missed_date + 1day, progress=False)
```

If yfinance returns no data for the date (holiday, data outage), skip this day entirely.

**Convert to price dict** (mirrors `validate_batch()` logic):

```python
def _recovery_price_dict(data, symbols, missed_date) -> Dict[str, float]:
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

### Step 2: Reconstruct Regime Score

The actual function is `compute_live_regime_score(spy_hist)` — it takes only SPY history (not VIX). The regime score is computed from SPY trend (SMA200, 50d/200d cross, 20d momentum) and SPY volatility (10d vs 1y std).

```python
spy_hist = yf.download('SPY', end=missed_date + 1day, period='2y', progress=False)
if isinstance(spy_hist.columns, pd.MultiIndex):
    spy_hist.columns = [c[0] for c in spy_hist.columns]
self._spy_hist = spy_hist  # override for get_max_positions() and stop calcs
self.current_regime_score = self.compute_live_regime_score(spy_hist)
```

Note: `period='2y'` is required because `compute_live_regime_score` needs ≥252 rows (line 485) and `vol_score` needs ≥262 rows (line 513) — matches what `refresh_daily_data` fetches in live operation. This ensures `get_max_positions()` and adaptive stop calculations (which read `self._spy_hist` internally) use the correct historical data for the missed day.

### Step 3: Fetch Historical SPY Close for Cycle Log

```python
gspc_data = yf.download('^GSPC', start=missed_date, end=missed_date + 1day, progress=False)
spy_close_for_date = float(gspc_data['Close'].iloc[-1])  # for cycle log spy_end
```

This is stored and passed explicitly to `_update_cycle_log` (Step 5) to avoid the bug where `_get_spy_close()` always fetches today's data.

### Step 4: Run Rotation Logic (on rotation days)

On rotation days (`trading_day_counter + 1) % HOLD_DAYS == 0`), call `execute_preclose_entries()` which internally handles both exits and entries in the correct order. This avoids the double-exit-check problem of calling `check_position_exits()` separately.

```python
is_rotation_day = ((self.trading_day_counter + 1) % HOLD_DAYS == 0)
if is_rotation_day:
    self._preclose_entries_done = False
    # execute_preclose_entries handles exits + entries + cycle log internally
    self.execute_preclose_entries(historical_prices, _recovery_mode=True)
else:
    # Non-rotation day: only check stops
    self.check_position_exits(historical_prices)
```

**Recovery mode flag**: `execute_preclose_entries` receives `_recovery_mode=True` which:
- Skips Rattlesnake/Catalyst/EFA management (out of scope for recovery)
- Uses `self._recovery_spy_close` for cycle log instead of calling `_get_spy_close()`
- Uses the pre-fetched `historical_prices` dict for `_reconstruct_close_portfolio()` instead of re-downloading

**SPY price threading**: Before calling `execute_preclose_entries`, set `self._recovery_spy_close = spy_close_for_date`. Inside `_update_cycle_log_inner`, when `self._recovery_mode` is True, use `self._recovery_spy_close` instead of calling `_get_spy_close()`. This avoids changing the `_update_cycle_log` signature while keeping the recovery path clean.

### Step 5: Update Cycle Log with Correct SPY

If rotation occurred, `_update_cycle_log` is called (by `execute_preclose_entries` in recovery mode) with the historical SPY close from Step 3, not today's live price.

The cycle log entry gets an additional field:
```json
{
    "reconstructed": true,
    "recovery_date": "2026-03-21"
}
```

### Step 6: Log ML Events

Extend the ML pipeline to accept and propagate `**kwargs` through all layers:

```python
# In COMPASSMLOrchestrator (compass_ml_learning.py):
def on_entry(self, symbol, price, shares, meta, **kwargs):
    return self.logger.log_entry(symbol=symbol, ..., **kwargs)

# In DecisionLogger (compass_ml_learning.py):
def log_entry(self, symbol, price, shares, meta, **kwargs):
    record = { ... existing fields ... }
    record.update(kwargs)  # merges reconstructed=True if passed
    self._append_decision(record)
```

Both `COMPASSMLOrchestrator` methods AND `DecisionLogger` methods (`log_entry`, `log_exit`, `log_daily_snapshot`) must accept `**kwargs` and forward/merge them. The kwargs are merged at the `DecisionLogger` level right before writing the JSON record.

During recovery, all ML calls pass `reconstructed=True, recovery_date=today_str`:
```python
self.ml.on_exit(sym, price, shares, meta, reconstructed=True, recovery_date=today_str)
self.ml.on_entry(sym, price, shares, meta, reconstructed=True, recovery_date=today_str)
self.ml.on_end_of_day(prices, reconstructed=True, recovery_date=today_str)
```

### Step 7: Increment State

```python
self.trading_day_counter += 1
self.last_trading_date = missed_date_str
self.save_state()
logger.info("[RECOVERY] Replayed missed day %s (day %d)", missed_date_str, self.trading_day_counter)
```

Then proceed to the next missed day. After all missed days are recovered, `daily_open()` runs normally for today.

## Safety Constraints

### Max 5 Days

Beyond 5 missed trading days (1 full cycle), the system logs a `CRITICAL` warning and does NOT attempt auto-recovery. This bounds the blast radius of reconstructed trades and ensures human review for extended outages.

### No Double-Recovery

State is saved after each recovered day. If the engine crashes mid-recovery and restarts, `last_trading_date` already reflects the last successfully recovered day, so it picks up from there (idempotent).

### Atomic Per-Day

Each missed day is recovered independently. If recovery fails for day N (e.g., yfinance unavailable), days 1 through N-1 are already persisted and day N will be retried on the next `run_once()` cycle.

### State Override Safety

All internal state overrides (`_spy_hist`, `_hist_date`, `_preclose_entries_done`, `_daily_open_done`) are wrapped in `try/finally` to ensure restoration even on failure.

### Reconstructed Tag

All trades and ML events carry `"reconstructed": true`. This:
- Distinguishes them from live decisions in the ML training set
- Allows the cycle log to show they were auto-recovered
- Enables filtering in analytics dashboards

### State Validator Bypass

Recovery reads `last_trading_date` from raw state JSON before the validator runs. In `load_state()`, immediately after the candidate loop parses the raw JSON dict (line ~4448) but BEFORE `_validate_state()` is called (line ~4468):

```python
# In load_state(), after raw JSON is parsed, BEFORE _validate_state():
self._recovery_gap_baseline = state.get('last_trading_date')
# ... then _validate_state() runs and may reset last_trading_date
```

This preserves the original `last_trading_date` value that the validator may later erase (staleness >7 calendar days). `_recover_missed_days()` uses `self._recovery_gap_baseline` instead of `self.last_trading_date` for gap detection.

## Scope

### In Scope

- COMPASS rotation replay (momentum ranking, exit checks, position sizing)
- Regime score reconstruction (SPY trend via `compute_live_regime_score`)
- Cycle log close/open with date-specific SPY benchmark (^GSPC)
- ML event logging with `reconstructed` flag via `**kwargs`
- Adaptive stop calculations using historical SPY volatility

### Out of Scope

- **Rattlesnake/Catalyst/EFA replay** — these strategies are reactive to daily prices, not cyclical. Recovery skips them via `_recovery_mode=True`. Note: entry signals triggered on missed days will NOT be recovered. These strategies will self-correct for exits on the next live trading day, but missed entries are a known gap.
- **Notifications** — alerting (improvement area A) is a separate project.
- **Backfilling `daily_snapshots.jsonl`** — snapshots are informational, not decision-driving.

## Integration Point

```python
# In run_once(), BEFORE daily_open():
def run_once(self):
    if self.is_new_trading_day():
        self._recover_missed_days()  # ← runs FIRST (reads raw last_trading_date)
        self.daily_open()            # ← then increments counter for today

    if self.is_market_open():
        # ... normal trading logic
```

## Files Modified

| File | Change |
|------|--------|
| `omnicapital_live.py` | Add `_recover_missed_days()`, `_recovery_price_dict()`, `_trading_days_between()`. Modify `run_once()` to call recovery before `daily_open()`. Add `_recovery_mode` flag to `execute_preclose_entries()`. Add `_recovery_spy_close` instance var used by `_update_cycle_log_inner()` in recovery mode. Store `_recovery_gap_baseline` in `load_state()` before validator runs. |
| `compass_ml_learning.py` | Add `**kwargs` to both `COMPASSMLOrchestrator` methods (`on_entry`, `on_exit`, `on_end_of_day`) and `DecisionLogger` methods (`log_entry`, `log_exit`, `log_daily_snapshot`). Forward kwargs through orchestrator → logger. Merge into JSON record at logger level. |
| `tests/test_auto_recovery.py` | New test file: gap detection (1-day, 3-day, 5-day, 6-day), single-day replay with correct prices, multi-day sequential replay, rotation vs non-rotation day behavior, regime reconstruction accuracy, cycle log SPY benchmark correctness, ML reconstructed flag, idempotency (crash mid-recovery), yfinance failure graceful skip, state override save/restore, max-5-day cap with CRITICAL log. |

## Success Criteria

1. Engine restarts after 1–5 missed trading days → auto-recovers all COMPASS rotations
2. Cycle log shows correct positions, SPY benchmark, and returns for recovered days
3. ML decision log has no gaps — recovered events tagged `reconstructed: true`
4. Recovery is idempotent — crashing mid-recovery and restarting produces the same final state
5. Engine does NOT attempt recovery beyond 5 days — logs CRITICAL and waits
6. Regime score for each recovered day matches what `compute_live_regime_score` would have produced on that date
7. Internal engine state (`_spy_hist`, `_hist_date`, flags) is correctly restored after recovery completes or fails
