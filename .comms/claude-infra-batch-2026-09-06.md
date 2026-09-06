# Infrastructure batch — TASK-359..368 (Claude, 2026-09-06)

Lucas's brief: leave Grok ten tasks that build the infrastructure for HYDRA to become something big,
while Claude rests. This note is the rationale behind the ten entries in `GROKBOARD.md` (Queue), the
order, and the one rule that matters this week.

## What "big" means here

Production is a single 100k book, run by hand on one Windows machine, fed by yfinance with no local
history, verified by nothing but the tests, with one operator. The strategy side is closed until the
2026-Q4 evidence review (spec section 10). What can grow now is everything around the engine:

| Dimension | Today | After the batch |
|---|---|---|
| Data | re-download 2y each run, nothing kept | local SQLite bar store, provider interface, PIT universe/sector snapshots accumulating from day one (361, 362) |
| Reproducibility | prints on a console | run manifest per execution: commit, config hash, data fingerprints, artefacts (359) |
| Book integrity | trusted | ledger replay, schema migrations, restore drill, preflight HARD on mismatch (360) |
| Corporate actions | dividends only | splits pre-registered as H-003, flag off until Lucas decides (363) |
| Operation | Lucas runs `daily.py` | unattended mode with exit codes, alerts (Discord/Telegram/file), Task Scheduler (364) |
| Scale | one book | portfolio registry with per-portfolio state dir and cfg overrides; default byte-identical (365) |
| Extensibility | two hardcoded sleeves | sleeve protocol + registry + N-sleeve engine design doc, engine untouched (366) |
| Insight | P/L in the dashboard | attribution: selection / ETF / interest / dividends / fees / transfers / rounding / write-offs (367) |
| Engineering | one CI job | ruff, coverage report, matrix, nightly data smoke, ARCHITECTURE + RUNBOOK (368) |

Nothing in the batch changes a formula, a threshold, a weight or the engine's accounting. Rule 6 holds.

## The freeze

The first production orders execute Tuesday **2026-09-08** at the close and Lucas then runs `daily.py`
(preflight -> settle -> dividends -> interest -> plan -> sheet -> journal). That run must use the code that
was reviewed on 2026-09-06 04:00. Therefore: **no commits touching `portfolio_v9.py`, `daily.py`,
`preflight.py`, `core/*` or `config.py` values until Claude posts "first settle verified" in Messages.**
Six of the ten tasks are pure additions and can be delivered during the freeze (new modules, CLIs, tests,
docs, workflows); their one-line hooks into the live path are explicitly deferred inside each entry.

Order while frozen: 361 (bar store) -> 366 (sleeve seam + design) -> 368 (hygiene, docs) -> 359 (run
manifest module) -> 360 (state check module + CLI) -> 362 (snapshots CLI).
After the freeze: 364 (unattended) -> 365 (portfolios) -> 367 (attribution) -> 363 (splits; wiring needs
Lucas's OK on H-003).

## Why these ten and not others

- **Bar store before anything else**: every later idea (own PIT panel, faster runs, a second provider such
  as Norgate if Lucas buys it, offline reproducibility) needs prices that live on our disk. SQLite, not
  parquet: stdlib, one file, ACID, and the machine runs Python 3.14 where wheels lag.
- **PIT snapshots now**: TASK-326 showed Russell point-in-time membership is not free. The only way to have
  it in three years is to start writing it down today. Cost: one JSON per week when the list changes.
- **State check**: the engine defects found by TASK-347/350 were plumbing. A ledger replay would have caught
  the stale-counter leak the first week. It also makes the restore drill real instead of theoretical.
- **Splits**: the one corporate action that silently corrupts units. Pre-registered as H-003 because it is
  accounting, like H-001 (dividends), and Lucas decides.
- **Unattended + alerts**: the operator is one person. The system must tell him when not to trade.
- **Portfolio registry + sleeve seam**: the two seams that let capital and strategies multiply without
  forking the code. Both are delivered as additive layers with byte-identical defaults; the N-sleeve
  engine itself is a design document for Claude to review, not code.
- **Attribution**: Lucas's stated objective is return per unit of risk; the evidence review (10.2) needs
  to know which component produced each week's return, not just the total.
- **Hygiene**: ruff/coverage/matrix/nightly smoke are cheap and catch the class of failure (Yahoo shape
  change, Python version drift) that would otherwise show up on a Tuesday at 16:30.

Not included, on purpose: broker API integration (Lucas trades by hand; the read-only CSV path exists and
we do not know the broker yet), any new sleeve or signal (protocol 10.3), a cloud deployment (Lucas: no
more Render), a database for the journal (JSON files + the backup dir are enough at this scale).

## What Claude does when back

Review each task against its entry (parity tests present, default path unchanged, engine untouched, note
written), verify the Tuesday settle and lift the freeze, decide on `USE_BAR_STORE` after comparing a cached
run against a direct run on the same day, ask Lucas about H-003, and pick a coverage floor once 368 reports.
