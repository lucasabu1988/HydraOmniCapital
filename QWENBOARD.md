# QWENBOARD — Claude ↔ Qwen

This file is your instructions. Claude (the architect) writes the tasks. You (Qwen) do them
and write a report at the bottom of this file. Read the whole file before you touch anything.

**Your working directory is always:**

```
C:\Users\caslu\HydraOmniCapital\hydra_screener_local
```

This is a real trading system that a person runs with real money every week. That is why the
rules below are strict. Follow them exactly. Doing less than a task asks is fine; doing more
is not.

---

## Rules — read every time

1. **Never run `git`.** No `git add`, no `git commit`, no `git checkout`, no `git stash`.
   Claude commits. If you run git you can destroy work that is not yours.
2. **Only edit the files listed in the task** under `Files:`. Not one file more.
3. **Never touch these, for any reason:** `core/`, `config.py`, `HYDRA_ALGORITHM_SPEC.md`,
   `state/`, `data_cache/`, `history/`, `.github/`, `daily.py`, `portfolio_v9.py`.
4. **Do one task at a time**, in order, starting from the first `[ ]` in the Queue.
5. **Do not reformat, rename, or "improve" anything you were not asked to change.**
   A diff with unrelated changes in it gets thrown away.
6. **Do not create new files** unless the task says to create them, with the exact name.
7. **Always run the `Verify:` commands** at the end of the task. Paste their last lines into
   your report. If you did not run them, the task is not done.
8. **If something fails and two attempts do not fix it: stop.** Write `BLOCKED` in your
   report with the exact error text. A correct "I am blocked" is worth more than a guess.
9. **Never invent a fact.** If you are unsure what a function does, open the file and read it.
   Do not guess at behaviour, file names, or command flags.
10. When a task is finished, change its `[ ]` to `[x]` in the Queue and write your report.

## How to run things

```
cd C:\Users\caslu\HydraOmniCapital\hydra_screener_local
python run_all_tests.py
```

The last line must be `All tests passed!`. It takes about 2.5 minutes. That command is the
final word on whether you broke something.

## How to report

Append to the **Reports** section at the bottom of this file. Never edit someone else's
report, never edit the Queue text of a task, and never delete anything from this file.

Use exactly this shape:

```
### QW-001 — done (or: BLOCKED)
What I changed: <one line per file>
Verify: <the last line of each command you ran>
Notes: <anything Claude should know, or "none">
```

---

## Queue

- [ ] `QW-001` **Remove unused imports and unused local variables from five experiment
  scripts.** These are offline research scripts, not the live path, which is why they are a
  safe place to start. `ruff` already knows exactly what is wrong; your job is to apply it
  carefully, one file at a time, and prove the suite still passes.

  For **each** of the five files listed below, in this order:

  1. Run: `python -m ruff check <file> --isolated --select F401,F841 --line-length 120`
  2. Read what it reports. `F401` = an import nobody uses. `F841` = a variable assigned and
     never read.
  3. Delete the unused import, or the unused assignment. When `F841` is on an
     `except ... as e:` line where `e` is never used, change it to `except ...:` and keep the
     `except` body exactly as it is.
  4. **Do not** delete anything the file still uses. If ruff points at a line and you cannot
     see why it is unused, leave it alone and say so in your report.
  5. Run the ruff command again. It must print `All checks passed!`.

  Files (this is the complete list — do not clean any other file):
  - `experiments/backtest_screener_top5_hold5d.py`
  - `experiments/test_screener_logic.py`
  - `experiments/panel_methodology.py`
  - `experiments/analysis_experiments.py`
  - `experiments/rehearsal.py`

  Verify:
  - `python -m ruff check experiments/backtest_screener_top5_hold5d.py experiments/test_screener_logic.py experiments/panel_methodology.py experiments/analysis_experiments.py experiments/rehearsal.py --isolated --select F401,F841 --line-length 120`
    → must print `All checks passed!`
  - `python run_all_tests.py` → must print `All tests passed!`

- [ ] `QW-002` **Write tests for the two CI gate scripts that have none.**
  `tools/check_coverage.py` and `tools/check_secrets.py` decide whether a build is allowed
  through, and nothing tests them — a gate nobody tests is the exact problem the last audit
  was about. Create **one** new file, `test_gate_tools.py`, in `hydra_screener_local/`.

  Read both scripts first. The functions you are testing are:

  - `tools/check_coverage.py`: `read_line_rate(path)` returns the overall line coverage as a
    percentage (a float); `per_package(path)` returns a list of `(package_name, percentage)`;
    `main(argv)` returns `0` when coverage is at or above `--min` and `1` when it is below.
  - `tools/check_secrets.py`: `scan(root)` returns a list of findings (empty list = clean);
    `env_files(root)` returns tracked `.env`-shaped files.

  Write these tests, using `tmp_path` (the pytest fixture that gives you a temporary
  directory) so nothing you write touches the real repository:

  1. `read_line_rate` on a small `coverage.xml` you write yourself in `tmp_path` returns the
     percentage you put in it. A `coverage.xml` looks like
     `<coverage line-rate="0.8193" ...><packages>...</packages></coverage>` — open the real
     `coverage.xml` in `hydra_screener_local/` to copy its exact shape.
  2. `main` returns `0` when the measured coverage is above the floor.
  3. `main` returns `1` when the measured coverage is below the floor. **A gate that cannot
     fail is not a gate — this is the most important test in the file.**
  4. `scan` returns an empty list for a directory holding one harmless file.
  5. `scan` reports a file that contains a credential-shaped line, for example a line reading
     `AWS_SECRET_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"`.

  Import the two modules like this, at the top of your test file:

  ```python
  import os
  import sys
  sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
  import check_coverage
  import check_secrets
  ```

  Keep each test short and give it a name that says what it proves. If a function does not
  behave the way this task describes, **do not change the function** — write down what it
  actually does in your report and leave the test out.

  Files: `test_gate_tools.py` (new, and the only file you create).

  Verify:
  - `python -m pytest -q test_gate_tools.py` → all tests pass
  - `python run_all_tests.py` → must print `All tests passed!` (the runner finds new
    `test_*.py` files automatically, so your file will be in it)

---

## Messages from Claude

**[2026-09-06] Welcome.** You are helping with the HYDRA screener while Grok is unavailable.
Start with `QW-001`. It is deliberately small: it is how we find out what works between us.
Two things I care about more than speed:

- **Tell me the truth about what you ran.** If a command failed, paste the error. Never write
  that a test passed unless you saw it pass.
- **Stop when you are unsure.** Nobody here is annoyed by a question. Everybody is hurt by a
  confident wrong change to a system that moves money.

I read this file and review everything before it is committed. You never commit.

---

## Reports

<!-- Qwen: append your reports below this line. Newest at the bottom. -->
