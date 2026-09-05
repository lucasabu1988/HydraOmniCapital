# TASK-332 — paired block bootstrap T20−PROD and F1−PROD

**From:** Grok
**Date:** 2026-09-06
Full sample, already-reported series. Not a new variant. Moving block = 13 weeks, 5000 draws.
Lab imported, not edited.

Aligned lengths: PROD 1084, T20 1084 (5-bar), F1 542 (10-bar). F1 comparison compounds PROD onto F1 dates.

## Point estimates and intervals (annualised net, percentage points)

```
pair      n  d_ann_net  90% CI           95% CI           P(≤ PROD)  d_Sharpe  95% CI Sharpe
T20-PROD 1084    +2.23   [-2.61, +4.24]   [-3.61, +5.22]      0.386    +0.184   [-0.286, +0.636]
F1-PROD   542    +1.74   [-1.96, +1.89]   [-2.51, +2.45]      0.508    +0.129   [-0.362, +0.625]
```

Both 95% intervals for the net-return gap **contain zero**. T20's extra ~2 pp of net is not distinguishable from noise on this panel. F1 is a coin flip against PROD.

## Deflated Sharpe (Bailey & López de Prado 2014)

N = 38 DEV trials, ρ ≈ 0.7, DEV n_obs = 549 weekly bars (~10.9 years).
σ_SR ≈ 1/√years.

- E[max SR] independent: **0.66**
- E[max SR] correlated (N_eff = 12.1): **0.51**

T20 DEV Sharpe **0.58**, full-sample **0.60**. That is at the lucky-pick haircut, not above it. The verdict doc already flagged this; the bootstrap agrees.

## Verdict line

Do not treat T20−PROD as a significant alpha gap. T20's case, if any, is the **drawdown and turnover**, which this test does not speak to.

Reproduce: `python experiments/bootstrap_compare.py`
Tests: `pytest test_bootstrap_compare.py` (identical series → CI contains 0; shifted series → excludes 0).
