# TASK-356 — evidence review (spec 10.2)

`python evidence_review.py --quarter 2026-Q4` (or `--since YYYY-MM-DD`)
reads `journal/*.json` and writes `.comms/evidence-<period>.md`.

Seven fixed questions, tables only. Three triggers printed and in the report:

1. live cumulative below the backtest cone p5 (95th-percentile adverse path)
2. any preflight HARD
3. reconcile residual > 0.5% of the book

No recommendations beyond "evidence for a hypothesis (spec 10.3)". No
parameter change. Engine not edited.

Tests: synthetic 8-week journal fires all three triggers; quarter filter; CLI write.
