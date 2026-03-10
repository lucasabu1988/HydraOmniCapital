# IBKR Live Readiness Audit

**Date:** 2026-03-10
**Status:** Open — roadmap for PaperBroker → IBKR live migration
**Current state:** PaperBroker (mock), HYDRA v8.4 with EFA third pillar

---

## Phase 1: CRITICAL — Before Any IBKR Testing

### 1.1 Broker Factory
**Files:** `omnicapital_live.py:711`, `compass_dashboard.py:241-254`

`COMPASSLive.__init__()` always creates `PaperBroker`, ignoring `config['BROKER_TYPE']`. IBKRBroker isn't imported.

**Fix:** Add conditional broker instantiation based on config. Import IBKRBroker. Add CLI parameter `--broker IBKR` for dashboard startup.

### 1.2 Direct Broker State Manipulation
**Files:** `omnicapital_live.py:2482, 2499, 2052, 1761, 1825`

Code directly sets `self.broker.cash` and `self.broker.positions[symbol]`. In live IBKR these are read-only properties that query the broker API.

**Locations:**
- `load_state()` — sets `self.broker.cash = state.get('cash', ...)`
- `load_state()` — sets `self.broker.positions[symbol] = Position(...)`
- `reconcile_entry_prices()` — modifies `self.broker.positions[symbol].avg_cost`
- `_liquidate_efa()` — `self.broker.cash += proceeds`
- `_manage_efa_position()` — `self.broker.cash -= cost`

**Fix:** Replace direct attribute access with broker API methods. In live mode, broker state comes from IBKR, not from JSON. State load should validate against broker, not overwrite it.

### 1.3 EFA Trades Bypass Order Pipeline
**Files:** `omnicapital_live.py:1654-1764`

EFA buys/sells directly manipulate `broker.cash` instead of routing through `_submit_order()`. No commission, no audit trail, won't work on live IBKR.

**Fix:** Route EFA through `_submit_order(Order(...))`. Track EFA in `broker.positions` alongside COMPASS/Rattlesnake positions.

---

## Phase 2: HIGH — Before IBKR Paper Trading

### 2.1 State Reconciliation (Broker = Truth)
**Files:** `omnicapital_live.py:2482-2550`

`load_state()` restores positions from JSON into the broker, then calls `reconcile_positions()`. By then broker state is already corrupted with stale JSON. In live mode, IBKR's account is the source of truth.

**Fix:**
- Move reconciliation BEFORE position restoration
- `json_only` positions: log ERROR + alert (position lost)
- `broker_only` positions: fetch IBKR data, reconstruct position_meta
- `quantity_mismatch`: take broker's quantity as truth
- Cash reconciliation: use IBKR's available funds as ground truth

### 2.2 Partial Fill Handling
**Files:** `omnicapital_live.py:1159-1162, 1421-1430`

Code checks `result.status == 'FILLED'` but never validates `filled_quantity == quantity`. Partial MOC fills create silent position size mismatch.

**Fix:** Validate `order.filled_quantity == order.quantity`. For partial fills, adjust position size and position_meta. Log partial fills as WARNING.

### 2.3 No ib_async Error Handling
**Files:** `omnicapital_broker.py:1074-1120`

`_submit_live()` calls `ib.placeOrder()` and `ib.sleep()` with no try/except. Network drops, account restrictions, or API errors crash the engine.

**Fix:** Wrap `_submit_live()` in try/except. Catch Exception, return `order.status = 'ERROR'`. Add ib_async error callbacks for disconnect detection.

---

## Phase 3: MEDIUM — During IBKR Paper Trading

### 3.1 MOC Async Polling
**Files:** `omnicapital_broker.py:1074-1120`, `omnicapital_live.py:2650-2653`

MOC orders fill at 16:00 ET, not at submission. Current 5-second synchronous wait is insufficient. `_preclose_entries_done` flag set before fill confirmation prevents retries.

**Fix:** Store MOC orders in `_pending_orders`. Poll fill status in `run_once()` until 16:15 ET. Only set `_preclose_entries_done` after all fills confirmed or rejected.

### 3.2 Pending Order Persistence
**Files:** `omnicapital_live.py:2335-2425` (save_state)

`_pending_orders` dict is lost on restart. Engine doesn't know about in-flight orders after crash.

**Fix:** Persist `_pending_orders` to state JSON. On load, restore and poll IBKR for fill status.

### 3.3 Kill Switch Gaps
**Files:** `omnicapital_broker.py` (PaperBroker.submit_order)

Kill switch checked in main loop and IBKRBroker, but NOT in PaperBroker's `submit_order()`. Also not checked during data refresh.

**Fix:** Add kill switch check to PaperBroker.submit_order(). Check during data refresh.

---

## Phase 4: POLISH — Before Real Capital

### 4.1 Price Source Abstraction
System uses yfinance for signals but IBKR provides its own prices. PnL calculations can diverge.

**Fix:** In live mode, prefer IBKR's `ib.reqMktData()`. Log price discrepancies > 0.1%. Use IBKR fill prices for PnL, not yfinance.

### 4.2 Portfolio Concentration Limits
No check that single position exceeds X% of account or total exposure exceeds limits.

**Fix:** Add max single-position limit (e.g., 25% of portfolio). Add total exposure limit. Log and alert on breach.

### 4.3 Stale Price Window
300s max age for pre-close signal at 15:30 ET is too wide. Should be ~30s for order decisions.

**Fix:** Separate `max_age_seconds` for pre-close (30s) vs daily monitoring (300s).

### 4.4 Emergency Liquidation Mode
Current kill switch stops new trades but doesn't close positions.

**Fix:** Add `--emergency-liquidate` CLI mode that closes all positions at market.

---

## Summary Table

| # | Issue | Severity | Phase | Status |
|---|-------|----------|-------|--------|
| 1.1 | Broker factory missing | CRITICAL | 1 | Open |
| 1.2 | Direct broker state manipulation | CRITICAL | 1 | Open |
| 1.3 | EFA bypasses order pipeline | CRITICAL | 1 | Open |
| 2.1 | State reconciliation (broker = truth) | HIGH | 2 | Open |
| 2.2 | Partial fill handling | HIGH | 2 | Open |
| 2.3 | ib_async error handling | HIGH | 2 | Open |
| 3.1 | MOC async polling | MEDIUM | 3 | Open |
| 3.2 | Pending order persistence | MEDIUM | 3 | Open |
| 3.3 | Kill switch gaps | MEDIUM | 3 | Open |
| 4.1 | Price source abstraction | MEDIUM | 4 | Open |
| 4.2 | Portfolio concentration limits | MEDIUM | 4 | Open |
| 4.3 | Stale price window | MEDIUM | 4 | Open |
| 4.4 | Emergency liquidation | LOW | 4 | Open |
