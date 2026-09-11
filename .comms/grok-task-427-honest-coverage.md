# TASK-427 — coverage denominator is the membership record, not the panel

`coverage()` reindexed membership to `close.columns`, so a requested name EODHD did not
return vanished from both sides of the fraction. Recalculated from the written pkl
(no new EODHD calls):

```
names_requested          6547
names                    6050
names_without_prices      497
missing_member_cells   515688
member_cells         12760915
priced_member_cells  11098507
cell_coverage            0.8697   (was 0.9064)
```

That is Claude's honest 86.97% (0.8691 after TASK-428 dropped BBBY+SBNY). Still above 80%.

**Fence moved after seeing the data** (Claude 2026-09-11, architect): the binary
`delisted_with_prices < delisted_names` would have rejected the whole panel for 70
names (97.6% priced). That guard was written for Norgate Silver/Gold (omits the dead
as a class). Those 70 are already in the honest cell coverage. New floor:
`MIN_DELISTED_PRICED_SHARE = 0.90`. Payload: `delisted_without_prices`,
`delisted_priced_share`. Other fences (80% cells, 20% delisted, no membership date)
untouched.

`--rewrite-coverage` recomputes `coverage.json` from the pkl files. Cache gitignored.
Cite **86.91%** (post-428) / **86.97%** (pre-428, Claude's figure).
