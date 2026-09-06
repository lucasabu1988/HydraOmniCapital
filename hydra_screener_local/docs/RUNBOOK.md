# HYDRA runbook

Operator: Lucas. Machine: Windows, not in America/New_York. Production is HYDRA v9,
capital reference 100000 USD, first-run anchor Friday 2026-09-04, first execution
**Tuesday 2026-09-08** close (Monday 2026-09-07 is Labor Day).

Convert "16:00 America/New_York" to local time before scheduling anything. Peru is
UTC−5 year-round; US Eastern is UTC−4 during DST (March–November), so 16:00 ET is
15:00 Peru in September.

## Weekly ritual (a renewal bar)

v9 renews one tranche pair every **5 NYSE bars**, not every calendar Monday. The
instruction sheet always says `ejecutar al cierre del <next NYSE session>`.

After that close:

```
cd hydra_screener_local
python daily.py --v9
```

`daily.py` does, in order:

1. Screener (universe, fetch, sectors, ranking).
2. **preflight** — HARD fail stops here unless `--force`.
3. **settle** pending orders at today's close (t+1 of the previous plan).
4. **dividends** on ex-date (units held before the ex × dps) into tranche cash.
5. **plan** — marks, accrues T-bill interest on idle cash, renews tranche k if this
   is a step bar, writes the next sheet.
6. **journal** — `journal/<date>.json` + `JOURNAL.md`.

Then, the same afternoon or the next morning:

```
python confirm_fills.py                  # CSV or interactive; whole shares enter the book here
python reconcile.py --csv broker.csv --cash-total NNN
python dashboard_v9.py                   # 127.0.0.1:8765 only
```

If there is nothing to execute, the sheet says so. Still run `daily.py`: interest
and dividends accrue on non-renewal days too.

### First run (already done for 2026-09-04)

~30 pending orders, 100k cash, no `last_run_date`. Execute the sheet at the printed
close, then `daily.py` settles. Do **not** run `daily.py --v9` again before executing:
a same-day rerun is idempotent (no new orders) but a later rerun before settle raises.

## Failure modes

| Symptom | What to do |
|---|---|
| preflight **HARD** (stale bar / missing ETF / unknown schema) | Do not plan. Check yfinance / clock / NYSE holiday. `--force` only if you accept yesterday's prices. |
| preflight HARD "last bar != last NYSE session" on a Monday | Holiday: the session is the previous Friday. If the calendar is wrong, stop. |
| Yahoo bar missing, one name | Engine `hold_no_price` / 10-bar stale then write-off at last price. Do not invent a print. |
| A name split overnight | Yahoo closes are split-adjusted; book units are not. `reconcile` will show a phantom qty. H-003 / TASK-363 (flag off until Lucas OKs). Do not hand-edit units without a recorded split. |
| Delisting while held | Carry at last_px until `max_stale_bars=10`, then write-off. Confirm with the broker; `confirm_fills` if there was a residual sale. |
| `not_filled` on the ledger | No print on exec day. The order is recorded, not invented. Next plan will retry or drop. |
| Disk loss / corrupt `state/portfolio_v9.json` | Restore from `HYDRA_BACKUP_DIR/state_v9/<date>/` (or `state/backup/`). TASK-360 `verify_state.py` is the drill once it lands; until then diff the JSON against the last off-disk copy and the last sheet. |
| Sector cap silent (many "Other") | Sheet says **DEGRADED**. Run `python warm_sectors.py --universe all`. Cap is off while Other share of the 2n pool > 0.30. |
| `HYDRA_BACKUP_DIR` unset | preflight WARN. Set it to a folder that is not this disk (OneDrive / USB). |
| Reconcile residual | Listed, not subtracted. Known gaps: broker pays dividends on pay-date, book credits ex-date; interest is modelled not swept; pending orders. Residual > 0.5% is an evidence-review trigger. |
| Dashboard not loading | Bind is 127.0.0.1:8765. Restart `python dashboard_v9.py` after a code pull. |

## Moving the machine

Copy, in this order:

1. The git clone (code + `GROKBOARD.md`).
2. `hydra_screener_local/state/` (the book).
3. `hydra_screener_local/journal/`.
4. `hydra_screener_local/data_cache/` (sectors, universes, dividends, `bars.sqlite` if present).
5. Whatever `HYDRA_BACKUP_DIR` points at — keep it off the new disk too.

Python 3.14 locally, CI 3.12/3.13. `pip install -r requirements.txt`. Dashboard and
`daily.py` must be launched from `hydra_screener_local/` so imports resolve.

Do not commit `state/`, `journal/`, `data_cache/`, or `.coverage`.

## What not to do

- Do not place orders from the machine. The sheet is the order.
- Do not revive Render / COMPASS / a cloud dashboard.
- Do not change scoring, `k`, `MAX_PER_SECTOR`, or `core/portfolio_engine.py` without
  Claude + a hypothesis in `.comms/hypotheses.md`.
- Do not `git add -A`.
