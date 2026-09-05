# HYDRA Meta-Layer v1 — Phase 4 Integration Preparation
**Date**: 2026-05-31  
**Status**: Ready for implementation (after Task 3.2 completes)  
**Context**: Live code inspection of `omnicapital_live.py` (4723 lines) + `hydra_capital.py` (319 lines) performed in the feature worktree. All Phase 0-2 complete + Task 3.1 committed. Task 3.2 subagent in progress.

---

## 1. Integration Philosophy (Non-Negotiable)

- **Meta-Layer is optional and default-OFF** for first deployment.
- **Never touches locked COMPASS v8.4 signal logic** (`omnicapital_v84_compass.py` and equivalents).
- **Extends**, does not replace, the existing May 2026 regime-aware `HydraCapitalManager`.
- **Fail-safe everywhere**: any error in Meta-Layer path → fall back to current behavior (neutral multipliers = 1.0, recycling_mult = 1.0).
- **Atomic state writes only** (the pattern already used in `save_state`).
- **Rich decision logging** for every cycle where Meta-Layer is active (rationale, scores, decision, applied multipliers).
- **Human override** knobs must exist from day one.

---

## 2. Exact Code Locations Identified (Live Inspection)

### 2.1 `hydra_capital.py` (Task 4.1 target)
- **Current regime support**: Simple string `regime` passed to `compute_allocation(...)`, `update_accounts_after_day(...)`, and helpers.
- **Key methods to extend**:
  - `compute_allocation(rattle_exposure, regime="neutral")` → add optional `meta_decision: Optional[MetaLayerDecision] = None`
  - `get_status(...)` → include meta-derived fields when present.
  - `to_dict()` / `from_dict()` → must survive round-trip with new meta fields (backward compatible).
- **Proposed minimal extension** (backward compatible):
  ```python
  def compute_allocation(self, rattle_exposure: float, regime: str = "neutral",
                         meta_decision: Optional["MetaLayerDecision"] = None) -> Dict[str, float]:
      ...
      if meta_decision:
          # Apply gross exposure target + pillar multipliers + recycling_multiplier
          ...
  ```
- New helper (or extend existing):
  - `apply_meta_layer_decision(self, decision: "MetaLayerDecision") -> None`
  - Or purely functional: decision is passed per-call (preferred for statelessness).

### 2.2 `omnicapital_live.py` (Task 4.2 + 4.3 + 4.4 targets)
**Initialization site** (≈ line 971):
```python
if _hydra_available:
    self.hydra_capital = HydraCapitalManager(...)
    self._current_regime = "neutral"
```

**Allocation call sites** (multiple, ~1955, 1976, 2200, etc.):
```python
current_regime = getattr(self, '_current_regime', 'neutral')
alloc = self.hydra_capital.compute_allocation(r_exposure, regime=current_regime)
```

**State persistence** (`save_state`, ≈4684+):
- Already persists `capital_manager: self.hydra_capital.to_dict()`
- Uses strict atomic write (`tempfile.mkstemp` + `os.replace`)
- We must add under a `meta_layer` top-level key (or inside `capital_manager`).

**Regime detection** (existing simple regime + new full MetaLayer):
- There is already `_current_regime` + calls to `detect_regime` / `regime.py`.
- The new `BasicRegimeOS` (Phase 1) + `RiskBudgetMetaLayer` / ensemble will produce much richer `RegimeScores` + `MetaLayerDecision`.

**Import guards** (pattern to copy):
- `_hydra_available`, `_ml_available`, `_git_sync_available`
- We will add `_meta_layer_available = False` and set it only when flag + imports succeed.

---

## 3. Proposed Feature Flag & Safety Design (Task 4.4)

### 3.1 Recommended Flag (simple, effective, matches existing patterns)
Environment variable (Render + local):
```bash
ENABLE_META_LAYER=0          # default, completely disabled
ENABLE_META_LAYER=1          # enabled (still conservative)
ENABLE_META_LAYER=shadow     # enabled for logging only (decisions computed and logged, but multipliers forced to 1.0)
```

Config fallback in `omnicapital_config.json` or `config` dict passed to `COMPASSLive`.

### 3.2 Runtime Controls (exposed in state + dashboard later)
- `meta_layer_enabled: bool`
- `meta_layer_mode: "off" | "shadow" | "live"`
- `meta_layer_override_gross_exposure: float | null`  (manual force)
- `meta_layer_override_recycling_mult: float | null`

### 3.3 Graceful Degradation Matrix
| Condition                        | Behavior                              | Logged? |
|----------------------------------|---------------------------------------|---------|
| `ENABLE_META_LAYER` not set / 0  | Skip entirely (current behavior)      | No      |
| Import of hydra_meta fails       | `_meta_layer_available = False`       | Yes (once) |
| `compute_decision` raises        | Return neutral decision, disable for this cycle | Yes |
| MetaLayerDecision has low confidence | Still apply (rules already conservative) | Yes |
| Any NaN / inf in multipliers     | Clamp to [0.6, 1.5] + warning         | Yes |
| Shadow mode                      | Compute + log full decision, but force multipliers=1.0, recycling=1.0 | Yes (rich) |

---

## 4. New State Fields (Task 4.3) — Proposal

Add under top level of `compass_state_latest.json` (and daily files):

```json
"meta_layer": {
  "enabled": true,
  "mode": "live",
  "version": "meta-v1.0-risk-202606",
  "last_decision": {
    "as_of": "2026-05-31",
    "gross_exposure": 0.92,
    "multipliers": {
      "COMPASS": 1.12,
      "Rattlesnake": 0.95,
      "Catalyst": 0.88,
      "EFA": 1.05
    },
    "recycling_multiplier": 0.85,
    "active_modes": ["POST_CRISIS_RECOVERY", "ELEVATED_VOL_DEFENSIVE"],
    "risk_flags": ["RECOVERY_ACCEL"],
    "confidence": 0.71,
    "rationale": "Recovery mode + elevated vol → defensive tilt on diversifiers + accelerated recycle"
  },
  "regime_scores": { ... full RegimeScores snapshot ... },
  "ensemble_prediction": { ... optional forward signals if 3.1 used ... }
}
```

Also add lightweight fields at top level for quick dashboard consumption:
- `meta_layer_gross_exposure_target`
- `meta_layer_compass_mult`
- etc. (or keep everything nested under `meta_layer`).

**Persistence rule**: only write these keys when meta layer was actually active in the cycle.

---

## 5. Implementation Order (Recommended)

1. **Task 4.4 first** (flag + import guard + safety harness) — zero risk.
2. **Task 4.1** (extend `HydraCapitalManager` with optional `meta_decision` param + `apply_...` helper + update `to_dict`/`get_status`).
3. **Task 4.3** (state schema + logging helpers) — can be done in parallel with 4.1.
4. **Task 4.2** (wire in `COMPASSLive.__init__`, one call site first as pilot, then all allocation sites, plus `save_state`).
5. Add rich cycle logging (new method `log_meta_decision`).
6. Update dashboard / API surface (later, Phase 6).

All changes must keep the existing simple string `regime` path 100% working when flag is off.

---

## 6. Concrete Next Steps for Implementer Subagent (when ready)

- [ ] Add `ENABLE_META_LAYER` handling + lazy import block in `omnicapital_live.py` near other `_xxx_available` flags.
- [ ] Create (or extend) `hydra_meta/__init__.py` to export the main classes cleanly.
- [ ] Modify `HydraCapitalManager` (minimal diff, all new params optional with safe defaults).
- [ ] Add unit tests for the new `compute_allocation(..., meta_decision=...)` path (synthetic `MetaLayerDecision` objects).
- [ ] Implement the atomic state extension + round-trip test (`to_dict` → `from_dict`).
- [ ] Wire one allocation call site behind the flag as a pilot.
- [ ] Full self-review + update plan checkboxes.

---

## 7. Risks & Mitigations Specific to Phase 4

- **State file bloat** → Only persist when meta active; keep snapshots small.
- **Multiple allocation call sites** → Centralize the "get effective budgets" logic if possible (or accept small duplication behind a helper method on the live engine).
- **Version skew on restart** (old state without meta fields) → `from_dict` must be robust.
- **Dashboard / API consumers** → New fields must be optional in all readers.

---

## 8. References

- Design spec: `docs/superpowers/specs/2026-06-05-hydra-meta-layer-v1-design.md` (esp. §8)
- Implementation plan: `docs/superpowers/plans/2026-06-05-hydra-meta-layer-v1-implementation.md`
- Current regime work (May 2026): comments at top of `hydra_capital.py`
- Atomic write pattern: `omnicapital_live.py:save_state`
- Existing import guards: top of `omnicapital_live.py`

---

**Prepared by**: Controller (after live code inspection on 2026-05-31)  
**Ready for**: Subagent-driven implementation of Phase 4 once Task 3.2 is complete and reviewed.

This document should be the single source of truth handed to the implementer subagent(s) for Phase 4.
