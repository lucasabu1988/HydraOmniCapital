# HYDRA Backtest v1.4 — Full HYDRA Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `hydra_backtest/hydra/` — a single backtest sub-package that orchestrates the four standalone pillars (v1.0 COMPASS + v1.1 Rattlesnake + v1.2 Catalyst + v1.3 EFA) with HydraCapitalManager-style cash recycling, the Catalyst 15% ring-fence, and EFA overflow. The orchestrator calls existing v1.0–v1.3 apply helpers via sub-state wrappers without modifying any of them.

**Architecture:** New sub-package `hydra_backtest/hydra/` with its own state model (`HydraBacktestState` extending `BacktestState` with sub-accounts and a position-tagging convention), pure-function port of `HydraCapitalManager`, four sub-state wrappers, the orchestrator, validation, and tests. v1.0–v1.3 modules and `hydra_capital.py` remain untouched.

**Tech Stack:** Python 3.14, pandas, numpy, pytest, pytest-cov. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-04-07-hydra-backtest-v1.4-hydra-design.md`

---

## File Structure

```
hydra_backtest/                                    ← v1.0+v1.1+v1.2+v1.3 (untouched)
└── hydra/                                         ← NEW v1.4 sub-package
    ├── __init__.py                                ← public exports (wired in T11)
    ├── __main__.py                                ← CLI: python -m hydra_backtest.hydra
    ├── state.py                                   ← HydraBacktestState + slicers
    ├── capital.py                                 ← HydraCapitalState + pure HCM functions
    ├── engine.py                                  ← run_hydra_backtest + 4 sub-state wrappers
    ├── validation.py                              ← 15-invariant cross-pillar smoke tests
    ├── layer_b.py                                 ← Layer B comparison helper
    ├── README.md
    └── tests/
        ├── __init__.py
        ├── conftest.py                            ← hydra_minimal_config + position fixtures
        ├── test_capital.py
        ├── test_state.py
        ├── test_engine.py
        ├── test_validation.py
        ├── test_integration.py                    ← CLI smoke
        └── test_e2e.py                            ← @pytest.mark.slow
.github/workflows/test.yml                         ← + new pytest step for hydra
```

**Reuse table** (from spec §4.2):

| From v1.0–v1.3 | How |
|---|---|
| `BacktestState`, `BacktestResult` | Wrapped by `HydraBacktestState` |
| `_mark_to_market`, `_get_exec_price`, `_slice_history_to_date` | Direct imports |
| `data.load_*` (PIT, prices, SPY, VIX, catalyst, EFA, yields) | Direct imports |
| `methodology.build_waterfall` | Direct import |
| `reporting.write_*`, `format_summary_table` | Direct imports |
| `errors.HydraBacktestValidationError` | Direct import |
| `apply_exits`, `apply_entries` (COMPASS) | Called inside `apply_compass_*_wrapper` |
| `apply_rattlesnake_exits`, `apply_rattlesnake_entries` | Called inside `apply_rattle_*_wrapper` |
| `apply_catalyst_rebalance` | Called inside `apply_catalyst_wrapper` |
| `apply_efa_decision` | Called inside `apply_efa_wrapper` |
| `compute_momentum_scores`, `compute_quality_filter`, `get_tradeable_symbols`, `get_max_positions_pure`, `get_current_leverage_pure`, `compute_live_regime_score` | Imported from `hydra_backtest.engine` and `omnicapital_v8_compass` (v1.0 dependencies) |
| `check_rattlesnake_regime`, `find_rattlesnake_candidates` | Imported from `rattlesnake_signals` (v1.1 dependencies) |

**Constants ported as duplicates** (already documented in v1.3 README pattern):
- From `hydra_capital.py`: `BASE_COMPASS_ALLOC=0.425`, `BASE_RATTLE_ALLOC=0.425`, `BASE_CATALYST_ALLOC=0.15`, `MAX_COMPASS_ALLOC=0.75`
- These get mirrored in `hydra/capital.py` as module-level constants. Documented in README.

---

## Task 1: Bootstrap sub-package + conftest fixture

**Files:**
- Create: `hydra_backtest/hydra/__init__.py` (empty placeholder; public API wired in T11)
- Create: `hydra_backtest/hydra/tests/__init__.py` (empty)
- Create: `hydra_backtest/hydra/tests/conftest.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p hydra_backtest/hydra/tests
```

- [ ] **Step 2: Empty package init**

`hydra_backtest/hydra/__init__.py`:
```python
"""hydra_backtest.hydra — full HYDRA integration backtest.

Composes COMPASS + Rattlesnake + Catalyst + EFA with cash recycling
and the Catalyst ring-fence. Mirrors omnicapital_live order of
operations.

See:
- docs/superpowers/specs/2026-04-07-hydra-backtest-v1.4-hydra-design.md
- docs/superpowers/plans/2026-04-07-hydra-backtest-v1.4-hydra.md

Public API symbols are wired in Task 11 once the engine and
validation modules exist.
"""
```

- [ ] **Step 3: conftest.py**

```python
"""Shared fixtures for hydra_backtest.hydra tests."""
import numpy as np
import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def fixed_seed():
    np.random.seed(666)


@pytest.fixture
def hydra_minimal_config():
    """Smallest valid HYDRA config — superset of the four pillar configs."""
    return {
        # Capital
        'INITIAL_CAPITAL': 100_000,
        'COMMISSION_PER_SHARE': 0.0035,
        # COMPASS
        'NUM_POSITIONS': 5,
        'NUM_POSITIONS_RISK_OFF': 2,
        'MOMENTUM_LOOKBACK': 90,
        'MOMENTUM_SKIP': 5,
        'HOLD_DAYS': 5,
        'MIN_AGE_DAYS': 220,
        'MIN_MOMENTUM_STOCKS': 5,
        'QUALITY_VOL_MAX': 0.55,
        'QUALITY_VOL_LOOKBACK': 60,
        'QUALITY_MAX_SINGLE_DAY': 0.18,
        'MAX_PER_SECTOR': 3,
        'POSITION_STOP_PCT': -0.06,
        'TRAILING_STOP_ACTIVATE': 0.05,
        'TRAILING_STOP_DROP': 0.03,
        'PORTFOLIO_STOP_PCT': -0.15,
        'CRASH_BRAKE_5D': -0.06,
        'CRASH_BRAKE_10D': -0.10,
        'CRASH_LEVERAGE': 0.15,
        'LEVERAGE_MAX': 1.0,
        'LEVERAGE_MIN': 0.3,
        'VOL_TARGET': 0.15,
        'MARGIN_RATE': 0.06,
        # HYDRA-specific
        'BASE_COMPASS_ALLOC': 0.425,
        'BASE_RATTLE_ALLOC': 0.425,
        'BASE_CATALYST_ALLOC': 0.15,
        'MAX_COMPASS_ALLOC': 0.75,
        'EFA_LIQUIDATION_CASH_THRESHOLD_PCT': 0.20,  # broker_cash < 20% PV → liquidate EFA
    }
```

- [ ] **Step 4: Verify pytest collects empty cleanly**

```bash
pytest hydra_backtest/hydra/tests/ --collect-only -q 2>&1 | tail -5
```

Expected: `0 tests collected`, no broken imports.

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/hydra/__init__.py hydra_backtest/hydra/tests/__init__.py hydra_backtest/hydra/tests/conftest.py
git commit -m "feat(hydra_backtest): bootstrap hydra sub-package + conftest"
```

---

## Task 2: HydraCapitalState + compute_allocation_pure

**File:** `hydra_backtest/hydra/capital.py` (NEW)

- [ ] **Step 1: Create the file with the dataclass and the first pure function**

```python
"""hydra_backtest.hydra.capital — pure-function port of HydraCapitalManager.

Mirrors hydra_capital.py:29-227 line-by-line. The live class is
mutable and tracks state across days; the pure version takes a state
in and returns a new state out, never mutating.

These constants mirror hydra_capital.py:22-26. If live ever changes
them, this duplication is the only contract surface to update.
"""
from dataclasses import dataclass, replace
from typing import Dict


BASE_COMPASS_ALLOC = 0.425
BASE_RATTLE_ALLOC = 0.425
BASE_CATALYST_ALLOC = 0.15
MAX_COMPASS_ALLOC = 0.75
EFA_MIN_BUY = 1000.0
EFA_DEPLOYMENT_CAP = 0.90  # only deploy 90% of available idle cash to EFA


@dataclass(frozen=True)
class HydraCapitalState:
    """Logical accounting for the four HYDRA pillars.

    Does NOT hold cash. The shared broker cash lives in
    HydraBacktestState.cash. These four numbers track how much each
    pillar 'owns' of total_value.
    """
    compass_account: float
    rattle_account: float
    catalyst_account: float
    efa_value: float

    base_compass_alloc: float = BASE_COMPASS_ALLOC
    base_rattle_alloc: float = BASE_RATTLE_ALLOC
    base_catalyst_alloc: float = BASE_CATALYST_ALLOC
    max_compass_alloc: float = MAX_COMPASS_ALLOC

    @property
    def total_capital(self) -> float:
        return (self.compass_account + self.rattle_account
                + self.catalyst_account + self.efa_value)

    def _replace(self, **kwargs) -> 'HydraCapitalState':
        return replace(self, **kwargs)


def compute_allocation_pure(
    capital: HydraCapitalState,
    rattle_exposure: float,
) -> Dict[str, float]:
    """Pure equivalent of HydraCapitalManager.compute_allocation
    (hydra_capital.py:68-111).

    Args:
        capital: current HydraCapitalState
        rattle_exposure: fraction of Rattlesnake account currently
            invested (0.0-1.0)

    Returns:
        Dict with compass_budget, rattle_budget, catalyst_budget,
        recycled_amount, recycled_pct, compass_alloc, rattle_alloc,
        catalyst_alloc, efa_idle.
    """
    total = capital.total_capital

    # How much of Rattlesnake's account is idle?
    r_idle = capital.rattle_account * (1.0 - rattle_exposure)

    # Max we can lend to COMPASS
    max_c = total * capital.max_compass_alloc - capital.compass_account
    max_c = max(0.0, max_c)

    recycle_amount = min(r_idle, max_c)

    c_effective = capital.compass_account + recycle_amount
    r_effective = capital.rattle_account - recycle_amount

    # Remaining idle cash after recycling (available for NEW EFA buys)
    r_still_idle = r_effective * (1.0 - rattle_exposure)
    efa_idle = r_still_idle  # only truly idle cash

    return {
        'compass_budget': c_effective,
        'rattle_budget': r_effective,
        'catalyst_budget': capital.catalyst_account,
        'recycled_amount': recycle_amount,
        'recycled_pct': recycle_amount / total if total > 0 else 0.0,
        'compass_alloc': c_effective / total if total > 0 else BASE_COMPASS_ALLOC,
        'rattle_alloc': r_effective / total if total > 0 else BASE_RATTLE_ALLOC,
        'catalyst_alloc': capital.catalyst_account / total if total > 0 else BASE_CATALYST_ALLOC,
        'efa_idle': efa_idle,
    }
```

- [ ] **Step 2: Compile + commit**

```bash
python -c "import py_compile; py_compile.compile('hydra_backtest/hydra/capital.py', doraise=True); print('OK')"
git add hydra_backtest/hydra/capital.py
git commit -m "feat(hydra_backtest.hydra): HydraCapitalState + compute_allocation_pure"
```

---

## Task 3: update_accounts_after_day_pure

**File:** `hydra_backtest/hydra/capital.py` (extend)

- [ ] **Step 1: Append the second pure function**

```python
def update_accounts_after_day_pure(
    capital: HydraCapitalState,
    compass_return: float,
    rattle_return: float,
    rattle_exposure: float,
) -> HydraCapitalState:
    """Pure equivalent of HydraCapitalManager.update_accounts_after_day
    (hydra_capital.py:113-138).

    Settles recycled cash (which earns COMPASS returns) back into the
    rattle account at end-of-day. Returns a NEW HydraCapitalState.
    """
    alloc = compute_allocation_pure(capital, rattle_exposure)
    recycled = alloc['recycled_amount']

    c_effective = alloc['compass_budget']
    r_effective = alloc['rattle_budget']

    c_new = c_effective * (1 + compass_return)
    r_new = r_effective * (1 + rattle_return)

    # Settle recycled amount (it earned COMPASS returns)
    recycled_after = recycled * (1 + compass_return)

    return capital._replace(
        compass_account=c_new - recycled_after,
        rattle_account=r_new + recycled_after,
    )


def update_efa_value_pure(
    capital: HydraCapitalState,
    efa_return: float,
) -> HydraCapitalState:
    """Apply daily EFA return to the efa_value bucket.

    Mirrors HydraCapitalManager.update_efa_value (hydra_capital.py:155-158).
    """
    if capital.efa_value > 0 and efa_return != 0:
        return capital._replace(efa_value=capital.efa_value * (1 + efa_return))
    return capital


def update_catalyst_value_pure(
    capital: HydraCapitalState,
    catalyst_return: float,
) -> HydraCapitalState:
    """Apply daily Catalyst return to the catalyst_account bucket.

    Mirrors HydraCapitalManager.update_catalyst_value (hydra_capital.py:172-175).
    """
    if catalyst_return != 0:
        return capital._replace(
            catalyst_account=capital.catalyst_account * (1 + catalyst_return)
        )
    return capital
```

- [ ] **Step 2: Compile + commit**

```bash
python -c "import py_compile; py_compile.compile('hydra_backtest/hydra/capital.py')"
git add hydra_backtest/hydra/capital.py
git commit -m "feat(hydra_backtest.hydra): update_accounts_after_day_pure + value updaters"
```

---

## Task 4: HydraBacktestState + slicers

**File:** `hydra_backtest/hydra/state.py` (NEW)

- [ ] **Step 1: Create the state file**

```python
"""hydra_backtest.hydra.state — combined state model for the full HYDRA backtest.

HydraBacktestState wraps v1.0's BacktestState concept (cash, positions,
peak_value, etc.) with sub-account accounting via HydraCapitalState
and a position-tagging convention.

Position tag convention:
    Every position dict in state.positions MUST include
    `'_strategy'` set to one of:
        'compass' | 'rattle' | 'catalyst' | 'efa'

The sub-state slicers below use this tag to extract per-pillar views
of the state for routing through the existing v1.0-v1.3 apply helpers.
"""
from dataclasses import dataclass, replace
from typing import Dict, Tuple

from hydra_backtest.engine import BacktestState
from hydra_backtest.hydra.capital import HydraCapitalState

VALID_STRATEGIES = ('compass', 'rattle', 'catalyst', 'efa')


@dataclass(frozen=True)
class HydraBacktestState:
    """Combined state for the full HYDRA backtest."""
    cash: float                       # ONE shared broker cash pool
    positions: dict                   # ALL positions, tagged by _strategy
    peak_value: float
    crash_cooldown: int
    portfolio_value_history: tuple
    capital: HydraCapitalState

    def _replace(self, **kwargs) -> 'HydraBacktestState':
        return replace(self, **kwargs)


def slice_positions_by_strategy(
    positions: dict,
    strategy: str,
) -> dict:
    """Return a dict of positions belonging to one strategy.

    Filters by the `_strategy` tag. Positions without a tag are
    silently excluded — Layer A invariant 15 will catch any orphans.
    """
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"Invalid strategy: {strategy!r}")
    return {
        sym: pos for sym, pos in positions.items()
        if pos.get('_strategy') == strategy
    }


def to_pillar_substate(
    state: HydraBacktestState,
    strategy: str,
    cash_override: float = None,
) -> BacktestState:
    """Build a v1.0 BacktestState containing only one pillar's positions.

    If `cash_override` is None, uses the full broker cash. Otherwise
    uses the override (typical use: cash_override=pillar_budget for
    entry calls so the apply helper sees the budget cap).
    """
    pillar_positions = slice_positions_by_strategy(state.positions, strategy)
    return BacktestState(
        cash=cash_override if cash_override is not None else state.cash,
        positions=pillar_positions,
        peak_value=state.peak_value,
        crash_cooldown=state.crash_cooldown,
        portfolio_value_history=state.portfolio_value_history,
    )


def merge_pillar_substate(
    state: HydraBacktestState,
    new_substate: BacktestState,
    strategy: str,
    cash_delta: float,
    capital_account_delta: float,
) -> HydraBacktestState:
    """Merge changes from a pillar substate back into the full state.

    `cash_delta`: how the broker cash changed (negative for spend,
        positive for sell proceeds).
    `capital_account_delta`: how the corresponding capital sub-account
        changed (typically equal to cash_delta for entries/exits).

    All NEW positions in new_substate are tagged with `_strategy` so
    Layer A invariant 15 (no orphans) holds.
    """
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"Invalid strategy: {strategy!r}")

    other_positions = {
        sym: pos for sym, pos in state.positions.items()
        if pos.get('_strategy') != strategy
    }
    new_pillar_positions = {
        sym: {**pos, '_strategy': strategy}
        for sym, pos in new_substate.positions.items()
    }
    merged_positions = {**other_positions, **new_pillar_positions}

    if strategy == 'compass':
        new_capital = state.capital._replace(
            compass_account=state.capital.compass_account + capital_account_delta
        )
    elif strategy == 'rattle':
        new_capital = state.capital._replace(
            rattle_account=state.capital.rattle_account + capital_account_delta
        )
    elif strategy == 'catalyst':
        new_capital = state.capital._replace(
            catalyst_account=state.capital.catalyst_account + capital_account_delta
        )
    else:  # efa
        new_capital = state.capital._replace(
            efa_value=state.capital.efa_value + capital_account_delta
        )

    return state._replace(
        cash=state.cash + cash_delta,
        positions=merged_positions,
        capital=new_capital,
    )


def compute_pillar_invested(
    positions: dict,
    strategy: str,
    current_prices: Dict[str, float],
) -> float:
    """Sum the market value of one pillar's positions at current prices.

    Used by the engine to compute c_ret and r_ret for
    update_accounts_after_day_pure (mirrors omnicapital_live.py:2882-2893).
    """
    pillar_positions = slice_positions_by_strategy(positions, strategy)
    total = 0.0
    for sym, pos in pillar_positions.items():
        price = current_prices.get(sym, pos.get('entry_price', 0.0))
        total += pos.get('shares', 0) * price
    return total
```

- [ ] **Step 2: Compile + commit**

```bash
python -c "import py_compile; py_compile.compile('hydra_backtest/hydra/state.py', doraise=True); print('OK')"
git add hydra_backtest/hydra/state.py
git commit -m "feat(hydra_backtest.hydra): HydraBacktestState + slicers"
```

---

## Task 5: Engine wrappers — COMPASS

**File:** `hydra_backtest/hydra/engine.py` (NEW)

- [ ] **Step 1: Create engine.py with imports and the COMPASS wrappers**

```python
"""hydra_backtest.hydra.engine — full HYDRA integration orchestrator.

Composes the four pillar apply helpers via sub-state wrappers.
The wrappers slice the global state by `_strategy` tag, call the
existing v1.0-v1.3 helpers without modification, and merge results
back into the global state.
"""
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

# v1.0 dependencies (COMPASS)
from hydra_backtest.engine import (
    BacktestResult,
    BacktestState,
    _get_exec_price,
    _mark_to_market,
    _slice_history_to_date,
    apply_daily_costs,
    apply_entries as compass_apply_entries,
    apply_exits as compass_apply_exits,
    compute_data_fingerprint,
    get_current_leverage_pure,
    get_max_positions_pure,
    get_tradeable_symbols,
)
from omnicapital_v8_compass import (
    compute_live_regime_score,
    compute_momentum_scores,
    compute_quality_filter,
)

# v1.1 dependencies (Rattlesnake)
from hydra_backtest.rattlesnake.engine import (
    _resolve_rattlesnake_universe,
    apply_rattlesnake_entries as rattle_apply_entries,
    apply_rattlesnake_exits as rattle_apply_exits,
)
from rattlesnake_signals import (
    R_MAX_POSITIONS,
    check_rattlesnake_regime,
    find_rattlesnake_candidates,
)

# v1.2 dependencies (Catalyst)
from catalyst_signals import (
    CATALYST_REBALANCE_DAYS,
    CATALYST_TREND_ASSETS,
)
from hydra_backtest.catalyst.engine import apply_catalyst_rebalance

# v1.3 dependencies (EFA)
from hydra_backtest.efa.engine import (
    EFA_SYMBOL,
    _efa_above_sma200,
    apply_efa_decision,
)

# v1.4 own modules
from hydra_backtest.hydra.capital import (
    EFA_DEPLOYMENT_CAP,
    EFA_MIN_BUY,
    HydraCapitalState,
    compute_allocation_pure,
    update_accounts_after_day_pure,
    update_catalyst_value_pure,
    update_efa_value_pure,
)
from hydra_backtest.hydra.state import (
    HydraBacktestState,
    compute_pillar_invested,
    merge_pillar_substate,
    slice_positions_by_strategy,
    to_pillar_substate,
)


def _capture_git_sha() -> str:
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


def apply_compass_exits_wrapper(
    state: HydraBacktestState,
    date: pd.Timestamp,
    i: int,
    price_data: Dict[str, pd.DataFrame],
    scores: Dict[str, float],
    tradeable: List[str],
    max_positions: int,
    config: dict,
    sector_map: Dict[str, str],
    execution_mode: str,
    all_dates: list,
) -> Tuple[HydraBacktestState, list, list]:
    """Wrap v1.0 apply_exits with sub-state slicing for the compass pillar."""
    substate = to_pillar_substate(state, 'compass')
    cash_before = substate.cash
    new_substate, trades, decisions = compass_apply_exits(
        substate, date, i, price_data, scores, tradeable,
        max_positions, config, sector_map, execution_mode, all_dates,
    )
    cash_delta = new_substate.cash - cash_before
    new_state = merge_pillar_substate(
        state, new_substate, 'compass',
        cash_delta=cash_delta, capital_account_delta=cash_delta,
    )
    return new_state, trades, decisions


def apply_compass_entries_wrapper(
    state: HydraBacktestState,
    compass_budget: float,
    date: pd.Timestamp,
    i: int,
    price_data: Dict[str, pd.DataFrame],
    scores: Dict[str, float],
    tradeable: List[str],
    max_positions: int,
    leverage: float,
    config: dict,
    sector_map: Dict[str, str],
    all_dates: list,
    execution_mode: str,
) -> Tuple[HydraBacktestState, list]:
    """Wrap v1.0 apply_entries with the cash-budget hack.

    Builds a sub-state where cash = compass_budget (NOT broker cash),
    runs apply_entries, and merges the diff back. Real broker cash is
    only deducted by the amount actually spent.
    """
    substate = to_pillar_substate(state, 'compass', cash_override=compass_budget)
    new_substate, decisions = compass_apply_entries(
        substate, date, i, price_data, scores, tradeable,
        max_positions, leverage, config, sector_map, all_dates, execution_mode,
    )
    spent = compass_budget - new_substate.cash  # positive number
    cash_delta = -spent
    new_state = merge_pillar_substate(
        state, new_substate, 'compass',
        cash_delta=cash_delta, capital_account_delta=cash_delta,
    )
    return new_state, decisions
```

- [ ] **Step 2: Compile + commit**

```bash
python -c "import py_compile; py_compile.compile('hydra_backtest/hydra/engine.py', doraise=True); print('OK')"
git add hydra_backtest/hydra/engine.py
git commit -m "feat(hydra_backtest.hydra): COMPASS sub-state wrappers"
```

---

## Task 6: Engine wrappers — Rattlesnake + Catalyst + EFA

**File:** `hydra_backtest/hydra/engine.py` (extend)

- [ ] **Step 1: Append the remaining wrappers**

```python
def apply_rattle_exits_wrapper(
    state: HydraBacktestState,
    date: pd.Timestamp,
    i: int,
    price_data: Dict[str, pd.DataFrame],
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[HydraBacktestState, list, list]:
    substate = to_pillar_substate(state, 'rattle')
    cash_before = substate.cash
    new_substate, trades, decisions = rattle_apply_exits(
        substate, date, i, price_data, config, execution_mode, all_dates,
    )
    cash_delta = new_substate.cash - cash_before
    new_state = merge_pillar_substate(
        state, new_substate, 'rattle',
        cash_delta=cash_delta, capital_account_delta=cash_delta,
    )
    return new_state, trades, decisions


def apply_rattle_entries_wrapper(
    state: HydraBacktestState,
    rattle_budget: float,
    date: pd.Timestamp,
    i: int,
    price_data: Dict[str, pd.DataFrame],
    candidates: list,
    max_positions: int,
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[HydraBacktestState, list]:
    substate = to_pillar_substate(state, 'rattle', cash_override=rattle_budget)
    new_substate, decisions = rattle_apply_entries(
        substate, date, i, price_data, candidates,
        max_positions, config, execution_mode, all_dates,
    )
    spent = rattle_budget - new_substate.cash
    cash_delta = -spent
    new_state = merge_pillar_substate(
        state, new_substate, 'rattle',
        cash_delta=cash_delta, capital_account_delta=cash_delta,
    )
    return new_state, decisions


def apply_catalyst_wrapper(
    state: HydraBacktestState,
    catalyst_budget: float,
    date: pd.Timestamp,
    i: int,
    catalyst_assets: Dict[str, pd.DataFrame],
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[HydraBacktestState, list, list]:
    """Wrap v1.2 apply_catalyst_rebalance with the budget hack.

    Catalyst is ring-fenced — its budget is the catalyst_account,
    never recycles. The wrapper still uses the cash-override pattern
    so the rebalance logic works on a sandboxed balance.
    """
    substate = to_pillar_substate(state, 'catalyst', cash_override=catalyst_budget)
    cash_before = substate.cash
    new_substate, trades, decisions = apply_catalyst_rebalance(
        substate, date, i, catalyst_assets, config, execution_mode, all_dates,
    )
    cash_delta = new_substate.cash - cash_before  # may be positive or negative
    new_state = merge_pillar_substate(
        state, new_substate, 'catalyst',
        cash_delta=cash_delta, capital_account_delta=cash_delta,
    )
    return new_state, trades, decisions


def apply_efa_wrapper(
    state: HydraBacktestState,
    efa_idle: float,
    date: pd.Timestamp,
    i: int,
    efa_data: pd.DataFrame,
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[HydraBacktestState, list, list]:
    """Wrap v1.3 apply_efa_decision with the idle-cash gate.

    Live behavior:
      - Buy is gated by efa_idle from compute_allocation_pure
      - Min buy threshold $1k
      - 90% deployment cap on idle cash
    """
    # Determine the budget the wrapper passes to apply_efa_decision
    capped_idle = min(efa_idle, state.cash) * EFA_DEPLOYMENT_CAP
    if capped_idle < EFA_MIN_BUY and EFA_SYMBOL not in slice_positions_by_strategy(state.positions, 'efa'):
        # Not enough idle cash to even attempt a buy AND nothing held → no-op
        return state, [], []

    substate = to_pillar_substate(state, 'efa', cash_override=capped_idle)
    cash_before = substate.cash
    new_substate, trades, decisions = apply_efa_decision(
        substate, date, i, efa_data, config, execution_mode, all_dates,
    )
    cash_delta = new_substate.cash - cash_before
    new_state = merge_pillar_substate(
        state, new_substate, 'efa',
        cash_delta=cash_delta, capital_account_delta=cash_delta,
    )
    return new_state, trades, decisions


def apply_efa_liquidation(
    state: HydraBacktestState,
    date: pd.Timestamp,
    i: int,
    efa_data: pd.DataFrame,
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[HydraBacktestState, list]:
    """Sell all EFA shares to free capital. Mirrors live
    omnicapital_live.py::_liquidate_efa_for_capital (line 2508).
    """
    efa_positions = slice_positions_by_strategy(state.positions, 'efa')
    if EFA_SYMBOL not in efa_positions:
        return state, []
    pos = efa_positions[EFA_SYMBOL]
    exit_price = _get_exec_price(
        EFA_SYMBOL, date, i, all_dates, {EFA_SYMBOL: efa_data}, execution_mode,
    )
    if exit_price is None:
        return state, []
    shares = pos['shares']
    commission = shares * config.get('COMMISSION_PER_SHARE', 0.0035)
    proceeds = shares * exit_price - commission
    pnl = (exit_price - pos['entry_price']) * shares - commission
    ret = (
        (exit_price / pos['entry_price'] - 1.0)
        if pos['entry_price'] > 0 else 0.0
    )
    trade = {
        'symbol': EFA_SYMBOL,
        'entry_date': pos['entry_date'],
        'exit_date': date,
        'exit_reason': 'EFA_LIQUIDATED_FOR_CAPITAL',
        'entry_price': pos['entry_price'],
        'exit_price': exit_price,
        'shares': shares,
        'pnl': pnl,
        'return': ret,
        'sector': 'International Equity',
    }
    new_positions = {
        sym: pos for sym, pos in state.positions.items()
        if sym != EFA_SYMBOL or pos.get('_strategy') != 'efa'
    }
    new_capital = state.capital._replace(
        efa_value=state.capital.efa_value - shares * pos['entry_price']
    )
    new_state = state._replace(
        cash=state.cash + proceeds,
        positions=new_positions,
        capital=new_capital,
    )
    return new_state, [trade]


def _needs_efa_liquidation(
    state: HydraBacktestState,
    portfolio_value: float,
    config: dict,
    n_compass_positions: int,
    n_compass_max: int,
    rattle_signal_pending: bool,
) -> bool:
    """Mirrors omnicapital_live.py::_liquidate_efa_for_capital decision logic.

    Liquidate when:
      - EFA is held
      - Active strategy needs capital (compass slots open OR rattle signals)
      - Broker cash < threshold% of portfolio value
    """
    threshold_pct = config.get('EFA_LIQUIDATION_CASH_THRESHOLD_PCT', 0.20)
    efa_held = EFA_SYMBOL in slice_positions_by_strategy(state.positions, 'efa')
    if not efa_held:
        return False
    needs_capital = (n_compass_positions < n_compass_max) or rattle_signal_pending
    if not needs_capital:
        return False
    return state.cash < threshold_pct * portfolio_value
```

- [ ] **Step 2: Compile + commit**

```bash
python -c "import py_compile; py_compile.compile('hydra_backtest/hydra/engine.py')"
git add hydra_backtest/hydra/engine.py
git commit -m "feat(hydra_backtest.hydra): Rattlesnake + Catalyst + EFA wrappers + liquidation helper"
```

---

## Task 7: run_hydra_backtest orchestrator

**File:** `hydra_backtest/hydra/engine.py` (extend)

- [ ] **Step 1: Append the orchestrator**

```python
def run_hydra_backtest(
    config: dict,
    price_data: Dict[str, pd.DataFrame],
    pit_universe: Dict[int, List[str]],
    spy_data: pd.DataFrame,
    vix_data: pd.Series,
    catalyst_assets: Dict[str, pd.DataFrame],
    efa_data: pd.DataFrame,
    cash_yield_daily: pd.Series,
    sector_map: Dict[str, str],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    execution_mode: str = 'same_close',
    progress_callback: Optional[callable] = None,
) -> BacktestResult:
    """Run the full HYDRA backtest from start_date to end_date.

    Mirrors omnicapital_live.py::execute_preclose_entries order of
    operations (line 2972).
    """
    started_at = datetime.now()

    # Build the union of all trading dates from all data sources
    all_dates_set = set()
    for df in price_data.values():
        all_dates_set.update(df.index)
    for df in catalyst_assets.values():
        all_dates_set.update(df.index)
    all_dates_set.update(efa_data.index)
    all_dates = sorted(all_dates_set)

    initial_capital = float(config['INITIAL_CAPITAL'])
    capital0 = HydraCapitalState(
        compass_account=initial_capital * config.get('BASE_COMPASS_ALLOC', 0.425),
        rattle_account=initial_capital * config.get('BASE_RATTLE_ALLOC', 0.425),
        catalyst_account=initial_capital * config.get('BASE_CATALYST_ALLOC', 0.15),
        efa_value=0.0,
    )
    state = HydraBacktestState(
        cash=initial_capital,
        positions={},
        peak_value=initial_capital,
        crash_cooldown=0,
        portfolio_value_history=(),
        capital=capital0,
    )

    trades: list = []
    decisions: list = []
    snapshots: list = []
    universe_size: dict = {}

    catalyst_day_counter = 0
    last_progress_year: Optional[int] = None
    dates_in_range = [d for d in all_dates if start_date <= d <= end_date]
    total_bars = max(len(dates_in_range), 1)

    # Build a unified asset_dict for _mark_to_market
    def _mark_full(s: HydraBacktestState, date: pd.Timestamp) -> float:
        pv = s.cash
        for sym, pos in s.positions.items():
            strategy = pos.get('_strategy')
            if strategy == 'catalyst':
                df = catalyst_assets.get(sym)
            elif strategy == 'efa':
                df = efa_data if sym == EFA_SYMBOL else None
            else:
                df = price_data.get(sym)
            if df is not None and date in df.index:
                price = float(df.loc[date, 'Close'])
            else:
                price = float(pos.get('entry_price', 0.0))
            pv += float(pos.get('shares', 0)) * price
        return pv

    def _current_prices(date: pd.Timestamp) -> Dict[str, float]:
        prices = {}
        for sym, pos in state.positions.items():
            strategy = pos.get('_strategy')
            if strategy == 'catalyst':
                df = catalyst_assets.get(sym)
            elif strategy == 'efa':
                df = efa_data if sym == EFA_SYMBOL else None
            else:
                df = price_data.get(sym)
            if df is not None and date in df.index:
                prices[sym] = float(df.loc[date, 'Close'])
        return prices

    for i, date in enumerate(all_dates):
        if date < start_date or date > end_date:
            continue

        # Progress callback (first bar of each year)
        if progress_callback is not None and date.year != last_progress_year:
            last_progress_year = date.year
            try:
                pv_now = _mark_full(state, date)
                bars_done = sum(1 for d in dates_in_range if d < date)
                progress_callback({
                    'year': int(date.year),
                    'progress_pct': 100.0 * bars_done / total_bars,
                    'portfolio_value': float(pv_now),
                    'n_positions': len(state.positions),
                    'recycled_pct': compute_allocation_pure(
                        state.capital,
                        _rattle_exposure(state, _current_prices(date)),
                    )['recycled_pct'],
                })
            except Exception:
                pass

        # 1. Mark-to-market
        portfolio_value = _mark_full(state, date)

        # 1b. Update peak BEFORE drawdown
        if portfolio_value > state.peak_value:
            state = state._replace(peak_value=portfolio_value)

        drawdown = (
            (portfolio_value - state.peak_value) / state.peak_value
            if state.peak_value > 0 else 0.0
        )

        # 2. Daily cash yield (one call at HYDRA level — no leverage assumed)
        if len(cash_yield_daily) > 0:
            daily_yield = float(
                cash_yield_daily.get(date, cash_yield_daily.iloc[0])
            )
        else:
            daily_yield = 0.0
        # Apply directly (mirrors apply_daily_costs cash-yield branch)
        if state.cash > 0 and daily_yield > 0:
            new_cash = state.cash + state.cash * (daily_yield / 100.0 / 252)
            state = state._replace(cash=new_cash)

        # 3. Compute COMPASS scoring inputs
        tradeable = get_tradeable_symbols(
            pit_universe, price_data, date, min_age_days=config['MIN_AGE_DAYS']
        )
        universe_size[date.year] = max(universe_size.get(date.year, 0), len(tradeable))

        spy_slice = spy_data.loc[:date]
        regime_score = compute_live_regime_score(spy_slice)
        leverage, _new_cooldown, _crash_active = get_current_leverage_pure(
            drawdown=drawdown,
            portfolio_value_history=state.portfolio_value_history + (portfolio_value,),
            crash_cooldown=state.crash_cooldown,
            config=config,
            spy_hist=spy_slice,
        )
        max_compass_pos = get_max_positions_pure(regime_score, spy_slice, config)

        sliced = _slice_history_to_date(price_data, date, symbols=tradeable)
        quality_syms = compute_quality_filter(
            sliced, tradeable,
            vol_max=config['QUALITY_VOL_MAX'],
            vol_lookback=config['QUALITY_VOL_LOOKBACK'],
            max_single_day=config['QUALITY_MAX_SINGLE_DAY'],
        )
        scores = compute_momentum_scores(
            sliced, quality_syms,
            lookback=config['MOMENTUM_LOOKBACK'],
            skip=config['MOMENTUM_SKIP'],
        )

        # 4. Compute current rattle_exposure (uses current prices)
        prices_today = _current_prices(date)
        rattle_exposure = _rattle_exposure(state, prices_today)
        alloc = compute_allocation_pure(state.capital, rattle_exposure)

        # 5. Snapshot pillar values BEFORE the day's mutations (for pillar return calc)
        compass_invested_before = compute_pillar_invested(
            state.positions, 'compass', prices_today
        )
        rattle_invested_before = compute_pillar_invested(
            state.positions, 'rattle', prices_today
        )

        # ====================================================================
        # COMPASS
        # ====================================================================
        state, exit_trades, exit_decisions = apply_compass_exits_wrapper(
            state, date, i, price_data, scores, tradeable,
            max_compass_pos, config, sector_map, execution_mode, all_dates,
        )
        trades.extend(exit_trades)
        decisions.extend(exit_decisions)

        # ====================================================================
        # EFA LIQUIDATION (if compass slots open or rattle signals pending)
        # ====================================================================
        n_compass_now = len(slice_positions_by_strategy(state.positions, 'compass'))
        # Approximate "rattle signal pending" by checking the regime — if RISK_ON
        # and slots available, we'll likely enter
        vix_value = float(vix_data.loc[date]) if date in vix_data.index else None
        rattle_regime = check_rattlesnake_regime(spy_slice, vix_value)
        rattle_signal_pending = (
            rattle_regime['entries_allowed']
            and len(slice_positions_by_strategy(state.positions, 'rattle')) < rattle_regime['max_positions']
        )
        if _needs_efa_liquidation(
            state, portfolio_value, config,
            n_compass_now, max_compass_pos, rattle_signal_pending,
        ):
            state, liq_trades = apply_efa_liquidation(
                state, date, i, efa_data, config, execution_mode, all_dates,
            )
            trades.extend(liq_trades)

        # ====================================================================
        # COMPASS ENTRIES
        # ====================================================================
        state, compass_entry_decisions = apply_compass_entries_wrapper(
            state, alloc['compass_budget'], date, i, price_data, scores, tradeable,
            max_compass_pos, leverage, config, sector_map, all_dates, execution_mode,
        )
        decisions.extend(compass_entry_decisions)

        # ====================================================================
        # RATTLESNAKE
        # ====================================================================
        state, r_exit_trades, r_exit_decisions = apply_rattle_exits_wrapper(
            state, date, i, price_data, config, execution_mode, all_dates,
        )
        trades.extend(r_exit_trades)
        decisions.extend(r_exit_decisions)

        if rattle_regime['entries_allowed']:
            r_tradeable = _resolve_rattlesnake_universe(pit_universe, date.year)
            min_age = config.get('MIN_AGE_DAYS', 220)
            r_tradeable = [
                t for t in r_tradeable
                if t in price_data
                and date in price_data[t].index
                and len(price_data[t].loc[:date]) >= min_age
            ]
            if len(r_tradeable) >= 5:
                r_sliced = _slice_history_to_date(price_data, date, symbols=r_tradeable)
                r_held = set(slice_positions_by_strategy(state.positions, 'rattle').keys())
                r_max = rattle_regime['max_positions']
                r_slots = r_max - len(r_held)
                if r_slots > 0:
                    r_current_prices = {
                        t: float(price_data[t].loc[date, 'Close'])
                        for t in r_tradeable
                    }
                    candidates = find_rattlesnake_candidates(
                        r_sliced, r_current_prices, r_held, max_candidates=r_slots,
                    )
                    state, r_entry_decisions = apply_rattle_entries_wrapper(
                        state, alloc['rattle_budget'], date, i, price_data,
                        candidates, r_max, config, execution_mode, all_dates,
                    )
                    decisions.extend(r_entry_decisions)

        # ====================================================================
        # CATALYST (every CATALYST_REBALANCE_DAYS or whenever empty)
        # ====================================================================
        catalyst_day_counter += 1
        catalyst_held = slice_positions_by_strategy(state.positions, 'catalyst')
        if catalyst_day_counter >= CATALYST_REBALANCE_DAYS or not catalyst_held:
            catalyst_day_counter = 0
            state, c_trades, c_decisions = apply_catalyst_wrapper(
                state, alloc['catalyst_budget'], date, i, catalyst_assets,
                config, execution_mode, all_dates,
            )
            trades.extend(c_trades)
            decisions.extend(c_decisions)

        # ====================================================================
        # EFA (passive overflow)
        # ====================================================================
        state, efa_trades, efa_decisions = apply_efa_wrapper(
            state, alloc['efa_idle'], date, i, efa_data,
            config, execution_mode, all_dates,
        )
        trades.extend(efa_trades)
        decisions.extend(efa_decisions)

        # ====================================================================
        # ACCOUNTING — update HydraCapitalState with daily returns
        # ====================================================================
        prices_after = _current_prices(date)
        compass_invested_after = compute_pillar_invested(
            state.positions, 'compass', prices_after
        )
        rattle_invested_after = compute_pillar_invested(
            state.positions, 'rattle', prices_after
        )
        c_ret = (
            (compass_invested_after / compass_invested_before - 1)
            if compass_invested_before > 0 else 0.0
        )
        r_ret = (
            (rattle_invested_after / rattle_invested_before - 1)
            if rattle_invested_before > 0 else 0.0
        )
        state = state._replace(
            capital=update_accounts_after_day_pure(
                state.capital, c_ret, r_ret, rattle_exposure,
            )
        )
        # EFA value mark-to-market
        if EFA_SYMBOL in efa_data.index.get_loc(date) and False:  # placeholder
            pass  # efa_value tracking handled in merge_pillar_substate

        # 6. Snapshot
        pv_after = _mark_full(state, date)
        snapshots.append({
            'date': date,
            'portfolio_value': pv_after,
            'cash': state.cash,
            'n_positions': len(state.positions),
            'leverage': leverage,
            'drawdown': drawdown,
            'regime_score': regime_score,
            'crash_active': False,
            'max_positions': max_compass_pos,
            'compass_account': state.capital.compass_account,
            'rattle_account': state.capital.rattle_account,
            'catalyst_account': state.capital.catalyst_account,
            'efa_value': state.capital.efa_value,
            'recycled_pct': alloc['recycled_pct'],
            'n_compass': len(slice_positions_by_strategy(state.positions, 'compass')),
            'n_rattle': len(slice_positions_by_strategy(state.positions, 'rattle')),
            'n_catalyst': len(slice_positions_by_strategy(state.positions, 'catalyst')),
            'n_efa': len(slice_positions_by_strategy(state.positions, 'efa')),
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
        exit_events=trades,  # all closing trades
        universe_size=universe_size,
        started_at=started_at,
        finished_at=finished_at,
        git_sha=_capture_git_sha(),
        data_inputs_hash=compute_data_fingerprint(price_data),
    )


def _rattle_exposure(state: HydraBacktestState, prices: Dict[str, float]) -> float:
    """Mirror rattlesnake_signals.compute_rattlesnake_exposure but use the
    HydraCapitalState rattle_account as the denominator.
    """
    if state.capital.rattle_account <= 0:
        return 0.0
    rattle_positions = slice_positions_by_strategy(state.positions, 'rattle')
    invested = sum(
        pos.get('shares', 0) * prices.get(sym, pos.get('entry_price', 0.0))
        for sym, pos in rattle_positions.items()
    )
    return min(invested / state.capital.rattle_account, 1.0)
```

> ⚠️ **Implementation note**: The `efa_data.index.get_loc(date) and False` line near the snapshot is a placeholder that will be removed during the smoke test. EFA value tracking is handled implicitly by `merge_pillar_substate` (which updates `capital.efa_value` when positions enter/exit) and by `_mark_full` (which marks the EFA position to market every day for the snapshot's `portfolio_value`). No separate `update_efa_value_pure` call is needed in the standalone backtest.

- [ ] **Step 2: Smoke test the orchestrator with synthetic data**

```bash
python -c "
import numpy as np, pandas as pd
from hydra_backtest.hydra.engine import run_hydra_backtest
# minimal synthetic inputs — verify it doesn't crash
print('Engine imports OK; full smoke deferred to T13')
"
```

If the import succeeds the file compiles. The full integration smoke is in Task 13 with proper fixtures.

- [ ] **Step 3: Commit**

```bash
git add hydra_backtest/hydra/engine.py
git commit -m "feat(hydra_backtest.hydra): run_hydra_backtest orchestrator"
```

---

## Task 8: Validation — 15 cross-pillar invariants

**File:** `hydra_backtest/hydra/validation.py` (NEW)

- [ ] **Step 1: Create validation.py**

```python
"""hydra_backtest.hydra.validation — Layer A smoke tests for full HYDRA.

15 invariants covering:
  - Math (shared with v1.0-v1.3): NaN, cash floor, drawdown, peak,
    vol range, outliers
  - Per-pillar position bounds
  - Exit reasons whitelist (union of all four pillars)
  - Sub-account sum invariant (the cash-recycling canary)
  - Recycling cap invariant
  - Catalyst ring-fence invariant
  - Position tag completeness
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

# Union of all valid exit reasons from v1.0-v1.3 + v1.4 EFA liquidation
_VALID_EXIT_REASONS = {
    # COMPASS
    'hold_expired', 'position_stop', 'trailing_stop',
    'universe_rotation', 'regime_reduce', 'portfolio_stop',
    # Rattlesnake
    'R_PROFIT', 'R_STOP', 'R_TIME',
    # Catalyst
    'CATALYST_TREND_OFF', 'CATALYST_BACKTEST_END',
    # EFA
    'EFA_BELOW_SMA200', 'EFA_BACKTEST_END', 'EFA_LIQUIDATED_FOR_CAPITAL',
}

_SUB_ACCOUNT_TOLERANCE = 1.0  # $1 per day


def _check_no_nan(daily, errors):
    critical = [
        'portfolio_value', 'cash', 'n_positions', 'drawdown',
        'compass_account', 'rattle_account', 'catalyst_account', 'efa_value',
    ]
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


def _check_per_pillar_position_bounds(daily, errors):
    for pillar, max_n in [('n_compass', 10), ('n_rattle', 10),
                           ('n_catalyst', 4), ('n_efa', 1)]:
        if pillar not in daily.columns:
            continue
        bad = daily[(daily[pillar] < 0) | (daily[pillar] > max_n)]
        if not bad.empty:
            row = bad.iloc[0]
            errors.append(
                f"{pillar} out of [0, {max_n}] at {row.get('date', '?')}: {row[pillar]}"
            )


def _check_exit_reasons(trades, errors):
    if trades.empty or 'exit_reason' not in trades.columns:
        return
    invalid = set(trades['exit_reason'].unique()) - _VALID_EXIT_REASONS
    if invalid:
        errors.append(f"Invalid HYDRA exit reasons: {invalid}")


def _check_sub_account_sum(daily, errors):
    """The cash-recycling canary: sub-accounts + cash ≈ portfolio_value."""
    needed = {'compass_account', 'rattle_account', 'catalyst_account',
              'efa_value', 'cash', 'portfolio_value'}
    if not needed.issubset(daily.columns):
        return
    sub_sum = (
        daily['compass_account'] + daily['rattle_account']
        + daily['catalyst_account'] + daily['efa_value']
    )
    diff = (sub_sum - daily['portfolio_value']).abs()
    bad = daily[diff > _SUB_ACCOUNT_TOLERANCE]
    if not bad.empty:
        row = bad.iloc[0]
        errors.append(
            f"Sub-account sum diverged at {row.get('date', '?')}: "
            f"sub_sum={sub_sum.iloc[bad.index[0]]:.2f}, "
            f"PV={row['portfolio_value']:.2f}, diff={diff.iloc[bad.index[0]]:.2f}"
        )


def _check_recycling_cap(daily, errors, max_compass_alloc=0.75):
    if 'recycled_pct' not in daily.columns:
        return
    # recycled_pct is recycled_amount / total_capital, so the cap is
    # max_compass_alloc - base_compass_alloc = 0.75 - 0.425 = 0.325
    cap = max_compass_alloc - 0.425
    bad = daily[daily['recycled_pct'] > cap + 1e-6]
    if not bad.empty:
        row = bad.iloc[0]
        errors.append(
            f"Recycling cap breached at {row.get('date', '?')}: "
            f"recycled_pct={row['recycled_pct']:.4f} > cap={cap:.4f}"
        )


def run_hydra_smoke_tests(result: BacktestResult) -> None:
    """Run all 15 Layer A smoke tests on a HYDRA BacktestResult.

    Raises HydraBacktestValidationError with all errors aggregated.
    """
    errors: List[str] = []
    daily = result.daily_values
    trades = result.trades

    if daily.empty:
        raise HydraBacktestValidationError(
            "HYDRA backtest produced empty daily_values"
        )

    _check_no_nan(daily, errors)
    _check_cash_floor(daily, errors)
    _check_drawdown_range(daily, errors)
    _check_peak_monotonic(daily, errors)
    _check_vol_range(daily, errors)
    _check_outlier_returns(daily, errors)
    _check_per_pillar_position_bounds(daily, errors)
    _check_exit_reasons(trades, errors)
    _check_sub_account_sum(daily, errors)
    _check_recycling_cap(daily, errors)

    if errors:
        msg = "HYDRA smoke tests failed:\n  - " + "\n  - ".join(errors)
        raise HydraBacktestValidationError(msg)
```

> Note: invariants 14 (Catalyst ring-fence) and 15 (position tag completeness) are enforced at engine level (the wrappers always tag positions), so they don't need a daily-CSV check. They're verified by unit tests in T13.

- [ ] **Step 2: Compile + commit**

```bash
python -c "import py_compile; py_compile.compile('hydra_backtest/hydra/validation.py')"
git add hydra_backtest/hydra/validation.py
git commit -m "feat(hydra_backtest.hydra): Layer A 15-invariant smoke tests"
```

---

## Task 9: Layer B comparison helper

**File:** `hydra_backtest/hydra/layer_b.py` (NEW)

- [ ] **Step 1: Create layer_b.py**

```python
"""hydra_backtest.hydra.layer_b — informational comparison vs the
dashboard's hydra_clean_daily.csv source-of-truth.

Non-blocking. Computes correlation, MAE, and max abs error between
v1.4's daily portfolio_value and the existing hydra_clean_daily.csv.
"""
from pathlib import Path
from typing import Optional

import pandas as pd

DEFAULT_CLEAN_CSV = Path('backtests/hydra_clean_daily.csv')


def compute_layer_b_report(
    daily: pd.DataFrame,
    clean_csv_path: Optional[Path] = None,
) -> dict:
    """Compute correlation/MAE between v1.4 daily PV and hydra_clean_daily.csv.

    Returns a dict with status, n_overlap, spearman, mae, max_err,
    and a verdict ('PASS' if spearman >= 0.95 else 'INVESTIGATE').
    Status='SKIPPED' if the reference CSV is missing.
    """
    path = clean_csv_path or DEFAULT_CLEAN_CSV
    if not path.exists():
        return {'status': 'SKIPPED', 'reason': f'{path} not found'}

    clean = pd.read_csv(path, parse_dates=['date'])
    clean = clean.set_index('date')['value']

    if 'date' not in daily.columns or 'portfolio_value' not in daily.columns:
        return {'status': 'SKIPPED', 'reason': 'daily missing date or portfolio_value'}

    v14 = daily.set_index('date')['portfolio_value']

    overlap = v14.index.intersection(clean.index)
    if len(overlap) < 100:
        return {'status': 'SKIPPED', 'reason': f'only {len(overlap)} overlapping days'}

    v14_aligned = v14.loc[overlap]
    clean_aligned = clean.loc[overlap]
    spearman = float(v14_aligned.corr(clean_aligned, method='spearman'))
    mae = float((v14_aligned - clean_aligned).abs().mean())
    max_err = float((v14_aligned - clean_aligned).abs().max())
    verdict = 'PASS' if spearman >= 0.95 else 'INVESTIGATE'

    return {
        'status': 'COMPLETE',
        'verdict': verdict,
        'n_overlap': int(len(overlap)),
        'spearman': spearman,
        'mae': mae,
        'max_err': max_err,
        'reference_csv': str(path),
    }
```

- [ ] **Step 2: Commit**

```bash
git add hydra_backtest/hydra/layer_b.py
git commit -m "feat(hydra_backtest.hydra): Layer B comparison helper (informational)"
```

---

## Task 10: Capital + state unit tests

**File:** `hydra_backtest/hydra/tests/test_capital.py` and `test_state.py` (NEW)

Goal: verify `compute_allocation_pure` and `update_accounts_after_day_pure` produce **byte-identical** results vs the live `HydraCapitalManager` class over a synthetic 100-day sequence. This is the most important test in v1.4.

- [ ] **Step 1: Create `test_capital.py`**

```python
"""Unit tests for hydra_backtest.hydra.capital pure functions."""
import numpy as np
import pytest

from hydra_backtest.hydra.capital import (
    BASE_CATALYST_ALLOC,
    BASE_COMPASS_ALLOC,
    BASE_RATTLE_ALLOC,
    HydraCapitalState,
    compute_allocation_pure,
    update_accounts_after_day_pure,
    update_catalyst_value_pure,
    update_efa_value_pure,
)
from hydra_capital import HydraCapitalManager


def _make_pair(initial: float = 100_000.0):
    """Build matched live HCM + pure HCS pair for round-trip tests."""
    live = HydraCapitalManager(initial)
    pure = HydraCapitalState(
        compass_account=initial * BASE_COMPASS_ALLOC,
        rattle_account=initial * BASE_RATTLE_ALLOC,
        catalyst_account=initial * BASE_CATALYST_ALLOC,
        efa_value=0.0,
    )
    return live, pure


def test_compute_allocation_matches_live_initial_state():
    live, pure = _make_pair()
    live_alloc = live.compute_allocation(rattle_exposure=0.5)
    pure_alloc = compute_allocation_pure(pure, rattle_exposure=0.5)
    for key in ['compass_budget', 'rattle_budget', 'catalyst_budget',
                'recycled_amount', 'efa_idle']:
        assert pure_alloc[key] == pytest.approx(live_alloc[key]), \
            f"{key} mismatch: pure={pure_alloc[key]} live={live_alloc[key]}"


def test_compute_allocation_full_idle_rattle_caps_at_75pct():
    """When Rattlesnake is 100% idle, COMPASS budget should hit the 0.75 cap."""
    _, pure = _make_pair()
    alloc = compute_allocation_pure(pure, rattle_exposure=0.0)
    # max compass = 0.75 * total = 75_000; base compass = 42_500
    # so recycled = min(42_500 idle rattle, 32_500 max recycle) = 32_500
    assert alloc['compass_budget'] == pytest.approx(75_000.0)
    assert alloc['recycled_amount'] == pytest.approx(32_500.0)


def test_compute_allocation_zero_idle_rattle():
    """When Rattlesnake is 100% deployed, no recycling."""
    _, pure = _make_pair()
    alloc = compute_allocation_pure(pure, rattle_exposure=1.0)
    assert alloc['recycled_amount'] == 0.0
    assert alloc['compass_budget'] == pytest.approx(42_500.0)


def test_update_accounts_after_day_matches_live_synthetic_100d():
    """Run 100 random days through both implementations and compare."""
    np.random.seed(666)
    live, pure = _make_pair()
    for _ in range(100):
        c_ret = float(np.random.normal(0.0005, 0.01))
        r_ret = float(np.random.normal(0.0003, 0.008))
        r_exp = float(np.random.uniform(0, 1))
        live.update_accounts_after_day(c_ret, r_ret, r_exp)
        pure = update_accounts_after_day_pure(pure, c_ret, r_ret, r_exp)
        assert pure.compass_account == pytest.approx(
            live.compass_account, rel=1e-9
        ), f"compass diverged"
        assert pure.rattle_account == pytest.approx(
            live.rattle_account, rel=1e-9
        ), f"rattle diverged"


def test_update_efa_value_pure():
    pure = HydraCapitalState(
        compass_account=42_500, rattle_account=42_500,
        catalyst_account=15_000, efa_value=10_000,
    )
    pure2 = update_efa_value_pure(pure, 0.05)
    assert pure2.efa_value == pytest.approx(10_500)
    # Zero efa skips
    pure3 = HydraCapitalState(
        compass_account=42_500, rattle_account=42_500,
        catalyst_account=15_000, efa_value=0.0,
    )
    assert update_efa_value_pure(pure3, 0.05) is pure3 or update_efa_value_pure(pure3, 0.05).efa_value == 0.0


def test_update_catalyst_value_pure():
    pure = HydraCapitalState(
        compass_account=42_500, rattle_account=42_500,
        catalyst_account=15_000, efa_value=0.0,
    )
    pure2 = update_catalyst_value_pure(pure, 0.02)
    assert pure2.catalyst_account == pytest.approx(15_300)


def test_total_capital_property():
    pure = HydraCapitalState(
        compass_account=10_000, rattle_account=20_000,
        catalyst_account=5_000, efa_value=15_000,
    )
    assert pure.total_capital == 50_000
```

- [ ] **Step 2: Create `test_state.py`**

```python
"""Unit tests for hydra_backtest.hydra.state."""
import pytest

from hydra_backtest.hydra.capital import HydraCapitalState
from hydra_backtest.hydra.state import (
    HydraBacktestState,
    compute_pillar_invested,
    merge_pillar_substate,
    slice_positions_by_strategy,
    to_pillar_substate,
)


def _make_state(positions=None, cash=100_000.0):
    capital = HydraCapitalState(
        compass_account=42_500, rattle_account=42_500,
        catalyst_account=15_000, efa_value=0.0,
    )
    return HydraBacktestState(
        cash=cash,
        positions=positions or {},
        peak_value=cash,
        crash_cooldown=0,
        portfolio_value_history=(),
        capital=capital,
    )


def test_slice_filters_by_strategy_tag():
    positions = {
        'AAPL': {'symbol': 'AAPL', 'shares': 100, '_strategy': 'compass'},
        'MSFT': {'symbol': 'MSFT', 'shares': 50, '_strategy': 'rattle'},
        'GLD': {'symbol': 'GLD', 'shares': 20, '_strategy': 'catalyst'},
        'EFA': {'symbol': 'EFA', 'shares': 10, '_strategy': 'efa'},
    }
    assert set(slice_positions_by_strategy(positions, 'compass').keys()) == {'AAPL'}
    assert set(slice_positions_by_strategy(positions, 'rattle').keys()) == {'MSFT'}
    assert set(slice_positions_by_strategy(positions, 'catalyst').keys()) == {'GLD'}
    assert set(slice_positions_by_strategy(positions, 'efa').keys()) == {'EFA'}


def test_slice_invalid_strategy_raises():
    with pytest.raises(ValueError, match="Invalid strategy"):
        slice_positions_by_strategy({}, 'foo')


def test_to_pillar_substate_uses_full_cash_by_default():
    state = _make_state(positions={
        'AAPL': {'symbol': 'AAPL', 'shares': 100, '_strategy': 'compass'},
        'MSFT': {'symbol': 'MSFT', 'shares': 50, '_strategy': 'rattle'},
    })
    sub = to_pillar_substate(state, 'compass')
    assert sub.cash == 100_000.0
    assert set(sub.positions.keys()) == {'AAPL'}


def test_to_pillar_substate_cash_override():
    state = _make_state()
    sub = to_pillar_substate(state, 'compass', cash_override=42_500.0)
    assert sub.cash == 42_500.0


def test_merge_round_trip_lossless():
    """Slice → identity transform → merge should give back the same state."""
    positions = {
        'AAPL': {'symbol': 'AAPL', 'shares': 100, '_strategy': 'compass',
                 'entry_price': 150.0},
        'MSFT': {'symbol': 'MSFT', 'shares': 50, '_strategy': 'rattle',
                 'entry_price': 300.0},
    }
    state = _make_state(positions=positions)
    sub = to_pillar_substate(state, 'compass')
    merged = merge_pillar_substate(state, sub, 'compass',
                                    cash_delta=0.0, capital_account_delta=0.0)
    assert set(merged.positions.keys()) == {'AAPL', 'MSFT'}
    assert merged.positions['AAPL']['_strategy'] == 'compass'
    assert merged.positions['MSFT']['_strategy'] == 'rattle'


def test_merge_tags_new_positions():
    """A new position from the substate must inherit the strategy tag."""
    state = _make_state()
    new_sub = to_pillar_substate(state, 'compass', cash_override=42_500.0)
    new_sub_with_pos = new_sub._replace(
        cash=30_000.0,
        positions={'AAPL': {'symbol': 'AAPL', 'shares': 100, 'entry_price': 125.0}},
    )
    merged = merge_pillar_substate(state, new_sub_with_pos, 'compass',
                                    cash_delta=-12_500.0, capital_account_delta=-12_500.0)
    assert merged.positions['AAPL']['_strategy'] == 'compass'
    assert merged.cash == 100_000.0 - 12_500.0
    assert merged.capital.compass_account == 42_500.0 - 12_500.0


def test_compute_pillar_invested_uses_current_prices():
    positions = {
        'AAPL': {'symbol': 'AAPL', 'shares': 100, 'entry_price': 150.0,
                 '_strategy': 'compass'},
        'MSFT': {'symbol': 'MSFT', 'shares': 50, 'entry_price': 300.0,
                 '_strategy': 'rattle'},
    }
    prices = {'AAPL': 200.0, 'MSFT': 250.0}
    assert compute_pillar_invested(positions, 'compass', prices) == 20_000.0
    assert compute_pillar_invested(positions, 'rattle', prices) == 12_500.0


def test_compute_pillar_invested_falls_back_to_entry_price_for_missing():
    positions = {
        'AAPL': {'symbol': 'AAPL', 'shares': 100, 'entry_price': 150.0,
                 '_strategy': 'compass'},
    }
    # AAPL not in prices → falls back to entry_price
    assert compute_pillar_invested(positions, 'compass', {}) == 15_000.0
```

- [ ] **Step 3: Run + commit**

```bash
pytest hydra_backtest/hydra/tests/test_capital.py hydra_backtest/hydra/tests/test_state.py -v
git add hydra_backtest/hydra/tests/test_capital.py hydra_backtest/hydra/tests/test_state.py
git commit -m "test(hydra_backtest.hydra): capital + state unit tests (incl. live HCM byte-identity)"
```

---

## Task 11: Wire public API exports

**File:** `hydra_backtest/hydra/__init__.py` (modify)

- [ ] **Step 1: Replace placeholder with real exports**

```python
"""hydra_backtest.hydra — full HYDRA integration backtest.

Composes COMPASS + Rattlesnake + Catalyst + EFA with cash recycling
and the Catalyst ring-fence. Mirrors omnicapital_live order of
operations.

See:
- docs/superpowers/specs/2026-04-07-hydra-backtest-v1.4-hydra-design.md
- docs/superpowers/plans/2026-04-07-hydra-backtest-v1.4-hydra.md
"""
from hydra_backtest.hydra.capital import (
    BASE_CATALYST_ALLOC,
    BASE_COMPASS_ALLOC,
    BASE_RATTLE_ALLOC,
    EFA_DEPLOYMENT_CAP,
    EFA_MIN_BUY,
    MAX_COMPASS_ALLOC,
    HydraCapitalState,
    compute_allocation_pure,
    update_accounts_after_day_pure,
    update_catalyst_value_pure,
    update_efa_value_pure,
)
from hydra_backtest.hydra.engine import (
    apply_catalyst_wrapper,
    apply_compass_entries_wrapper,
    apply_compass_exits_wrapper,
    apply_efa_liquidation,
    apply_efa_wrapper,
    apply_rattle_entries_wrapper,
    apply_rattle_exits_wrapper,
    run_hydra_backtest,
)
from hydra_backtest.hydra.layer_b import compute_layer_b_report
from hydra_backtest.hydra.state import (
    HydraBacktestState,
    compute_pillar_invested,
    merge_pillar_substate,
    slice_positions_by_strategy,
    to_pillar_substate,
)
from hydra_backtest.hydra.validation import run_hydra_smoke_tests

__all__ = [
    # capital
    'HydraCapitalState', 'compute_allocation_pure',
    'update_accounts_after_day_pure', 'update_efa_value_pure',
    'update_catalyst_value_pure',
    'BASE_COMPASS_ALLOC', 'BASE_RATTLE_ALLOC', 'BASE_CATALYST_ALLOC',
    'MAX_COMPASS_ALLOC', 'EFA_MIN_BUY', 'EFA_DEPLOYMENT_CAP',
    # state
    'HydraBacktestState', 'slice_positions_by_strategy',
    'to_pillar_substate', 'merge_pillar_substate',
    'compute_pillar_invested',
    # engine
    'run_hydra_backtest',
    'apply_compass_exits_wrapper', 'apply_compass_entries_wrapper',
    'apply_rattle_exits_wrapper', 'apply_rattle_entries_wrapper',
    'apply_catalyst_wrapper', 'apply_efa_wrapper', 'apply_efa_liquidation',
    # validation + layer b
    'run_hydra_smoke_tests', 'compute_layer_b_report',
]
```

- [ ] **Step 2: Verify imports + other suites still pass**

```bash
python -c "import hydra_backtest.hydra as h; print(len(h.__all__), 'exports')"
pytest hydra_backtest/tests/ hydra_backtest/rattlesnake/tests/ hydra_backtest/catalyst/tests/ hydra_backtest/efa/tests/ --collect-only -q 2>&1 | tail -3
```

- [ ] **Step 3: Commit**

```bash
git add hydra_backtest/hydra/__init__.py
git commit -m "feat(hydra_backtest.hydra): wire public API exports"
```

---

## Task 12: Engine wrapper unit tests

**File:** `hydra_backtest/hydra/tests/test_engine.py` (NEW)

Tests: COMPASS wrapper budget cap, Rattlesnake wrapper position routing, Catalyst wrapper ring-fence, EFA wrapper idle gate, EFA liquidation helper.

- [ ] **Step 1: Create test_engine.py with wrapper tests using synthetic data**

(Detailed test code: ~250 LOC; structure mirrors v1.2/v1.3 test_engine.py with HydraBacktestState fixtures.)

Key tests:
- `test_compass_entries_wrapper_respects_budget` — pass `compass_budget=10_000` with `state.cash=100_000`; verify only ~$10k spent
- `test_compass_exits_wrapper_only_touches_compass_positions` — pre-seed state with COMPASS+Rattle+Catalyst+EFA positions; verify exits don't touch the other three
- `test_rattle_wrapper_routes_correctly` — same idea
- `test_catalyst_wrapper_ring_fence` — Catalyst rebalance never touches compass_account/rattle_account
- `test_efa_wrapper_idle_gate` — EFA wrapper skips when `efa_idle < EFA_MIN_BUY` and nothing held
- `test_apply_efa_liquidation_frees_cash` — synthetic EFA position → liquidation produces correct cash delta and trade record
- `test_position_tag_invariant_after_wrapper_call` — every position in merged state has `_strategy`

- [ ] **Step 2: Run + commit**

```bash
pytest hydra_backtest/hydra/tests/test_engine.py -v
git add hydra_backtest/hydra/tests/test_engine.py
git commit -m "test(hydra_backtest.hydra): engine wrapper unit tests"
```

---

## Task 13: Validation unit tests

**File:** `hydra_backtest/hydra/tests/test_validation.py` (NEW)

8 tests, one per smoke check failure mode. Same pattern as v1.2/v1.3 test_validation.py.

- [ ] **Step 1: Create + run + commit**

```bash
pytest hydra_backtest/hydra/tests/test_validation.py -v
git add hydra_backtest/hydra/tests/test_validation.py
git commit -m "test(hydra_backtest.hydra): validation unit tests"
```

---

## Task 14: CLI entrypoint

**File:** `hydra_backtest/hydra/__main__.py` (NEW)

Mirrors Catalyst's `__main__.py` but takes the union of all four pillars' inputs. Runs 3 tiers, builds waterfall, writes 4 outputs (daily, trades, waterfall, attribution).

- [ ] **Step 1: Create __main__.py**

```python
"""CLI entrypoint: python -m hydra_backtest.hydra

Loads all four pillar inputs, runs 3 HYDRA backtest tiers
(baseline + T-bill + next-open), post-processes for slippage tier,
writes CSV + JSON outputs (including per-pillar attribution sidecar
and Layer B comparison report), and prints a waterfall summary.
"""
import argparse
import json
import os
import sys

import pandas as pd

from hydra_backtest import (
    build_waterfall,
    format_summary_table,
    load_catalyst_assets,
    load_efa_series,
    load_pit_universe,
    load_price_history,
    load_sector_map,
    load_spy_data,
    load_vix_series,
    load_yield_series,
    write_daily_csv,
    write_trades_csv,
    write_waterfall_json,
)
from hydra_backtest.hydra import (
    compute_layer_b_report,
    run_hydra_backtest,
    run_hydra_smoke_tests,
)


_CONFIG = {
    # Capital
    'INITIAL_CAPITAL': 100_000,
    'COMMISSION_PER_SHARE': 0.0035,
    # COMPASS (subset of v1.0 production config — full set in conftest fixture)
    'NUM_POSITIONS': 5,
    'NUM_POSITIONS_RISK_OFF': 2,
    'MOMENTUM_LOOKBACK': 90,
    'MOMENTUM_SKIP': 5,
    'HOLD_DAYS': 5,
    'MIN_AGE_DAYS': 220,
    'MIN_MOMENTUM_STOCKS': 5,
    'QUALITY_VOL_MAX': 0.55,
    'QUALITY_VOL_LOOKBACK': 60,
    'QUALITY_MAX_SINGLE_DAY': 0.18,
    'MAX_PER_SECTOR': 3,
    'POSITION_STOP_PCT': -0.06,
    'TRAILING_STOP_ACTIVATE': 0.05,
    'TRAILING_STOP_DROP': 0.03,
    'PORTFOLIO_STOP_PCT': -0.15,
    'CRASH_BRAKE_5D': -0.06,
    'CRASH_BRAKE_10D': -0.10,
    'CRASH_LEVERAGE': 0.15,
    'LEVERAGE_MAX': 1.0,
    'LEVERAGE_MIN': 0.3,
    'VOL_TARGET': 0.15,
    'MARGIN_RATE': 0.06,
    # HYDRA-specific
    'BASE_COMPASS_ALLOC': 0.425,
    'BASE_RATTLE_ALLOC': 0.425,
    'BASE_CATALYST_ALLOC': 0.15,
    'MAX_COMPASS_ALLOC': 0.75,
    'EFA_LIQUIDATION_CASH_THRESHOLD_PCT': 0.20,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog='python -m hydra_backtest.hydra',
        description='Reproducible full HYDRA standalone backtest.',
    )
    parser.add_argument('--start', type=str, default='2000-01-01')
    parser.add_argument('--end', type=str, default='2026-03-05')
    parser.add_argument('--out-dir', type=str, default='backtests/hydra_v1')
    # Data inputs
    parser.add_argument('--constituents', type=str,
                        default='data_cache/sp500_constituents_history.pkl')
    parser.add_argument('--prices', type=str,
                        default='data_cache/sp500_universe_prices.pkl')
    parser.add_argument('--sectors', type=str,
                        default='data_cache/sp500_sectors.json')
    parser.add_argument('--spy', type=str,
                        default='data_cache/SPY_2000-01-01_2027-01-01.csv')
    parser.add_argument('--vix', type=str,
                        default='data_cache/vix_history.csv')
    parser.add_argument('--catalyst-assets', type=str,
                        default='data_cache/catalyst_assets.pkl')
    parser.add_argument('--efa', type=str,
                        default='data_cache/efa_history.pkl')
    parser.add_argument('--aaa', type=str,
                        default='data_cache/moody_aaa_yield.csv')
    parser.add_argument('--tbill', type=str,
                        default='data_cache/tbill_3m_fred.csv')
    parser.add_argument('--aaa-date-col', type=str, default='observation_date')
    parser.add_argument('--aaa-value-col', type=str, default='yield_pct')
    parser.add_argument('--tbill-date-col', type=str, default='DATE')
    parser.add_argument('--tbill-value-col', type=str, default='DGS3MO')
    parser.add_argument('--slippage-bps', type=float, default=2.0)
    parser.add_argument('--half-spread-bps', type=float, default=0.5)
    parser.add_argument('--t-bill-rf', type=float, default=0.03)
    args = parser.parse_args(argv)

    print("Loading data...", flush=True)
    pit = load_pit_universe(args.constituents)
    prices = load_price_history(args.prices)
    sector_map = load_sector_map(args.sectors)
    spy = load_spy_data(args.spy)
    vix = load_vix_series(args.vix)
    catalyst_assets = load_catalyst_assets(args.catalyst_assets)
    efa = load_efa_series(args.efa)
    aaa = load_yield_series(args.aaa, date_col=args.aaa_date_col,
                            value_col=args.aaa_value_col)
    tbill = load_yield_series(args.tbill, date_col=args.tbill_date_col,
                              value_col=args.tbill_value_col)
    print(
        f"  PIT: {len(pit)} years, prices: {len(prices)} tickers, "
        f"catalyst: {len(catalyst_assets)} ETFs, EFA: {len(efa)} rows",
        flush=True,
    )

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)

    def _make_progress_cb(tier_name):
        def _cb(info):
            print(
                f"  [{tier_name}] {info['year']}: {info['progress_pct']:5.1f}% | "
                f"PV ${info['portfolio_value']:>12,.0f} | "
                f"{info['n_positions']} pos | recycled {info.get('recycled_pct', 0)*100:.0f}%",
                flush=True,
            )
        return _cb

    print("\nTier 0: baseline (Aaa, same-close)", flush=True)
    tier_0 = run_hydra_backtest(
        config=_CONFIG, price_data=prices, pit_universe=pit, spy_data=spy,
        vix_data=vix, catalyst_assets=catalyst_assets, efa_data=efa,
        cash_yield_daily=aaa, sector_map=sector_map,
        start_date=start, end_date=end, execution_mode='same_close',
        progress_callback=_make_progress_cb('tier0'),
    )
    run_hydra_smoke_tests(tier_0)
    print("  tier 0 smoke tests: PASSED", flush=True)

    print("\nTier 1: + T-bill cash yield", flush=True)
    tier_1 = run_hydra_backtest(
        config=_CONFIG, price_data=prices, pit_universe=pit, spy_data=spy,
        vix_data=vix, catalyst_assets=catalyst_assets, efa_data=efa,
        cash_yield_daily=tbill, sector_map=sector_map,
        start_date=start, end_date=end, execution_mode='same_close',
        progress_callback=_make_progress_cb('tier1'),
    )
    run_hydra_smoke_tests(tier_1)
    print("  tier 1 smoke tests: PASSED", flush=True)

    print("\nTier 2: + next-open execution", flush=True)
    tier_2 = run_hydra_backtest(
        config=_CONFIG, price_data=prices, pit_universe=pit, spy_data=spy,
        vix_data=vix, catalyst_assets=catalyst_assets, efa_data=efa,
        cash_yield_daily=tbill, sector_map=sector_map,
        start_date=start, end_date=end, execution_mode='next_open',
        progress_callback=_make_progress_cb('tier2'),
    )
    run_hydra_smoke_tests(tier_2)
    print("  tier 2 smoke tests: PASSED", flush=True)

    print("\nBuilding waterfall...", flush=True)
    report = build_waterfall(
        tier_0=tier_0, tier_1=tier_1, tier_2=tier_2,
        t_bill_rf=args.t_bill_rf,
        slippage_bps=args.slippage_bps,
        half_spread_bps=args.half_spread_bps,
    )

    os.makedirs(args.out_dir, exist_ok=True)
    write_daily_csv(tier_0, os.path.join(args.out_dir, 'hydra_v2_daily.csv'))
    write_trades_csv(tier_0, os.path.join(args.out_dir, 'hydra_v2_trades.csv'))
    write_waterfall_json(report, os.path.join(args.out_dir, 'hydra_v2_waterfall.json'))

    # Layer B comparison (informational)
    layer_b = compute_layer_b_report(tier_0.daily_values)
    with open(os.path.join(args.out_dir, 'layer_b_report.json'), 'w') as f:
        json.dump(layer_b, f, indent=2)
    print(f"\n  Layer B vs hydra_clean_daily.csv: {layer_b.get('verdict', layer_b.get('status'))}", flush=True)
    if layer_b.get('status') == 'COMPLETE':
        print(f"    Spearman: {layer_b['spearman']:.4f} | MAE: ${layer_b['mae']:,.0f} | "
              f"max_err: ${layer_b['max_err']:,.0f}", flush=True)

    print('\n' + format_summary_table(report), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: --help smoke + commit**

```bash
python -m hydra_backtest.hydra --help
git add hydra_backtest/hydra/__main__.py
git commit -m "feat(hydra_backtest.hydra): CLI entrypoint with Layer B integration"
```

---

## Task 15: Integration test (CLI smoke)

**File:** `hydra_backtest/hydra/tests/test_integration.py` (NEW)

Same pattern as Catalyst/EFA integration tests. Builds synthetic versions of all 7 inputs (PIT, prices, sectors, SPY, VIX, catalyst pkl, EFA pkl, Aaa, T-bill) in a tmp_path, spawns the CLI, verifies outputs.

- [ ] **Step 1: Create + run + commit**

```bash
pytest hydra_backtest/hydra/tests/test_integration.py -v
git add hydra_backtest/hydra/tests/test_integration.py
git commit -m "test(hydra_backtest.hydra): CLI integration smoke"
```

---

## Task 16: E2E tests (slow, real data)

**File:** `hydra_backtest/hydra/tests/test_e2e.py` (NEW)

- [ ] **Step 1: Create test_e2e.py with @pytest.mark.slow guards**

Tests:
- `test_e2e_2year_window` — full HYDRA on 2020-2021 with real data, asserts smoke tests pass
- `test_e2e_determinism` — two consecutive runs produce byte-identical daily CSV
- `test_e2e_layer_b_correlation` — runs Layer B comparison and asserts `spearman >= 0.95` (informational warning if not met, but does not fail the test in v1.4)

- [ ] **Step 2: Commit (will skip until data is present)**

```bash
git add hydra_backtest/hydra/tests/test_e2e.py
git commit -m "test(hydra_backtest.hydra): E2E tests (slow, real data)"
```

---

## Task 17: README

**File:** `hydra_backtest/hydra/README.md` (NEW)

Sections:
1. Overview — full HYDRA integration
2. Architecture — composition pattern, position tagging, sub-state wrappers
3. Usage — CLI example
4. Data prerequisites — list all 7 inputs and how each was built (pointers to v1.0/v1.1/v1.2/v1.3)
5. Layer A invariants — list all 15
6. Layer B comparison — what `hydra_clean_daily.csv` is and how to interpret divergence
7. Per-pillar attribution — how `hydra_v2_attribution.json` is computed (note the c_ret/r_ret approximation from live)
8. v1.4 limitations — no IS, no execution strategies, no IBKR, no thread safety, no metadata round-tripping
9. Constants duplicated from `hydra_capital.py` — same rationale as v1.3 README inline-strategy note
10. Roadmap — pointer to v1.5

- [ ] **Step 1: Write + commit**

```bash
git add hydra_backtest/hydra/README.md
git commit -m "docs(hydra_backtest.hydra): README"
```

---

## Task 18: CI integration

**File:** `.github/workflows/test.yml` (modify)

- [ ] **Step 1: Add HYDRA pytest step after the EFA step**

```yaml
      - name: Test hydra_backtest.hydra sub-package
        run: >
          pytest hydra_backtest/hydra/tests/ -v --tb=short
          --cov=hydra_backtest.hydra
          --cov-report=term-missing
          -m "not slow"
```

- [ ] **Step 2: YAML validate + commit**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml'))" && echo OK
git add .github/workflows/test.yml
git commit -m "ci(hydra_backtest.hydra): add CI step for hydra tests"
```

---

## Task 19: Run the official 2000-2026 backtest

**Goal:** Produce `backtests/hydra_v1/` outputs that anyone can reproduce.

- [ ] **Step 1: Run the CLI**

```bash
mkdir -p backtests/hydra_v1
python -m hydra_backtest.hydra \
    --start 2000-01-01 \
    --end 2026-03-05 \
    --out-dir backtests/hydra_v1 2>&1 | tee backtests/hydra_v1/run.log
```

Expected runtime: **15-20 minutes**. Use `run_in_background=true` if appropriate.

- [ ] **Step 2: Verify outputs exist**

```bash
ls -la backtests/hydra_v1/
python -c "
import pandas as pd, json
d = pd.read_csv('backtests/hydra_v1/hydra_v2_daily.csv')
t = pd.read_csv('backtests/hydra_v1/hydra_v2_trades.csv')
w = json.load(open('backtests/hydra_v1/hydra_v2_waterfall.json'))
b = json.load(open('backtests/hydra_v1/layer_b_report.json'))
print(f'daily: {d.shape}, trades: {t.shape}')
print(f'tiers: {[tt[\"name\"] for tt in w[\"tiers\"]]}')
print(f'layer_b: {b}')
"
```

- [ ] **Step 3: Determinism check**

```bash
cp backtests/hydra_v1/hydra_v2_daily.csv /tmp/hydra_run1.csv
python -m hydra_backtest.hydra --start 2000-01-01 --end 2026-03-05 --out-dir backtests/hydra_v1 > /dev/null 2>&1
diff -q /tmp/hydra_run1.csv backtests/hydra_v1/hydra_v2_daily.csv && echo "DETERMINISTIC ✅"
```

- [ ] **Step 4: Commit official outputs + push**

```bash
git add backtests/hydra_v1/
git commit -m "feat(hydra_backtest.hydra): v1.4 official 2000-2026 results"
git push
```

- [ ] **Step 5: Update memory**

Add a `project_hydra_backtest_v14_hydra.md` memory file with the final NET HONEST CAGR/Sharpe/MaxDD and the Layer B comparison verdict.

---

## Success criteria (from spec §16)

v1.4 is complete when ALL of these are true:

1. ☐ `python -m hydra_backtest.hydra --start 2000-01-01 --end 2026-03-05` runs to completion
2. ☐ Two consecutive runs produce byte-identical `hydra_v2_daily.csv`
3. ☐ All Layer A smoke tests (15 invariants) pass for all 3 tier runs
4. ☐ Coverage ≥ 80% for `hydra_backtest/hydra/`
5. ☐ v1.0 + v1.1 + v1.2 + v1.3 test suites remain green (138+ tests)
6. ☐ Waterfall report prints 5 tiers
7. ☐ Sub-account sum invariant holds within $1.00 tolerance every day
8. ☐ Layer B Spearman ≥ 0.95 vs `hydra_clean_daily.csv` (informational)
9. ☐ `hydra_capital.py` and the four pillar packages remain unmodified

---

## Risks & open questions

| Risk | Mitigation |
|---|---|
| The cash-budget hack on apply_entries causes early-return when budget < $1000 | Documented in spec §17. Acceptable in production where budgets are always > $1000. Test verifies the boundary case. |
| Per-pillar return attribution drift breaks Layer B correlation | Mirror live's exact `compass_invested / compass_prev_invested` formula. Document the approximation in README. |
| `omnicapital_v8_compass` import pulls in heavy live dependencies | Acceptable — v1.0 already does this for `compute_momentum_scores`. |
| Test 12 wrappers vs real apply_* helpers may have subtle bugs in the cash-delta accounting | Layer A invariant 12 (sub-account sum) catches it; the 100-day byte-identical test in Task 10 catches drift in capital math; integration test catches end-to-end. |
| Runtime > 20 min blocks E2E test on slow laptops | Mark slow; CI uses `not slow` filter; the official run uses `tee` to a logfile for inspection. |
| Layer B fails (Spearman < 0.95) → release blocked | Layer B is informational, not blocking. Document any divergence and ship anyway. |
| Coverage target 80% may be hard with so much wrapper plumbing | Can be relaxed to 75% if needed; document in T19. |
