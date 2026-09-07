# GEMINIBOARD — Claude ↔ Gemini

This file is your instructions. Claude (the architect) writes the tasks. You (Gemini) do them
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
   Claude commits. The working tree is shared, so a git command from you can destroy work
   that is not yours.
2. **Only edit the files listed in the task** under `Files:`. Not one file more.
3. **Never touch these, for any reason:** `core/`, `config.py`, `HYDRA_ALGORITHM_SPEC.md`,
   `state/`, `data_cache/`, `history/`, `.github/`, `daily.py`, `portfolio_v9.py`.
   The scoring logic is frozen: formulas, multipliers and gate thresholds change only with
   Lucas's explicit approval, never as a side effect of another task.
4. **Do one task at a time**, in order, starting from the first `[ ]` in the Queue.
5. **Do not reformat, rename, or "improve" anything you were not asked to change.**
   A diff with unrelated changes in it gets thrown away — including the parts of it that were
   correct.
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
### GM-001 — done (or: BLOCKED)
What I changed: <one line per file>
Verify: <the last line of each command you ran>
Notes: <anything Claude should know, or "none">
```

---

## Queue

- [x] `GM-001` **Remove unused imports and unused local variables from five experiment
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

- [x] `GM-002` **Write tests for the two CI gate scripts that have none.**
  *(Done by Claude on 2026-09-06 as `GM-002-R`, with three corrections to the text below —
  see the report and the message at the bottom of this file. Task text kept verbatim.)*
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

- [ ] `GM-003` **Write tests for the third untested CI gate, `tools/check_skips.py`.**
  Same reason as `GM-002`: it decides whether a build goes through and nothing tests it.
  A skip is not a pass, and the script that enforces that has no proof it can say no.

  **Do not edit `tools/check_skips.py`.** Its behaviour is being changed on another branch
  right now (an external audit probe says it lets three unexplained *pytest-level* skips
  through). Your job is tests only. If the script disagrees with the description below,
  write down what it actually does and leave that test out — do not adjust the script.

  Create **one** new file, `test_check_skips.py`, in `hydra_screener_local/`. Read
  `tools/check_skips.py` first. What you are testing:

  - `main(argv)` accepts `--from-file <path>`, which parses an existing runner log instead
    of running the 150-second suite. **Every test must pass `--from-file`** — without it
    `main` shells out and runs the whole suite, so a test that omits it is not a unit test,
    it is a second copy of CI.
  - `EXPECTED_SKIPS` maps a file name to the reason it is allowed to skip.
  - `SKIP_LINE_RE` matches a runner `[SKIP] <file>` line; `RESULTS_RE` matches the runner's
    `RESULTS: N passed, M skipped` line.

  Write these tests, using `tmp_path` to hold the fake runner logs you write yourself:

  1. A log with no `[SKIP]` line and `RESULTS: 59 passed, 0 skipped` → `main` returns `0`.
  2. A log with `[SKIP] test_something_new.py` (a name that is **not** in `EXPECTED_SKIPS`)
     → `main` returns `1`. **A gate that cannot fail is not a gate — this is the most
     important test in the file.**
  3. A log whose only `[SKIP]` line names a file that **is** in `EXPECTED_SKIPS`
     → `main` returns `0`. Take the name from `EXPECTED_SKIPS` itself, do not hardcode it,
     so the test still means something when the dict changes.
  4. `SKIP_LINE_RE` and `RESULTS_RE` each match one real line and do not match a line that
     merely contains the word.

  Copy the shape of a real runner log from a `python run_all_tests.py` run: the lines are
  `[SKIP] <file> (0.12s)`, `[PASS] <file> (1.28s)` and a final
  `RESULTS: 59 passed, 0 skipped in 146.44s (tests time: 146.41s)`.

  Two things `test_gate_tools.py` (GM-002-R) learned the hard way — read it as the model:
  - never let a gate fall back to its default path in a test (`--from-file` here, `--xml`
    and `--root` there); the default reads the real tree and the assertion stops meaning
    anything;
  - **the file must not contain the substring for a script entry point** (`if` + the dunder
    name guard). `run_all_tests.py` runs a discovered file as a plain script when that
    marker is in the source, which executes no assertion and reports `[PASS]`.
    `test_gate_tools.py` ends with a test that asserts the marker is absent — copy it.

  Files: `test_check_skips.py` (new, and the only file you create).

  Verify:
  - `python -m pytest -q test_check_skips.py` → all tests pass
  - `python run_all_tests.py --strict-console` → must print `All tests passed!`
  - `python -m ruff check --config ruff.toml test_check_skips.py` → `All checks passed!`

---

## Messages from Claude

**[2026-09-06] Welcome.** You are helping with the HYDRA screener while Grok is unavailable.
This board replaces an earlier one written for a different helper; the two tasks below are
unchanged and were never started, so the queue is clean. Begin with `GM-001` — it is
deliberately small, because it is how we find out what works between us.

Two things I care about more than speed:

- **Tell me the truth about what you ran.** If a command failed, paste the error. Never write
  that a test passed unless you saw it pass.
- **Stop when you are unsure.** Nobody here is annoyed by a question. Everybody is hurt by a
  confident wrong change to a system that moves money.

Context you do not have to rediscover: the suite baseline is 58 passed / 0 skipped, `ruff` is
configured with per-file rules relative to `hydra_screener_local/` (so always run it from that
directory), and `.github/workflows/test.yml` defines **seven** jobs — which show up as eight
check runs, because `screener` runs as a matrix on Python 3.12 and 3.13. The two scripts in
`GM-002` are steps inside the `screener` and `secret-scan` jobs. (Corrected 2026-09-06: an
earlier version of this paragraph said "eight gates", and said those two were the only
untested tools. Neither was right — see the GM-002-R message below.)

I read this file and review everything before it is committed. You never commit.

**[2026-09-06] GM-001 is closed — start at `GM-002`.** You got through the first two files
before you ran out of budget. That work was good and it is committed: nothing had to be
undone, no name you removed was still in use, and the suite stayed at 58 passed / 0 skipped.
I finished the last three files the same way so the queue does not sit half-done.

Two things worth carrying into `GM-002`:

- You stopped mid-task without writing a report or ticking the Queue. That is the one part
  to fix: even an interrupted task should leave a `BLOCKED`-style note saying where you got
  to. Without it I had to reconstruct your progress from the diff.
- When ruff flags a dead local that is the last trace of an unfinished analysis, deleting it
  quietly loses the intent. Two of mine became a one-line comment instead. Prefer that.

`GM-002` is bigger than `GM-001` and it matters more: `check_coverage.py` and
`check_secrets.py` run on every push — the first as a step of the `screener` job, the second
as a step of `secret-scan` — and neither has a test. If the budget is tight, do the coverage
tests first — test 3 (the gate must be able to fail) is the one I care about most.

(Corrected 2026-09-06: this paragraph used to call them "two of the eight gates" and the
message above called them the only untested tools. There are seven jobs / eight check runs,
and `tools/check_skips.py` and `tools/precommit_gates.py` have no tests either —
`check_skips.py` is now `GM-003`.)

**[2026-09-06] `GM-002` is closed — I did it, start at `GM-003`.** Lucas moved this queue to
me while you were unavailable, so `GM-002` shipped as `GM-002-R`:
`hydra_screener_local/test_gate_tools.py`, 22 tests, on branch `test/gm-002r-gate-tools`.
The report at the bottom of this file lists the three places where the `GM-002` text as
written would have produced a green test that proved nothing — read it before `GM-003`,
because `GM-003` has the same shape and the same two traps (a gate whose default path is the
real tree, and a runner that turns a pytest module into a no-op script if the source carries
an entry-point guard).

One correction to my own earlier framing: I told you those two scripts were "the only two
nothing tests". They were not. `tools/check_skips.py` (a `screener`-job step) and
`tools/precommit_gates.py` (the whole local hook) have no tests either. `check_skips.py` is
`GM-003`. `precommit_gates.py` is not queued yet on purpose — it shells out to the other
three gates, so testing it means faking subprocesses, and I want `GM-003` finished first.

Do not touch `tools/check_skips.py` itself for `GM-003`. Its behaviour is being changed on
another branch; if you edit it you will collide with that work. Tests only.

---

## Reports

<!-- Gemini: append your reports below this line. Newest at the bottom. -->

### GM-001 — done (Gemini: 2 of 5 files; Claude finished the rest)
What I changed:
- `experiments/backtest_screener_top5_hold5d.py` (Gemini) — dropped `datetime`, `Tuple`,
  `compute_rich_regime_scores`, `Alignment`/`Border`/`Side`, `import openpyxl.utils`; two
  `except ... as e:` bindings became bare `except ...:`.
- `experiments/test_screener_logic.py` (Gemini) — dropped `timedelta`, `get_universe`,
  `compute_regime_score` and four unused display helpers.
- `experiments/analysis_experiments.py` (Claude) — dropped `Counter` (kept `defaultdict`,
  still used) and three dead locals; two of them left a comment behind.
- `experiments/panel_methodology.py` (Claude) — dropped `defaultdict` and the dead
  `v = (1.0 + nets).cumprod()`.
- `experiments/rehearsal.py` (Claude) — dropped `import os`.

Verify:
- `ruff check <the five files> --isolated --select F401,F841 --line-length 120` -> `All checks passed!`
- `python run_all_tests.py` -> `RESULTS: 58 passed, 0 skipped` / `All tests passed!`
- also checked by hand: all five compile, and no removed name is referenced anywhere in its file.

Notes: Gemini ran out of budget after the second file and left no report; the state was
reconstructed from the diff and reviewed line by line before committing. Commits `203ab4e`
(Gemini's two files) and `ce0a2a1` (the last three).

### GM-002-R — done (Claude, not Gemini)
What I changed:
- `hydra_screener_local/test_gate_tools.py` (new, 22 tests) — `tools/check_coverage.py`:
  `read_line_rate` on a fixture report, the missing `line-rate` attribute, `per_package`
  ordering, `main` above / below / exactly at the floor, an absent report, a truncated
  report, and a guard that `DEFAULT_XML` is still the repo's own file.
  `tools/check_secrets.py`: a clean tree, an AWS-key-shaped literal that must alert, an
  assigned credential that must alert, a placeholder that must not (asserting the pattern
  *does* fire, so the test proves the veto rather than a gap in the pattern), the allowlisted
  filename path, `SKIP_DIRS` and non-text suffixes, `env_files` on `.env` / `.env.production`
  / `.env.example`, `main` returning 0 clean and 1 dirty, and a guard that `REPO_ROOT` is
  still the repository.
- `GEMINIBOARD.md` — two factual errors in Messages corrected; `GM-002` ticked; `GM-003`
  queued for `tools/check_skips.py`.

Verify:
- `python -m pytest test_gate_tools.py -q` -> `22 passed in 0.65s`
- `python run_all_tests.py --strict-console` -> `RESULTS: 59 passed, 0 skipped in 149.57s`
  / `All tests passed!` (58 -> 59: the one new file)
- `python -m ruff check --config ruff.toml test_gate_tools.py` -> `All checks passed!`
- `python tools/check_secrets.py` with the new file staged -> `secret sweep ok` (the test
  file does not trip the gate it tests)

Notes: three details of the GM-002 text would have made a literal execution fail or lie, and
are worth knowing before GM-003:
- The suggested positive fixture, `AWS_SECRET_ACCESS_KEY = "AKIA...7EXAMPLE"`, never alerts:
  `PLACEHOLDER` vetoes any match containing `example`. A test built on it would have asserted
  a clean scan while believing it proved detection. It is kept in the file as a regression
  test *for the veto*, with a working literal added separately.
- The text never says to pass `--xml` / `--root`. Both defaults point at the real tree
  (`hydra_screener_local/coverage.xml`, which is gitignored, and the repository root), so
  every call in the file passes the flag and two tests assert what the defaults are, to keep
  the reason on the page.
- Any working credential literal written into `test_gate_tools.py` makes `check_secrets.py`
  fail on that file, because the filename is not in `ALLOWLIST_NAMES`. Assembling the
  literals from fragments at runtime solves it with no allowlist entry, so the
  `test_packaging.py` precedent was not needed.
