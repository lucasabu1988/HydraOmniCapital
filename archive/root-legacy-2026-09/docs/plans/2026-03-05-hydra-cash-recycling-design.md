# HYDRA: Multi-Strategy Portfolio with Cash Recycling — Design Doc

## Summary

Combine COMPASS (momentum) and Rattlesnake (mean-reversion) into a single portfolio with dynamic cash recycling. When one strategy has idle cash, it flows to the other. Validated over 2000-2026 on survivorship-free data.

## Results (EXP59)

| Metric | HYDRA | COMPASS solo | 50/50 static | Delta vs COMPASS |
|--------|-------|-------------|-------------|-----------------|
| CAGR | 13.28% | 12.27% | 11.87% | +1.01% |
| MaxDD | -23.49% | -32.10% | -18.57% | +8.61% |
| Sharpe | 1.04 | 0.85 | 1.09 | +0.19 |
| Final ($100K) | $2,586K | $2,044K | $1,862K | +$542K |
| Volatility | 12.85% | ~14% | ~10% | -1.15% |
| Worst Year | -21.1% | -24.6% | -16.6% | +3.5% |

Strictly dominates COMPASS solo on all three dimensions (CAGR, MaxDD, Sharpe).

## Architecture

### Segregated Accounts Model

Each strategy runs independently with its own capital account. Cash recycling operates as a capital management layer on top.

```
Total Portfolio ($100K)
├── COMPASS Account (base 50%)
│   ├── Invested in momentum positions
│   └── Idle cash (from DD scaling, vol targeting, etc.)
├── Rattlesnake Account (base 50%)
│   ├── Invested in mean-reversion positions
│   └── Idle cash (51% of the time, 0 positions)
└── Cash Recycling Layer
    └── Daily: R idle cash → C account (capped at 75% total)
```

### Why Segregated Accounts

Integrated backtest (HYDRA v1) failed because:
- COMPASS position sizing depends on available cash, leverage, DD scaling
- Merging capital pools breaks these internal calculations
- Result: 10.29% CAGR (worse than either strategy solo)

Segregated accounts preserve each strategy's behavior exactly, and recycling operates at the account level.

### Cash Recycling Mechanics

Daily process:
1. Compute Rattlesnake exposure: `r_exposure = invested / account_value`
2. Compute idle cash: `r_idle = r_account * (1 - r_exposure)`
3. Compute max recyclable: `max_c = total * 0.75 - c_account`
4. Transfer: `recycle = min(r_idle, max_c)` from R → C
5. Apply returns: recycled cash earns COMPASS returns
6. Settle: return recycled amount (with C returns) to R account

### Parameters

```python
BASE_COMPASS_ALLOC = 0.50    # Base allocation
BASE_RATTLE_ALLOC = 0.50     # Base allocation
MAX_COMPASS_ALLOC = 0.75     # Cap with recycling
```

### Key Statistics

- Rattlesnake idle 51.2% of the time (0 positions)
- Average effective allocation: COMPASS 72.3%, Rattlesnake 27.7%
- Days at max allocation (75%): 77.7%
- Correlation between strategies: 0.38

## What Stays the Same

Both strategies are locked — no parameter changes:

**COMPASS v8.4:**
- Signal: raw momentum 90d, skip 5d, risk-adjusted
- Regime: sigmoid + bull override
- Stops: adaptive (vol-scaled) + trailing
- DD scaling: piecewise-linear 3-tier
- Vol targeting, sector limits, quality filter
- Universe: 750 clean stocks, top-40 annual rotation

**Rattlesnake v1.0:**
- Signal: RSI<25, 8% drop in 5 days, above SMA200
- Exits: +4% profit target, -5% stop, 8-day max hold
- Regime: SPY SMA200 + VIX panic (>35)
- Universe: S&P 100 (OEX)

## Files

### New
- `exp59_hydra_v2.py` — Validated backtest (segregated accounts)
- `exp59_hydra.py` — Integrated backtest (failed, kept for reference)
- `docs/plans/2026-03-05-hydra-cash-recycling-design.md` — This doc

### To Modify
- `omnicapital_live.py` — Add Rattlesnake signal generation + cash recycling logic
- `compass_dashboard.py` — Add HYDRA multi-strategy view (pending user approval)

### Data Files
- `backtests/hydra_v2_daily.csv` — HYDRA daily portfolio values
- `backtests/rattlesnake_daily.csv` — Rattlesnake daily with exposure data

## Risk Assessment

- **Low risk**: Each strategy unchanged internally. Only capital allocation changes.
- **No leverage**: Total portfolio leverage stays at 1.0x max.
- **Graceful degradation**: If Rattlesnake engine fails, COMPASS runs standalone at 50% allocation. Worst case = half of COMPASS, not total failure.
- **Correlation risk**: Strategies can lose simultaneously (10 months in 25 years where both lose >2%). MaxDD reflects this.

## Experiments Leading Here

| Experiment | What | Result | Verdict |
|-----------|------|--------|---------|
| EXP55 | Residual momentum | 10.82% CAGR | FAIL |
| EXP55 baseline | Raw momentum, 750 clean stocks | 12.27% CAGR, 0.85 Sharpe | BASELINE |
| EXP56 | Multi-lookback ensemble | 10.81% CAGR (clean) | FAIL |
| EXP57 | Dynamic hold time | 12.12% CAGR | FAIL |
| EXP58 | Tail hedge overlay | Cost too high | FAIL |
| EXP59 v1 | Integrated HYDRA | 10.29% CAGR | FAIL |
| **EXP59 v2** | **Segregated HYDRA** | **13.28% CAGR, 1.04 Sharpe** | **WIN** |
