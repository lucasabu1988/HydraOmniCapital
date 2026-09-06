# TASK-352 — preflight.py: refuse to plan on bad data

Pure function over fetched frames (no network). `portfolio_v9.run` / `daily.py`
print the table and stop on a hard fail unless `--force`. Engine not edited.

## Checks

| check | hard / warn | rule |
|---|---|---|
| last bars | HARD | stock, ETF and `^IRX` last dates must be equal, and equal to the last NYSE session |
| universe print share | WARN | share of names with a print on that bar < 90% |
| ETFs present | HARD | 10/10 of `V9["etf_universe"]` have a print on that bar |
| sector-unknown | WARN | existing `sector_degraded_message` (Other share in 2n pool > 0.30) |
| pending age | WARN | pending planned more than one session behind today |
| `HYDRA_BACKUP_DIR` | WARN | unset |
| `schema_version` | HARD | missing or not in `{STATE_SCHEMA}` (= 1) |

Last NYSE session = last weekday on or before `asof`. Holidays false-alarm a few
times a year; `--force` is the escape. Live `run()` uses wall-clock `asof`;
injected `fetch_fn` (tests) uses the fixture's last bar so the suite is not
clock-dependent.

A hard fail happens **before** settle/plan/write, so a stale Yahoo day does not
produce a sheet and does not mutate `state/`.

## CLI

- `python portfolio_v9.py --force`
- `python daily.py --force` (passed through)

## Tests (`test_preflight.py`)

Matching Friday, mismatched dates, stale IRX, bar ≠ session, Saturday→Friday,
9/10 ETFs, ETF NaN, 80% print share, Other-sector warn, pending 2 sessions,
pending 1 session, backup unset, schema 99 / missing, `--force` swallows HARD,
`run()` stops without writing state, `run(force=True)` continues.

CLI fixture `_market` now ships the 10 ETF columns so the wired check does not
false-hard the existing v9 tests.
