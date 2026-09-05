# Overlay Integration into COMPASS Production System

**Date**: 2026-03-02
**Status**: Approved
**Scope**: Integrate validated v3 overlay system into live engine, dashboard, and cloud

## Context

The overlay system (BSO + M2 + FOMC + Fed Emergency + Credit Filter) was validated via A/B backtest:
- Full period: CAGR -0.20%, Sharpe +0.008 (passes kill criteria)
- OOS 2020-2026: MaxDD improved by +3.72%
- Cash Optimization disabled (loses ~1% CAGR during ZIRP)

Overlays exist as standalone modules (`compass_overlays.py`, `compass_fred_data.py`, `compass_overlay_backtest.py`) but are not wired into the live system.

## Design

### Approach: Minimal-Injection (Option A)

Modify `omnicapital_live.py` directly with 4 surgical injection points matching the backtest hooks. Hardcoded v3 config — no runtime toggles.

### Files Modified

| File | Change |
|------|--------|
| `omnicapital_live.py` | 4 injection points (~60 lines) |
| `compass_dashboard.py` | `/api/overlay-status` endpoint + overlay panel |
| `compass_dashboard_cloud.py` | Same endpoint for cloud |
| `templates/dashboard.html` | Overlay status UI card |
| `compass/` | Sync overlay files + updated dashboard/live engine |

### Injection Points in omnicapital_live.py

**1. `__init__()` — Initialize overlays**
- Import and instantiate 5 overlay objects (BSO, M2, FOMC, FedEmergency, CreditFilter)
- Download FRED data with caching
- Wrapped in try/except — fails safe to scalar=1.0

**2. `refresh_daily_data()` — Refresh FRED daily**
- Re-download FRED series alongside SPY/universe refresh
- On failure, use cached data (no crash)

**3. `open_new_positions()` — Two sub-injections**
- After quality filter: apply `CreditSectorPreFilter.filter_universe()`
- After leverage calc: apply capital scalar with conditional damping
  - DD-scaling inactive → full overlay scalar
  - DD-scaling active → 25% blend: `1.0 - 0.25 * (1.0 - scalar)`

**4. `get_max_positions()` — Position floor**
- Apply Fed Emergency position floor (min 2 positions)

**5. `save_state()` — Persist diagnostics**
- Add `overlay` dict to state JSON with scalar values and diagnostics

### Dashboard Changes

- New `/api/overlay-status` endpoint returning current signals
- New "Macro Overlay" UI card with color-coded scalar display
- Individual overlay breakdown (BSO, M2, FOMC, FedEmergency, CreditFilter)

### Safety Guarantees

- All overlay code wrapped in try/except (fail-safe)
- FRED data cached locally — network failures use stale cache
- Cash Optimization remains disabled
- No changes to signal logic, sizing math, or exit conditions
- Overlay only affects capital multiplier on new entries
