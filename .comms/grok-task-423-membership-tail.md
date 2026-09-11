# TASK-423 — cut every column at last membership + 10 business days

Claude's wolf note (`.comms/claude-task-423-the-guard-cries-wolf-2026-09-11.md`)
measured that `identity_problems()` on "still printing after 2026-06-01" is four false
positives (ASGN/ASRT/ATLN/AVB: recent deaths, one company) and misses the real reuse
(SBNY is not even on the delisted list). Detecting reuse is the wrong job.

## What landed

`prices()` cuts **every** column at `last_membership_date + MEMBERSHIP_TAIL_BARS`
(default **10**, declared). A June deletion is sold at the next rebalance, days later;
the tail is that window. A name not in the record is not cut.

`identity_problems()` no longer refuses recent deaths. It only refuses codes with
**no membership date**. After the cut, the glued half is unreadable, so a date-cutoff
guard would only cry wolf.

Flag: `cut_at_membership_tail=True`.

## Measured on the 6547-name record (no network; membership only)

```
symbols                         6547
membership_tail_bars            10
columns the cut applies to      3163   (departed: last membership + tail < 2026-09-11)
current members (cut is no-op)  3384
no membership date              0
member_cells_dropped            0
```

Zero member-cells dropped is measured, not assumed: after last membership the held
record is already False, so the tail sits in non-member days the panel does not read.

Tests: normal death intact, spliced code cut, current member intact; GHOST with no
membership still refuses in strict.

Suite: 95 passed, 0 skipped, ruff clean (after this commit).
