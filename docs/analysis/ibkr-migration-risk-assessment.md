# IBKR Migration Risk Assessment
**Date**: 2026-03-16
**Analyst**: Gemini
**Status**: Complete

## Executive Summary
This assessment evaluates the risks associated with migrating the HYDRA system from its current PaperBroker environment to Interactive Brokers (IBKR). Ten critical blockers were identified in the internal audit, with **ib_async error handling** and **state reconciliation** posing the highest technical risk to live capital.

## Risk Matrix

| Blocker | Description | Probability | Impact | Risk Score |
|---------|-------------|-------------|--------|------------|
| 2.3 | **ib_async Error Handling** | High | Critical | **High** |
| 2.1 | **State Reconciliation (Broker=Truth)** | High | Critical | **High** |
| 3.1 | **MOC Async Polling** | Medium | High | **Medium-High** |
| 1.2 | **Direct Broker State Manipulation** | Low | High | **Medium** |
| 2.2 | **Partial Fill Handling** | Medium | Medium | **Medium** |
| 3.2 | **Pending Order Persistence** | Medium | Medium | **Medium** |
| 1.3 | **EFA Direct Bypass** | Low | High | **Medium** |
| 3.3 | **Kill Switch Gaps** | Low | High | **Medium** |
| 4.1 | **Price Source Abstraction** | Low | Medium | **Low-Medium** |
| 4.4 | **Emergency Liquidation Mode** | Low | Medium | **Low** |

## Critical Path Analysis
- **Phase 1 Stability**: The system cannot enter live IBKR paper trading until **2.3 (Async Error Handling)** is resolved. A network drop currently causes a full process crash.
- **Phase 2 Integrity**: **2.1 (State Reconciliation)** is the primary gatekeeper for capital safety. The system MUST defer to IBKR for position data to avoid phantom trades or missing stops.
- **Phase 3 Execution**: **3.1 (MOC Polling)** and **3.2 (Persistence)** are necessary for reliable 24/7 operation. Without these, the engine is blind to "in-flight" orders after a restart.

## Recommended Implementation Order
1. **Priority 1: Error Handling (2.3)** — Add try/except wrappers and disconnect recovery.
2. **Priority 2: State Reconciliation (2.1)** — Refactor `load_state` to poll IBKR first.
3. **Priority 3: MOC Polling (3.1)** — Replace 5s wait with async status polling loop.
4. **Priority 4: Pending Order Persistence (3.2)** — Save active order IDs to JSON state.
5. **Priority 5: Broker Factory & State Fixes (1.1-1.3)** — Refactor legacy direct attribute access.

## Technical Recommendation
The most critical architectural change is shifting the **Source of Truth** from the `compass_state_latest.json` file to the **Broker Account**. The JSON file should serve as metadata (entry dates, momentum scores) but never as the ground truth for cash or share counts.

## Data Sources
- `docs/plans/2026-03-10-ibkr-live-readiness-audit.md`
- `omnicapital_broker.py`
- `omnicapital_live.py`
