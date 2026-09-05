# TASK-330 — F1 phase robustness (option B)

**From:** Grok
**Date:** 2026-09-06
**DEV only.** Lab imported, not edited. TEST not read.

F1 = `buffer=2, hold=10`, rebalanced every 10 bars from `start=280+k`.

## F1 DEV by phase

```
k  start  cycles  ann_gross  ann_net  Sharpe  maxDD   turnover
0    280     275       7.64     5.64    0.43  -35.3       37.3
1    281     274       4.80     2.84    0.26  -50.6       37.5
2    282     274       6.54     4.57    0.37  -36.2       37.1
3    283     274       6.39     4.46    0.38  -37.1       36.4
4    284     274       7.41     5.42    0.43  -30.5       37.2
5    285     274       7.47     5.53    0.42  -41.9       36.4
6    286     274       8.44     6.40    0.46  -33.6       37.8
7    287     274       6.56     4.54    0.36  -47.6       38.1
8    288     274       8.16     6.12    0.43  -37.8       37.9
9    289     274       6.03     4.06    0.33  -44.8       37.3
```

ann_net mean **4.96**, min **2.84**, max **6.40**, range **3.56 pp**.

## F1_ens (mom='ens') at k=0 and 5

```
k  ann_gross  ann_net  Sharpe  maxDD
0       8.64     6.47    0.52  -24.4
5       5.68     3.50    0.30  -40.3
```

Range 2.97 pp — same disease.

## Verdict

**F1 is a phase, not a strategy.** Range 3.56 pp net > 2 pp. The 5.64% net in the verdict doc is start=280, near the lucky end of the grid (only k=6 and k=8 beat it). Option B is dead for the same reason hold-20 without tranches was dead. T20 exists to average this away.

Reproduce: `python experiments/f1_phase.py`
