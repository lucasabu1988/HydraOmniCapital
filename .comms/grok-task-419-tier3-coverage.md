# TASK-419 — seed, type tier 3, settle() list, coverage floor 81.0

Cherry-picked `10e2675` from `fix/task-390-tier3-and-stable-coverage` onto current
main (freeze is lifted). Annotations only on the money path.

## What landed

1. `test_volume_watchdog.py` draws from `np.random.default_rng(20260906)`, not the
   global stream. `test_task_390_gates.py` pins that, and that no other test module
   reintroduces the unseeded draw.
2. `core.portfolio_engine.settle() -> list[dict]` (it always returned a list; the
   annotation was the lie). Behaviour untouched. `settle.py` the CLI driver was
   already `-> dict` for its own helpers; the defect was in the engine.
3. mypy tier 3: 9 more modules, **25 total, Success: no issues found**.
4. Coverage of this commit, twice, Windows / Python 3.14, `run_all_tests.py --cov`:

   | run | line-rate | missed / stmts |
   |---|---|---|
   | 1 | **82.33%** | 1161 / 6572 |
   | 2 | **82.35%** | 1160 / 6572 |

   One-statement jitter in `data/fetch.py`. Floor moved **80.0 -> 81.0**
   (`test.yml` `--min 81.0`): 1.33 pp under the lower figure, covering the
   historical Linux-vs-Windows gap plus that hundredth. `BASELINE_PCT = 82.33`.

mypy 25 files clean. Gates tests 15 passed. Full suite 93/0.
