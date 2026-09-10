# Hypothesis register — HYDRA evolution protocol (spec section 10.3)

Write the hypothesis BEFORE testing it. One entry per idea; rejected ideas stay with their numbers.
Status: PROPOSED -> TESTED (numbers) -> ACCEPTED (version) | REJECTED | WITHDRAWN.

| id | date | proposer | statement | decides on | status |
|---|---|---|---|---|---|
| H-001 | 2026-09-06 | Claude | Dividends credited to the tranche holding the units on ex-date (accounting parity with total-return backtests) | book vs broker residual | ACCEPTED by Lucas 2026-09-06 (accounting, not scoring): TASK-349, `a38c732`; spec 9.3 |
| H-002 | 2026-09-06 | Claude | The 1/8-per-week pair reset vs a full weekly 50/50 reset: measure the return/Sharpe difference on the OOS panel with the production engine | paired ann_net / Sharpe, OOS | **TESTED 2026-09-08, closed as INDISTINGUISHABLE** (TASK-409, `experiments/reset_ab.py`). Full weekly 50/50 reset 6.97 % / Sharpe 0.567 against the pair reset 7.10 % / 0.569, paired on the same weeks with a single block-index matrix: **d_ann -0.13 pp, 90 % [-0.82, +0.55]; d_sharpe -0.003, [-0.075, +0.069]**; p(full <= pair) 0.625. Both intervals straddle zero, so the reset rule is not what makes the difference and production keeps the pair reset because it is already there. Two notes: the interest confound the spec blamed **did not exist** (`P_5050` is `mix(T20_cy + ETF)` to 0.0e+00 — SPEC 9.5 corrected), and the residual is lab-versus-engine accounting; the fully clean A/B needs a full-weekly-reset flag in `plan()`, deferred until the first settle is verified. Nothing adopted, nothing rejected on narrative. |
| H-003 | 2026-09-06 | Claude | Stock splits applied to the book's units on the effective date (`units *= ratio`, `last_px /= ratio`, recorded in `state["splits"]`); accounting parity with split-adjusted closes, same principle as H-001 | book vs broker residual; no phantom quantity diff in `reconcile` after a split | ACCEPTED by Lucas 2026-09-06 (accounting, not scoring): TASK-363 on branch `post-freeze-wiring`, `APPLY_SPLITS = True` (`4a77d6f`), SPEC 9.3; live after the post-settle merge |

| H-008 | 2026-09-08 | Lucas (pregunta) / Claude (registro) | Buffett indicator (equities Z.1 / GDP nominal) as a RISK-BUDGET modifier - never as a selection criterion, which is arithmetically impossible for a market-wide scalar | paired OOS `sharpe_excess` difference with SE, **behind a pre-declared power gate** | **PROPOSED, phase 1 only** - the indicator is recorded and changes nothing; phase 2 is gated and the gate currently fails, see below |

| H-009 | 2026-09-08 | Lucas (elige) / Claude (propone) | The PATH of the momentum, not its size: information discreteness (Da-Gurun-Warachka 2014) as a **tie-break** inside the candidate pool - a gradual riser continues better than a jumpy one with the same 12-7 return | DEV forward-return spread by ID tercile first; only then paired DEV `sharpe_excess` with a block-bootstrap interval | **REJECTED at step 0, same day.** Full pool **-0.42 bp** [-5.29, +5.29], wrong sign; winners-only (the pre-declared subsample) **+2.20 bp** [-4.45, +8.23], right sign but indistinguishable from zero. No portfolio lever built, TEST not read. |

| H-010 | 2026-09-08 | Claude (propone) / Lucas (elige) | **Residual momentum** (Blitz-Huij-Martens 2011): rank the momentum of the part of the return the market does not explain, not the raw return. Same 12-7 window, same everything downstream | DEV tercile-spread of the residual ranking **against** the conventional one, paired; only then the portfolio A/B | **REJECTED at step 0, same day.** Primary `sum(e)/sd(e)`: paired **-1.08 bp** [-6.65, +5.31]; secondary `sum(e)/vol63`: **-3.07 bp** [-8.51, +3.31]. Both standardisations wrong-signed, Spearman 0.85 so there WAS room. TEST not read. |
| H-011 | 2026-09-10 | Claude (propone) / Lucas (elige) | Drop the `/vol63` penalty from the stock score: `mom12_7` instead of `mom12_7 / vol63`, nothing else changes (lab lever `risk_adjust`) | Δ CAGR net vs B0: sleeve > +1.00 pp = valid; 50/50 engine > +1.00 pp = production | **REJECTED at step 0** (2026-09-10) |
| H-012 | 2026-09-10 | Lucas (especifica) / Claude (registro) | **Same-calendar-month seasonality** (Heston-Sadka): `SEA` = mean of the same calendar month's total return at lags 24/36/48/60 months; step 0 tercile spread in the pool, then secondary selection inside the top 1.5n | step 0: high-minus-low SEA tercile fwd 5-bar spread, DEV, block bootstrap; step 1: Δ CAGR net engine > +1.00 pp vs B0 | **REJECTED at step 0** (2026-09-10, wrong sign, interval clear of zero) |
| H-013 | 2026-09-10 | Claude (idea) / Lucas (retira) | GRJMOM-style partial vol scaling (`mom / vol^a`, a in (0,1)) | — | **WITHDRAWN** - premise falsified by H-011, never measured |
| H-014 | 2026-09-10 | Lucas (especifica) / Claude (registro) | **Absolute + cross-sectional momentum inside the ETF sleeve**: among the ETFs that already pass production's TSMOM-12m filter, keep the upper half by 12-month excess return, same total risky exposure | step 0: HIGH-minus-LOW fwd 20-bar spread, DEV, block bootstrap, 90 % CI; step 1 DEV: Δ CAGR HYDRA > +1.00 pp; step 2 TEST once: Δ ALL > +1.00 pp and Δ TEST > 0 | **REJECTED at step 0** (2026-09-10, predicted sign, 90 % interval includes zero) |
| H-015 | 2026-09-10 | Lucas (especifica) / Claude (registro) | **Fast confirmation of ETF absolute momentum**: when the 12-month excess return is still > 0 but the 21-bar excess return is <= 0 (CORRECTION), does the ETF lose against the T-bill over the next 20 bars, so that slice should sit in cash? | step 0: mean per-date CORRECTION forward-20 EXCESS over the T-bill < 0 with the 90 % upper bound < 0; step 1 DEV: Δ CAGR HYDRA > +1.00 pp; step 2 TEST once: Δ ALL > +1.00 pp and Δ TEST > 0 | **REJECTED at step 0** (2026-09-10: CORRECTION beat the T-bill by +88.8 bp per 20 bars, CI clear of zero on the WRONG side) |
| H-016 | 2026-09-10 | Lucas (especifica) / Claude (registro) | **Treasury momentum as a cross-asset predictor for the equity ETFs**: when an equity ETF keeps its own 12-month excess return > 0 but IEF's 12-month excess return is <= 0 (CROSS-BAD), does the equity exposure lose against the T-bill over the next 20 bars? | step 0: per-date mean CROSS-BAD forward-20 EXCESS over the T-bill < 0 with the 90 % upper bound < 0, >= 130 CROSS-BAD dates; step 1 DEV: dCAGR HYDRA > +1.00 pp; step 2 TEST once: dALL > +1.00 pp and dTEST > 0 | **REJECTED at step 0** (2026-09-10: CROSS-BAD beat the T-bill by +88.8 bp per 20 bars, CI clear of zero on the WRONG side) |
| H-017 | 2026-09-10 | H-015 (post hoc) / Lucas (reserva) | Short-term reversal conditional on a positive 12-month trend in the ETF sleeve ("buy the CORRECTION"): generated by OBSERVING H-015's result, not pre-registered before it | to be written before any run; pays its own trial | PROPOSED, **post-hoc hypothesis generated by H-015**, not measured |

## Template

```
### H-### — <short title>
- Date / proposer:
- Statement: what changes, exactly (parameter, rule, accounting).
- Motivation: journal entries / evidence review / paper / audit finding that prompted it.
- Expected effect and the single deciding metric (e.g. paired OOS Sharpe difference >= +0.05 with
  SE; or reconciliation residual reduced to < 0.1%).
- Falsifier: what result rejects it.
- Test plan: DEV panel (< 2016) first; TEST (>= 2016) read once and declared; executable accounting
  (`run_exec` / engine driver), costs included; paired difference with standard error.
- Result: table (gross, net, Sharpe, maxDD, turnover, distinct) current vs proposed; DEV and TEST.
- Decision (Lucas, date): ACCEPTED -> version vX.Y, ALGO_VERSION bump, SPEC section, journal marker
  date | REJECTED (why) | WITHDRAWN.
```

### H-008 — Buffett indicator as a risk-budget modifier (phase 1 done, phase 2 gated)

- **Date / proposer:** 2026-09-08. Lucas asked whether it could be a selection criterion; Claude
  registered it as this, because it cannot be that.
- **Why it cannot be a selection criterion:** it is one number per day for the whole universe.
  In the cross-section it multiplies every ticker by the same constant, so the ranking does not
  move — the same arithmetic that makes the Meta-Layer unable to tilt anything (SPEC 4.4, Spearman
  1.000 between regimes). A market-wide scalar can only change HOW MUCH is bought.
- **Statement, if it ever becomes a rule:** the expanding percentile of the indicator scales the
  stock sleeve's risk budget — `stock_target_vol * f(percentile)`, bounded, or a bias of the 50/50
  split toward the T-bill. The functional form, the bounds and the direction are declared **here,
  before any measurement**, and cannot be chosen after seeing returns.
- **Phase 1, done 2026-09-08 (no rule, no approval needed):** `data/macro.py` fetches the two FRED
  series key-free and appends **one vintage per run** to `data_cache/macro_snapshots.json`;
  `core/valuation.py` turns a level into an expanding percentile plus its episode count;
  `snapshot_macro.py` is the sidecar CLI. Nothing in the live path imports any of it. First
  reading recorded: **2.1814** (2026 Q1), percentile-as-known **98.84** against a 1947-2026
  median of 0.72 and an all-time high of 2.287.
- **Why the vintages matter:** GDP is revised for years, so building the indicator from today's
  vintage and applying it to 2008 is look-ahead. ALFRED serves real vintages only through its
  keyed API (the key-free CSV endpoint 404s on `vintage_date`, verified), so the honest history
  starts today and grows. The revised series is kept, labelled `revised`, and `pit_series()`
  refuses to return it.
- **THE POWER GATE, pre-declared (`core/valuation.enough_episodes_to_decide`):** a rule gets one
  observation per **episode** above the 80th percentile, not one per quarter — the series is
  autocorrelated at ~0.98. Minimum to attempt a measurement: **5 episodes inside the window where
  a price panel exists**. Measured 2026-09-08: **14 episodes since 1947, but only 4 overlap
  2004-2026**, and two of those last 3 and 4 quarters while the other two are single runs of 54
  and 58 quarters (1995-2008 and 2011-2026). **The gate fails.** The pre-declared conclusion is
  therefore **UNMEASURABLE on this data** — not "no effect", not "small effect".
- **A property any percentile rule inherits:** it habituates. With a midrank expanding percentile a
  level that stays elevated stops scoring as extreme (pinned by
  `test_episodes_are_contiguous_runs_not_observations`). That is the standard criticism of this
  indicator — expensive since 2013 and still climbing — and it is not a defect to be fixed with a
  full-sample percentile, which would be look-ahead.
- **Falsifier for phase 2, if the gate ever passes:** paired difference of `sharpe_excess` between
  the modified and unmodified engine on the same weeks (`experiments/reset_ab.py`'s machinery),
  with the interval straddling zero read as indistinguishable. Plus the arithmetic that has to be
  reported alongside: a rule that de-risks above the 80th percentile would have been de-risked for
  most of 2013-2026, which is where the system earned.
- **Result:** phase 1 only. No effect on any order.
- **Decision (Lucas, 2026-09-08):** "Fase 1 sí, fase 2 con el freno puesto." Recorded as agreed:
  registering costs little and gives HYDRA a macro series of its own with honest vintages;
  turning it into a rule would add a parameter fitted on two effective episodes on top of a
  vol-target and a trend gate that already de-risk, and would de-risk sooner.

### H-009 — information discreteness as a tie-break (pre-registered 2026-09-08, before any run)

- **Date / proposer:** 2026-09-08. Claude proposed three candidate layers, Lucas picked this one.
- **Statement:** two names with the same 12-7 momentum do not continue equally. Information that
  arrived **gradually** is absorbed more slowly than information that arrived in jumps, so the
  gradual riser has more continuation left (Da, Gurun & Warachka, *Frog in the Pan*, RFS 2014).
  Measured as information discreteness over the SAME formation window production already uses
  (the 126 daily returns from t-251 to t-126, i.e. the window behind `MOM_12_7`):

      ID = sign(PRET) x (%neg - %pos)

  with `%pos`/`%neg` the fractions of NON-ZERO days in the window that were positive/negative and
  `PRET` the window's cumulative return. Low (negative) ID = continuous information. High ID =
  discrete. Zero-return days count in neither fraction.
- **Why this shape and not a new score:** it consumes almost no test budget. The momentum ranking
  is untouched; ID only re-orders candidates that already passed selection, so `m = 1.0 x n`
  reproduces production **exactly** and the lever has one structural constant, in the same spirit
  as the existing `buffer = 2.0`.

**Step 0 - does the effect exist in OUR data (DEV only, < 2016-01-01).** Before any portfolio
variant: at each rebalance date, take the eligible candidate pool `rank_day` produces (same
filters, same gate as production), split it into ID terciles, and measure the forward 5-bar return
on the production convention (buy at the t+1 close, sell at the t+6 close). Pre-declared
expectation: **continuous (low ID) beats discrete (high ID) among winners**. The deciding number
is the tercile spread in bp per 5-bar step with a moving-block bootstrap interval (13-step blocks,
one index matrix for both legs - the paired construction from `experiments/reset_ab.py`).
**If the DEV spread does not have the predicted sign, this hypothesis stops here and no portfolio
variant is built.** A wrong-signed spread is a rejection, not an invitation to flip the rule.

**Step 1 - the portfolio A/B, only if step 0 passes.** Lab lever `id_tiebreak = m`: take the top
`round(m x n)` names by composite score, keep the `n` with the lowest ID, then apply the sector
cap, the buffer and the veto gate exactly as now. Primary specification `m = 1.5`, declared here.

- **Deciding metric:** paired difference of DEV `sharpe_excess` between the lever and production on
  the same weeks, with a block-bootstrap interval; `ann_net` and maxDD reported alongside; turnover
  reported, because a re-ordered pool still changes trades and this book pays 10 bp a side.
- **Robustness requirement, pre-declared:** the sign of the difference must hold at `m = 1.25` and
  `m = 2.0`. If it flips with the widening, the effect is fragile and the hypothesis is REJECTED
  regardless of how good `m = 1.5` looks. This is the guard against picking the pool width that
  happens to work.
- **Falsifier:** a DEV interval straddling zero -> indistinguishable, and TEST is not read.
- **TEST discipline:** TEST (>= 2016-01-01) is read ONCE, and only after Lucas has seen DEV and
  said so. Nothing in this hypothesis touches it before that.
- **Rule 6:** this changes selection, so production stays exactly as it is until Lucas approves
  with the measured table in front of him. `config.py` is untouched by the measurement.
- **Result (2026-09-08, `experiments/path_momentum.py`, DEV < 2016-01-01, 1084-bar PIT panel):**

  | pool | steps | continuous | middle | discrete | spread | 90 % interval | p(spread<=0) | steps positive |
  |---|---|---|---|---|---|---|---|---|
  | full eligible pool (mean 257 names) | 545 | 16.00 bp | 15.59 bp | 16.42 bp | **-0.42 bp** | [-5.29, +5.29] | 0.484 | 52.7 % |
  | winners only (mean 186 names) | 512 | 14.66 bp | 12.90 bp | 12.46 bp | **+2.20 bp** | [-4.45, +8.23] | 0.304 | 53.1 % |

  ID separated the terciles as intended (mean ID -0.13 continuous vs +0.02 discrete), so the
  measure works; what is absent is the return difference. On the full pool the point estimate has
  the **wrong sign** and sits in the middle of its own interval. On winners - the subsample the
  paper predicts and this pre-registration declared - the sign is right and the interval still
  straddles zero, with 53 % of steps positive against a coin's 50 %.

- **Decision: REJECTED at step 0, by the rule written before the run.** No portfolio lever, no
  robustness sweep at m = 1.25 / 2.0, and **TEST was not read**. Two further reasons not to
  rescue it: a +2.20 bp TERCILE SPREAD is not what a tie-break would capture (the lever re-orders
  inside a pool of ~1.5 x n, it does not go long-continuous / short-discrete), and this book pays
  10 bp a side, so the effect would have to be an order of magnitude larger before costs left
  anything. The `frog in the pan` result may well be real in its original sample (US 1927-2010,
  monthly, no costs, deciles); it is not measurable in the pool HYDRA actually chooses from.
- **Testing budget:** this spent **2 DEV trials**. The deflated-Sharpe haircut currently assumes
  N=38; it should be read as 40 from here.
- **What is kept:** the measure and its harness (`information_discreteness`, the tercile study, 14
  tests including the two look-ahead guards). The next path-shaped idea costs an afternoon, not a
  week - and a negative result that is recorded is worth more than one that is forgotten and
  re-proposed in six months.

### H-010 — residual momentum (pre-registered 2026-09-08, before any run)

- **Date / proposer:** 2026-09-08. Claude's first-ranked candidate of the three; Lucas asked for
  H-009 first, it was rejected the same day, and then asked for this one.
- **The claim:** conventional momentum is contaminated by market exposure. A name that rose because
  the market rose is not showing the same thing as a name that rose against a flat market, yet
  `ret / vol63` scores them alike. Ranking the momentum of the **residual** — the part of the
  return a market regression does not explain — isolates the idiosyncratic piece, and in
  Blitz, Huij & Martens (*Residual Momentum*, JEmpFin 2011) it roughly doubles the information
  ratio of conventional momentum at the same turnover.
- **Why it is a different claim from H-009:** H-009 was about the PATH of the return (gradual vs
  jumpy) and died at step 0. This is about the SOURCE of the return (market vs idiosyncratic).
  A rejection of one says nothing about the other.
- **Verified 2026-09-08:** never tried in this repo. The levers ever swept are `mom90`, `mom12_1`,
  `mom6_1`, `mom12_7`, the `ens` ensemble, `invvol`, `hold`, `buffer`, `exposure`,
  `vol_estimator`, `crash_brake`, `cash_yield`, `regime_breadth`. Nothing beta-adjusted.

**The construction, fixed here so it cannot be tuned later.** Same formation window production
already uses (the 126 daily returns from t-251 to t-126, the window behind `MOM_12_7`):

1. `beta_i` and `alpha_i` from an OLS of the name's daily returns on SPY's over the **756 bars
   ending at t-126** (36 months, the paper's estimation length). That window CONTAINS the
   formation window as its last 126 bars and **nothing after it**, so the residuals are the
   paper's in-sample ones and no post-window information can enter.
2. Residuals over the formation window with those fixed coefficients:
   `e_s = r_s - alpha - beta * m_s`.
3. **Primary score (the paper's):** `S_e / sd(e)` over the window — a t-stat-like quantity, so it
   is ALREADY risk-adjusted and it replaces `mom / vol63` wholesale rather than feeding into it.
   Dividing by `vol63` on top would standardise twice.
4. **Secondary, robustness only:** `S_e / vol63`, i.e. only the numerator changes. Declared here so
   that if the two disagree, that disagreement is a finding and not a choice.

Data guards, declared: a name needs >= 500 of the 756 bars for its beta and >= 100 of the 126
returns for its window, or it has no residual momentum that day and drops out exactly as a NaN
momentum does today.

**Step 0 — does the residual ranking sort future returns better than the one in production?**
DEV only (< 2016-01-01), the pool straight out of `rank_day` so filters and gate are production's,
forward return on the production convention (buy at the t+1 close, sell at the t+6 close). At each
rebalance date, split the pool into terciles by each score and take top-minus-bottom. The deciding
number is the **paired** difference of those two spreads — residual minus conventional — in bp per
5-bar step, with a moving-block interval (13-step blocks, ONE index matrix for both legs).
Reported alongside, because it decides whether there is anything to gain at all: the cross-
sectional **Spearman correlation** between the two scores. If they rank the pool nearly
identically there is no room for a difference regardless of the spread.

- **Pre-declared expectation:** the residual spread is the larger, so the paired difference is
  positive.
- **Falsifier:** a paired interval straddling zero -> indistinguishable, stop, do not read TEST.
  A negative point estimate -> REJECTED, and, as with H-009, a wrong sign is not an invitation to
  invert the rule.
- **Step 1, only if step 0 passes:** lab lever `mom='resid12_7'` in `redesign_lab.rank_day`, added
  so every existing config stays **bit-identical** (proven by re-running one and comparing, not
  asserted), then the portfolio A/B on DEV: paired `sharpe_excess` with its interval, `ann_net`,
  maxDD and turnover.
- **TEST discipline:** TEST (>= 2016-01-01) is read ONCE and only after Lucas has seen DEV and said
  so.
- **Rule 6:** this changes the score, so production stays exactly as it is until Lucas approves
  with the measured table in front of him.
- **Testing budget:** step 0 spends 1 primary trial (+1 secondary robustness). The deflated-Sharpe
  haircut's N should be read as 42 after this, having been 38 before H-009.
- **Result (2026-09-08, `experiments/residual_momentum.py`, DEV < 2016-01-01, 475 rebalance
  dates, both scores on the SAME pool and dates so the comparison is paired by construction):**

  | score | conventional spread | residual spread | paired difference | 90 % interval | p(<=0) | steps residual better |
  |---|---|---|---|---|---|---|
  | primary `sum(e)/sd(e)` | 7.89 bp | 6.81 bp | **-1.08 bp** | [-6.65, +5.31] | 0.583 | 50.7 % |
  | secondary `sum(e)/vol63` | 7.89 bp | 4.82 bp | **-3.07 bp** | [-8.51, +3.31] | 0.785 | 48.2 % |

  Cross-sectional Spearman between the two scores: **0.848** (primary) / 0.854 (secondary), so the
  residual ranking genuinely differs from production's - there was room for it to win, and it did
  not. Mean pool beta 1.037. The residual score starts later than the conventional one (2006-07
  rather than 2005-02) because it needs 756 + 126 bars of history, which is why there are 475
  steps and not 545.

- **Decision: REJECTED at step 0, both cells of the pre-registration.** No lab lever, no portfolio
  A/B, and **TEST was not read**. What this does NOT say: that Blitz-Huij-Martens is wrong. Their
  result is long-short deciles on a broad universe with monthly data and no costs. This measured
  something much narrower and much closer to what HYDRA does - whether, inside an already
  liquidity-filtered, gate-passed, large-cap pool (mean beta 1.04), re-ranking by the residual
  sorts the NEXT FIVE DAYS better than `ret/vol63` does. It does not.
- **A property found while testing, and it changes how the signal reads:** a constant idiosyncratic
  drift across the whole 756-bar estimation window is **absorbed by alpha** and scores ~0. What
  survives is the deviation from the name's own three-year alpha, so residual momentum is not
  "this name has quietly compounded for three years" but "the last six months beat what this name
  normally does". My first test asserted the opposite and failed; the code was right. Pinned by
  two tests.
- **Correctness of the machinery, verified rather than assumed:** betas, `sum(e)` and `sd(e)` come
  from rolling sums in closed form (6.9 million regressions would be the naive route) and match
  `numpy.linalg.lstsq` on the same bars to 8 decimals. An algebra error here would have produced
  plausible wrong numbers that no portfolio test would have caught.
- **Testing budget:** 2 more DEV trials. With H-009's two, the deflated-Sharpe haircut's N should
  be read as **42** from here, having been 38.
- **What is kept:** `residual_momentum()` and its 15 tests, including the two look-ahead guards
  (a return after the formation window cannot move any output; one inside it must). If the Russell
  PIT panel ever lands (TASK-403), this is worth re-running there before anything else: the paper's
  effect is strongest in small caps, which is exactly the half of production this panel cannot
  see.

## Closed before the register existed (for the record)

- NO momentum skip (skip-minus-last-5d was a reversal bet; worse in- and OOS) — 2026-09-06.
- vol-scaling k=1 stays (k=0 is beta, loses OOS) — 2026-09-06.
- MAX_PER_SECTOR=5 hard cap on GICS at selection — 2026-09-06.
- Regime on SPY, IWM secondary persisted for evidence only — 2026-09-06.
- MR (Rattlesnake) sleeve killed at pre-registration (DEV Sharpe 0.21) — 2026-09-06.
- Redesign target >= 10% net: not reached by any robust variant; production moved to the 50/50
  portfolio for return per unit of risk — 2026-09-06/07.

### B0 — the frozen baseline (2026-09-10, run once, `experiments/baseline_b0.py`)

ASTRA-06 showed the lab's breadth carried look-ahead; correcting it moved T20 (~7.55 -> ~7.28 in the
audit's own words). So the published 7.10 / 7.08 of older trees are NOT the comparison point for new
hypotheses. B0 is: commit **`e29599e`** (main after the consolidation: hardening, ASTRA-03/05/06/07/11,
corrected runner), today's caches, OOS S&P 500 PIT panel with delistings (TASK-350), sectors `fixed`,
same dates, executable accounting (`run_exec` / engine, costs included). Deciding metric everywhere:
**`ann_net`, a geometric annualised net return (CAGR), in percentage points**.

| B0 row | cycles | ann_net (CAGR) | net/vol | sharpe_excess | maxDD | turnover | how |
|---|---|---|---|---|---|---|---|
| engine 50/50 (production) | 1083 | **7.03** | 0.74 | 0.56 | -17.7 | 13.4 | `engine_backtest.py --oos` at e29599e, 2026-09-10 |
| T20 sleeve (cash at 0) | 1084 | **7.50** | 0.59 | 0.47 | -31.0 | 11.4 | `run_exec(CONFIGS["T20"])`, `metrics.stats` step 5 with the ^IRX leg |
| T20 sleeve, cash earns T-bill (`T20_cy`) | 1084 | **7.68** | 0.60 | 0.48 | -30.4 | 11.4 | same, `cash_yield=True` (the sleeve as the engine actually runs it) |
| PROD (legacy single portfolio) | 1084 | 4.91 | 0.38 | 0.27 | -41.2 | 39.4 | `run_exec(CONFIGS["PROD"])` |

Panel: 1209 names, 2004-01-02 -> 2026-09-04, 1084 five-bar marks 2005-02-11 -> 2026-08-24, eligibility on the
contemporaneous raw close where the cache has one (ASTRA-05), breadth on the PIT eligible set (ASTRA-06). All four rows
share the convention of the published engine row (`metrics.stats` on per-step NET returns, step 5, T-bill leg from the
same ^IRX); the lab's own `stats(df, hold)` annualises a 4-tranche book wrongly and is NOT used here. Frozen in
`experiments/_lab_scratch/b0.json` (`experiments/baseline_b0.py`, refuses to overwrite without `--force`).

Rules set by Lucas (2026-09-10): **Δ CAGR net > +1.00 pp** (percentage points, not relative) over the
matching B0 row = APPROVED; two criteria are kept apart - a sleeve improvement (`T20` vs B0 T20) is a
valid finding, a production change needs the **50/50 engine** to clear +1.00 pp over B0's engine row.
Sharpe, maxDD and turnover are reported alongside; CAGR decides. B0 is frozen: it is not re-run when
a hypothesis is tested, and a new B0 is minted only when `main` changes the lab or the engine, with
the reason written here.

### H-011 — drop the `/vol63` penalty from the stock score (pre-registered 2026-09-10, before any run)

- **Date / proposer:** 2026-09-10. Claude proposed, Lucas picked it as candidate #1 after the
  consolidation.
- **Statement:** control `score = mom12_7 / vol63` (production, `rank_day`'s `comp`, boosts and veto
  gate included); candidate `score = mom12_7`. **Nothing else changes**: same eligible pool, same
  filters, same sector cap, same buffer, same veto, same hold, same tranches, same exposure rule. Lab
  lever `risk_adjust` in `redesign_lab.BASE` (default `True` reproduces production bit for bit; the
  config `T20_raw` is `T20` with `risk_adjust=False`, nothing else).
- **Motivation:** dividing by realised vol tilts the sleeve toward low-vol names, which lowers gross
  return and may or may not pay for itself in drawdown; ASTRA-06 removed a source of false alpha in
  the lab, so the question is now askable on clean numbers.
- **Step 0 (DEV only, < 2016-01-01, `experiments/h011_vol_penalty.py`):** at each rebalance date, the
  same veto-filtered pool scored both ways; deciding number = the paired difference of the mean
  forward 5-bar return of the **top-14 names each score picks** (the selection the sleeve trades),
  with a moving-block bootstrap interval (13-step blocks, one index matrix for both legs); the
  top-minus-bottom tercile spread of each score is reported for context, and the top-14 overlap and
  mean vol63 of each pick set, so a difference can be read as "different names" or "riskier names".
  Pre-declared expectation: raw momentum picks earn MORE over the next five days (the penalty costs
  return). **Wrong sign = rejection at step 0, no portfolio A/B, TEST not read.** Predicted sign with
  an interval straddling zero = weak; the portfolio A/B may still be run because the deciding metric
  is CAGR on B0, but the expectation is written down as small.
- **Step 1 (portfolio A/B, executable accounting):** `run_exec(T20_raw)` vs B0's `T20` on the OOS
  panel; then the 50/50 engine with the lever (`engine_backtest.py --oos` with `T20_raw` as the
  ranking config) vs B0's engine row. Report ann_net, sharpe, maxDD, turnover, distinct names.
- **Deciding metric:** Δ CAGR net. Sleeve: `T20_raw.ann_net - B0.T20.ann_net > +1.00 pp` = valid
  sleeve improvement. Production: `engine(T20_raw).ann_net - B0.engine.ann_net > +1.00 pp` = APPROVED.
- **Falsifier:** step 0 wrong sign; or step 1 Δ CAGR <= +1.00 pp on the engine (then it is at most a
  sleeve finding, kept for combination with an independent ETF-side improvement, never approved alone).
- **TEST discipline:** DEV (< 2016) first at step 0; the portfolio A/B is run on the full OOS panel
  because B0 is defined on the full panel, and its DEV/TEST split is reported alongside so a
  post-2016-only gain is visible as such.
- **Rule 6:** production untouched; `config.py`, `core/signals.py`, `core/meta_layer.py` not edited.
- **Testing budget:** step 0 spends 1 DEV trial; step 1 spends 1 more. The deflated-Sharpe haircut's
  N, 42 after H-010, should be read as 44 after H-011.
- **Result (2026-09-10, `experiments/h011_vol_penalty.py`, DEV < 2016-01-01, OOS PIT panel, sectors fixed,
  pool from `T20`, 546 rebalance dates, mean pool 259 names, Spearman between the two scores 0.941,
  top-14 overlap 0.595):**

  | leg | control `mom12_7/vol63` | raw `mom12_7` | paired diff | 90 % interval | p(diff<=0) | steps raw better |
  |---|---|---|---|---|---|---|
  | mean fwd 5-bar return of the top-14 picks (deciding) | **23.41 bp** | **18.91 bp** | **-4.50 bp** | [-12.47, +3.44] | 0.822 | 46.2 % |
  | top-minus-bottom tercile spread (context) | 4.94 bp | 3.16 bp | -1.77 bp | [-8.10, +3.60] | 0.663 | 51.6 % |
  | mean vol63 of the picks | 0.272 | 0.354 | +30 % riskier | | | |

  The two scores pick different names four times out of ten, and the names raw momentum adds are
  30 % more volatile and earn LESS over the next five days: the penalty is not a drag on return on
  this pool, it is doing the selecting. The interval straddles zero, so this is not proof that the
  penalty helps either - it is the absence of the predicted effect with the point estimate on the
  wrong side.
- **Decision: REJECTED at step 0, by the rule written above before the run.** No portfolio A/B, no
  engine run, **TEST was not read**. Not rescued by "but CAGR decides": step 0 is the gate CAGR sits
  behind, and a -4.5 bp per step selection effect compounds to roughly -2 pp a year before costs, the
  opposite of the +1 pp the rule asks for.
- **Testing budget:** 1 DEV trial spent. N: 42 -> **43**.
- **What is kept:** the `risk_adjust` lever (default reproduces production bit for bit, `T20_raw`
  config) and the harness with 4 tests; the next "change one term of the score" idea costs an hour.

### H-012 — same-calendar-month seasonality inside the candidate pool (pre-registered 2026-09-10, before any run)

- **Date / proposer:** 2026-09-10. Lucas specified the effect and the protocol; Claude registers and measures.
- **Statement (Heston & Sadka 2008; Keloharju, Linnainmaa & Nyberg 2016):** stocks that were relatively
  strong in a given calendar month tend to be relatively strong in that same month again, at ANNUAL
  lags. Not "September is a good month": a cross-sectional persistence. For stock i and decision date
  t in calendar month M of year Y:

      SEA_{i,t} = ( R_{i,(Y-2,M)} + R_{i,(Y-3,M)} + R_{i,(Y-4,M)} + R_{i,(Y-5,M)} ) / 4

  with each R the TOTAL return of that whole calendar month (dividend-adjusted closes, month-end to
  month-end). Lags 24/36/48/60 months = the "years 2-5" specification; **the month one year back is
  deliberately excluded** so the signal cannot overlap conceptually with `mom12_7`. A name without
  all four months has `SEA` = not available; it is never expelled for lacking history.
- **Step 0 (DEV only, < 2016-01-01, `experiments/h012_seasonality.py`):** same dates, same
  `rank_day`, same filters, same veto, same universe, same forward return (t+1 close -> t+6 close)
  as H-009/H-010/H-011. Inside the veto-filtered pool, names with a valid `SEA` are split into
  terciles; **deciding number = mean forward 5-bar return of the high-SEA tercile minus the low-SEA
  tercile**, with the moving-block bootstrap already in use (13-step blocks, 5000 draws, one index
  matrix). Pre-declared: **direction positive**. **Negative point estimate -> REJECTED at once. 90 %
  interval crossing zero -> INDISTINGUISHABLE, treated as REJECTED. TEST is not read.** One DEV cell,
  one trial, no second subsample. Because the panel starts in 2004 and lag 60 needs five prior
  years, the DEV cell with a valid `SEA` runs from January 2009 to December 2015; this is written
  down here, before the run, as a property of the panel and not a choice.
- **Step 1 (only if step 0 survives), the mechanism inherited from H-009 with no new degree of
  freedom:** production ranking by `mom12_7 / vol63`; take the top `1.5 x n`; inside that pool
  prioritise the highest `SEA`; veto, sector cap, buffer, dynamic count, tranches, vol targeting,
  costs and execution unchanged. `1.5` is inherited, not optimised; no 1.2 / 1.7 / 2.3. Names with
  `SEA` not available are neither favoured nor expelled: the slots that cannot be filled with a
  valid signal are filled following the original production ranking.
- **Deciding metric at step 1:** Δ CAGR net of the 50/50 ENGINE vs B0's engine row (7.03):
  **APPROVED iff engine CAGR > 8.03 %**, unrounded (8.0301 passes, 8.0299 does not). T20, Sharpe
  excess, maxDD, turnover, number of substitutions and concentration are reported alongside and
  decide nothing.
- **Rule 6:** production untouched throughout; `fix/astra-06-followup` stays out of this cycle so B0
  is not contaminated.
- **Testing budget:** step 0 = 1 DEV trial. If it dies, N goes 43 -> 44 and that is the end of it.
- **Result (2026-09-10, `experiments/h012_seasonality.py`, DEV < 2016-01-01, OOS PIT panel, sectors fixed,
  pool from `T20`; valid `SEA` from 2009-02-03 (lag 60 needs 2004), 347 rebalance dates, mean pool 284
  names of which 276 (96.9 %) had all four months):**

  | | high-SEA tercile | low-SEA tercile | spread (high - low) | 90 % interval | p(spread<=0) | steps positive |
  |---|---|---|---|---|---|---|
  | mean `SEA` (same-month total return, lags 2-5y) | +5.06 % | -2.80 % | the sort works | | | |
  | mean forward 5-bar return | **28.53 bp** | **38.73 bp** | **-10.19 bp** | [-16.95, -3.23] | 0.992 | 42.1 % |

  The signal separates the pool as intended (a 7.9-point gap in same-month history between the
  terciles), and the names with the STRONG same-month history earned ten basis points LESS over the
  next five days, with the whole 90 % interval below zero. Inside a pool that has already been
  selected on 12-7 momentum, the calendar-month persistence of Heston-Sadka does not show; what
  shows has the opposite sign, which is not a licence to trade it (a wrong sign is a rejection, not an
  inverted rule - the same discipline as H-009/H-010/H-011).
- **Decision: REJECTED at step 0, by the rule written above before the run.** No secondary-selection
  lever, no portfolio A/B, **TEST was not read**. The paper's effect may well be real in its own sample
  (US, monthly, all stocks, no costs); it is not present in the pool HYDRA actually chooses from, on
  the five-day horizon it trades.
- **Testing budget:** 1 DEV trial spent. N: 43 -> **44**.
- **What is kept:** `month_returns()` / `sea_at()` and the harness with 4 tests (exact lags, the
  year-ago month excluded, missing history -> no signal, the decision rule). Next in the queue per
  Lucas: H-014, the ETF sleeve with absolute + cross-sectional momentum, to be written before any run.

### H-013 — GRJMOM-style partial volatility scaling (WITHDRAWN 2026-09-10, never measured)

Only made sense if H-011 showed the `/vol63` penalty was suppressing an edge. H-011 showed the
opposite (raw momentum: -4.50 bp per step, 46 % of dates, ~30 % more volatile picks). Trying
`mom / vol^0.7`, `mom / vol^0.5`, ... now would turn a negative result into a parameter search.
**WITHDRAWN - premise falsified by H-011**, not REJECTED: GRJMOM itself was never measured, so it
carries no result and spends no trial.

### H-014 — absolute + cross-sectional momentum inside the ETF sleeve (pre-registered 2026-09-10, before any run)

- **Date / proposer:** 2026-09-10. Lucas specified the hypothesis, the universe, the signals, the step-0
  design, the exposure invariant and the decision rules; Claude registers and measures. One new question
  only: among the ETFs that already pass production's absolute filter, do the relatively strong ones keep
  beating the relatively weak ones? The absolute filter itself is not re-examined (the sleeve already
  validated it; re-opening the 12-month horizon would spend a trial on a settled question).
- **Universe:** exactly production's, `SPY QQQ IWM EFA EEM TLT IEF GLD DBC VNQ`. Nothing added or
  removed. An ETF participates only with at least 252 bars of history, as in B0.
- **Absolute signal (unchanged from B0):** `ABS_{i,t} = R252_{i,t} - RF252_t`, the 252-bar total return
  minus the 252-bar accumulated T-bill (`(IRX/252).rolling(252).sum()`, the lab's and the engine's
  definition). Active iff `ABS > 0`. Horizon, threshold and T-bill definition untouched.
- **Cross-sectional signal:** among the active ETFs at the same date, `CS_{i,t} = ABS_{i,t}` (the T-bill
  is common across ETFs on a date, so this orders by 12-month total return; `ABS` is kept so there is
  one definition). No combination, coefficient, normalisation or optimisable parameter.
- **Step 0 (DEV only, TEST closed; `experiments/h014_etf_xs_momentum.py`):** at each ETF-sleeve decision
  date (the sleeve's own grid: from bar 280, every 5 bars), with information at the close of t only:
  (1) the set of ETFs with 252 valid bars and `ABS > 0`; (2) a date is comparable iff at least 4 are
  active; (3) sort by `CS` descending; (4) split at the median - `HIGH` upper half, `LOW` lower half,
  the middle name left out of both when the count is odd so the halves are equal; (5) forward total
  return from the t+1 close to the t+21 close (the ~20 bars an ETF tranche lives); (6) per date,
  `SPREAD_t = mean(R_fwd20_HIGH) - mean(R_fwd20_LOW)`. Primary statistic: the mean of `SPREAD_t` in bp
  per 20-bar period. **Single expectation: E[SPREAD] > 0.** Inference: moving-block bootstrap, ONE
  index matrix shared by HIGH and LOW, 13 decision dates per block, 90 % interval. Also reported,
  descriptive only: comparable dates, mean active ETFs, HIGH return, LOW return, spread, CI, p(spread <= 0),
  share of dates positive.
- **Power / coverage gate:** if fewer than 50 % of the DEV dates after the universe becomes available
  (the first date on which every ETF in the universe has 252 bars) have at least four active ETFs,
  the result is **UNMEASURABLE**, not REJECTED. The definition is not modified to manufacture
  observations.
- **Falsifier at step 0 - REJECTED and finished at once if the point estimate of SPREAD is <= 0 OR the
  90 % interval includes 0.** Then: no lever, no portfolio A/B, TEST not read, the signal not inverted,
  no top-2 / top-3 / terciles / quintiles / other horizons / combinations. Exactly one trial.
- **Step 1 (portfolio A/B, only if step 0 passes):** the candidate ETF sleeve keeps the same absolute
  filter and the same total risky exposure as B0. At each renewal: compute production's ETF portfolio;
  ETFs ON by `ABS > 0`; sort ON by `CS`; keep only the upper half, `K = ceil(N/2)`; no ETF ON -> all
  T-bill as in B0; one ETF ON -> identical to B0 that date. **Exposure invariant:** with
  `E_t = sum_i w_B0_{i,t}` the risky ETF exposure B0 would have had, the candidate's weights are
  inverse-vol (vol63) over the selected ETFs, rescaled so `sum_i w_H014_{i,t} = E_t`: same total risky
  exposure and same T-bill share as B0 at every renewal, only WHICH ETFs receive it changes; no
  renormalising to 100 % where B0 held cash. Frozen: hold 20, tranches 4, step 5, vol63, inverse-vol,
  ETF cost 5 bp/side, execution lag, T-bill, reset and executable accounting, 50/50 mix, T20
  byte-identical to B0. **Step 1 gate on DEV:** `Δ CAGR_HYDRA,DEV <= +1.00 pp` -> REJECTED, TEST stays
  closed, no variants; `> +1.00 pp` -> one reading of TEST is authorised.
- **Step 2 (TEST, once):** B0 and H-014 on TEST with the spec frozen; DEV, TEST and ALL reported
  separately: HYDRA net CAGR, Δ CAGR in pp, ETF-sleeve CAGR, Sharpe excess, net/vol, maxDD, turnover,
  costs, ETF exposure, mean number of ETFs, maximum concentration per asset.
- **Final decision:** **APPROVED iff `Δ CAGR_HYDRA,ALL > +1.00 pp` AND `Δ CAGR_HYDRA,TEST > 0`**
  (the second stops a > 1 pp gain made entirely in DEV that reverses sign out of sample; TEST need not
  itself clear +1 pp). REJECTED otherwise. No "almost approved".
- **Multiplicity:** step 0 is one trial; if it dies, N 44 -> 45. The portfolio A/B is not a new
  specification search but the test of the single pre-registered rule that survived step 0; no other
  ranking cuts or horizons under H-014. Why the upper half and not "top 3": top-3 is a new arbitrary
  parameter; the median split ties step 0 to the portfolio exactly - first ask whether HIGH beats LOW,
  then, only if it does, retire LOW and hand its risk budget to HIGH.
- **Rule 6:** nothing here touches production while PROPOSED or TESTED; any production change needs
  APPROVED and Lucas's explicit authorisation.
- **Expectation, written down:** moderate. Cross-sectional momentum is well documented across asset
  classes and considerably weaker in ETF-only samples (country/sector ETFs, late 1990s-2014). This
  hypothesis is worth running because it can die cheaply at step 0; a clean positive spread inside
  the small universe HYDRA actually trades would be the more valuable outcome, not the more likely.
- **Result (2026-09-10, `experiments/h014_etf_xs_momentum.py`, DEV < 2016-01-01, production ETF panel on
  the OOS calendar, ^IRX from the panel):** coverage gate PASSED - the universe is complete (every ETF
  with 252 bars) from 2007-02-07; of the 449 DEV decision dates after that, 404 (**90.0 %**) had at least
  four active ETFs, mean 6.9 active. Comparable dates in all of DEV: 504 (2005-02-11 -> 2015-12-31),
  mean 7.3 active ETFs.

  | | HIGH (upper half by CS) | LOW (lower half) | spread | 90 % interval | p(spread<=0) | dates positive |
  |---|---|---|---|---|---|---|
  | mean `CS` = `ABS` (12-m excess return) | +26.3 % | +8.4 % | the sort works | | | |
  | mean forward 20-bar total return | **70.86 bp** | **68.21 bp** | **+2.65 bp** | [-53.63, +57.92] | 0.422 | 55.0 % |

  The relatively strong active ETFs earned 2.65 bp more per 20-bar period than the relatively weak ones,
  a difference that is small next to a 20-bar ETF return of about 70 bp and sits in the middle of a
  110 bp-wide interval. The sign is the predicted one; the evidence is not.
- **Decision: REJECTED at step 0, by the rule written above before the run** (predicted sign, 90 %
  interval includes 0). No lever, no portfolio A/B, **TEST was not read**, signal not inverted, no
  top-2 / top-3 / terciles / other horizons. Consistent with the ETF-only literature that found
  cross-sectional momentum weak in country/sector ETF samples: with ten broad-asset ETFs, of which about
  seven are ON on a typical date, there is very little cross-section to rank.
- **Testing budget:** 1 DEV trial spent. N: 44 -> **45**.
- **What is kept:** `abs_signal()` (B0's rule, pinned bit for bit by test), `split_halves()`, the coverage
  gate and the harness with 5 tests. The ETF sleeve keeps its TSMOM-12m rule exactly as B0 has it.

### H-015 — fast confirmation of the ETF absolute momentum (pre-registered 2026-09-10, before any run)

- **Date / proposer:** 2026-09-10. Lucas specified it after checking it repeats no earlier experiment: the
  old `crash_brake` was a market rule on SPY (-6 %/5d, -10 %/10d) that cost T20 return, not a per-ETF
  trend confirmation; the old VORTEX "dual timeframe" was stock selection (120d/30d, acceleration,
  vol adjustment, stops). Support: Goulding, Harvey & Mazzoleni (JFE 2023) - the disagreement of slow
  and fast signals carries information about turning points; classic TSMOM finds persistence between
  one and twelve months. Budget before the trial: N = 45. Baseline: B0 frozen. Scope: the ETF sleeve
  only; T20 identical to B0.
- **Single question:** when the 12-month absolute momentum is still positive but the 1-month momentum
  is no longer positive, does the ETF exposure earn LESS than the T-bill over the next 20 bars, so that
  it should sit temporarily in cash? Nothing else in the algorithm changes.
- **Universe:** exactly B0's ten ETFs, same data-availability rules; nothing added or removed.
- **SLOW - production's signal, reused literally:** `SLOW_{i,t} = R252_{i,t} - RF252_t` with B0's T-bill
  convention; ON iff `SLOW > 0`. The harness may NOT re-implement it approximately: it calls the same
  function H-014 pinned against `sleeve_lab.run_sleeve`, and a test proves identity.
- **FAST - the only new variable:** `FAST_{i,t} = R21_{i,t} - RF21_t`, the same convention over 21 bars.
  No 5 / 10 / 20 / 42 / 63; the fast horizon is not optimised.
- **States, for ETFs with `SLOW > 0`:** CONFIRMED = `FAST > 0`; CORRECTION = `FAST <= 0`. `SLOW <= 0` is
  outside the hypothesis (B0 already holds it in T-bill).
- **Step 0 (DEV only, TEST closed; `experiments/h015_fast_confirmation.py`):** decision at the close of
  t; forward return from the next executable price over the life of an ETF tranche,
  `R_fwd20 = P_{t+21} / P_{t+1} - 1`; the T-bill realisable over exactly that interval,
  `RF_fwd20 = sum of IRX/252 over bars t+2..t+21` (the 20 accrual bars between the two closes, the
  same per-bar convention as `RF252`); `EXCESS_fwd20 = R_fwd20 - RF_fwd20`. Not gross return against
  zero: the economic alternative is the T-bill, so the falsifier compares against the T-bill. For each
  DEV date with at least one CORRECTION ETF, `C_t = mean(EXCESS_fwd20 | SLOW > 0, FAST <= 0)`; the
  deciding statistic is `C_bar = mean(C_t)`; each date weighs once however many ETFs are in
  CORRECTION (ten correlated same-day observations are not ten observations).
- **Single expectation:** `E[C_bar] < 0`. Deliberately stronger than "CONFIRMED beats CORRECTION": if
  CORRECTION still beats the T-bill, switching it off has no economic justification even if it earns
  less than CONFIRMED.
- **Inference:** moving-block bootstrap over decision dates, block 13, 90 % interval. Reported but not
  deciding: eligible DEV dates; dates with >= 1 CORRECTION and their share; ETF-CORRECTION observations;
  mean CORRECTION count when present; mean fwd-20 excess of CORRECTION and of CONFIRMED and their
  difference; 90 % CI of CORRECTION; `p(C >= 0)`; share of CORRECTION dates with negative excess. No
  second research cell.
- **Falsifier:** REJECTED at once if `C_bar >= 0` OR the 90 % interval contains zero. To survive:
  `C_bar < 0` AND `CI_90_upper < 0`. Too few observations for a valid bootstrap (fewer than two full
  blocks, i.e. < 26 CORRECTION dates) -> UNMEASURABLE; the specification is not modified; TEST stays
  closed. If step 0 fails, NOT tried: FAST 5d/10d/42d/63d, 3/6/12, majority votes, signal averages,
  FAST/SLOW weights, the inverted signal, a non-zero FAST threshold, waiting periods, multi-day
  confirmation. H-015 ends; N 45 -> 46.
- **Step 1 (portfolio A/B, only if step 0 survives):** B0 unchanged. H-015 changes one condition of the
  ETF sleeve: B0 `SLOW > 0 -> ON`; H-015 `SLOW > 0 and FAST > 0 -> ON`, `SLOW > 0 and FAST <= 0 ->
  T-bill`, `SLOW <= 0 -> T-bill`. Potential weights are B0's inverse-vol63 exactly; the survivors are
  NOT renormalised - an ETF that would carry 8 % in B0 and enters CORRECTION sends that 8 % to the
  T-bill, not to the other ETFs (this is an absolute-timing hypothesis, not a concentration one; H-014
  already tested and rejected that). Frozen: 4 tranches, renewal every 5 bars, hold 20, ETF costs
  5 bp/side, inverse-vol63, B0 execution, T-bill, accounting, pair reset, identical T20, identical
  50/50 mix, no leverage, no regime or universe change. The only causal difference: SLOW positive and
  FAST non-positive -> cash. **DEV gate:** `Δ CAGR_HYDRA,DEV > +1.00 pp` (unrounded) to open TEST;
  otherwise REJECTED, TEST closed, FAST not tuned.
- **Step 2 (TEST once):** code, parameters, input hashes and spec frozen; one run. DEV, TEST and ALL
  reported: HYDRA net CAGR, Δ CAGR, ETF-sleeve CAGR, T20 return, Sharpe excess, net/vol, maxDD, ETF
  turnover, costs, mean ETF exposure, mean T-bill share, CORRECTION frequency, extra switch-offs caused
  by FAST.
- **Final decision:** APPROVED iff `Δ CAGR_HYDRA,ALL > +1.00 pp` (with B0 = 7.03, strictly
  `CAGR_H015,ALL > 8.03 %`, unrounded) AND `Δ CAGR_HYDRA,TEST > 0`. REJECTED otherwise. No "almost".
- **Ex-ante mechanism:** not better ETF selection; detecting a lost trend before the 252-bar window
  recognises it. SLOW brings persistence and noise reduction, FAST brings recent information; when
  they disagree in this specific direction the old information is stale enough that staying exposed
  is worse than the T-bill over the tranche's economic horizon. That is the only claim being tested.
- **Multiplicity:** one specification, one FAST = 21, one threshold = 0, one forward horizon = 20, one
  DEV cell, no TEST unless survival. Running step 0 moves N 45 -> 46.
- **Rule 6:** research; production untouched while PROPOSED or TESTED; any engine change needs
  APPROVED and Lucas's explicit authorisation.
- **Result (2026-09-10, `experiments/h015_fast_confirmation.py`, DEV < 2016-01-01, production ETF panel on
  the OOS calendar, ^IRX from the panel):** 549 eligible DEV dates (>= 1 ETF with `SLOW > 0`); CORRECTION
  present on **450 of them (82.0 %)**, 1358 ETF-CORRECTION observations, 3.02 CORRECTION ETFs on average
  when present - the state is common, not rare, so the rule would have cut exposure most of the time.

  | | CORRECTION (`SLOW > 0`, `FAST <= 0`) | CONFIRMED (`SLOW > 0`, `FAST > 0`) |
  |---|---|---|
  | mean forward 20-bar EXCESS over the T-bill, per date | **+88.81 bp** | +37.27 bp |
  | 90 % bootstrap interval (block 13, 5000 draws) | **[+49.68, +139.86]** | |
  | p(C_bar >= 0) | 1.000 | |
  | share of CORRECTION dates with negative excess | 37.8 % | |
  | CONFIRMED - CORRECTION | | **-51.54 bp** |

  The ETFs whose 1-month excess return had turned non-positive while the 12-month trend was still up
  did not lose against the T-bill over the next 20 bars: they beat it by about 89 bp, more than twice
  what the CONFIRMED ETFs earned, with the entire 90 % interval on the wrong side of zero. In this
  universe and at this horizon a one-month dip inside a twelve-month uptrend has been a point of
  short-term reversal, not the early sign of a lost trend.
- **Decision: REJECTED at step 0, by the rule written above before the run** (`C_bar >= 0`). No lever,
  no portfolio A/B, **TEST was not read**. **The signal is NOT inverted:** the pre-registration lists the
  inverted signal among the things not to try, and "buy the CORRECTION ETFs" would be a new hypothesis
  with its own registration, not a rescue of this one. Not tried either: FAST 5/10/42/63, 3/6/12,
  votes, averages, weights, thresholds, waiting periods, multi-day confirmation.
- **Testing budget:** 1 DEV trial spent. N: 45 -> **46**.
- **What is kept:** `slow_signal()` (production's rule, reused, identity pinned by test), `fast_signal()`,
  `forward_excess()` (return net of the T-bill accrued over the same bars) and the harness with 5
  tests. Per Lucas's ex-ante plan, the next move is not another momentum speed but a genuinely
  different hypothesis (cross-asset predictive signals inside the ETF sleeve), to be written before any run.

### H-016 — Treasury momentum as a cross-asset predictor for the equity ETFs (pre-registered 2026-09-10, before any run)

- **Date / proposer:** 2026-09-10. Lucas specified it; Claude registers and measures. Budget before the
  trial: N = 46. Baseline: B0 frozen. Scope: the ETF sleeve only; T20 identical to B0. The repo search
  found no earlier cross-asset implementation (the old variants were multi-horizon momentum, the
  crash-brake and other overlays, not bonds -> equities conditioning). Support: cross-asset time-series
  momentum (Pitkajarvi, Suominen & Vaittinen, JFE 2020): past bond-market returns predict equity
  returns positively (and past equity returns predict bonds negatively; that second mechanism is NOT
  tested here - one mechanism, one trial, one economic falsifier).
- **Single question:** when an equity ETF keeps a positive 12-month absolute momentum but the US
  7-10y Treasury shows a non-positive 12-month absolute momentum, does the equity exposure lose
  against the T-bill over the next 20 bars?
- **Target assets (the only ones the signal may switch):** `SPY QQQ IWM EFA EEM VNQ` (VNQ counted as
  equity/REIT). **Not touched:** `IEF TLT GLD DBC`, byte-identical to B0.
- **Predictor:** IEF is the single Treasury proxy, fixed before observing anything. Not TLT, not an
  average, not chosen afterwards by results. Design reason: IEF is the intermediate/long zone and avoids
  the duration extremes of TLT dominating the signal.
- **Signals:** `OWN_{i,t} = R252 - RF252` for each equity ETF - literally the SLOW function fixed by
  H-014/H-015 (B0 says ON iff `OWN > 0`; H-016 does not redefine it). `BOND_t = R252_IEF - RF252`,
  computed by calling the SAME function; a test proves `BOND_t = SLOW_{IEF,t}` number for number and
  state for state.
- **States, among the equity ETFs currently ON (`OWN > 0`):** CROSS-CONFIRMED = `BOND > 0`; CROSS-BAD
  = `BOND <= 0`. The hypothesis is about CROSS-BAD only; `OWN <= 0` is already T-bill in B0.
- **Step 0 (DEV only, TEST closed, no alternative portfolio yet; `experiments/h016_bond_cross_asset.py`):**
  decision at the close of t; `R_fwd20 = P_{t+21}/P_{t+1} - 1`; `RF_fwd20` = the T-bill accrued over
  exactly those 20 bars (t+2..t+21), H-015's convention reused; `EXCESS_fwd20 = R_fwd20 - RF_fwd20`.
  For each date with >= 1 equity ETF with `OWN > 0` and `BOND_t <= 0`:
  `X_t = mean(EXCESS_fwd20 | OWN > 0, BOND <= 0)` across the eligible equity ETFs of that date;
  deciding statistic `X_bar = mean(X_t)`; each date weighs once (the six equity ETFs are not treated
  as independent observations).
- **Single expectation:** `E[X_bar] < 0`. Why against the T-bill and not the spread vs CROSS-CONFIRMED:
  if CROSS-BAD still clearly beats the T-bill, switching those ETFs off destroys CAGR even if
  CROSS-CONFIRMED is better; H-015 fixed this convention before H-016 was measured.
- **Inference:** moving-block bootstrap over dates, block 13, one index matrix, 90 % interval. Reported,
  not deciding: first date with IEF and the targets available; potentially eligible DEV dates; CROSS-BAD
  dates and their share; mean equity ETFs ON per date; mean ETFs affected during CROSS-BAD; mean fwd-20
  excess of CROSS-BAD and of CROSS-CONFIRMED and their difference; 90 % CI of X_bar; `p(X >= 0)`; share
  of CROSS-BAD dates with negative excess.
- **Power gate:** at least **130** DEV dates with CROSS-BAD and a complete forward return (about ten
  full bootstrap blocks); fewer -> UNMEASURABLE; no switch to TLT, no shorter horizon, no threshold
  change, no pooling of signals to manufacture observations; TEST stays closed.
- **Falsifier at step 0:** survives only if `X_bar < 0` AND `CI_90_upper < 0`; REJECTED at once if
  `X_bar >= 0` or the 90 % interval contains zero. If step 0 fails, expressly forbidden under H-016:
  TLT instead of IEF, IEF+TLT, 1m/3m/6m returns, 12-1, non-zero thresholds, z-scores, regressions,
  signal weights, the inverted signal, equities -> bonds, commodities -> equities, GLD as predictor,
  multiple confirmations. H-016 ends; N 46 -> 47.
- **Step 1 (portfolio A/B, only if step 0 survives):** B0: equity ETF ON iff `OWN > 0`. H-016: ON iff
  `OWN > 0 and BOND > 0`; `OWN > 0 and BOND <= 0` -> that ETF's B0 weight goes to the T-bill;
  `OWN <= 0` -> T-bill as in B0. Weights are B0's inverse-vol63, NOT renormalised: if B0 would hold SPY
  7 %, QQQ 6 %, IWM 5 % and `BOND <= 0`, those fractions go to the T-bill, not to other equity ETFs, TLT,
  IEF, GLD or DBC. IEF, TLT, GLD, DBC keep exactly B0's weights. Frozen: universe, 4 tranches, renewal
  every 5 bars, hold 20, inverse-vol63, 5 bp/side, execution, T-bill, dividends, pair reset, accounting,
  T20, 50/50 mix, no leverage. **DEV gate:** `dCAGR_HYDRA,DEV > +1.00 pp` (unrounded) to open TEST;
  otherwise REJECTED, TEST closed.
- **Step 2 (TEST once):** freeze code, commit, inputs, hashes, dates, signal, parameters; one run; report
  DEV/TEST/ALL: HYDRA net CAGR, dCAGR, ETF-sleeve CAGR, T20 CAGR, Sharpe excess, net/vol, maxDD,
  turnover, costs, mean ETF exposure, T-bill share, CROSS-BAD frequency, equity exposure removed,
  intervention frequency.
- **Final decision:** APPROVED iff `dCAGR_HYDRA,ALL > +1.00 pp` (strictly > 8.03 % with B0 = 7.03,
  unrounded) AND `dCAGR_HYDRA,TEST > 0`; REJECTED if TEST reverses sign or ALL does not clear +1.00 pp.
  No "almost".
- **Multiplicity:** one predictor (IEF), one horizon (252), one threshold (0), one target group (equity
  ETFs), one forward (20), one DEV cell, at most one TEST reading; nothing optimised after the result.
- **Rule 6:** research; production untouched while PROPOSED or TESTED; any engine change needs APPROVED
  and Lucas's explicit authorisation.
- **Result (2026-09-10, `experiments/h016_bond_cross_asset.py`, DEV < 2016-01-01, production ETF panel on the
  OOS calendar, ^IRX from the panel):** BOND defined from 2005-01-03; 490 eligible DEV dates (>= 1 equity
  ETF with `OWN > 0`, IEF with 252 bars); **CROSS-BAD on 150 of them (30.6 %)** - the power gate (130) is
  passed; 5.0 equity ETFs ON per eligible date, 5.6 affected when CROSS-BAD. CROSS-BAD dates run from
  2005-02-28 to 2014-06-16; none in 2015 (IEF's 12-month excess return stayed positive).

  | | CROSS-BAD (`OWN > 0`, `BOND <= 0`) | CROSS-CONFIRMED (`OWN > 0`, `BOND > 0`) |
  |---|---|---|
  | mean forward 20-bar EXCESS over the T-bill, per date | **+88.83 bp** | +68.85 bp |
  | 90 % bootstrap interval (block 13, 5000 draws) | **[+36.49, +160.61]** | |
  | p(X_bar >= 0) | 0.994 | |
  | share of CROSS-BAD dates with negative excess | 28.7 % | |
  | CROSS-CONFIRMED - CROSS-BAD | | **-19.98 bp** |

  Equity ETFs in their own 12-month uptrend did not lose against the T-bill when IEF's 12-month excess
  return was non-positive: they beat it by about 89 bp per 20-bar period, MORE than when Treasuries were
  also trending up, with the whole 90 % interval on the wrong side of zero. In this universe and at this
  horizon a weak Treasury trend has coincided with risk-on equity periods (rising rates, expansions), not
  with equity weakness; the bonds -> equities mechanism of the cross-asset TSMOM literature does not
  show as a switch-off signal for the tranche horizon HYDRA trades.
- **Decision: REJECTED at step 0, by the rule written above before the run** (`X_bar >= 0`). No lever,
  no portfolio A/B, **TEST was not read**. Not tried, as forbidden: TLT, IEF+TLT, 1m/3m/6m, 12-1,
  thresholds, z-scores, regressions, weights, the inverted signal, equities -> bonds, commodities ->
  equities, GLD, multiple confirmations.
- **Testing budget:** 1 DEV trial spent. N: 46 -> **47**.
- **What is kept:** `bond_signal()` (SLOW on IEF, identity pinned by test), the equity/untouched partition
  and the harness with 4 tests. Two hypotheses in a row (H-015, H-016) found that a "bad" fast or
  cross-asset signal inside a 12-month equity uptrend marked BETTER, not worse, forward excess returns;
  each is recorded, neither is inverted, and any hypothesis built on that observation (H-017) enters as
  post hoc and pays its own trial.

### H-017 — short-term reversal conditional on a positive 12-month trend (post-hoc, reserved 2026-09-10, NOT measured)

- **Origin, stated plainly:** this hypothesis was generated by OBSERVING H-015's result - CORRECTION
  ETFs (`SLOW > 0`, `FAST <= 0`) earned +88.81 bp over the T-bill per 20 bars against +37.27 bp for
  CONFIRMED, with the 90 % interval [+49.68, +139.86]. H-015's pre-registration forbade inverting the
  signal, so "buy the CORRECTION" is a NEW hypothesis: it enters the register as a **post-hoc hypothesis
  generated by H-015**, it must be written in full (states, weights, exposure invariant, falsifier)
  before any run, and it pays its own trial (N) when it is executed. The number that motivated it
  cannot serve as its own evidence.
- **Status:** PROPOSED, reserved. Not scheduled: Lucas's plan after H-016 is to weigh H-017 against
  widening the opportunity set (Russell 3000 PIT) before spending the next trial.
