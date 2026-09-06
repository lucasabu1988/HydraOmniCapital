# TASK-359 — Run manifest + structured logging

Live path not wrapped (`portfolio_v9.py`, `daily.py`, `core/journal.py` wait for
the freeze to lift). `runs/` is gitignored.

## What landed

- `utils/runlog.py` — `start_run(name, argv) -> RunContext` creates
  `runs/<YYYYMMDD_HHMMSS>_<name>/` with `manifest.json` and `log.txt`.
  Manifest: git commit + dirty, `ALGO_VERSION`, sha256 of `V9` and `FILTERS`,
  python/pandas/numpy/yfinance versions, hostname, argv, `env_set` (names only:
  `HYDRA_BACKUP_DIR`, `UNIVERSE`), start/end/duration, exit status, exception.
  `ctx.fingerprint(name, frame)`: last bar, shape, sha256 of the last row.
  `ctx.artifact(path)` records written files. FileHandler INFO on a private
  logger (`propagate=False`); console untouched. `prune(..., keep=90)`.
- `runlog_cli.py --last` prints the latest manifest; `--prune` keeps 90
  (`--keep` / `--dir` for tests).
- Copying `runs/` to `HYDRA_BACKUP_DIR` waits for the `portfolio_v9` hook.

## Tests (`test_runlog.py`, no network)

5 passed: manifest keys + env values never written; fingerprint of a 3×2 frame;
artifact + finish + log line; exception text; prune keeps last 3 of 5; CLI
`--last` / `--prune`.

## Left for the hook-up (after "first settle verified")

- Wrap `portfolio_v9.run` and `daily.main`; fingerprint stocks/ETF/IRX after
  `fetch_v9_market`.
- `core/journal.py` one field `manifest_path`.
- Copy `runs/` with the state to `HYDRA_BACKUP_DIR`.
