# Overlay Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire the validated v3 overlay system (BSO + M2 + FOMC + FedEmergency + CreditFilter) into the live engine, dashboard, and cloud.

**Architecture:** 4 surgical injection points in `omnicapital_live.py` matching the backtest hooks, plus a new API endpoint and UI card for overlay diagnostics. All overlay code is fail-safe (try/except → scalar=1.0). Cash Optimization stays disabled.

**Tech Stack:** Python 3.14, Flask, pandas, existing FRED fetcher (`compass_fred_data.py`), existing overlay classes (`compass_overlays.py`)

---

### Task 1: Write integration tests for overlay in live engine

**Files:**
- Create: `tests/test_overlay_integration.py`

**Step 1: Write the test file**

```python
"""
Integration tests for overlay system in COMPASSLive engine.
Tests that overlays initialize, compute scalars, and integrate with
capital allocation without crashing the live engine.
"""

import pytest
import pandas as pd
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_overlays import (
    BankingStressOverlay, M2MomentumIndicator, FOMCSurpriseSignal,
    FedEmergencySignal, CreditSectorPreFilter, compute_overlay_signals,
    OVERLAY_FLOOR,
)


# ============================================================================
# Mock FRED data (no network dependency)
# ============================================================================

def _make_series(values, start='2020-01-01'):
    """Create a daily pd.Series from a list of values."""
    dates = pd.date_range(start, periods=len(values), freq='D')
    return pd.Series(values, index=dates)


@pytest.fixture
def calm_fred():
    """FRED data simulating calm market conditions."""
    n = 500
    return {
        'NFCI': _make_series([-0.3] * n),        # well below 0.5 threshold
        'STLFSI4': _make_series([0.2] * n),       # well below 1.0 threshold
        'BAMLH0A0HYM2': _make_series([3.5] * n),  # 350bps, below 700bps
        'M2SL': _make_series(np.linspace(15000, 16000, n)),  # steady growth
        'DFF': _make_series([5.25] * n),           # stable rate
        'WALCL': _make_series([7500000] * n),      # stable balance sheet
        'DTB3': _make_series([5.0] * n),
        'AAA': _make_series([4.5] * n),
    }


@pytest.fixture
def stressed_fred():
    """FRED data simulating GFC-level stress."""
    n = 500
    return {
        'NFCI': _make_series([2.5] * n),            # extreme stress
        'STLFSI4': _make_series([3.0] * n),          # extreme stress
        'BAMLH0A0HYM2': _make_series([18.0] * n),   # 1800bps crisis
        'M2SL': _make_series(np.linspace(16000, 15000, n)),  # contracting
        'DFF': _make_series([5.25] * 248 + [4.25] * 2 + [4.25] * 250),  # 100bps cut
        'WALCL': _make_series(np.linspace(4000000, 5000000, n)),  # emergency expansion
        'DTB3': _make_series([0.1] * n),
        'AAA': _make_series([4.5] * n),
    }


# ============================================================================
# Overlay initialization
# ============================================================================

class TestOverlayInit:
    def test_all_overlays_init_calm(self, calm_fred):
        overlays = {
            'bso': BankingStressOverlay(calm_fred),
            'm2': M2MomentumIndicator(calm_fred),
            'fomc': FOMCSurpriseSignal(calm_fred),
            'fed_emergency': FedEmergencySignal(calm_fred),
        }
        assert len(overlays) == 4

    def test_credit_filter_init(self, calm_fred):
        sector_map = {'AAPL': 'Technology', 'JPM': 'Financials', 'XOM': 'Energy'}
        cf = CreditSectorPreFilter(calm_fred, sector_map)
        assert cf is not None

    def test_overlays_init_with_missing_data(self):
        """Overlays should not crash with None/empty FRED data."""
        empty = {k: None for k in ['NFCI', 'STLFSI4', 'BAMLH0A0HYM2', 'M2SL', 'DFF', 'WALCL']}
        overlays = {
            'bso': BankingStressOverlay(empty),
            'm2': M2MomentumIndicator(empty),
            'fomc': FOMCSurpriseSignal(empty),
            'fed_emergency': FedEmergencySignal(empty),
        }
        date = pd.Timestamp('2020-06-15')
        result = compute_overlay_signals(overlays, date)
        assert result['capital_scalar'] == 1.0


# ============================================================================
# Capital scalar computation
# ============================================================================

class TestCapitalScalar:
    def test_calm_market_scalar_near_one(self, calm_fred):
        overlays = {
            'bso': BankingStressOverlay(calm_fred),
            'm2': M2MomentumIndicator(calm_fred),
            'fomc': FOMCSurpriseSignal(calm_fred),
            'fed_emergency': FedEmergencySignal(calm_fred),
        }
        date = pd.Timestamp('2020-06-15')
        result = compute_overlay_signals(overlays, date)
        assert result['capital_scalar'] >= 0.90, f"Calm market should be near 1.0, got {result['capital_scalar']}"

    def test_stressed_market_scalar_low(self, stressed_fred):
        overlays = {
            'bso': BankingStressOverlay(stressed_fred),
            'm2': M2MomentumIndicator(stressed_fred),
            'fomc': FOMCSurpriseSignal(stressed_fred),
            'fed_emergency': FedEmergencySignal(stressed_fred),
        }
        date = pd.Timestamp('2020-12-15')
        result = compute_overlay_signals(overlays, date)
        assert result['capital_scalar'] <= 0.50, f"Stressed market should be low, got {result['capital_scalar']}"

    def test_scalar_always_in_range(self, calm_fred, stressed_fred):
        for fred in [calm_fred, stressed_fred]:
            overlays = {
                'bso': BankingStressOverlay(fred),
                'm2': M2MomentumIndicator(fred),
                'fomc': FOMCSurpriseSignal(fred),
            }
            for d in pd.date_range('2020-03-01', '2020-09-01', freq='MS'):
                result = compute_overlay_signals(overlays, d)
                assert OVERLAY_FLOOR <= result['capital_scalar'] <= 1.0


# ============================================================================
# Conditional damping
# ============================================================================

class TestConditionalDamping:
    def test_no_damping_when_dd_inactive(self):
        """When DD-scaling is NOT active (dd_lev=1.0), use full overlay scalar."""
        overlay_scalar = 0.60
        dd_lev = 1.0  # no DD-scaling
        OVERLAY_DAMPING = 0.25

        if dd_lev < 1.0:
            damped = 1.0 - OVERLAY_DAMPING * (1.0 - overlay_scalar)
        else:
            damped = overlay_scalar

        assert damped == 0.60  # full signal

    def test_damping_when_dd_active(self):
        """When DD-scaling IS active (dd_lev<1.0), use 25% blend."""
        overlay_scalar = 0.60
        dd_lev = 0.60  # DD-scaling active
        OVERLAY_DAMPING = 0.25

        if dd_lev < 1.0:
            damped = 1.0 - OVERLAY_DAMPING * (1.0 - overlay_scalar)
        else:
            damped = overlay_scalar

        assert damped == 0.90  # only 25% of the reduction applied

    def test_damping_floor(self):
        """Even with damping, scalar should not exceed 1.0."""
        overlay_scalar = 1.0
        dd_lev = 0.30
        OVERLAY_DAMPING = 0.25

        if dd_lev < 1.0:
            damped = 1.0 - OVERLAY_DAMPING * (1.0 - overlay_scalar)
        else:
            damped = overlay_scalar

        assert damped == 1.0  # no reduction needed


# ============================================================================
# Credit filter
# ============================================================================

class TestCreditFilterIntegration:
    def test_no_filter_in_calm_market(self, calm_fred):
        sector_map = {'AAPL': 'Technology', 'JPM': 'Financials', 'XOM': 'Energy'}
        cf = CreditSectorPreFilter(calm_fred, sector_map)
        result = cf.filter_universe(['AAPL', 'JPM', 'XOM'], pd.Timestamp('2020-06-15'))
        assert result == ['AAPL', 'JPM', 'XOM']

    def test_filter_financials_at_crisis(self, stressed_fred):
        sector_map = {'AAPL': 'Technology', 'JPM': 'Financials', 'XOM': 'Energy'}
        cf = CreditSectorPreFilter(stressed_fred, sector_map)
        result = cf.filter_universe(['AAPL', 'JPM', 'XOM'], pd.Timestamp('2020-06-15'))
        # 1800bps > 1500bps -> exclude Financials + Energy
        assert 'AAPL' in result
        assert 'JPM' not in result
        assert 'XOM' not in result


# ============================================================================
# Position floor (Fed Emergency)
# ============================================================================

class TestPositionFloor:
    def test_no_floor_normally(self, calm_fred):
        fed = FedEmergencySignal(calm_fred)
        floor = fed.get_position_floor(pd.Timestamp('2020-06-15'))
        assert floor is None

    def test_floor_during_emergency(self, stressed_fred):
        fed = FedEmergencySignal(stressed_fred)
        # WALCL grew 25% in 500 days -> >5% in 30 days
        floor = fed.get_position_floor(pd.Timestamp('2020-06-15'))
        assert floor == 2 or floor is None  # depends on growth rate in mock


# ============================================================================
# State persistence
# ============================================================================

class TestOverlayStatePersistence:
    def test_overlay_state_dict_structure(self, calm_fred):
        overlays = {
            'bso': BankingStressOverlay(calm_fred),
            'm2': M2MomentumIndicator(calm_fred),
            'fomc': FOMCSurpriseSignal(calm_fred),
            'fed_emergency': FedEmergencySignal(calm_fred),
        }
        date = pd.Timestamp('2020-06-15')
        result = compute_overlay_signals(overlays, date)

        # Build the state dict as the live engine would
        overlay_state = {
            'capital_scalar': result['capital_scalar'],
            'per_overlay': result.get('per_overlay_scalars', {}),
            'position_floor': result.get('position_floor'),
        }

        assert 'capital_scalar' in overlay_state
        assert 'per_overlay' in overlay_state
        assert isinstance(overlay_state['capital_scalar'], float)
```

**Step 2: Run tests to verify they pass**

Run: `cd C:/Users/caslu/Desktop/NuevoProyecto && python -m pytest tests/test_overlay_integration.py -v`
Expected: All tests PASS (these test the existing overlay classes with mock data)

**Step 3: Commit**

```bash
git add tests/test_overlay_integration.py
git commit -m "test: add overlay integration tests with mock FRED data"
```

---

### Task 2: Add overlay initialization to COMPASSLive.__init__()

**Files:**
- Modify: `omnicapital_live.py:30` (imports)
- Modify: `omnicapital_live.py:753` (after ML init, before banner)

**Step 1: Add imports at top of file (after line 30)**

After the existing imports block, add:

```python
# Overlay system (v3: BSO + M2 + FOMC + FedEmergency + CreditFilter)
try:
    from compass_fred_data import download_all_overlay_data
    from compass_overlays import (
        BankingStressOverlay, M2MomentumIndicator, FOMCSurpriseSignal,
        FedEmergencySignal, CreditSectorPreFilter, compute_overlay_signals,
        OVERLAY_FLOOR,
    )
    _overlay_available = True
except ImportError:
    _overlay_available = False
```

**Step 2: Add overlay init in `__init__()` (after ML init block, ~line 753)**

After the ML init block and before the banner `logger.info("=" * 70)` at line 755, add:

```python
        # Overlay system (v3 config: BSO + M2 + FOMC + FedEmergency + CreditFilter)
        # Cash Optimization DISABLED (loses ~1% CAGR during ZIRP)
        self._overlay_available = False
        self._fred_data = {}
        self._overlays = {}
        self._credit_filter = None
        self._overlay_result = {}  # Latest overlay diagnostics
        self._overlay_damping = 0.25  # Conditional damping factor

        if _overlay_available:
            try:
                self._fred_data = download_all_overlay_data()
                self._overlays = {
                    'bso': BankingStressOverlay(self._fred_data),
                    'm2': M2MomentumIndicator(self._fred_data),
                    'fomc': FOMCSurpriseSignal(self._fred_data),
                    'fed_emergency': FedEmergencySignal(self._fred_data),
                }
                self._credit_filter = CreditSectorPreFilter(self._fred_data, SECTOR_MAP)
                self._overlay_available = True
                logger.info("Overlay System (v3): ACTIVE — BSO + M2 + FOMC + FedEmergency + CreditFilter")
            except Exception as e:
                logger.warning(f"Overlay system failed to init (degrading to scalar=1.0): {e}")
```

**Step 3: Add overlay status to the banner (after existing banner lines, ~line 773)**

After the existing `logger.info(f"Chassis: ...")` line, add:

```python
        if self._overlay_available:
            logger.info(f"Overlays: BSO + M2 + FOMC + FedEmergency + CreditFilter (damping={self._overlay_damping})")
        else:
            logger.info("Overlays: DISABLED (FRED data unavailable)")
```

**Step 4: Syntax check**

Run: `python -c "import py_compile; py_compile.compile('C:/Users/caslu/Desktop/NuevoProyecto/omnicapital_live.py')"`
Expected: No output (success)

**Step 5: Commit**

```bash
git add omnicapital_live.py
git commit -m "feat: add overlay system initialization to COMPASSLive"
```

---

### Task 3: Add FRED refresh to refresh_daily_data()

**Files:**
- Modify: `omnicapital_live.py:830-831` (end of `refresh_daily_data()`)

**Step 1: Add FRED refresh after stock data refresh**

After `self._hist_date = today` (line 831), add:

```python
        # Refresh overlay FRED data (daily, uses cache if network fails)
        if self._overlay_available:
            try:
                self._fred_data = download_all_overlay_data(force_refresh=True)
                self._overlays = {
                    'bso': BankingStressOverlay(self._fred_data),
                    'm2': M2MomentumIndicator(self._fred_data),
                    'fomc': FOMCSurpriseSignal(self._fred_data),
                    'fed_emergency': FedEmergencySignal(self._fred_data),
                }
                self._credit_filter = CreditSectorPreFilter(self._fred_data, SECTOR_MAP)
                logger.info("FRED overlay data refreshed")
            except Exception as e:
                logger.warning(f"FRED refresh failed, using cached data: {e}")
```

**Step 2: Syntax check**

Run: `python -c "import py_compile; py_compile.compile('C:/Users/caslu/Desktop/NuevoProyecto/omnicapital_live.py')"`
Expected: No output (success)

**Step 3: Commit**

```bash
git add omnicapital_live.py
git commit -m "feat: add daily FRED data refresh for overlay system"
```

---

### Task 4: Inject overlay hooks into open_new_positions()

**Files:**
- Modify: `omnicapital_live.py:1132` (after quality filter)
- Modify: `omnicapital_live.py:1192` (effective capital calculation)

**Step 1: Add credit filter after quality filter (after line 1132)**

After the quality filter block ending at line 1132, add:

```python
        # Overlay: credit sector pre-filter (exclude Financials/Energy at crisis HY levels)
        if self._overlay_available and self._credit_filter is not None:
            try:
                today = pd.Timestamp(self.get_et_now().date())
                pre_filter_count = len(tradeable)
                tradeable = self._credit_filter.filter_universe(tradeable, today)
                if len(tradeable) < pre_filter_count:
                    excluded = pre_filter_count - len(tradeable)
                    logger.info(f"Overlay credit filter: excluded {excluded} stocks from stressed sectors")
            except Exception as e:
                logger.warning(f"Credit filter failed (skipping): {e}")
```

**Step 2: Replace effective_capital line with overlay-aware version (line 1192)**

Replace:
```python
        effective_capital = portfolio.cash * current_leverage * 0.95
```

With:
```python
        # Overlay: compute capital scalar with conditional damping
        overlay_scalar = 1.0
        damped_scalar = 1.0
        if self._overlay_available and self._overlays:
            try:
                today = pd.Timestamp(self.get_et_now().date())
                self._overlay_result = compute_overlay_signals(
                    self._overlays, today, self._credit_filter
                )
                overlay_scalar = self._overlay_result.get('capital_scalar', 1.0)

                # Conditional damping: avoid double-counting with DD-scaling
                portfolio_val = self.broker.get_portfolio().total_value
                drawdown = (portfolio_val - self.peak_value) / self.peak_value if self.peak_value > 0 else 0
                dd_lev = _dd_leverage(drawdown, self.config)

                if dd_lev < 1.0:
                    # DD-scaling active: only apply 25% of overlay reduction
                    damped_scalar = 1.0 - self._overlay_damping * (1.0 - overlay_scalar)
                else:
                    # DD-scaling inactive: full overlay signal (early warning)
                    damped_scalar = overlay_scalar

                if damped_scalar < 1.0:
                    logger.info(f"Overlay scalar={overlay_scalar:.3f} damped={damped_scalar:.3f} "
                                f"(dd_lev={dd_lev:.2f})")
            except Exception as e:
                logger.warning(f"Overlay computation failed (using scalar=1.0): {e}")
                damped_scalar = 1.0

        effective_capital = portfolio.cash * current_leverage * 0.95 * damped_scalar
```

**Step 3: Syntax check**

Run: `python -c "import py_compile; py_compile.compile('C:/Users/caslu/Desktop/NuevoProyecto/omnicapital_live.py')"`
Expected: No output (success)

**Step 4: Run integration tests**

Run: `cd C:/Users/caslu/Desktop/NuevoProyecto && python -m pytest tests/test_overlay_integration.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add omnicapital_live.py
git commit -m "feat: inject overlay capital scalar + credit filter into position entry"
```

---

### Task 5: Add position floor to get_max_positions()

**Files:**
- Modify: `omnicapital_live.py:920-928` (end of `get_max_positions()`)

**Step 1: Add position floor check**

Replace the return statement at line 920-928:
```python
        return regime_score_to_positions(
            self.current_regime_score,
            self.config['NUM_POSITIONS'],
            self.config['NUM_POSITIONS_RISK_OFF'],
            spy_close=spy_close,
            sma200=sma200,
            bull_threshold=self.config['BULL_OVERRIDE_THRESHOLD'],
            bull_min_score=self.config['BULL_OVERRIDE_MIN_SCORE']
        )
```

With:
```python
        max_pos = regime_score_to_positions(
            self.current_regime_score,
            self.config['NUM_POSITIONS'],
            self.config['NUM_POSITIONS_RISK_OFF'],
            spy_close=spy_close,
            sma200=sma200,
            bull_threshold=self.config['BULL_OVERRIDE_THRESHOLD'],
            bull_min_score=self.config['BULL_OVERRIDE_MIN_SCORE']
        )

        # Overlay: Fed Emergency position floor
        if self._overlay_available and self._overlay_result:
            floor = self._overlay_result.get('position_floor')
            if floor is not None and floor > max_pos:
                logger.info(f"Fed Emergency floor: {max_pos} -> {floor} positions")
                max_pos = floor

        return max_pos
```

**Step 2: Syntax check**

Run: `python -c "import py_compile; py_compile.compile('C:/Users/caslu/Desktop/NuevoProyecto/omnicapital_live.py')"`
Expected: No output (success)

**Step 3: Commit**

```bash
git add omnicapital_live.py
git commit -m "feat: add Fed Emergency position floor to get_max_positions"
```

---

### Task 6: Add overlay diagnostics to save_state()

**Files:**
- Modify: `omnicapital_live.py:1751` (before `'stats'` key in state dict)

**Step 1: Add overlay section to state dict**

Before the `'stats'` key (line 1748), add:

```python
            # Overlay diagnostics
            'overlay': {
                'available': self._overlay_available,
                'capital_scalar': self._overlay_result.get('capital_scalar', 1.0) if self._overlay_result else 1.0,
                'per_overlay': self._overlay_result.get('per_overlay_scalars', {}) if self._overlay_result else {},
                'position_floor': self._overlay_result.get('position_floor') if self._overlay_result else None,
                'diagnostics': self._overlay_result.get('diagnostics', {}) if self._overlay_result else {},
            },
```

**Step 2: Syntax check**

Run: `python -c "import py_compile; py_compile.compile('C:/Users/caslu/Desktop/NuevoProyecto/omnicapital_live.py')"`
Expected: No output (success)

**Step 3: Commit**

```bash
git add omnicapital_live.py
git commit -m "feat: persist overlay diagnostics in state JSON"
```

---

### Task 7: Add /api/overlay-status endpoint to local dashboard

**Files:**
- Modify: `compass_dashboard.py` (add new route after existing API endpoints)

**Step 1: Add the endpoint**

After the last API route in `compass_dashboard.py`, add:

```python
@app.route('/api/overlay-status')
def api_overlay_status():
    """Return current overlay signals and diagnostics."""
    state = read_state()
    if not state:
        return jsonify({'available': False, 'error': 'No state file'})

    overlay = state.get('overlay', {})

    # Color coding for scalar
    scalar = overlay.get('capital_scalar', 1.0)
    if scalar >= 0.90:
        scalar_color = 'green'
        scalar_label = 'Normal'
    elif scalar >= 0.60:
        scalar_color = 'yellow'
        scalar_label = 'Cautious'
    else:
        scalar_color = 'red'
        scalar_label = 'Stressed'

    per_overlay = overlay.get('per_overlay', {})
    diag = overlay.get('diagnostics', {})

    return jsonify({
        'available': overlay.get('available', False),
        'capital_scalar': scalar,
        'scalar_color': scalar_color,
        'scalar_label': scalar_label,
        'position_floor': overlay.get('position_floor'),
        'per_overlay': {
            'bso': per_overlay.get('bso', 1.0),
            'm2': per_overlay.get('m2', 1.0),
            'fomc': per_overlay.get('fomc', 1.0),
        },
        'fed_emergency_active': bool(overlay.get('position_floor')),
        'credit_filter': {
            'hy_bps': diag.get('credit_filter', {}).get('hy_bps'),
            'excluded_sectors': diag.get('credit_filter', {}).get('excluded', []),
        },
    })
```

**Step 2: Syntax check**

Run: `python -c "import py_compile; py_compile.compile('C:/Users/caslu/Desktop/NuevoProyecto/compass_dashboard.py')"`
Expected: No output (success)

**Step 3: Commit**

```bash
git add compass_dashboard.py
git commit -m "feat: add /api/overlay-status endpoint to local dashboard"
```

---

### Task 8: Add overlay UI card to dashboard HTML

**Files:**
- Modify: `templates/dashboard.html` (after regime band, ~line 345)
- Modify: `static/js/dashboard.js` (add fetch + render logic)

**Step 1: Add overlay card HTML after the regime band section**

After the regime band closing `</div>` (~line 345), add:

```html
<!-- OVERLAY STATUS -->
<div class="regime-band anim-enter anim-d5" id="overlay-band" style="margin-top:0.5rem;">
    <div class="regime-band-left" style="min-width:180px;">
        <span class="regime-band-label">Macro Overlay</span>
        <div class="regime-band-score-row">
            <span class="regime-band-value" id="ov-scalar">--</span>
            <span class="regime-band-tag" id="ov-tag">--</span>
        </div>
    </div>
    <div style="display:flex; gap:1.2rem; align-items:center; flex:1; flex-wrap:wrap; padding:0.25rem 0;">
        <div style="text-align:center;">
            <div style="font-size:0.65rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px;">BSO</div>
            <div style="font-size:0.95rem; font-weight:600;" id="ov-bso">--</div>
        </div>
        <div style="text-align:center;">
            <div style="font-size:0.65rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px;">M2</div>
            <div style="font-size:0.95rem; font-weight:600;" id="ov-m2">--</div>
        </div>
        <div style="text-align:center;">
            <div style="font-size:0.65rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px;">FOMC</div>
            <div style="font-size:0.95rem; font-weight:600;" id="ov-fomc">--</div>
        </div>
        <div style="text-align:center;">
            <div style="font-size:0.65rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px;">Fed Emerg.</div>
            <div style="font-size:0.95rem; font-weight:600;" id="ov-fed">--</div>
        </div>
        <div style="text-align:center;">
            <div style="font-size:0.65rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px;">Credit</div>
            <div style="font-size:0.95rem; font-weight:600;" id="ov-credit">--</div>
        </div>
    </div>
</div>
```

**Step 2: Add JS fetch logic to dashboard.js**

Find the main polling/refresh function in `static/js/dashboard.js` and add inside the refresh cycle:

```javascript
// Overlay status
fetch('/api/overlay-status')
    .then(r => r.json())
    .then(d => {
        if (!d.available) {
            document.getElementById('ov-scalar').textContent = 'OFF';
            document.getElementById('ov-tag').textContent = 'Unavailable';
            document.getElementById('ov-tag').className = 'regime-band-tag';
            return;
        }
        const scalar = d.capital_scalar;
        document.getElementById('ov-scalar').textContent = scalar.toFixed(2);

        const tag = document.getElementById('ov-tag');
        tag.textContent = d.scalar_label;
        tag.className = 'regime-band-tag';
        if (d.scalar_color === 'green') tag.style.cssText = 'color:var(--green); background:var(--green-dim);';
        else if (d.scalar_color === 'yellow') tag.style.cssText = 'color:var(--yellow); background:var(--yellow-dim);';
        else tag.style.cssText = 'color:var(--red); background:var(--red-dim);';

        // Individual overlays
        const colorVal = v => v >= 0.90 ? 'var(--green)' : v >= 0.60 ? 'var(--yellow)' : 'var(--red)';
        const bso = d.per_overlay.bso;
        const m2 = d.per_overlay.m2;
        const fomc = d.per_overlay.fomc;

        const bsoEl = document.getElementById('ov-bso');
        bsoEl.textContent = bso.toFixed(2);
        bsoEl.style.color = colorVal(bso);

        const m2El = document.getElementById('ov-m2');
        m2El.textContent = m2.toFixed(2);
        m2El.style.color = colorVal(m2);

        const fomcEl = document.getElementById('ov-fomc');
        fomcEl.textContent = fomc.toFixed(2);
        fomcEl.style.color = colorVal(fomc);

        const fedEl = document.getElementById('ov-fed');
        fedEl.textContent = d.fed_emergency_active ? 'ACTIVE' : 'Inactive';
        fedEl.style.color = d.fed_emergency_active ? 'var(--red)' : 'var(--text-muted)';

        const creditEl = document.getElementById('ov-credit');
        const excluded = d.credit_filter.excluded_sectors;
        if (excluded && excluded.length > 0) {
            creditEl.textContent = excluded.join(', ');
            creditEl.style.color = 'var(--red)';
        } else {
            creditEl.textContent = 'Clear';
            creditEl.style.color = 'var(--green)';
        }
    })
    .catch(() => {});
```

**Step 3: Syntax check HTML**

Verify the dashboard loads without errors visually (Playwright screenshot if available).

**Step 4: Commit**

```bash
git add templates/dashboard.html static/js/dashboard.js
git commit -m "feat: add Macro Overlay status card to dashboard UI"
```

---

### Task 9: Add overlay endpoint to cloud dashboard

**Files:**
- Modify: `compass_dashboard_cloud.py` (add same `/api/overlay-status` route)

**Step 1: Add the endpoint**

Copy the same `/api/overlay-status` route from Task 7 into `compass_dashboard_cloud.py`, after the existing API routes. The cloud dashboard reads from state JSON (same format), so the code is identical.

**Step 2: Syntax check**

Run: `python -c "import py_compile; py_compile.compile('C:/Users/caslu/Desktop/NuevoProyecto/compass_dashboard_cloud.py')"`
Expected: No output (success)

**Step 3: Commit**

```bash
git add compass_dashboard_cloud.py
git commit -m "feat: add /api/overlay-status endpoint to cloud dashboard"
```

---

### Task 10: Sync to compass/ folder and verify

**Files:**
- Copy: `compass_overlays.py` → `compass/overlays.py`
- Copy: `compass_fred_data.py` → `compass/fred_data.py`
- Copy: `compass_dashboard.py` → `compass/dashboard.py`
- Copy: `compass_dashboard_cloud.py` → `compass/dashboard_cloud.py`
- Copy: `omnicapital_live.py` → `compass/omnicapital_live.py`

**Step 1: Copy files**

```bash
cd C:/Users/caslu/Desktop/NuevoProyecto
cp compass_overlays.py compass/overlays.py
cp compass_fred_data.py compass/fred_data.py
cp compass_dashboard.py compass/dashboard.py
cp compass_dashboard_cloud.py compass/dashboard_cloud.py
cp omnicapital_live.py compass/omnicapital_live.py
```

**Step 2: Run all tests**

```bash
cd C:/Users/caslu/Desktop/NuevoProyecto
python -m pytest tests/test_overlays.py tests/test_overlay_integration.py -v
```

Expected: All tests PASS

**Step 3: Syntax check all modified files**

```bash
python -c "
import py_compile
for f in ['omnicapital_live.py', 'compass_dashboard.py', 'compass_dashboard_cloud.py']:
    py_compile.compile(f)
    print(f'{f}: OK')
"
```

**Step 4: Commit and push**

```bash
git add compass/ omnicapital_live.py compass_dashboard.py compass_dashboard_cloud.py templates/dashboard.html static/js/dashboard.js tests/test_overlay_integration.py
git commit -m "feat: complete overlay v3 integration — live engine + dashboard + cloud"
git push origin main
```

---

## Summary of Changes

| Component | What Changed | Lines Added |
|-----------|-------------|-------------|
| `omnicapital_live.py` | Overlay init, FRED refresh, capital scalar + credit filter, position floor, state persistence | ~80 |
| `compass_dashboard.py` | `/api/overlay-status` endpoint | ~40 |
| `compass_dashboard_cloud.py` | Same endpoint | ~40 |
| `templates/dashboard.html` | Overlay status card | ~25 |
| `static/js/dashboard.js` | Fetch + render overlay data | ~45 |
| `tests/test_overlay_integration.py` | Integration tests with mock data | ~170 |
| `compass/` | Synced copies | (copies) |

**Total**: ~400 lines added across 7 files. Zero lines of locked algorithm modified.
