# 4th Pillar (Catalyst) Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 4th pillar to HYDRA: 10% cross-asset trend following + 5% gold, reducing Momentum+Rattlesnake to 85% of capital.

**Architecture:** The Catalyst pillar is a permanent 15% allocation managed by `HydraCapitalManager`. It holds 2 sub-strategies: (a) cross-asset trend — equal-weight ETFs above SMA200 among SPY/EFA/TLT/GLD/DBC, rebalanced every 5 days; (b) gold — permanent GLD allocation. Catalyst positions are managed AFTER Rattlesnake but BEFORE EFA in the execution order. EFA continues to absorb remaining idle cash from Rattlesnake.

**Tech Stack:** Python 3.14, yfinance for data, PaperBroker for execution, Flask dashboard

**Backtest reference:** EXP68 — CAGR 14.42% -> 15.62%, Sharpe 0.908 -> 1.079, MaxDD -27% -> -21.7%

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `catalyst_signals.py` | CREATE | Signal generator: which trend assets to hold, gold allocation |
| `hydra_capital.py` | MODIFY | Add `catalyst_account`, adjust base allocations to 42.5/42.5/15 |
| `omnicapital_live.py` | MODIFY | Integrate Catalyst into execution flow, state persistence |
| `compass_dashboard_cloud.py` | MODIFY | Expose Catalyst positions in API response |
| `templates/dashboard.html` | MODIFY | Add Catalyst section to UI |
| `static/js/dashboard.js` | MODIFY | Render Catalyst positions |

---

### Task 1: Create Catalyst Signal Generator

**Files:**
- Create: `catalyst_signals.py`

- [ ] **Step 1: Create `catalyst_signals.py`**

```python
"""
Catalyst Signals -- 4th Pillar: Cross-Asset Trend + Gold
=========================================================
10% of capital: equal-weight among ETFs above their SMA200
5% of capital: permanent gold (GLD) allocation

Trend assets: SPY, EFA, TLT, GLD, DBC
Rule: every 5 days, hold those above 200-day SMA. If none qualify, cash.
Gold: always hold GLD (separate from trend basket).
"""
import logging
import pandas as pd
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Parameters
CATALYST_TREND_ASSETS = ['SPY', 'EFA', 'TLT', 'GLD', 'DBC']
CATALYST_GOLD_SYMBOL = 'GLD'
CATALYST_SMA_PERIOD = 200
CATALYST_REBALANCE_DAYS = 5  # Aligned with HYDRA's cycle

# Allocation within the 15% catalyst budget
CATALYST_TREND_WEIGHT = 0.667   # 10% of total = 2/3 of catalyst
CATALYST_GOLD_WEIGHT = 0.333    # 5% of total = 1/3 of catalyst


def compute_trend_holdings(hist_data: Dict[str, pd.DataFrame]) -> List[str]:
    """Determine which trend assets are above their SMA200.

    Args:
        hist_data: dict of {ticker: DataFrame with 'Close' column}

    Returns:
        List of tickers currently above SMA200
    """
    holdings = []
    for ticker in CATALYST_TREND_ASSETS:
        df = hist_data.get(ticker)
        if df is None or len(df) < CATALYST_SMA_PERIOD:
            continue
        close = float(df['Close'].iloc[-1])
        sma = float(df['Close'].iloc[-CATALYST_SMA_PERIOD:].mean())
        if close > sma:
            holdings.append(ticker)
    return holdings


def compute_catalyst_targets(hist_data: Dict[str, pd.DataFrame],
                              catalyst_budget: float,
                              current_prices: Dict[str, float]) -> List[Dict]:
    """Compute target positions for the Catalyst pillar.

    Args:
        hist_data: historical data per ticker
        catalyst_budget: total $ allocated to Catalyst (15% of portfolio)
        current_prices: current prices per ticker

    Returns:
        List of {symbol, target_shares, target_value, sub_strategy}
    """
    trend_budget = catalyst_budget * CATALYST_TREND_WEIGHT
    gold_budget = catalyst_budget * CATALYST_GOLD_WEIGHT

    targets = []

    # 1. Cross-asset trend: equal-weight among qualifying assets
    trend_holdings = compute_trend_holdings(hist_data)
    if trend_holdings:
        per_asset = trend_budget / len(trend_holdings)
        for ticker in trend_holdings:
            price = current_prices.get(ticker, 0)
            if price > 0:
                shares = int(per_asset / price)
                if shares > 0:
                    targets.append({
                        'symbol': ticker,
                        'target_shares': shares,
                        'target_value': shares * price,
                        'sub_strategy': 'trend',
                    })

    # 2. Gold: permanent allocation (GLD always)
    gold_price = current_prices.get(CATALYST_GOLD_SYMBOL, 0)
    if gold_price > 0:
        gold_shares = int(gold_budget / gold_price)
        if gold_shares > 0:
            # Check if GLD is already in trend targets
            existing = [t for t in targets if t['symbol'] == CATALYST_GOLD_SYMBOL]
            if existing:
                # Add gold budget shares on top of trend shares
                existing[0]['target_shares'] += gold_shares
                existing[0]['target_value'] += gold_shares * gold_price
                existing[0]['sub_strategy'] = 'trend+gold'
            else:
                targets.append({
                    'symbol': CATALYST_GOLD_SYMBOL,
                    'target_shares': gold_shares,
                    'target_value': gold_shares * gold_price,
                    'sub_strategy': 'gold',
                })

    return targets
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import py_compile; py_compile.compile('catalyst_signals.py')"`

- [ ] **Step 3: Commit**

```bash
git add catalyst_signals.py
git commit -m "feat: add catalyst_signals.py — 4th pillar signal generator"
```

---

### Task 2: Modify HydraCapitalManager

**Files:**
- Modify: `hydra_capital.py`

- [ ] **Step 1: Adjust base allocations and add catalyst_account**

Changes:
1. `BASE_COMPASS_ALLOC` = 0.425 (was 0.50)
2. `BASE_RATTLE_ALLOC` = 0.425 (was 0.50)
3. Add `BASE_CATALYST_ALLOC` = 0.15
4. Add `self.catalyst_account` in `__init__`
5. Include catalyst in `total_capital` property
6. Add `record_catalyst_trade()`, `update_catalyst_value()` methods
7. Add catalyst to `to_dict()` / `from_dict()` / `get_status()`
8. The `compute_allocation()` return dict should include `catalyst_budget`
9. Keep `MAX_COMPASS_ALLOC = 0.75` — recycling only from Rattlesnake idle

Key principle: Catalyst's 15% is **ring-fenced** — it does not participate in cash recycling. Momentum/Rattlesnake recycling works as before within their combined 85%.

- [ ] **Step 2: Verify syntax**

- [ ] **Step 3: Commit**

```bash
git add hydra_capital.py
git commit -m "feat: add catalyst_account to HydraCapitalManager (15% allocation)"
```

---

### Task 3: Integrate Catalyst into COMPASSLive

**Files:**
- Modify: `omnicapital_live.py`

- [ ] **Step 1: Add imports and constants**

At top of file, add:
```python
from catalyst_signals import (
    compute_catalyst_targets, compute_trend_holdings,
    CATALYST_TREND_ASSETS, CATALYST_GOLD_SYMBOL, CATALYST_REBALANCE_DAYS
)
```

Add constants near EFA constants:
```python
# Catalyst 4th Pillar (HYDRA: cross-asset trend + gold)
CATALYST_SYMBOLS = ['SPY', 'EFA', 'TLT', 'GLD', 'DBC']
```

- [ ] **Step 2: Add catalyst state to `__init__`**

After rattle_positions init (~line 794), add:
```python
self.catalyst_positions: List[dict] = []  # {symbol, shares, entry_price, sub_strategy}
self._catalyst_hist: Dict[str, pd.DataFrame] = {}  # historical data per catalyst asset
self._catalyst_day_counter = 0  # track days since last rebalance
```

- [ ] **Step 3: Add `_fetch_catalyst_data()` method**

Fetch historical data for all catalyst assets (similar to `_fetch_efa_data()`).
Called during daily data refresh. Store in `self._catalyst_hist`.

- [ ] **Step 4: Add `_manage_catalyst_positions()` method**

Logic:
1. Increment `_catalyst_day_counter`
2. If counter < CATALYST_REBALANCE_DAYS and positions exist, skip (hold)
3. Reset counter on rebalance
4. Call `compute_catalyst_targets()` with budget from `hydra_capital.catalyst_account`
5. Sell positions not in new targets
6. Buy positions in new targets (adjust shares to match target)
7. Update `self.catalyst_positions`
8. Update `hydra_capital.catalyst_account` with trade P&L

Important: Catalyst positions must be tracked separately from Momentum positions.
Use a tag in `position_meta` to distinguish: `'_catalyst': True`

- [ ] **Step 5: Add `_liquidate_catalyst_for_capital()` method**

Similar to `_liquidate_efa_for_capital()`. Called before active strategy entries
if Momentum or Rattlesnake desperately need cash (rare — Catalyst is ring-fenced
but safety valve in extreme scenarios).

- [ ] **Step 6: Insert into execution order**

In `execute_preclose_entries()`, the new order is:
```
1. Sell hold-expired COMPASS positions
2. Liquidate EFA if needed
3. Liquidate Catalyst if desperately needed (new)
4. Open new COMPASS positions
5. Open new Rattlesnake positions
6. Manage Catalyst positions (new — rebalance every 5 days)
7. Manage EFA (buy with remaining idle cash)
```

- [ ] **Step 7: Add catalyst to state persistence**

In the state dict (`save_state`), add:
```python
'catalyst_positions': self.catalyst_positions,
'catalyst_day_counter': self._catalyst_day_counter,
```

In `load_state()`, restore:
```python
self.catalyst_positions = state.get('hydra', {}).get('catalyst_positions', [])
self._catalyst_day_counter = state.get('hydra', {}).get('catalyst_day_counter', 0)
```

- [ ] **Step 8: Update HYDRA init log message**

```python
logger.info("HYDRA multi-strategy: ACTIVE (Momentum + Rattlesnake + Catalyst + EFA + Cash Recycling)")
```

- [ ] **Step 9: Verify syntax**

- [ ] **Step 10: Commit**

```bash
git add omnicapital_live.py
git commit -m "feat: integrate Catalyst 4th pillar into live engine"
```

---

### Task 4: Update Cloud Dashboard API

**Files:**
- Modify: `compass_dashboard_cloud.py`

- [ ] **Step 1: Expose catalyst_positions in HYDRA state**

In the `_compute_hydra_state()` or `/api/state` route, add catalyst data:
```python
'catalyst_positions': state.get('hydra', {}).get('catalyst_positions', []),
'catalyst_day_counter': state.get('hydra', {}).get('catalyst_day_counter', 0),
```

Also add catalyst_account to the capital manager status dict.

- [ ] **Step 2: Add live prices to catalyst positions**

Similar to how rattle_positions get enriched with current prices,
compute current P&L for each catalyst position.

- [ ] **Step 3: Verify syntax**

- [ ] **Step 4: Commit**

```bash
git add compass_dashboard_cloud.py
git commit -m "feat: expose Catalyst positions in cloud dashboard API"
```

---

### Task 5: Update Dashboard UI

**Files:**
- Modify: `templates/dashboard.html`
- Modify: `static/js/dashboard.js`

- [ ] **Step 1: Add Catalyst section in HTML**

After the Rattlesnake section and before P2P scatter, add a new
`positions-hero` section for Catalyst with:
- Header: "ESTRATEGIA 3 — Catalyst" with green diamond icon
- Summary stats: positions count, trend assets, gold allocation
- Positions grid (same card format as Momentum/Rattlesnake)

- [ ] **Step 2: Add `updateCatalyst(hydra)` function in JS**

Similar to the Rattlesnake rendering code. Display:
- Each catalyst position as a card with symbol, price, P&L
- Tag each position as "T" (trend) or "G" (gold)
- Show which assets are above/below SMA200

- [ ] **Step 3: Add Catalyst to HYDRA allocation bar**

The HYDRA allocation bar currently shows MOMENTUM | RATTLESNAKE.
Add CATALYST segment with a green color.

- [ ] **Step 4: Verify visually with Playwright**

- [ ] **Step 5: Commit**

```bash
git add templates/dashboard.html static/js/dashboard.js
git commit -m "feat: add Catalyst 4th pillar to dashboard UI"
```

---

### Task 6: Update local dashboard

**Files:**
- Modify: `compass_dashboard.py`

- [ ] **Step 1: Mirror cloud changes to local dashboard**

Same API changes as Task 4 but in `compass_dashboard.py`.

- [ ] **Step 2: Commit and push all**

```bash
git add -A
git commit -m "feat: complete 4th pillar implementation across engine + dashboard"
git push
```
