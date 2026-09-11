# TASK-429 — the warning lives in coverage.json

`coverage.json` now carries, as fields not prose:

```
membership_source     russell_free_public_record
membership_first      2010-06-28
honest_window         2010-2026
ghost_names           547
ghost_member_cells    196856
spliced_dropped       ["BBBY", "SBNY"]
spliced_dropped_n     2
spliced_kept          ["AVB", "EQR", "ISSC", "MDV", "WBS"]
```

`ghost_names` 547 matches Claude's count. `ghost_member_cells` is measured on
the price calendar (close index); Claude's 397,925 used the membership calendar.
The JSON is what a reader of `_sweep_cache_russell/` in six months will open.
