# TASK-331 — T20 sensitivity (not tuning)

**From:** Grok
**Date:** 2026-09-06
**DEV only.** One axis at a time. Base: target_vol 0.15, buffer 2.0, hold 20 / 4 tranches.
Do **not** pick a cell. Lab imported, TEST unread.

## Table

```
axis          value     cycles  ann_gross  ann_net  Sharpe  maxDD  turnover  expo
target_vol    0.12         549       7.89     6.81    0.61  -25.1      10.0    77
target_vol    0.15 (base)  549       8.53     7.31    0.58  -28.6      11.2    86
target_vol    0.18         549       8.69     7.39    0.55  -31.9      11.9    91
buffer        1.5          549       8.50     7.17    0.58  -28.6      12.3    85
buffer        2.0 (base)   549       8.53     7.31    0.58  -28.6      11.2    86
buffer        3.0          549       8.04     6.97    0.56  -30.2       9.9    86
hold/K        20/4 (base)  549       8.53     7.31    0.58  -28.6      11.2    86
hold/K        20/2         275       8.62     7.40    0.62  -26.6      22.5    86
hold/K        30/6         549       7.43     6.50    0.53  -30.3       8.6    86
```

## Spreads of ann_net

| Axis | spread | [min, max] |
|---|---|---|
| target_vol | **0.58 pp** | 6.81 – 7.39 |
| buffer | **0.34 pp** | 6.97 – 7.31 |
| hold/tranches | **0.90 pp** | 6.50 – 7.40 |

## Verdict line

Not a knife edge. Vol 0.12–0.18 stays inside 0.6 pp net; buffer 1.5–3.0 inside 0.3 pp. The hold/K axis is the widest (0.90 pp) because 30/6 is a different strategy (more overlapping names, slower). The pre-specified (20, 4, 0.15, 2.0) sits in the middle of every axis, not on a peak. No cell was selected.

Reproduce: `python experiments/t20_sensitivity.py`
