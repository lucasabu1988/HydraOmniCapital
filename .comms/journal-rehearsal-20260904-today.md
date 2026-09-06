# Tuesday rehearsal — mode `today` — session 2026-09-04

Live `state/portfolio_v9.json` unchanged: **True**. `journal/` exists after the run: **False** (expected False). Scratch copy: `C:\Users\caslu\HydraOmniCapital\hydra_screener_local\experiments\_lab_scratch\rehearsal_state`.

## Console (portfolio_v9.run on the copy)

```
[v9] preflight
  last bars             OK    stocks/etf/^IRX = 2026-09-04 = session
  universe print share  OK    100% with a print on 2026-09-04
  ETFs present          OK    10/10
  sector-unknown        SKIP  no ranking
  pending age           OK    planned 2026-09-04, 0 session(s) behind
  HYDRA_BACKUP_DIR      WARN  unset — state/ backup stays on the same disk
  schema_version        OK    schema_version=1
[v9] pending orders from 2026-09-04 still waiting for t+1 (today=2026-09-04)
[v9] skip plan — pending not settled
[v9] AVISO: HYDRA_BACKUP_DIR no esta definido; el backup de state/ queda en el mismo disco
[v9] backed up previous state -> C:\Users\caslu\HydraOmniCapital\hydra_screener_local\experiments\_lab_scratch\rehearsal_state\backup\20260906_080339.json
[v9] state -> C:\Users\caslu\HydraOmniCapital\hydra_screener_local\experiments\_lab_scratch\rehearsal_state\portfolio_v9.json
[v9] instructions -> C:\Users\caslu\HydraOmniCapital\hydra_screener_local\experiments\_lab_scratch\rehearsal_state\instructions_20260904.md
[v9] interest since last run 0.00  cumulative 0.00
[v9] dividends since last run 0.00  cumulative 0.00
[v9] no trades today
```

## Result

- today = 2026-09-04, orders planned = 0, fills settled = 0, pending after run = 30, ledger = 0, last_run_date = 2026-09-04, week_index = 0
- interest records = 0, dividends records = 0, transfers = 0, write_offs = 0
- sheet: C:\Users\caslu\HydraOmniCapital\hydra_screener_local\experiments\_lab_scratch\rehearsal_state\instructions_20260904.md
- sector_warning: None

## sector_report()

```
{
  "cached": 0,
  "fetched": 0,
  "negative": 0,
  "override": 0,
  "unknown": 0
}
```

## universe_report()

```
{
  "universe": "all",
  "source_used": "union",
  "count": 3002,
  "from_cache": false,
  "fallback": false
}
```

## verify_state on the copy

```
state check: clean (0 findings)
```

## Journal record (built, NOT persisted)

None/empty fields (22): `seen.regime_score`, `seen.regime_label`, `seen.recommended_count`, `seen.recommended_n`, `seen.basket_vol63`, `seen.vol_target_exposure`, `seen.etf_on`, `seen.etf_weights`, `seen.sector_cap_displaced`, `seen.degraded`, `did.slippage.mean_bp`, `did.slippage.by_sleeve_mean_bp`, `did.slippage.rows`, `book.sleeves.stocks.names`, `book.sleeves.etf.names`, `expectation.step_return`, `expectation.step_return_percentile`, `expectation.cone`, `expectation.oos_source`, `process.reconcile_residual`, `process.errors`, `observations`

Expectation block:

```
{
  "step_return": null,
  "step_return_percentile": null,
  "live_cumulative": 0.0,
  "cone": null,
  "oos_source": null
}
```

### Rendered record

# HYDRA v9 journal

Automatic rollup (spec 10.1). Does not change any parameter.

## 2026-09-04

Book **100,000.00**  week 0  renewal 2026-09-04
Regime None (None)  rec None/None  expo 0.0  vol63 None
ETF on []  off ['SPY', 'QQQ', 'IWM', 'EFA', 'EEM', 'TLT', 'IEF', 'GLD', 'DBC', 'VNQ']
Orders 30  presumed 0  confirmed 0  not_filled 0  hold_no_price 0  write-offs 0  transfers 0  interest 0
Slippage mean None bp vs modelled 10/5.
Preflight hard=False warn=True
