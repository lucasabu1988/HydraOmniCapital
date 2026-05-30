"""
hydra_meta — HYDRA Meta-Layer v1 Package (Phase 2)

Public surface for the Meta-Layer Decision Engine (Task 2.1 interface)
and future components (risk budgeting, pillar multipliers, special modes).

This package was created per clarification during Task 2.1 implementation
(evolution from initial plan's single meta_layer.py at root; mirrors
the "may adopt hydra_meta/ later" note in regime_os.py).

Exports:
- PortfolioState (frozen input snapshot)
- MetaLayerDecision (frozen output contract)
- MetaLayer (runtime_checkable Protocol)
- StubMetaLayer (minimal neutral implementation for safe defaults)
- RiskBudgetParams + RiskBudgetMetaLayer (Task 2.2)
- PillarMultiplierParams (Task 2.3 dedicated config)
- SEED (project convention)

See:
- meta_layer.py for the full contract + documentation
- docs/superpowers/plans/2026-06-05-hydra-meta-layer-v1-implementation.md (Task 2.1)
- docs/superpowers/specs/2026-06-05-hydra-meta-layer-v1-design.md (Section 6)
- regime_os.py for the upstream Regime OS types this depends on
"""

from .meta_layer import (
    PortfolioState,
    MetaLayerDecision,
    MetaLayer,
    StubMetaLayer,
    RiskBudgetParams,
    RiskBudgetMetaLayer,
    PillarMultiplierParams,  # NEW Task 2.3
    SEED,
)

__all__ = [
    "PortfolioState",
    "MetaLayerDecision",
    "MetaLayer",
    "StubMetaLayer",
    "RiskBudgetParams",
    "RiskBudgetMetaLayer",
    "PillarMultiplierParams",  # NEW Task 2.3
    "SEED",
]
