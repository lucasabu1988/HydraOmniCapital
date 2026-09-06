# TASK-360 — State integrity (ledger replay, migrations, restore)

Engine not edited. Live path (`portfolio_v9.load_state`, preflight HARD) waits
for the freeze. New modules only.

## What landed

- `core/state_check.py` — `replay(state)` rebuilds tranche `units`/`cash` from
  `capital_reference` + ledger fills + transfers + dividends + interest (sleeve
  dollars split by cash weights) + write-offs. `check(state) -> [Finding]`:
  replay vs stored within 1e-6, units >= 0, cash >= -1e-6, pending tranche +
  units-or-dollars, ledger dates monotone and <= `last_run_date`, schema_version,
  ticker case (WARN), duplicate dividend keys, stale ⊆ units.
- `core/state_migrations.py` — `MIGRATIONS[1]` fills `interest` / `dividends` /
  `stale` and leaves `schema_version` at 1. Unknown version -> `SchemaError`.
  Idempotent.
- `verify_state.py --state` exit 1 on any ERROR. `--restore <backup.json>`
  prints both checks side by side and refuses without `--yes`; with `--yes`
  keeps the overwritten file as `state/backup/<ts>_replaced.json`.

## Live state (2026-09-04 first run)

```
python verify_state.py
state .../state/portfolio_v9.json:
state check: clean (0 findings)
```

pending **30**, ledger **0**, schema 1, cash 8 × 12500. Replay matches.

## Tests (`test_state_check.py`)

6 passed: empty book; buy/sell/cost/transfer; interest+dividend+write-off;
replay gap + bad pending + unknown schema; migrate fill + refuse v7; CLI
clean / restore-without-yes / restore-with-yes.

## Left for the hook-up

- `portfolio_v9.load_state` applies `migrate`, refuses unknown schema.
- preflight HARD on replay mismatch, WARN on other findings.
- Splits in replay when TASK-363 lands.
