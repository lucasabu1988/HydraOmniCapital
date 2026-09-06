# TASK-344 — sector cache cold start

The first real v9 run hit the 120s budget after 277/2027 names; 1750 fell to
"Other" (exempt from the cap) and the stock tranche clustered in biotech.

## Delivered

- `data/sectors.py`: save every **50** successful lookups (`SAVE_EVERY`), not only at
  the end. `other_share_in_selection_pool` / `sector_degraded_message` over the top
  `2 * recommended_count` names.
- `config.py`: `SECTOR_UNKNOWN_MAX_SHARE = 0.30` (selection quality, not scoring).
- `warm_sectors.py`: no time budget, incremental save, progress print.
- `screener.py` and `portfolio_v9.py`: DEGRADED warning if the share exceeds the
  knob. The instruction sheet header gets the same text. CLI still exits 0.
- `test_warm_sectors.py`: incremental save, threshold message, sheet header.

Run `python warm_sectors.py` once (overnight-ish from cold) before the next v9 plan.
