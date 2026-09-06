# TASK-380 — Console encoding (cp1252)

Entry points reconfigure stdout to UTF-8 with `errors="replace"`. Library
print/log strings in `data/universe.py` are ASCII (`[OK]` / `[ERR]`). Frozen
live-path files were not edited (`portfolio_v9.py`, `daily.py`, `preflight.py`
already had the idiom). `core/filters.py` and `data/fetch.py` had no non-ASCII
prints.

## What landed

- `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` after `import sys`
  on every `__main__` script that lacked it (CLIs, labs, journal, senders).
- `run_all_tests.py --strict-console` runs children with
  `PYTHONIOENCODING=cp1252:strict`. CI uses it on 3.12 and 3.13.
- `test_console_encoding.py` greps the idiom in every `__main__` file.
- `send_hydra_summary` `[STRICT]` instead of the green-circle emoji;
  volume watchdog `[WARN]` instead of the warning sign.

## Tests

`python run_all_tests.py --strict-console` → 45 passed, 0 skipped.
