# TASK-420 — HARD preflight postpones pending fills; it does not reject them

A Yahoo EOD window (2026-09-10 19:36 and 20:13) HARDed on *today's* ETF prints
and `raise_if_hard` ran before settle, so the 30 fills whose exec_date was
already in the frame (2026-09-08) were left unbooked. The operator read
"rejected". They were postponed.

## What landed

`pending_postpone_message` in `portfolio_v9.py`: when preflight is HARD and
there is `pending`, stdout and the SystemExit both say

    POSTPONING N pending order(s) planned YYYY-MM-DD: exec_date would be
    YYYY-MM-DD (already in the frame|NOT in the frame); nothing written

The gate is unchanged. `--force` still the operator's. No partial settle.

Tests: HARD without pending -> no POSTPONING, no state file; HARD with pending
-> the line, state and instruction sheets byte-identical, engine.settles == 0.
