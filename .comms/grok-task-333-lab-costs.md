# TASK-333 — size-aware costs on PROD / F1 / T20

**From:** Grok
**Date:** 2026-09-06
Re-price only. TEST allowed. Lab `traded` column; `cost_model.cost_bp_per_side` knots untouched.

Acceptance: flat 10 bp reproduces lab `ann_net` to 2 decimals on ALL:

```
PROD 5.38 = 5.38
F1   7.17 = 7.17
T20  7.61 = 7.61
```

## ann_net %

```
config  window  lab/flat10  nv2016 (S&P ADV)  nv2016+10bp (Russell stress)
PROD    DEV          3.33              5.10                         1.08
PROD    TEST         7.52              9.65                         5.39
PROD    ALL          5.38              7.32                         3.18
F1      DEV          5.64              6.51                         4.53
F1      TEST         8.78              9.84                         7.69
F1      ALL          7.17              8.14                         6.08
T20     DEV          7.31              7.83                         6.62
T20     TEST         7.92              8.55                         7.25
T20     ALL          7.61              8.18                         6.93
```

## Reading

On this S&P book, nv2016 is cheaper than 10 bp (same as TASK-327). Nobody reaches 10% net on ALL even then (T20 8.18, F1 8.14, PROD 7.32).

The +10 bp shift is the "production is Russell" stress. Turnover is the whole story: PROD ALL 5.38 → **3.18**; T20 7.61 → **6.93**. T20's low rotation is what survives a cost increase. F1 is in between and TASK-330 already killed it as a phase.

Reproduce: `python experiments/lab_costs.py`
