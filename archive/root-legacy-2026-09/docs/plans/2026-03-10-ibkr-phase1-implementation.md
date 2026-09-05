# IBKR Phase 1: Critical Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the 3 critical blockers that prevent switching from PaperBroker to IBKR: broker factory, direct state manipulation, and EFA order pipeline bypass.

**Architecture:** Add conditional broker creation based on config. Replace all direct `broker.cash`/`broker.positions` writes with proper API calls (`_submit_order`, `get_portfolio`). Route EFA trades through the order pipeline and track EFA in `broker.positions` like any other position.

**Tech Stack:** Python 3.14, existing `omnicapital_broker.py` (Order, PaperBroker, IBKRBroker), `omnicapital_live.py` (COMPASSLive)

---

### Task 1: Broker Factory

**Files:**
- Modify: `omnicapital_live.py:33` (imports)
- Modify: `omnicapital_live.py:710-716` (broker creation)

**Step 1: Add IBKRBroker import**

In `omnicapital_live.py:33`, change:
```python
from omnicapital_broker import PaperBroker, Order, Broker, Position
```
to:
```python
from omnicapital_broker import PaperBroker, IBKRBroker, Order, Broker, Position
```

**Step 2: Replace hardcoded PaperBroker with factory logic**

Replace `omnicapital_live.py:710-716`:
```python
        # Broker
        self.broker = PaperBroker(
            initial_cash=config['PAPER_INITIAL_CASH'],
            commission_per_share=config['COMMISSION_PER_SHARE'],
            max_fill_deviation=config.get('MAX_FILL_DEVIATION', 0.02)
        )
        self.broker.set_price_feed(self.data_feed)
```
with:
```python
        # Broker (factory based on config)
        broker_type = config.get('BROKER_TYPE', 'PAPER').upper()
        if broker_type == 'IBKR':
            self.broker = IBKRBroker(
                host=config.get('IBKR_HOST', '127.0.0.1'),
                port=config.get('IBKR_PORT', 7497),
                client_id=config.get('IBKR_CLIENT_ID', 1),
                mock=config.get('IBKR_MOCK', True),
                max_order_value=config.get('MAX_ORDER_VALUE', 50_000),
                price_feed=self.data_feed,
            )
        else:
            self.broker = PaperBroker(
                initial_cash=config['PAPER_INITIAL_CASH'],
                commission_per_share=config['COMMISSION_PER_SHARE'],
                max_fill_deviation=config.get('MAX_FILL_DEVIATION', 0.02)
            )
            self.broker.set_price_feed(self.data_feed)
        logger.info(f"Broker: {broker_type} ({'mock' if getattr(self.broker, 'mock', True) else 'LIVE'})")
```

**Step 3: Add IBKR config keys to CONFIG dict**

In `omnicapital_live.py` CONFIG dict (after line 172), add:
```python
    'IBKR_HOST': '127.0.0.1',
    'IBKR_PORT': 7497,       # 7497=paper, 7496=live
    'IBKR_CLIENT_ID': 1,
    'IBKR_MOCK': True,       # Start mock, switch to live later
    'MAX_ORDER_VALUE': 50_000,
```

**Step 4: Syntax check**

Run: `python -c "import py_compile; py_compile.compile('omnicapital_live.py')"`
Expected: No output (clean compile)

**Step 5: Commit**

```
feat: add broker factory — conditional PaperBroker/IBKRBroker creation from config
```

---

### Task 2: EFA Through Order Pipeline

Replace direct `broker.cash` manipulation in EFA methods with proper `_submit_order()` calls. Remove `self.efa_position` tracking — EFA goes into `broker.positions` like COMPASS positions. COMPASS position counting already filters by `position_meta`, so EFA in `broker.positions` won't interfere.

**Files:**
- Modify: `omnicapital_live.py:1654-1764` (_manage_efa_position, _liquidate_efa_for_capital)
- Modify: `omnicapital_live.py:775-779` (efa_position init)
- Modify: `omnicapital_live.py:2390-2397` (save_state hydra section)
- Modify: `omnicapital_live.py:2520-2532` (load_state hydra section)

**Step 1: Replace `_manage_efa_position` method**

Replace lines 1654-1727 with:
```python
    def _manage_efa_position(self, prices: Dict[str, float]):
        """Manage EFA third pillar: buy with idle cash, sell when needed.

        Called at the END of pre-close cycle, after all Momentum and Rattlesnake
        entries have been filled. Only truly idle cash flows to EFA.
        Uses _submit_order() for proper commission, audit trail, and IBKR compatibility.
        """
        if not self._hydra_available or not self.hydra_capital:
            return

        efa_price = prices.get(EFA_SYMBOL)
        if not efa_price or efa_price <= 0:
            if self._efa_hist is not None and len(self._efa_hist) > 0:
                efa_price = float(self._efa_hist['Close'].iloc[-1])
            else:
                return

        # Current EFA position from broker
        positions = self.broker.get_positions()
        efa_pos = positions.get(EFA_SYMBOL)
        efa_shares = efa_pos.shares if efa_pos else 0

        # Update hydra capital manager with current EFA value
        if efa_shares > 0 and self.hydra_capital:
            self.hydra_capital.efa_value = efa_shares * efa_price

        # Check if we should sell (EFA below SMA200)
        if efa_shares > 0 and not self._efa_above_sma200():
            order = Order(symbol=EFA_SYMBOL, action='SELL',
                          quantity=efa_shares, order_type='MARKET',
                          decision_price=efa_price)
            result = self._submit_order(order, prices)
            if result.status == 'FILLED':
                proceeds = result.filled_price * efa_shares
                logger.info(f"EFA SELL (below SMA200): {efa_shares} shares @ ${result.filled_price:.2f} = ${proceeds:,.0f}")
                if self.hydra_capital:
                    self.hydra_capital.sell_efa(proceeds)
            return

        # Check if we should buy (idle cash available and EFA above SMA200)
        if not self._efa_above_sma200():
            return

        portfolio = self.broker.get_portfolio()
        idle_cash = portfolio.cash * 0.90  # Keep 10% cash buffer

        if idle_cash < EFA_MIN_BUY:
            return

        shares = int(idle_cash / efa_price)
        if shares < 1:
            return

        order = Order(symbol=EFA_SYMBOL, action='BUY',
                      quantity=shares, order_type='MARKET',
                      decision_price=efa_price)
        result = self._submit_order(order, prices)
        if result.status == 'FILLED':
            cost = result.filled_price * shares
            logger.info(f"EFA BUY: {shares} shares @ ${result.filled_price:.2f} = ${cost:,.0f}")
            if self.hydra_capital:
                self.hydra_capital.buy_efa(cost)
```

**Step 2: Replace `_liquidate_efa_for_capital` method**

Replace lines 1729-1764 with:
```python
    def _liquidate_efa_for_capital(self, prices: Dict[str, float]):
        """Sell EFA to free capital for active strategies. Called BEFORE entries."""
        positions = self.broker.get_positions()
        efa_pos = positions.get(EFA_SYMBOL)
        if not efa_pos or efa_pos.shares <= 0:
            return

        efa_price = prices.get(EFA_SYMBOL)
        if not efa_price or efa_price <= 0:
            if self._efa_hist is not None and len(self._efa_hist) > 0:
                efa_price = float(self._efa_hist['Close'].iloc[-1])
            else:
                return

        # Check if active strategies need capital
        max_positions = self.get_max_positions()
        compass_positions = {s: p for s, p in positions.items() if s in self.position_meta}
        needed = max_positions - len(compass_positions)

        if needed <= 0:
            return  # No new positions needed, keep EFA

        portfolio = self.broker.get_portfolio()
        avg_position_cost = portfolio.total_value * 0.20
        if portfolio.cash >= avg_position_cost:
            return  # Enough cash already, keep EFA

        # Liquidate EFA
        shares = efa_pos.shares
        pnl = (efa_price - efa_pos.avg_cost) * shares
        order = Order(symbol=EFA_SYMBOL, action='SELL',
                      quantity=shares, order_type='MARKET',
                      decision_price=efa_price)
        result = self._submit_order(order, prices)
        if result.status == 'FILLED':
            proceeds = result.filled_price * shares
            logger.info(f"EFA LIQUIDATE (capital needed): {shares} shares @ ${result.filled_price:.2f} = ${proceeds:,.0f} (PnL: ${pnl:+,.0f})")
            if self.hydra_capital:
                self.hydra_capital.sell_efa(proceeds)
```

**Step 3: Remove `self.efa_position` from __init__**

In `omnicapital_live.py:778-779`, remove:
```python
        # EFA: Third pillar (idle cash → international)
        self.efa_position: Optional[dict] = None  # {shares, avg_cost, entry_date}
```

**Step 4: Update save_state — remove efa_position from hydra dict**

In `omnicapital_live.py:2396`, change:
```python
                'efa_position': self.efa_position,
```
to:
```python
                'efa_position': None,  # deprecated: EFA now tracked in broker.positions
```

**Step 5: Update load_state — remove efa_position restoration**

In `omnicapital_live.py:2525`, remove:
```python
            self.efa_position = hydra_state.get('efa_position')
```

And update the EFA log line at 2529 to read from broker:
```python
                efa_pos = self.broker.get_positions().get(EFA_SYMBOL)
                efa_str = f" | EFA={efa_pos.shares}sh" if efa_pos and efa_pos.shares > 0 else ""
```

**Step 6: Update status logging**

In `omnicapital_live.py:2588-2589`, change:
```python
            if self.efa_position and self.efa_position.get('shares', 0) > 0:
                hydra_str += f" | EFA:{self.efa_position['shares']}sh"
```
to:
```python
            efa_pos = self.broker.get_positions().get(EFA_SYMBOL)
            if efa_pos and efa_pos.shares > 0:
                hydra_str += f" | EFA:{efa_pos.shares}sh"
```

**Step 7: Syntax check**

Run: `python -c "import py_compile; py_compile.compile('omnicapital_live.py')"`

**Step 8: Commit**

```
feat: route EFA trades through _submit_order and track in broker.positions
```

---

### Task 3: Fix Direct State Manipulation in load_state

Replace direct `broker.cash` and `broker.positions` writes with conditional logic: in PaperBroker mode restore from JSON (current behavior); in IBKR mode use broker as source of truth and only reconcile.

**Files:**
- Modify: `omnicapital_live.py:2481-2503` (load_state portfolio restoration)
- Modify: `omnicapital_live.py:2050-2052` (reconcile_entry_prices)

**Step 1: Replace direct broker state restoration in load_state**

Replace lines 2481-2503:
```python
        # Restore portfolio state
        self.broker.cash = state.get('cash', self.config['PAPER_INITIAL_CASH'])
        self.peak_value = state.get('peak_value', self.config['PAPER_INITIAL_CASH'])

        # Restore drawdown / crash state
        self.crash_cooldown = state.get('crash_cooldown', 0)
        self.portfolio_values_history = state.get('portfolio_values_history', [])

        # Restore regime
        self.current_regime_score = state.get('current_regime_score', 0.5)

        # Restore counters
        self.trading_day_counter = state.get('trading_day_counter', 0)
        ltd = state.get('last_trading_date')
        self.last_trading_date = date.fromisoformat(ltd) if ltd else None

        # Restore positions
        for symbol, data in state.get('positions', {}).items():
            self.broker.positions[symbol] = Position(
                symbol=symbol,
                shares=data['shares'],
                avg_cost=data['avg_cost']
            )
```
with:
```python
        # Restore portfolio state
        self.peak_value = state.get('peak_value', self.config['PAPER_INITIAL_CASH'])

        # Restore drawdown / crash state
        self.crash_cooldown = state.get('crash_cooldown', 0)
        self.portfolio_values_history = state.get('portfolio_values_history', [])

        # Restore regime
        self.current_regime_score = state.get('current_regime_score', 0.5)

        # Restore counters
        self.trading_day_counter = state.get('trading_day_counter', 0)
        ltd = state.get('last_trading_date')
        self.last_trading_date = date.fromisoformat(ltd) if ltd else None

        # Restore positions — PaperBroker restores from JSON; IBKR uses broker as truth
        is_paper = isinstance(self.broker, PaperBroker)
        if is_paper:
            self.broker.cash = state.get('cash', self.config['PAPER_INITIAL_CASH'])
            for symbol, data in state.get('positions', {}).items():
                self.broker.positions[symbol] = Position(
                    symbol=symbol,
                    shares=data['shares'],
                    avg_cost=data['avg_cost']
                )
        else:
            # IBKR mode: broker has real positions, just log comparison
            broker_cash = self.broker.cash
            json_cash = state.get('cash', 0)
            if abs(broker_cash - json_cash) > 100:
                logger.warning(f"Cash mismatch: broker=${broker_cash:,.0f} vs state=${json_cash:,.0f}")
```

**Step 2: Guard direct avg_cost write in reconcile_entry_prices**

In `omnicapital_live.py:2050-2052`, change:
```python
                # Update broker's avg_cost too
                if symbol in self.broker.positions:
                    self.broker.positions[symbol].avg_cost = entry_close
```
to:
```python
                # Update broker's avg_cost (PaperBroker only — IBKR positions are read-only)
                if isinstance(self.broker, PaperBroker) and symbol in self.broker.positions:
                    self.broker.positions[symbol].avg_cost = entry_close
```

**Step 3: Move reconciliation before logging in load_state**

In the existing reconciliation block (lines 2543-2549), it already runs after position restore. For IBKR mode, we already skip JSON restore (step 1), so reconciliation compares state JSON vs broker reality — which is correct. No change needed.

**Step 4: Syntax check**

Run: `python -c "import py_compile; py_compile.compile('omnicapital_live.py')"`

**Step 5: Commit**

```
fix: guard direct broker state writes — PaperBroker only, IBKR uses broker as truth
```

---

### Task 4: Fix HydraCapitalManager.from_dict Bug

**Files:**
- Modify: `hydra_capital.py:191`

**Step 1: Include efa_value in total calculation**

In `hydra_capital.py:191`, change:
```python
        total = d['compass_account'] + d['rattle_account']
```
to:
```python
        total = d['compass_account'] + d['rattle_account'] + d.get('efa_value', 0.0)
```

**Step 2: Syntax check**

Run: `python -c "import py_compile; py_compile.compile('hydra_capital.py')"`

**Step 3: Commit**

```
fix: include efa_value in HydraCapitalManager.from_dict total calculation
```

---

### Task 5: Sync to compass/ and Final Verification

**Files:**
- Copy: `omnicapital_live.py` → `compass/live.py`
- Copy: `omnicapital_broker.py` → `compass/broker.py`
- Copy: `hydra_capital.py` → (if synced copy exists)

**Step 1: Sync files**

```bash
cp omnicapital_live.py compass/live.py
cp omnicapital_broker.py compass/broker.py
```

**Step 2: Syntax check all modified files**

```bash
python -c "import py_compile; py_compile.compile('omnicapital_live.py')"
python -c "import py_compile; py_compile.compile('hydra_capital.py')"
python -c "import py_compile; py_compile.compile('compass/live.py')"
```

**Step 3: Validate state JSON still loads**

```bash
python -c "import json; s=json.load(open('state/compass_state_latest.json')); print(f'OK: {len(s[\"positions\"])} positions, cash=${s[\"cash\"]:,.0f}')"
```

**Step 4: Commit and push**

```
chore: sync compass/ copies after Phase 1 IBKR readiness fixes
```
