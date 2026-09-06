# Tuesday rehearsal — mode `simulate-t1` — session 2026-09-08

Live `state/portfolio_v9.json` unchanged: **True**. `journal/` exists after the run: **False** (expected False). Scratch copy: `C:\Users\caslu\HydraOmniCapital\hydra_screener_local\experiments\_lab_scratch\rehearsal_state`.

## Console (portfolio_v9.run on the copy)

```
[v9] preflight
  last bars             OK    stocks/etf/^IRX = 2026-09-08 = session
  universe print share  OK    100% with a print on 2026-09-08
  ETFs present          OK    10/10
  sector-unknown        SKIP  no ranking
  pending age           OK    planned 2026-09-04, 1 session(s) behind
  HYDRA_BACKUP_DIR      WARN  unset — state/ backup stays on the same disk
  schema_version        OK    schema_version=1
[v9] settled 30 fill(s) at 2026-09-08 (planned 2026-09-04, run 2026-09-08)
   [DATA QUALITY] Eliminados 14 tickers por salto diario >100% en 252 barras: ['AGL', 'COGT', 'CRVS', 'DMRA', 'FTH', 'GPCR']...
   [SECTOR CONTROL] 11 nombres desplazados por el limite de 5 por sector: ['IMMX', 'IBRX', 'MAZE', 'RVMD', 'PEN']...
[v9] plan 2026-09-08: 0 order(s)
[v9] AVISO: HYDRA_BACKUP_DIR no esta definido; el backup de state/ queda en el mismo disco
[v9] backed up previous state -> C:\Users\caslu\HydraOmniCapital\hydra_screener_local\experiments\_lab_scratch\rehearsal_state\backup\20260906_081111.json
[v9] state -> C:\Users\caslu\HydraOmniCapital\hydra_screener_local\experiments\_lab_scratch\rehearsal_state\portfolio_v9.json
[v9] instructions -> C:\Users\caslu\HydraOmniCapital\hydra_screener_local\experiments\_lab_scratch\rehearsal_state\instructions_20260908.md
[v9] interest since last run 12.75  cumulative 12.75
[v9] dividends since last run 0.00  cumulative 0.00
[v9] no trades today
```

## Result

- today = 2026-09-08, orders planned = 0, fills settled = 30, pending after run = 0, ledger = 30, last_run_date = 2026-09-08, week_index = 0
- interest records = 2, dividends records = 0, transfers = 0, write_offs = 0
- sheet: C:\Users\caslu\HydraOmniCapital\hydra_screener_local\experiments\_lab_scratch\rehearsal_state\instructions_20260908.md
- sector_warning: None

## sector_report()

```
{
  "cached": 2518,
  "fetched": 0,
  "negative": 5,
  "override": 0,
  "unknown": 5
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

None/empty fields (10): `seen.regime_label`, `seen.degraded`, `did.orders`, `expectation.step_return`, `expectation.step_return_percentile`, `expectation.cone`, `expectation.oos_source`, `process.reconcile_residual`, `process.errors`, `observations`

Non-JSON-native fields (0, saved via default=str): none

Expectation block:

```
{
  "step_return": null,
  "step_return_percentile": null,
  "live_cumulative": 2e-05,
  "cone": null,
  "oos_source": null
}
```

### Rendered record

# HYDRA v9 journal

Automatic rollup (spec 10.1). Does not change any parameter.

## 2026-09-08

Book **100,001.97**  week 0  renewal 2026-09-04
Regime 0.686 (None)  rec 16/22  expo 0.14250843601239235  vol63 0.2626
ETF on ['DBC', 'EEM', 'EFA', 'GLD', 'IWM', 'QQQ', 'SPY', 'VNQ']  off ['TLT', 'IEF']
Sector-cap displaced: IMMX(Healthcare), IBRX(Healthcare), MAZE(Healthcare), RVMD(Healthcare), PEN(Healthcare), ROIV(Healthcare), DNTH(Healthcare), ALMS(Healthcare), GLUE(Healthcare), TYRA(Healthcare), RLAY(Healthcare)
Orders 0  presumed 30  confirmed 0  not_filled 0  hold_no_price 0  write-offs 0  transfers 0  interest 12.754437
Slippage mean 0.0 bp vs modelled 10/5.
Preflight hard=False warn=True
