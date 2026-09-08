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
