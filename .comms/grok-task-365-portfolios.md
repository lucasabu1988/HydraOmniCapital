# TASK-365 — Portfolio registry (done by Claude, 2026-09-06)

Branch `post-freeze-wiring`, commit `a9d8299`. Main untouched until the merge.

## What landed

- `portfolios.toml` (tracked, no secrets): `[default]` = the live book (`state/`, `journal/`, capital
  100000, no overrides — a default override is refused: the live book is `config.V9` by definition), plus
  two **disabled** examples that document the shape: `paper_t20_only` (`mix = {stocks 1.0, etf 0.0}`) and
  `paper_half_size` (capital 50000).
- `core/portfolios.py`: `load_registry()`, `resolve(name, allow_disabled=False) -> Portfolio(name, label,
  enabled, state_dir, journal_dir, capital, cfg)`; `cfg = deep_merge(config.V9, overrides)`; unknown or
  disabled names raise `PortfolioError`. `tomllib` (stdlib).
- `--portfolio <name>` on `portfolio_v9.py` (+ `--allow-disabled`; `--capital` now defaults to the book's
  `capital_reference`), `daily.py` (journal goes to `journal/<name>/` for non-default books), `dashboard_v9.py`,
  `reconcile.py`, `verify_state.py`, `confirm_fills.py`, `analytics_cli.py`. `portfolio_v9.run`,
  `fetch_v9_market` and `build_ranking` take `cfg`; every engine call passes it instead of the module
  global `V9`.
- Off-disk backup of a named book lands in `<HYDRA_BACKUP_DIR>/state_v9/<name>/<date>/`; default keeps
  `state_v9/<date>/`.

## Parity

`test_portfolios.py::test_default_portfolio_is_byte_identical_to_no_flag`: the instruction sheet and the
state written with `cfg = resolve("default").cfg` equal the old CLI's output byte for byte. The whole
existing suite (FakeEngine paths, preflight, dividends, splits) runs unchanged with the new signature.

## Tests

8 in `test_portfolios.py`: registry parses, default == V9 and `state/`, deep-merge only on the named
book (global `V9` not mutated), disabled/unknown refused, default may not carry overrides, missing
registry yields the implicit default, named book uses its own dir/cfg/capital (live dir untouched),
backup sub-folder.

## Not done on purpose

No second book is enabled. Turning one on is a decision (capital, broker account), not code.
