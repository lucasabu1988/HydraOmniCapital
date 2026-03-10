### System Status

COMPASS ML Learning is in **Phase 1** (data collection). 2 trading days logged.
 ML models activate at Phase 2 (~61 trading days remaining).

### Data Summary

- **14 decisions** logged: 11 entries, 3 exits, 0 skips
- **2 daily snapshots** tracking portfolio evolution
- **1 completed trade** with full outcome data

### Portfolio Performance

- **Portfolio Value**: $99,987.34 (return: -0.01%)
- **Peak Value**: $100,000.00
- **Max Drawdown**: -0.95%
- **Cash**: $35,585.89 (35.6%)
- **Invested**: $64,401.45 (64.4%)
- **Active Positions**: 3 (MRK, JNJ, GOOGL)
- **Regime**: RISK_OFF (score 0.548)

### Trade Analysis

- **1 completed trade**: LRCX (Technology)
  - Entry: 2026-03-07 @ $214.68 | Exit: 2026-03-09 (position_stop)
  - Return: **-8.25%** | P&L: **-$1,770.67**
  - Held: 2 trading days | Adaptive stop: -7.76%
  - LRCX breached the adaptive stop on day 2 — high volatility stock (49.3% ann vol) with widened stop (-7.76%) still triggered

### Regime Observations

- **mild_bull**: 1 day (50%)
- **bull**: 1 day (50%)
- Regime shifted from bull (0.70) to mild_bull (0.55) between day 1 and day 2
- SPY close to SMA200 (only +1.8% above) — borderline risk-on/risk-off territory

### Recent Activity

- `2026-03-06T09:33` **EXIT** AMAT — regime_reduce (max positions 5→4)
- `2026-03-07T00:10` **ENTRY** MRK, GOOGL, LRCX, JNJ + 7 simulation entries
- `2026-03-08T09:21` **ENTRY** GS — regime=bull
- `2026-03-09T08:35` **EXIT** LRCX — position_stop (return: -8.25%)

### P&L Breakdown (Cycle 1)

| Symbol | Entry Date | Entry Price | Current/Exit | Return | Status |
|--------|-----------|-------------|-------------|--------|--------|
| LRCX | 2026-03-07 | $214.68 | ~$196.97 | -8.25% | STOPPED |
| MRK | 2026-03-05 | $116.07 | $117.17 (high) | +0.9% | HOLDING |
| JNJ | 2026-03-05 | $239.63 | $244.04 (high) | +1.2% | HOLDING |
| GOOGL | 2026-03-05 | $300.88 | $306.60 (high) | +1.8% | HOLDING |

### Stop Event Log

| Date | Symbol | Reason | Return | Replacement |
|------|--------|--------|--------|-------------|
| 2026-03-09 | LRCX | position_stop | -8.2% | None (RISK_OFF, 3/4 slots used) |

### Next Milestone

Phase 2 ML begins in ~61 trading days. Continue collecting entry/exit decisions and completed trade outcomes.

### Backtest Reference (HYDRA + EFA/MSCI World)

- Period: **2000-01-04** to **2026-02-20** (26.1 years)
- CAGR: **14.9%**
- Sharpe: **1.124**
- Max Drawdown: **-22.2%**
- Total Return: **3669.1%** ($100,000 → $3,769,106)
- Trading Days: **6,572**

---
*Updated manually on 2026-03-10. Refreshes every 5 days.*
