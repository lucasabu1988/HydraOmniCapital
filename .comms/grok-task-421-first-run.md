# TASK-421 — first-run 416 diagnostic without a last-ok sidecar

`degraded_groups` returned [] when there was no prior successful run, so the
20:13 HARD printed no diagnostic — the first live run after the change, and
tonight.

## What landed

`first_run_low_share`: with no last-ok, any group whose print share is below
the preflight threshold (0.90, same as `PRINT_SHARE_WARN`) is named:

    provider refresh degraded: etf print_share 7% (last_bar 2026-09-09)
    — no prior successful run to compare; retry later; this is not
    'the session has no data'

With a prior run, the comparative message is unchanged. A healthy group and
no prior run prints nothing. Gate, drop threshold and `--force` untouched.

The diagnostic still cannot abort a run (`681e9bd` wrappers stay).
