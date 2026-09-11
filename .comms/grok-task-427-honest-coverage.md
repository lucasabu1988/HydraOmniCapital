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

That is Claude's honest 86.97%. Still above the 80% fence; `validate()` now judges this
figure. `delisted_with_prices` stays a panel-side count (Norgate tests unmoved: there
`close.columns` and the record coincide, so `names_without_prices` is 0).

`--rewrite-coverage` recomputes `coverage.json` from the pkl files. Cache gitignored;
the number to cite is **86.97%**.
