# Pre-registration — TASK-438, market impact overlay (the second half of TASK-434's `CAPACITY_NOT_CERTIFIED`)

**FROZEN 2026-09-14 (v1) — TASK-438.** Written before a single number is produced and before any
participation-vs-return distribution is looked at. Committed on `feat/task-438-impact-overlay`, cut from
`main = acddc37` (#95–#99 inside); sha256 on the board. Any later change is a new version, not an edit.

## 0 · The question, and what would falsify the answer

TASK-433 measured what a constant cost per side does to the strategy (10/5 → 50/15 bp: Russell
5.664 → 3.311 %, S&P 7.959 → 5.426 %). TASK-434 measured how much of ADV each footprint takes at a
given capital (participation ceiling Russell ≈ 19.7 M, S&P ≥ 100 M under P95 ≤ 3 %). Neither says
what the *price* of that participation is. This task asks: **at capital C, what effective cost per
side does market impact add, and at what C does that cost reach each of 433's stress scenarios?**

The deliverable is one curve per universe — **effective impact bp per side vs capital** — read
against the pre-registered yardstick 10/5, 20/8, 35/10, 50/15 bp, and the capitals at which the
impact-implied cost crosses each rung. Nothing here is a price prediction; it is a proxy cost
model with parameters declared below, and the label changes from `CAPACITY_NOT_CERTIFIED` to
**`IMPACT_MODELLED_NOT_MEASURED`** — modelled, because no fill of ours has ever been measured
against the tape.

Falsified as impact evidence if:

- **G1** the overlay is not computed on the F1-proved sidecars of run `20260914-cc34d9465892`
  (russell sha `3ec811915fcb`, sp500 `f916ea307e7b`) — a re-drive would be a new task;
- **G2** volatility is read at the settle bar or later (must be `t-1`, like ADV), or the window is
  shortened / filled when incomplete;
- **G3** the participation used is not 434's footprint participation under 434's frozen rules
  (execution footprint, ADV20 ex-ante, unknown = unknown);
- **G4** the model's parameters are changed after the first curve is seen;
- **G5** the "turnover does not react to cost" assumption is used without its 433 measurement
  beside it (Russell stocks 10.776 → 10.774 % per settle across 10 → 50 bp; S&P 11.322 → 11.317).

## 1 · Inputs — identified, not described

| logical name | path | identity |
|---|---|---|
| fill sidecars | `_lab_scratch/capacity/runs/20260914-cc34d9465892/{russell,sp500}_base.fills.pkl` | sha `3ec811915fcb`, `f916ea307e7b`; F1 PASSED both; `TASK_434_CODE_REF = aab3f62` |
| ADV panels | same run dir, `adv_usd_{russell,sp500,etf}.pkl` | shas in `capacity_drive.json` |
| close panels | `russell_prereg_cache/close.pkl`, `_sweep_cache_oos/close.pkl`, `_sweep_cache_etf/close.pkl` | the data blocks the 433 books recorded; ETF close sha `f866814457` |
| accredited books | `accredited/runs/20260914-cae2c54599aa/{russell,sp500}_base.pkl` | NAV path for the drag denominator; `12e478f9…`, `de56c7fb…` |
| 433 cost table | `task433_accredited_20260914-cae2c54599aa.json` | the yardstick rungs and their `ann_net` |

**Not available, and therefore not modelled:** bid-ask spread (no quote data), intraday
high/low (no Corwin–Schultz proxy), our own fills against the tape (none exist yet — the live book
has 30 pending orders and no reconciled fill). The spread half of execution cost stays inside
433's exogenous bp, where it already is; this task does not invent a spread.

## 2 · The model — declared now

**Square-root impact**, the one functional form with consistent empirical support across
markets and the only one whose inputs we have:

    impact_bp(fill) = k · σ_daily(ticker, t−1) · sqrt( participation(fill, C) ) · 10 000

- `σ_daily(ticker, t−1)` = standard deviation of close-to-close log returns over the previous
  **63 market bars** ending at `t−1` (the bar before the settle), on the panel's own index,
  **full window or unknown** — `rolling(63)` default `min_periods`, never shortened, never filled.
  Adjusted close, as the lab's returns are.
- `participation(fill, C)` = 434's footprint participation at capital C (fraction, not percent):
  `|net footprint dollars| · C / ADV20(t−1)`. The fill inherits its footprint's participation.
- `k` = **1.0** as the headline (the conservative end of the published range for US equities,
  where the coefficient on σ·√(Q/V) is typically quoted between ~0.5 and ~1.0), with a
  **sensitivity band k ∈ {0.5, 1.0, 1.5}** printed beside it. k is not fitted to anything here —
  there is nothing to fit it to — and does not move after the first curve is seen (G4).
- Unknown σ or unknown participation ⇒ **unknown impact** for that fill; the fill's dollars are
  reported in the uncovered share by count and by notional, exactly as 434 does. Fail-closed:
  if more than 5 % of the notional at a capital level is unknown, the curve point is
  `NOT MEASURABLE` and printed under that label.

**From per-fill impact to an effective cost per side.** Impact is a cost on the *dollars traded*,
which is what 433's bp are. So at capital C:

    eff_bp_side(C, sleeve) = Σ_fills impact_bp(fill) · |dollars(fill)|  /  Σ_fills |dollars(fill)|

over all covered fills of the sleeve across the 814 settles — a dollar-weighted mean impact in bp
per side. This is the number read against 10 / 20 / 35 / 50 bp (stocks) and 5 / 8 / 10 / 15 bp
(ETF). Reported per sleeve and total, at each C on the 434 grid (10 k … 100 M, ×1.25, ending
exactly at 100 M) and at the fixed levels 100 k, 500 k, 1 M, 19.7 M (Russell's participation
ceiling).

**The crossings.** For each yardstick rung r ∈ {20/8, 35/10, 50/15} and sleeve: the smallest C on
the grid with `eff_bp_side(C, sleeve) ≥ rung_bp − 10` for stocks (impact on top of the 10 bp base)
and `≥ rung_bp − 5` for ETF — bracketed (largest passing, smallest failing), `grid_exhausted` when
the top of the grid does not reach the rung. These capitals are the task's headline: "the
square-root model with k = 1 puts Russell at 433's *conservative* scenario at C ≈ …, at *stress* at
C ≈ …".

**Drag in return space, as a cross-check only.** `ann_drag_pp(C) ≈ turnover_per_year · eff_bp/1e4
· 100` with turnover from the sidecar (Russell stocks 542.7 %/yr one-way, ETF 95.3 %; S&P 570.2 %,
97.3 %). It is printed beside 433's measured Δann_net for the matching rung so the reader can see
the overlay is in the same units — the measured Δ is authoritative, the drag is arithmetic.

## 3 · What is fixed, what is a sensitivity, what is not claimed

- Fixed: the form, `k = 1.0` headline, σ window 63 bars at `t−1`, participation from 434, grid,
  fail-closed 5 % rule, dollar-weighted aggregation, the three rungs.
- Sensitivity, printed not chosen: `k ∈ {0.5, 1.5}`, σ window 21 bars.
- **Not claimed:** a measured cost (nothing of ours was measured against the tape); a spread; any
  intraday dynamics; that the strategy would trade the same way at C = 20 M as at C = 1 — 433
  showed turnover does not react to the *cost parameter*; whether it reacts to *impact* cannot be
  tested without an engine that knows about impact, which is out of scope here and would be a
  scoring-adjacent change needing Lucas's approval.
- The result feeds no engine parameter. If Lucas later wants an impact-aware cost in the engine,
  that is a separate task with a separate pre-registration.

## 4 · Accreditation

- Portable suite (`experiments/test_impact.py`): every rule above on a synthetic sidecar + ADV +
  close panel, each pinned by a mutation (σ at `t`, shortened window, k moved, percent/fraction
  confusion, unknown counted as zero, aggregation not dollar-weighted, grid beyond 100 M).
- External audits (registered, `DID NOT RUN` elsewhere): sidecar shas equal 434's recorded ones
  (G1); the report is what the rules produce (recompute one panel end-to-end); `eff_bp` is
  monotone in C (√ is monotone, so a violation is a bug); the label is on everything; the close
  panels used are the 433-recorded data blocks by sha.
- No new run id — nothing is driven. The report is `task_impact_<date>.json` beside 434's, with the
  434 run id and the 433 run id inside it.

## 5 · Order of work (numbers last)

1. Branch from `main ⊇ #99`; commit this prereg; sha256 on the board.
2. `experiments/impact.py` + `test_impact.py` on synthetic data.
3. `experiments/impact_report.py`: reads the 434 run dir and the 433 table; refuses if the sidecar
   shas are not the recorded ones.
4. Only then: the curves, the crossings, the drag cross-check. Board. PR.

## 6 · Pre-declared expectations

- At 100 k … 1 M the effective impact is well under 1 bp on both universes (participation is
  0.01–0.12 % at P95; √ of that times a ~2 % daily σ is a fraction of a bp): the 433 base
  scenario 10/5 already overstates impact at production size by an order of magnitude, and the
  live book's cost problem is fixed cost and spread, not impact.
- Russell reaches the *conservative* rung (+10 bp of impact) somewhere between 5 M and 20 M with
  k = 1; the S&P not before the top of the grid. If Russell reaches +10 bp **below 5 M**, the 434
  ceiling (19.7 M) was the wrong number to quote for Russell's operable size and the board says so.
- The crossing capitals scale as 1/k² — the k band therefore spans a factor ~9 in capital, which
  is the honest width of this model's answer, printed as such.
