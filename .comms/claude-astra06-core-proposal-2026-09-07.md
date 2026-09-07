# ASTRA-06 follow-up — the `core/regime.py` breadth patch, as a proposal (H-007)

**Claude, 2026-09-07. Branch `fix/astra-06-followup` (base `fix/astra-06-pit-breadth` + `origin/main`).
Nothing in `core/` is modified by that branch. This note asks Lucas for one decision.**

An adversarial review of `fix/astra-06-pit-breadth` returned NEEDS_WORK on three counts. This note
answers two of them; the third (a defect-pinning test that read as coverage) was answered in code.

| Objection | Answer |
|---|---|
| The fix is in the LAB only; `core/regime.py`, where Astra's probe points, is untouched | It stays untouched — rule 6. Here is the patch, its measured effect, and a kill criterion. Lucas decides. |
| Astra's assertion survives only as a test that PINS the wrong number (0.773 -> 0.723) | Replaced by `xfail(strict=True)` against the DESIRED behaviour, plus `@pytest.mark.defect` and `DEFECT` in the name. It goes RED the day the fix lands. |
| The branch reached into the production tree for its headline numbers | Every input is listed below with its size, mtime and SHA-256, and the measurement is a committed script. See "Provenance" and "The 5.38 -> 4.87 / 7.55 -> 7.28 headline". |

---

## 1. The defect, in three lines

`core.regime.compute_rich_regime_scores` computes breadth as three column-wise means over the last
row of the frame it is handed. `NaN > sma` is `False`, and that `False` sits in the denominator, so
a column with **no observation on the date** is counted as a name that is not participating.
Astra's probe: appending 50 all-NaN columns moves `overall` 0.773 -> 0.723 (breadth 1.0 -> 0.5).
Breadth is 10% of the regime; the regime sets aggression, which sets `dynamic_count`, which sets
how many names are bought.

ASTRA-06 fixed the **lab**, which was handing core the union of every S&P member 2004-2026. It did
not fix core, because `core/regime.py`'s treatment of missing data is GROKBOARD rule 6.

## 2. The patch (NOT applied)

`hydra_screener_local/core/regime.py`, lines 72-83. Two sizes; they are separate decisions.

### Variant A — minimal: drop columns with no observation on the date

```diff
     # 5. Breadth Proxy (10% weight, optional) - improved with positive movers + SMA participation
     breadth_score = 0.5
     if prices is not None and len(prices.columns) > 30:
         try:
-            ret_1d = prices.pct_change().iloc[-1]
-            pct_positive = (ret_1d > 0).mean()
-            above_sma50 = (prices.iloc[-1] > prices.rolling(50).mean().iloc[-1]).mean()
-            above_sma200 = (prices.iloc[-1] > prices.rolling(200).mean().iloc[-1]).mean()
-            # Blend: participation + momentum breadth
-            breadth_score = 0.3 * pct_positive + 0.3 * above_sma50 + 0.4 * above_sma200
-            breadth_score = max(0.0, min(1.0, breadth_score))
+            # ASTRA-06: a column with no price on this date is not a market participant.
+            # `NaN > sma` is False and that False used to sit in the denominator, so an
+            # unobserved name was counted as "not participating" and pushed breadth DOWN.
+            obs = prices.loc[:, prices.iloc[-1].notna()]
+            if len(obs.columns) > 30:
+                ret_1d = obs.pct_change().iloc[-1]
+                pct_positive = (ret_1d > 0).mean()
+                above_sma50 = (obs.iloc[-1] > obs.rolling(50).mean().iloc[-1]).mean()
+                above_sma200 = (obs.iloc[-1] > obs.rolling(200).mean().iloc[-1]).mean()
+                # Blend: participation + momentum breadth
+                breadth_score = 0.3 * pct_positive + 0.3 * above_sma50 + 0.4 * above_sma200
+                breadth_score = max(0.0, min(1.0, breadth_score))
         except:
             breadth_score = 0.5
```

### Variant B — complete: a column enters only when every comparison is DEFINED

```diff
     # 5. Breadth Proxy (10% weight, optional) - improved with positive movers + SMA participation
     breadth_score = 0.5
     if prices is not None and len(prices.columns) > 30:
         try:
-            ret_1d = prices.pct_change().iloc[-1]
-            pct_positive = (ret_1d > 0).mean()
-            above_sma50 = (prices.iloc[-1] > prices.rolling(50).mean().iloc[-1]).mean()
-            above_sma200 = (prices.iloc[-1] > prices.rolling(200).mean().iloc[-1]).mean()
-            # Blend: participation + momentum breadth
-            breadth_score = 0.3 * pct_positive + 0.3 * above_sma50 + 0.4 * above_sma200
-            breadth_score = max(0.0, min(1.0, breadth_score))
+            # ASTRA-06: a column enters the breadth statistics only when all three comparisons
+            # are DEFINED for it on this date -- it has a close, a return, a 50-bar SMA and a
+            # 200-bar SMA. `NaN > sma` is False, and that False used to sit in the denominator:
+            # an unobserved name, and a name too young to have a 200-day average, were both
+            # counted as "not participating" and pushed breadth DOWN. The count that matters is
+            # the number of columns that participate, not the width of the frame.
+            last = prices.iloc[-1]
+            ret_1d = prices.pct_change().iloc[-1]
+            sma50 = prices.rolling(50).mean().iloc[-1]
+            sma200 = prices.rolling(200).mean().iloc[-1]
+            ok = last.notna() & ret_1d.notna() & sma50.notna() & sma200.notna()
+            if int(ok.sum()) > 30:
+                pct_positive = (ret_1d[ok] > 0).mean()
+                above_sma50 = (last[ok] > sma50[ok]).mean()
+                above_sma200 = (last[ok] > sma200[ok]).mean()
+                # Blend: participation + momentum breadth
+                breadth_score = 0.3 * pct_positive + 0.3 * above_sma50 + 0.4 * above_sma200
+                breadth_score = max(0.0, min(1.0, breadth_score))
         except:
             breadth_score = 0.5
```

Both keep every new statement INSIDE the existing `try` and leave the outer
`len(prices.columns) > 30` guard alone, so no failure that is swallowed today becomes a crash: a
frame with fewer than 31 participating columns falls through to `breadth_score = 0.5`, which is the
same "breadth unknown" value core already uses. The bare `except:` is left as it is -- fixing it is
a separate change with its own reasons.

Deliberately **not** in either variant: `prices.pct_change()` keeps the padded default. The house
rule is `fill_method=None`, and this line breaks it — but changing it is a second behaviour change
with its own number, and bundling two into one approval is how a scoring change slips through.
Raised separately; not here.

## 3. How the effect was measured without patching core

`experiments/astra06_core_proposal.py` (committed on this branch). Every breadth statistic is a
column-wise mean over the last row of a **per-column** rolling quantity, so restricting the frame
to a subset of columns before the call returns exactly what the patched function would return on
the full frame:

    compute_rich_regime_scores(spy, prices.loc[:, defined]) == patched(spy, prices)

The script asserts that identity (`--self-check`, run on every invocation) and then measures with
the real, unmodified core function — so the numbers below are the proposed code's numbers, not a
re-implementation's. For the paired backtest it wraps the lab's `meta_for` the same way and
`validate_replica` asserts that, with the mask switched off, the wrapper reproduces the lab's own
`meta_for` bit for bit on six sample dates.

Four states are compared per date:

| | lab masks the frame (ASTRA-06) | core patched (H-007) |
|---|---|---|
| **A** | yes | no  — today's branch |
| **B** | yes | yes — what approval would give |
| **C** | no  | no  — pre-ASTRA-06 |
| **D** | no  | yes — the core patch alone |

## 4. Measured, OOS PIT S&P panel, 1084 five-bar dates 2005-02-11 .. 2026-08-24

Real membership, but ~53% price coverage in 2005: **absolute levels carry that caveat.**
Console output reproduced verbatim; per-date rows in `.comms/astra06-core-proposal-2026-09-07.csv`.

```
=== ASTRA-06 core proposal, config PROD, 1084 dates (2005-02-11 .. 2026-08-24) ===
panel 1209 columns; PIT eligible universe min/median/max 246/373/500
columns the patch would DROP from the breadth denominator: on the PIT frame min/median/max 0/1/6
  (of 373 median); on the whole panel 474/574/716
breadth sub-score mean: A 0.5861  B 0.5871  C 0.3029  D 0.5839

--- A -> B  the marginal effect of the core patch ON TOP of the lab fix (what H-007 asks for) ---
regime differs   122/1084 dates (11.3%)  mean +0.0001  mean|d| 0.0001  max|d| 0.0010  higher/lower 121/1
dynamic count    2 dates differ  mean 17.16 -> 17.16  delta {0: 1082, 3: 2}
gate flips       0 dates (threshold 0.2975)
order list differs 2 dates (0.2%)  mean in/out on a changed date 3.00/0.00
aggression differs 2 dates  mean 1.0410 -> 1.0412

--- C -> D  the core patch ALONE, on the unmasked panel (if the lab fix were reverted) ---
regime differs   1083/1084 dates (99.9%)  mean +0.0281  mean|d| 0.0281  max|d| 0.0480  higher/lower 1083/0
dynamic count    161 dates differ  mean 16.68 -> 17.17  delta {0: 923, 1: 8, 2: 22, 3: 55, 4: 76}
gate flips       14 dates (threshold 0.2975)
```

**Read this way:**

- **On top of ASTRA-06 the patch is nearly a no-op.** The regime moves on 122 of 1084 dates, by a
  mean of +0.0001 and never by more than 0.0010. `dynamic_count` moves on **2 dates** (+3 both
  times), the order list changes on those same 2 dates (0.2%, 3 names in / 0 out), and the regime
  gate never flips. That is because `eligible_at` already requires `px.notna()` at t, so Variant A
  drops **nothing** from the lab's frame by construction; the 0-6 columns Variant B drops are the
  names whose 50d or 200d average is undefined inside the 300-bar window core is handed -- too
  short a history, or a gap in it (`rolling(200).mean()` needs 200 consecutive prints).
- **The core patch alone would have fixed almost the same thing.** C -> D recovers breadth 0.3029
  -> 0.5839, against 0.5861 for the lab fix, and the same +0.028 mean regime shift. The lab fix and
  the core patch are two routes to one defect; ASTRA-06 took the route that needed no approval.
- Every regime difference is in the same direction (higher, 121/1 and 1083/0): counting undefined
  columns always understated participation.

### Paired executable backtest — the deciding metric

Same panel, same 1084 cycles, executable accounting, 10 bp/side. `current` = this branch;
`H-007` = the proposal, produced by wrapping the lab's `meta_for` with the masked frame (identity
of section 3, and `validate_replica` passed on six dates before the run).

```
=== paired executable backtest, T20 (current core vs H-007) ===
          config  cycles  hold  ann_gross  ann_net  sharpe_net  maxdd_net  turnover  exposure  avg_n  distinct
T20 DEV  current     549     5       8.16     6.97        0.56      -31.5      11.0      85.0   16.7      30.6
  T20 DEV  H-007     549     5       8.20     7.00        0.56      -31.5      11.0      85.0   16.7      30.6
T20 TEST current     535     5       8.89     7.60        0.59      -26.9      11.8      86.0   17.5      33.6
  T20 TEST H-007     535     5       8.88     7.60        0.59      -26.9      11.8      86.0   17.5      33.6
T20 ALL  current    1084     5       8.52     7.28        0.58      -31.5      11.4      86.0   17.1      32.1
  T20 ALL  H-007    1084     5       8.53     7.30        0.58      -31.5      11.4      86.0   17.1      32.1
paired net difference per cycle: mean +0.000003  cycles differing 744/1084

=== paired executable backtest, PROD (current core vs H-007) ===
           config  cycles  hold  ann_gross  ann_net  sharpe_net  maxdd_net  turnover  exposure  avg_n  distinct
PROD DEV  current     549     5       7.30     3.19        0.28      -41.6      38.8      93.0   16.3      16.3
  PROD DEV  H-007     549     5       7.32     3.20        0.28      -41.6      38.8      93.0   16.3      16.3
PROD TEST current     535     5      11.00     6.63        0.50      -26.5      39.9      92.0   17.0      17.0
  PROD TEST H-007     535     5      11.00     6.63        0.50      -26.5      39.9      92.0   17.0      17.0
PROD ALL  current    1084     5       9.11     4.87        0.38      -41.6      39.4      92.0   16.7      16.7
  PROD ALL  H-007    1084     5       9.12     4.88        0.38      -41.6      39.4      92.0   16.7      16.7
paired net difference per cycle: mean +0.000002  cycles differing 545/1084
```

- **ann_net: T20 7.28 -> 7.30 (ALL), 6.97 -> 7.00 (DEV), 7.60 -> 7.60 (TEST). PROD 4.87 -> 4.88,
  3.19 -> 3.20, 6.63 -> 6.63.** Sharpe, maxDD, turnover, exposure, avg_n and distinct do not move
  at all. The kill criterion asks for |delta| < 0.25 pp with the same sign on DEV and TEST: the
  measured delta is +0.02/+0.03 pp, positive or flat in both eras. **H-007 passes its own test.**
- The paired per-cycle difference is +0.000003 (T20) and +0.000002 (PROD) — three parts per
  million of a cycle's return.
- "cycles differing 744/1084" is path dependence, not 744 independent changes: `dynamic_count`
  differs on 2 dates, but a single different selection changes `held`, and with `buffer=2.0` the
  keep-zone carries that difference forward. The cumulative effect of the whole divergence is the
  +0.02 pp above.

## 5. The live path: what is measured and what is not

`screener.py` -> `core.signals.generate_daily_candidates` -> `compute_rich_regime_scores(spy,
prices)` is the LIVE call (`core/signals.py:195`; a second one at `screener.py:162` for the
secondary IWM regime, observability only). `prices` there is the post-filter frame.

- **Variant A cannot change the live number today.** `apply_practical_filters` compares
  `prices.iloc[-1] >= FILTERS["min_price"]` (5.0), which is `False` for NaN, so a column with no
  observation on the run date is already gone before scoring. Asserted, not argued:
  `test_pit_breadth.py::test_DEFECT_is_currently_unreachable_from_the_live_filter_chain`. If that
  test ever fails, the live regime IS eating unobserved columns and this stops being cosmetic.
> **MEASURED 2026-09-07, after Lucas approved (rule 6). The hole below is filled.**
> Read `data_cache/bars.sqlite` read-only (`mode=ro&immutable=1`, so no `-shm` file is created —
> the reason the first pass declined to open it). On a live-shaped frame, the last 200 sessions of
> a 2-year window over the store's 3011 tickers:
> - the patch drops **123 of 3011 columns (4.1%)** from the breadth denominator — names with a gap
>   or with fewer than 200 consecutive prints, so no defined SMA200. None is absent entirely; all
>   123 do print, which is exactly why the minimal variant would not have caught them;
> - breadth rises **+0.0110 / +0.0140 / +0.0150 / +0.0180 / +0.0200** on 2026-09-04, 08-28, 08-21,
>   08-07 and 07-10, and the regime with it by **+0.001 / +0.001 / +0.002 / +0.002 / +0.003**.
>   Those numbers come from calling the REAL function on both sides — the pre-patch module loaded
>   out of git as `regime_prepatch` and the patched one imported normally, on one identical panel.
>   A first pass used a re-implementation and reported +0.0112..+0.0205 for breadth; the real code
>   gives +0.0110..+0.0200, and the regime range looks quantised because `regime_score` is rounded
>   to three decimals. Measuring a claim with your own re-implementation of the thing you are
>   claiming about is how you end up off by 0.0002 and not know it;
> - the live effect is therefore **one to two orders of magnitude larger than the OOS panel's
>   +0.0001**, because that panel is S&P PIT (0-6 droppable columns) while production is
>   Russell-heavy and full of young names. Do not quote the 1084-date table as the live effect.
>
> What that can move: `dynamic_count = clamp(round(14 * aggression * compass), 6, 28)` changes only
> when a rounding boundary falls inside that shift, and the regime gate (0.2975) flips only on a
> date sitting within ~0.002 of it. Both are possible; neither is common.

- **Variant B does change the live number, and by how much is UNMEASURED.** The live frame is a 2y
  window over a ~3000-name Russell-heavy universe, and any name with fewer than 200 bars in it has
  an undefined SMA200 — those names are in the denominator today and would leave it. To measure it
  I would need the production price frame, which lives in `data_cache/bars.sqlite`; that database
  is in WAL mode and a reader touches its `-shm` file, so I did not open it. **Do not read the
  1084-date table above as the live effect of Variant B.** It is the S&P PIT analogue.

## 6. Provenance — every production file this measurement read (read-only)

No production CLI was run, nothing under `C:\Users\caslu\HydraOmniCapital\hydra_screener_local\`
was written, and `HYDRA_BACKUP_DIR` was never pointed at anything real (`conftest.py` +
`run_all_tests.py` redirect it for the suite; the measurement scripts write no state at all).

| file | bytes | mtime | SHA-256 |
|---|---|---|---|
| `experiments/_sweep_cache_oos/close.pkl` | 55232899 | 2026-09-05 20:26:12 | `c7c8ecfa7a748dadfb13160edaa54d76796acd3d96ac7a889f4902e30e0cf4da` |
| `experiments/_sweep_cache_oos/volume.pkl` | 55242671 | 2026-09-05 20:26:12 | `ebbba0777e0f734d2361eb9e0b4850c788491ce593ff200e0e531a0ee8071eee` |
| `experiments/_sweep_cache_oos/spy.pkl` | 92280 | 2026-09-05 19:14:22 | `b96adf2f9605dfb6575b853290ad3459853cd47a675a049a64c874143baa4f47` |
| `data_cache/sp500_pit.json` | 12161538 | 2026-09-05 20:25:26 | `12828fa20aef80dda6512683f2ef153a323c9097910030a0d0e15bbbf181e59b` |
| `data_cache/pit/sectors_20260905.json` | 86268 | 2026-09-06 00:08 | `400e4f88ee62e07bfcac83897b62d2a0af9161048bb891065bb805ce070d1d32` |
| `data_cache/pit/universe_sp500_20260905.json` | 6270 | 2026-09-06 00:08 | `f5a34b34aafbc29dfb50758f49e83fb0959afff4913ca052e616398729c31bbd` |
| `experiments/_sweep_cache/close.pkl` (in-sample, parity check only) | 6769805 | 2026-09-05 11:47 | `476f07fe5a8401e11f3a76bf383cfeae98ab2ede2a3e0534eb7d1084ae18fe87` |
| `experiments/_sweep_cache/volume.pkl` | 6773927 | 2026-09-05 11:47 | `5b8dc508b19f87050ef5d8abaa86f650598c774cff3ee4db1c5dae6bbdf54784` |
| `experiments/_sweep_cache/spy.pkl` | 27839 | 2026-09-05 11:47 | `7e5e1673301372b8bb2d1451d77d7d0e7c166581e43c27076cae41e2498477d8` |

Panel as loaded: `(5705, 1209)`, 2004-01-02 .. 2026-09-04. PIT payload
`updated=2026-09-05T15:25:25.702755 cache_version=2`. Sector map: pinned PIT snapshot `20260905`,
`mapped=669 fallback=540`. `experiments/_sweep_cache_oos/irx.pkl` was NOT read (it does not exist
in a worktree) — it only matters for `cash_yield=True`, which neither PROD nor T20 sets.

Exact commands (`PROD_TREE=C:\Users\caslu\HydraOmniCapital\hydra_screener_local`):

```
python experiments/astra06_core_proposal.py --self-check
python experiments/astra06_core_proposal.py \
    --cache-dir  $PROD_TREE/experiments/_sweep_cache_oos \
    --payload    $PROD_TREE/data_cache/sp500_pit.json \
    --pit-dir    $PROD_TREE/data_cache/pit \
    --csv .comms/astra06-core-proposal-2026-09-07.csv
python experiments/astra06_core_proposal.py --headline T20 PROD --cache-dir ... --payload ... --pit-dir ...
```

`--cache-dir / --payload / --pit-dir` were added to `experiments/redesign_lab.py`'s CLI on this
branch for the same reason: `load_panel` already accepted them, but the CLI did not, so a headline
could only be re-derived inside the operator's own tree. That is precisely how "5.38 -> 4.87"
became unreproducible for a reviewer.

## 7. The 5.38 -> 4.87 and 7.55 -> 7.28 headline

Those come from `fix/astra-06-pit-breadth`'s commit message (`1428acc`): PROD and T20 annualised
NET return on the OOS PIT panel, before vs after the lab masking, executable accounting. The
reviewer's complaint was not that they are wrong, but that they were unreproducible — they came out
of the operator's tree with no record of which files went in.

**The POST-fix side is now re-derived, independently, on this branch, and it matches to the last
digit** (section 4's `current` rows, from the inputs and hashes in section 6):

| reported in `1428acc` | re-derived here |
|---|---|
| T20 ALL 7.28 | **7.28** |
| T20 DEV 6.97 | **6.97** |
| T20 TEST 7.60 | **7.60** |
| PROD ALL 4.87, maxdd -41.6 | **4.87, -41.6** |
| PROD DEV 3.19 | **3.19** |
| PROD TEST 6.63 | **6.63** |

**The PRE-fix side (5.38, 7.55, DEV 3.39/7.15, TEST 7.46/7.96, maxdd -37.4) I did NOT re-derive**
and do not restate as measured fact here. Reproducing it needs the parent commit and the same
inputs:

```
git checkout 1c21bc4   # the commit before the ASTRA-06 lab fix
python experiments/redesign_lab.py --full T20 PROD     --cache-dir  $PROD_TREE/experiments/_sweep_cache_oos     --payload    $PROD_TREE/data_cache/sp500_pit.json     --pit-dir    $PROD_TREE/data_cache/pit
```

(that command only works because this branch added those three flags; on `1c21bc4` the CLI has no
way to point at a panel, which is exactly why the number could not be checked.)

What IS settled without that run is the direction and the mechanism: section 4's C -> D block shows
the pre-fix regime was lower by a mean of 0.028 with `dynamic_count` 16.68 vs 17.17 on 161 of 1084
dates, so the look-ahead breadth was moving the lab's positions materially — far more than the
0.02 pp that H-007 moves on top of the fix. Every T20/PROD OOS figure written in `.comms/` before
2026-09-06 predates the fix and should be re-read with that in mind.

## 8. The decision, and the kill criterion (registered as H-007)

**What I am asking for:** approval of **Variant A** (provably live-neutral, removes the latent
risk, makes the lab mask belt-and-braces) and a decision on **Variant B** (correct, but it moves
the live regime by an amount nobody has measured).

Kill criterion, from the register — **written before the backtest was run, and it passed**:

> REJECTED if T20 OOS `ann_net` (executable, paired) drops by more than 0.25 pp, or if DEV and TEST
> move in OPPOSITE directions — then the "fix" is a return lever in disguise: leave core as it is
> and document the defect instead of correcting it silently. Also killed, as an escalation rather
> than a decision, if `test_DEFECT_is_currently_unreachable_from_the_live_filter_chain` ever fails.

Measured: T20 `ann_net` **+0.02 pp** ALL (+0.03 DEV, 0.00 TEST), PROD **+0.01 pp** ALL (+0.01 DEV,
0.00 TEST); no era moves the wrong way; Sharpe and maxDD unchanged. So this is not a return lever —
which is the point. A correctness fix that moved the headline by half a point would have been the
suspicious outcome.

One thing the numbers do NOT settle: they are Variant B measured **inside the lab**, where the
ASTRA-06 mask already removes the worst of it. Variant B's effect on the LIVE regime is still
unmeasured (section 5). Variant A has no live effect at all, by the filter-chain proof.

If approved, the change lands with: the patch above, `HYDRA_ALGORITHM_SPEC.md` section 4.3 amended
to say which columns enter breadth, `test_DEFECT_core_regime_counts_unobserved_columns_in_breadth`
losing its `xfail` (it turns red on its own the moment the patch lands — that is the design), a
re-measured T20/PROD headline, and the ASTRA-06 lab mask left in place (it is still the right
thing: the lab must not hand core non-members even when core defends itself).

## 9. What this note does NOT do

- It does not modify `core/regime.py`, `core/signals.py`, `core/meta_layer.py`, `config.py` or
  `HYDRA_ALGORITHM_SPEC.md`.
- It does not measure Variant B's effect on the live regime (section 5).
- It does not re-derive the pre-fix headline (section 7).
- It says nothing about whether the strategy is any good. The panel is S&P-only with ~53% price
  coverage in 2005, and the 2026-09-08 settle has not been verified: the live path stays frozen.
