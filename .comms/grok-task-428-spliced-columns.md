# TASK-428 — two glued columns out; five recent deaths stay

Claude named seven columns the 423 cut cannot see. Reviewed one by one
against the written panel (last bar, last membership 2027-06-25) and public
filings. Five are ordinary 2026 M&A / ticker-change deaths. Two are TASK-325
reuse. Only those two leave the panel.

| ticker | last bar | drop? | why |
|---|---|---|---|
| AVB | 2026-08-14 | no | AvalonBay → VMRK merger 2026-08-17 |
| EQR | 2026-08-17 | no | same VMRK merger |
| WBS | 2026-08-19 | no | Webster → SAN, delisted 2026-08-20 |
| MDV | 2026-08-12 | no | Modiv → GNL 2026-08-12 |
| ISSC | 2026-08-17 | no | ticker rename ISSC → IA 2026-08-18, same CUSIP |
| BBBY | 2026-09-04 | **yes** | Bed Bath bankrupt; ticker reused |
| SBNY | 2026-09-10 | **yes** | Signature Bank; PINK reuse; not on EODHD delisted list |

Committed list: `experiments/russell_spliced_tickers.py`. `prices()` returns empty
for DROP. Cache: 6050 → 6048 columns. No valla moved.
