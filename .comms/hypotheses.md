# Hypothesis register — HYDRA evolution protocol (spec section 10.3)

Write the hypothesis BEFORE testing it. One entry per idea; rejected ideas stay with their numbers.
Status: PROPOSED -> TESTED (numbers) -> ACCEPTED (version) | REJECTED | WITHDRAWN.

| id | date | proposer | statement | decides on | status |
|---|---|---|---|---|---|
| H-001 | 2026-09-06 | Claude | Dividends credited to the tranche holding the units on ex-date (accounting parity with total-return backtests) | book vs broker residual | ACCEPTED by Lucas 2026-09-06 (accounting, not scoring): TASK-349, `a38c732`; spec 9.3 |
| H-002 | 2026-09-06 | Claude | The 1/8-per-week pair reset vs a full weekly 50/50 reset: measure the return/Sharpe difference on the OOS panel with the production engine | paired ann_net / Sharpe, OOS | **TESTED 2026-09-08, closed as INDISTINGUISHABLE** (TASK-409, `experiments/reset_ab.py`). Full weekly 50/50 reset 6.97 % / Sharpe 0.567 against the pair reset 7.10 % / 0.569, paired on the same weeks with a single block-index matrix: **d_ann -0.13 pp, 90 % [-0.82, +0.55]; d_sharpe -0.003, [-0.075, +0.069]**; p(full <= pair) 0.625. Both intervals straddle zero, so the reset rule is not what makes the difference and production keeps the pair reset because it is already there. Two notes: the interest confound the spec blamed **did not exist** (`P_5050` is `mix(T20_cy + ETF)` to 0.0e+00 — SPEC 9.5 corrected), and the residual is lab-versus-engine accounting; the fully clean A/B needs a full-weekly-reset flag in `plan()`, deferred until the first settle is verified. Nothing adopted, nothing rejected on narrative. |
| H-003 | 2026-09-06 | Claude | Stock splits applied to the book's units on the effective date (`units *= ratio`, `last_px /= ratio`, recorded in `state["splits"]`); accounting parity with split-adjusted closes, same principle as H-001 | book vs broker residual; no phantom quantity diff in `reconcile` after a split | ACCEPTED by Lucas 2026-09-06 (accounting, not scoring): TASK-363 on branch `post-freeze-wiring`, `APPLY_SPLITS = True` (`4a77d6f`), SPEC 9.3; live after the post-settle merge |

| H-008 | 2026-09-08 | Lucas (pregunta) / Claude (registro) | Buffett indicator (equities Z.1 / GDP nominal) as a RISK-BUDGET modifier - never as a selection criterion, which is arithmetically impossible for a market-wide scalar | paired OOS `sharpe_excess` difference with SE, **behind a pre-declared power gate** | **PROPOSED, phase 1 only** - the indicator is recorded and changes nothing; phase 2 is gated and the gate currently fails, see below |

| H-009 | 2026-09-08 | Lucas (elige) / Claude (propone) | The PATH of the momentum, not its size: information discreteness (Da-Gurun-Warachka 2014) as a **tie-break** inside the candidate pool - a gradual riser continues better than a jumpy one with the same 12-7 return | DEV forward-return spread by ID tercile first; only then paired DEV `sharpe_excess` with a block-bootstrap interval | **PROPOSED, written before measuring** |

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
- **Result:** (to be filled by the measurement, below this line)

## Closed before the register existed (for the record)

- NO momentum skip (skip-minus-last-5d was a reversal bet; worse in- and OOS) — 2026-09-06.
- vol-scaling k=1 stays (k=0 is beta, loses OOS) — 2026-09-06.
- MAX_PER_SECTOR=5 hard cap on GICS at selection — 2026-09-06.
- Regime on SPY, IWM secondary persisted for evidence only — 2026-09-06.
- MR (Rattlesnake) sleeve killed at pre-registration (DEV Sharpe 0.21) — 2026-09-06.
- Redesign target >= 10% net: not reached by any robust variant; production moved to the 50/50
  portfolio for return per unit of risk — 2026-09-06/07.
