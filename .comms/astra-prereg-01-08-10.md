# Pre-registration — Astra findings 01 / 08 / 10 (the three that need Lucas)

Author: Claude · Date: 2026-09-06 · Branch: `docs/astra-prereg-01-08-10` (base `origin/main` @ `1c21bc4`)
Source: external adversarial audit (Astra), `Auditoria-Hydra-2026-09-06/test_adversarial.py`.
Protocol: `.comms/hypotheses.md` (H-004, H-005, H-006 — all **PROPOSED**), spec section 10.3.

**This branch changes no behaviour.** It adds this document, the hypothesis rows, a read-only
measurement script (`hydra_screener_local/experiments/measure_astra_01_08_10.py`) and a strict-xfail
contract file (`hydra_screener_local/test_astra_prereg_contracts.py`) that keeps Astra's assertions
in the suite while marking them as not-yet-implemented. Nothing here may merge into the live path
before the first settle after the 2026-09-08 close is verified — and the three fixes themselves need
Lucas's explicit approval (GROKBOARD rule 6) *plus* the measurements listed under each finding.

Reproduce every "measured here" number in a fresh worktree:

```
cd hydra_screener_local
python experiments/measure_astra_01_08_10.py
python -m pytest test_astra_prereg_contracts.py -q      # 3 xfailed, 1 passed
```

Astra's line numbers come from `merge-prepared-2026-09`. All coordinates below were re-found on
`origin/main` @ `1c21bc4` and are quoted as `file:line`.

---

## Summary table

| id | finding | class of change | worst case measured here | what is still missing |
|---|---|---|---|---|
| H-004 | ASTRA-01: zero recommendations become 22 buy targets | **selection** (portfolio construction, spec 4.6/4.7/9) | `recommended=0`, `dynamic_count=22`, **22 positive targets**, 24.85% gross of the renewed tranche | frequency and P&L on the OOS PIT panel (`data_cache/`, `history/` absent) |
| H-005 | ASTRA-08: staleness ages per `mark()` call, not per session | **accounting policy** (spec 9.4) | 10 marks on **one** date → position written off, **+200.00 USD** cash minted; production ages **daily**, spec and lab say **weekly / 5-bar steps** (5×) | write-off count and P&L difference on the OOS panel |
| H-006 | ASTRA-10: the sector cap does not apply to buffered holds | **selection** | cap 5 → **6** Technology names held; and `dynamic_count` floor 6 means 5 names = **83.3%** of the tranche, not 25% | how often the cap binds on held names in the real panel |

---

## ASTRA-01 (CRITICAL) — the quota, not the survivors, sizes the tranche

### Where it is on main

- `hydra_screener_local/core/signals.py:312` — `df['recommended_count'] = dynamic_count`. The
  column is the **quota** (`clamp(round(14 · aggression · compass_mult), 6, 28)`,
  `core/signals.py:281-291`), written *after* the veto and never reduced by it. The comment on
  `core/signals.py:310-311` even says so: "el gate puede reducir el conteo efectivo por debajo de
  `dynamic_count`".
- `hydra_screener_local/core/portfolio_engine.py:138` — the engine reads that column as `n`:
  `n = int(ranking["recommended_count"].iloc[0]) if "recommended_count" in ranking.columns else int(ranking["recommended"].sum())`.
  The fallback branch is the correct quantity; the branch that actually runs is not.
- `hydra_screener_local/core/portfolio_engine.py:105-128` — `select_tranche_names()` then walks the
  ranking again and drops rows only by **text**: `df["reason"].str.startswith("Vetado")`
  (`:112-113`). It never looks at `ranking["recommended"]`.
- `hydra_screener_local/core/signals.py:139-142` — and here is the part that makes it worse than
  Astra stated. The gate writes the `"Vetado: …"` reason **only for names that were recommended**:
  `veto_downtrend = in_downtrend & df["recommended"]`. A name that is in a violent downtrend but
  never carried the flag keeps `reason = "Filtrado por Meta-Layer"`. So the one filter
  `select_tranche_names()` has is blind to exactly the names its fill loop reaches.

Net effect: the tranche is always filled to `dynamic_count` names walking down the momentum rank,
regardless of how many names the veto and the meta-layer actually authorised.

### Measured here (synthetic, no market data)

Fixture A — Astra's: 60 names, +0.2%/bar drift, last ten bars × 0.7; real v9 ranking
(`mom12_7`), all sectors `"Other"` so the cap cannot mask anything.

| quantity | value |
|---|---|
| `recommended.sum()` | **0** |
| `recommended_count` (the quota the engine uses as `n`) | **22** |
| positive `stock_targets` rows | **22** |
| gross weight of the renewed tranche | **0.248474** (vol-scaling `min(1, 0.15/σ63)` is the only brake) |
| max single weight | 0.011294 |
| reasons starting with `"Vetado"` | 22 of 60 — all filtered out by `select_tranche_names` |
| reasons `"Filtrado por Meta-Layer"` | 38 of 60 — **the pool the 22 slots are filled from** |

So the veto worked, all 22 vetoed names were correctly dropped, and the sheet then bought 22
*different* names that the meta-layer had already refused. The sleeve reopens ~25% gross exposure
on the exact bar the system decided nothing was worth owning.

Fixture B — not degenerate, so it cannot be dismissed as a corner: 60 names with a decaying drift,
only the 15 strongest shocked −25% over the last ten bars.

| quantity | value |
|---|---|
| `recommended.sum()` | 19 |
| `recommended_count` | 22 |
| positive targets | 22 |
| picked names with `recommended == False` | **3** (`A34` rank 23, `A3` rank 24, `A6` rank 25) |
| of those, names the downtrend gate *would* have vetoed had they carried the flag | **2** |

`A3` was bought at rank 24 with `ret_10d = −24.10%` and `dist_20d_high = −24.10%` — both gate
thresholds (`GATE_MIN_RET_SHORT_PCT = −5.0`, `GATE_MAX_DIST_TO_HIGH_PCT = −8.0`,
`config.py:127-128`) breached by a factor of three. Its reason is `"Filtrado por Meta-Layer"`, so
nothing downstream can tell it apart from a merely-unselected name.

Gross exposure in fixture B is 1.0 both before and after the patch below, so the defect is not
always an exposure story — in the normal case it is a *composition* story: the tranche silently
holds names the algorithm rejected.

### Patch I would apply (NOT applied)

```diff
--- a/hydra_screener_local/core/portfolio_engine.py
+++ b/hydra_screener_local/core/portfolio_engine.py
@@ def select_tranche_names(ranking, n, held, buffer, max_per_sector=MAX_PER_SECTOR)
     order = df["ticker"].tolist()
     sectors = dict(zip(df["ticker"], df["sector"])) if "sector" in df.columns else {}
+    # A vacancy may only be filled by a name the algorithm actually authorised. The "Vetado"
+    # text filter above is not enough: signals.apply_downtrend_gate only rewrites `reason` for
+    # names that already carried `recommended`, so a name in a downtrend that never made the
+    # list keeps "Filtrado por Meta-Layer" and is indistinguishable from an eligible one.
+    eligible = set(df.loc[df["recommended"].fillna(False), "ticker"]) if "recommended" in df.columns else set(order)
     keep_zone = set(order[:int(round(buffer * n))]) if buffer > 1.0 else set()
     picked, counts = [], {}
     for name in order:
         if name in held and name in keep_zone:
             picked.append(name); s = sectors.get(name, "Other"); counts[s] = counts.get(s, 0) + 1
     for name in order:
         if len(picked) >= n:
             break
-        if name in picked:
+        if name in picked or name not in eligible:
             continue
@@ def stock_targets(ranking, held, prices, cfg=None)
-    n = int(ranking["recommended_count"].iloc[0]) if "recommended_count" in ranking.columns else int(ranking["recommended"].sum())
+    # `recommended_count` is the QUOTA (spec 4.6); the veto (4.7) can only lower the effective
+    # count. Sizing the tranche by the quota reopens exposure the veto meant to withdraw.
+    n_quota = int(ranking["recommended_count"].iloc[0]) if "recommended_count" in ranking.columns else len(ranking)
+    n_eff = int(ranking["recommended"].fillna(False).sum()) if "recommended" in ranking.columns else n_quota
+    n = min(n_quota, n_eff)
     if n <= 0:
         return pd.Series(dtype=float)
```

Deliberately **not** in this patch: the buffer's keep loop still keeps a held name that lost its
flag while it ranks inside `buffer · n` and is not text-vetoed. That is the turnover buffer doing
its job (`stock_buffer = 2.0`, `config.py:71`) and removing it is a separate, larger change.

Measured effect of this exact patch on the fixtures (computed out-of-tree, module untouched):

| fixture | current | patched |
|---|---|---|
| A (`recommended = 0`) | 22 targets, 0.2485 gross | **0 targets, `targets.empty` → tranche goes to T-bill** |
| B (`recommended = 19`, quota 22) | 22 targets, 3 not recommended, gross 1.0 | **19 targets, 0 not recommended, gross 1.0** |

### Acceptance test

`hydra_screener_local/test_astra_prereg_contracts.py::test_zero_authoritative_recommendations_park_live_targets`
— Astra's probe, assertion verbatim (`targets.empty`), currently `xfail(strict=True)`. Removing the
marker is part of the fix commit. Add alongside it: fixture B asserting
`set(targets.index) <= set(ranking.loc[ranking.recommended, "ticker"])`, and a
`stock_targets` case with a held name inside the buffer that lost its flag, asserting the hold
survives (so the patch is not silently widened into a buffer change).

### Class of change

**Selection / portfolio construction.** No formula in `core/signals.py` or multiplier in
`core/meta_layer.py` moves; no threshold in `config.py` moves. But it changes the traded list on
every renewal where the veto or the meta-layer bites, so under rule 4 it must be measured, and
because it changes live orders it needs Lucas's OK.

It also needs a **spec correction**, because the spec currently contradicts itself:
`HYDRA_ALGORITHM_SPEC.md:353` says the veto "solo puede quitar el flag (el conteo efectivo puede
quedar < dynamic_count)", while `HYDRA_ALGORITHM_SPEC.md:537` defines the sleeve as
"`dynamic_count` = n". Section 9 must say `n = min(dynamic_count, count(recommended))`, and that a
tranche with `n = 0` holds T-bill.

### What must be MEASURED before Lucas can say yes

1. **Panel**: the OOS PIT panel, 2004-2026, real S&P 500 membership (TASK-324/326/338), run through
   the production engine driver (`experiments/engine_backtest.py`, the same path TASK-347 used) —
   not `redesign_lab.run_exec`, because the lab's `select()` shares the defect and would measure
   zero difference. Costs on (`stock_cost_bp = 10`). DEV (< 2016) first, TEST (≥ 2016) read once
   and declared.
2. **Comparison**: `n = dynamic_count` (current) vs `n = min(dynamic_count, count(recommended))`
   with the eligibility filter. Same seeds, same calendar, same anchor, same universe — the only
   difference is the two hunks above.
3. **Paired statistic**: per-renewal paired difference in tranche return, aggregated to
   `d_ann_net_pp` and `d_sharpe` with bootstrap p05/p95 via `experiments/bootstrap_compare.py`
   (`summarise_diff`, block bootstrap, 5-year blocks). Report gross, net, Sharpe, maxDD, turnover
   and distinct names, DEV and TEST, current vs proposed.
4. **The exposure-risk number that actually decides it** — a frequency, not a return:
   - share of renewal bars with `count(recommended) < dynamic_count`, and the distribution of the
     shortfall;
   - share of renewal bars with `count(recommended) == 0` (the fixture-A state) and the gross
     exposure the current code opened on each of them;
   - conditional mean forward 20-bar return of the names the current code bought that were
     **not** recommended, vs the recommended names it bought on the same bar. This is the direct
     test of "is the veto information or noise".
5. **Kill criterion.** Reject the patch if, on DEV, `d_ann_net_pp ≤ −1.0 pp` **and** the p95 of the
   paired difference is below 0 (i.e. the veto's information is negative with confidence). Accept it
   if `d_sharpe ≥ 0` OR (`|d_ann_net_pp| < 0.5 pp` and maxDD does not worsen) — because at
   return-parity the version that does not reopen exposure against its own veto is the one to run,
   and the fixture-A state is an uncontrolled tail whatever the mean says. If the number of
   `count(recommended) == 0` bars in 22 years is **zero**, say so and downgrade the finding from
   CRITICAL to a latent contract break: still worth fixing, no longer urgent.

**Missing in a worktree**: everything in 1-4. `data_cache/`, `history/` and `state/` are gitignored
and live only in the production tree; the PIT panel is not in the repo. I did not estimate any of it.

---

## ASTRA-08 — staleness counted per `mark()` call, not per session

### Where it is on main

- `hydra_screener_local/core/portfolio_engine.py:159-178` — `mark()` calls `book.age_stale(px)`
  unconditionally (`:166`) and appends the resulting write-offs stamped with
  `state.get("last_run_date")` (`:167-168`).
- `hydra_screener_local/core/tranche_book.py:142-158` — `age_stale()` increments
  `tr.stale[tk] += 1` for every held name without a print and writes the name off at `last_px`
  once the counter reaches `max_stale_bars` (10, `config.py:80`). It has **no notion of which
  session it is being called for**; its docstring says "call once per step" but nothing enforces it.
- `hydra_screener_local/core/portfolio_engine.py:56-63` — `_book()` builds a **fresh** `TrancheBook`
  on every call, so `self.step` is always 0. Every write-off record in production state therefore
  carries `step: 0` and the records cannot be ordered by anything but the run date.

Two distinct defects sit on top of that, and the second is the one with money on it:

**(a) repeat calls.** `plan()` is guarded against a same-day re-run
(`core/portfolio_engine.py:223-224`), so today the only way to hit Astra's probe is to call
`mark()` directly — it is public API and the only production caller is `plan()` (`:231`), but
`summary_table()` deliberately re-implements the read-only valuation to avoid it
(`:357-358`), which is exactly the trap a future dashboard walks into. Nothing in the type or the
name says "this mutates a counter".

**(b) cadence — the substantive one.** `portfolio_v9.run()` is documented as "**One daily step**"
(`portfolio_v9.py:314`) and `daily.py` calls it every day when `ALGO_VERSION == "v9"`
(`daily.py:167-172`). So in production staleness ages **once per calendar trading day**. But:
- `HYDRA_ALGORITHM_SPEC.md:592-595` states the carry is `max_stale_bars` (10) "**weekly marks**
  (plan() runs; the lab's `run_book` counts steps the same way)";
- the lab's `run_book` ages once per **step**, and a v9 step is `step_bars = 5` bars
  (`config.py:68`).

10 daily runs ≈ 2 calendar weeks. 10 lab steps = 50 bars ≈ 10 calendar weeks. **The production
write-off horizon is 5× shorter than the horizon every OOS number was measured with**, including
the TASK-350 evidence quoted in the same spec paragraph ("the OOS run now writes ESRX off at its
last price"). The spec's parenthesis asserts an equivalence — daily runs = weekly marks = lab steps
— that holds only if the CLI is run exactly once a week, which nothing enforces.

**Amplifier (Astra's, confirmed).** `portfolio_v9.fetch_v9_market()` (`portfolio_v9.py:123-134`)
downloads `get_universe(universe=uni)` only. It never unions the tickers the book holds or has
pending, so a holding that leaves the index simply stops printing and starts ageing as if it were a
data outage. The helper already exists and is already used two functions away for dividends:
`tickers_from_state(state)` (`portfolio_v9.py:378, 382`). `plan()` does receive the unfiltered
`prices` frame (`portfolio_v9.py:392`), so widening the download is sufficient — no change to the
filter chain is needed.

### Measured here

Astra's fixture: 10 units of `AAA` at 20.00, tranche cash 800.00, `last_run_date = "2026-09-11"`,
ten `mark()` calls with `{'AAA': NaN}` — one single date.

| quantity | before | after 10 marks |
|---|---|---|
| units `AAA` | 10.0 | **absent (written off)** |
| tranche 0 cash | 800.00 | **1000.00** |
| cash created out of one calendar day | — | **+200.00 USD** |
| `write_offs` | `[]` | one record, `date = "2026-09-11"`, `proceeds = 200.0`, **`step = 0`** |

The write-off is *recorded*, so this is not silent — but it is dated to a single session and the
position it liquidated was priced NaN, i.e. the book converted an unpriced position into cash
against ten repetitions of the same information.

### Patch I would apply (NOT applied)

Option **A — minimal, per distinct session** (preserves Astra's assertion exactly):

```diff
--- a/hydra_screener_local/core/tranche_book.py
+++ b/hydra_screener_local/core/tranche_book.py
-    def age_stale(self, px: pd.Series):
+    def age_stale(self, px: pd.Series, advance: bool = True):
         """Call once per step with the step's END prices: names without a price age; past the
-        limit they are written off at their last valuation (recorded, not silent)."""
+        limit they are written off at their last valuation (recorded, not silent).
+
+        `advance=False` refreshes `last_px` for the names that DO print without touching the
+        counters: a second valuation of the same session is not a second bar."""
         for k, tr in enumerate(self.tranches):
             for tk in list(tr.units):
                 p = px.get(tk, np.nan)
                 if np.isfinite(p):
                     tr.stale.pop(tk, None)
                     tr.last_px[tk] = float(p)
                     continue
+                if not advance:
+                    continue
                 tr.stale[tk] = tr.stale.get(tk, 0) + 1
--- a/hydra_screener_local/core/portfolio_engine.py
+++ b/hydra_screener_local/core/portfolio_engine.py
 def mark(state, stock_prices, etf_prices, cfg=None):
     cfg = cfg or V9
+    session = state.get("last_run_date")
+    advance = session is not None and state.get("last_mark_date") != session
     out = {"sleeves": {}, "total": 0.0}
     for sleeve, px, bp in (...):
         book = _book(state, sleeve, bp, cfg)
-        book.age_stale(px)
+        book.age_stale(px, advance=advance)
@@
     out["total"] += v
     _dump(state, sleeve, book)
+    if advance:
+        state["last_mark_date"] = session
     return out
```
plus `state.setdefault("last_mark_date", state.get("last_run_date"))` in
`core/state_migrations.py::_fill_missing_v1` and a `last_mark_date` consistency check in
`core/state_check.py` (it already validates `stale` keys against `units`, `:187-193`). No
`schema_version` bump: the migration only fills a missing key, which is the documented policy
(`core/state_migrations.py:1-4`).

Option **B — full lab parity**: age by `bars_between(index, last_mark_date, today) // step_bars`
steps, so `max_stale_bars = 10` means 50 bars in production exactly as in the lab, whatever the run
cadence. This is the version that removes the 5× divergence; option A only removes the
same-date repetition.

Prerequisite for either (not itself a policy change — a data-coverage fix, but it touches the frozen
live path):

```diff
--- a/hydra_screener_local/portfolio_v9.py
+++ b/hydra_screener_local/portfolio_v9.py
-def fetch_v9_market(universe: str = None) -> dict:
+def fetch_v9_market(universe: str = None, extra_tickers=()) -> dict:
     ...
     tickers = get_universe(universe=uni)
+    # A holding that leaves the index must still be quoted, or the book ages it as if the data
+    # feed had failed and writes it off at last price. Union holdings + pending (ETF sleeve
+    # tickers come from V9["etf_universe"] and are fetched separately).
+    tickers = sorted(set(tickers) | (set(extra_tickers) - set(V9["etf_universe"])))
```
called as `(fetch_fn or fetch_v9_market)(universe, tickers_from_state(state))` at
`portfolio_v9.py:319` (guarding `state is None` on the first run).

### Acceptance test

`test_astra_prereg_contracts.py::test_mark_same_date_does_not_write_off_after_ten_calls` — Astra's
assertion verbatim, `xfail(strict=True)` today. For option B add: a state whose `last_mark_date` is
25 bars back, one `mark()` with the name still unpriced, asserting `stale == 5` (25 // 5) and no
write-off; and a parity test running the same unpriced name through `run_book` and through
repeated `plan()` calls, asserting the write-off lands on the same **bar** in both.

### Class of change

**Accounting policy** (spec 9.4). It changes when a position leaves the book and how much cash
appears, so it changes the books Lucas reconciles — the same category as H-001 (dividends) and
H-003 (splits), both of which he approved as accounting rather than scoring.

### What must be MEASURED before Lucas can say yes

1. **Panel**: the OOS PIT panel 2004-2026 with real membership — this is the only place where names
   actually stop printing (AET / ESRX / TWX are the documented cases, TASK-350). Live state is
   useless here: the book is 2 days old and has never had a delisting.
2. **Comparison**: three arms on the same panel, same engine driver — (i) current per-run ageing at
   the panel's own cadence, (ii) option A, (iii) option B. And separately: (i) with vs without the
   `fetch_v9_market` union, to isolate how much of the observed staleness is a real delisting and
   how much is an index exit with a live quote.
3. **Paired statistic**: per-step paired book-value difference → `d_ann_net_pp` and `d_sharpe` with
   bootstrap p05/p95; plus the counts that make it interpretable — number of write-offs, total
   write-off proceeds as a share of NAV, and the mean number of bars a name was carried before
   write-off, per arm. The clinching number is **how many write-offs in arm (i) disappear under the
   `fetch_v9_market` union**: those were never delistings, they were download gaps.
4. **A cadence census that needs no panel and that I could not run either**: the distribution of
   gaps between consecutive `last_run_date` values in the production `state/portfolio_v9.json` and
   in `history/`. If Lucas has in fact run the CLI once a week, the 5× divergence is theoretical and
   option A suffices; if there are back-to-back daily runs, the horizon has already been compressed
   and option B is required. **This is the cheapest decisive measurement and it is missing** — the
   state file is gitignored and I must not read or run against the production tree.
5. **Kill criterion.** Reject option B if it produces a *worse* reconciliation residual than option
   A (it should not — it is strictly closer to the lab), or if lengthening the horizon to 50 bars
   makes DEV `maxDD` worse by more than 1.0 pp (carrying a dead name ten weeks is its own risk).
   Reject the `fetch_v9_market` union only if it cannot be done inside the fetch budget
   (`SECTOR_FETCH_BUDGET_SECONDS`, and the yfinance batch size) — a handful of extra tickers should
   be free. If arm (i) and arm (ii) are identical on the panel *and* the cadence census shows only
   weekly runs, close H-005 as WITHDRAWN-with-guard: keep the acceptance test, change nothing.

**Missing in a worktree**: items 1-4. Reported, not estimated.

---

## ASTRA-10 — the sector cap does not apply to the positions the buffer keeps

### Where it is on main

`hydra_screener_local/core/portfolio_engine.py:114-128`, `select_tranche_names()`:

```python
keep_zone = set(order[:int(round(buffer * n))]) if buffer > 1.0 else set()
picked, counts = [], {}
for name in order:                                    # loop 1 — the buffer's keep loop
    if name in held and name in keep_zone:
        picked.append(name); s = sectors.get(name, "Other"); counts[s] = counts.get(s, 0) + 1
for name in order:                                    # loop 2 — vacancies
    if len(picked) >= n: break
    if name in picked: continue
    s = sectors.get(name, "Other")
    if s != "Other" and counts.get(s, 0) >= max_per_sector: continue   # <- the cap, loop 2 only
    picked.append(name); counts[s] = counts.get(s, 0) + 1
return picked[:n]
```

Loop 1 has no cap check. `MAX_PER_SECTOR = 5` (`config.py:182`) therefore governs **new entries
only**. Holdings that end up in one sector — through GICS reclassification, through the sector cache
resolving `"Other"` into a real sector on a later run (`SECTOR_FETCH_BUDGET_SECONDS`,
`config.py:186`), or through a name entering when its sector had room and staying after it filled —
survive the cap indefinitely. `HYDRA_ALGORITHM_SPEC.md:311-312` claims the opposite: "The cap holds
by construction, and still holds after the Downtrend Veto Gate (4.7), since vetoing names can only
lower a sector's count." That is true of the spec's pseudocode (`:301-309`, one loop, no buffer) and
false of the implementation, which has two loops.

Second effect of the same unguarded loop: with `stock_buffer = 2.0` the keep zone is the top `2n`,
so loop 1 can append **more than `n`** names. `picked[:n]` truncates by rank afterwards, but
`counts` has already been charged for the names that get truncated away — so loop 2's view of the
sector counts is wrong whenever the book is holding heavily inside the buffer.

### Measured here

Astra's fixture: 10 ranked names, 6 Technology + 4 Energy, the 6 Technology names all held, `n = 10`,
`buffer = 2.0`, `max_per_sector = 5`.

| quantity | value |
|---|---|
| picked | `A0 … A9` (all ten) |
| Technology in the picked list | **6** |
| cap | 5 |
| over the cap by | **1** |

Overfill fixture (mine): `n = 6` — the **floor** of `dynamic_count` — 12 ranked names (8 Technology
+ 4 Energy), 8 Technology names held, all inside the keep zone `2n = 12`.

| quantity | value |
|---|---|
| loop 1 appends | 8 names, `counts["Technology"] = 8` |
| returned after `picked[:6]` | `A0 … A5` — **6 Technology names, 100% of the tranche** |
| over the cap by | 1 |

Patched behaviour of the same fixtures (computed out-of-tree):
`['A0','A1','A2','A3','A4','A6','A7','A8','A9']` — 5 Technology, 4 Energy, and **9 names for a
10-slot tranche**, because with only 4 Energy names available the cap genuinely cannot be filled;
and `['A0','A1','A2','A3','A4','A8']` for the overfill fixture (5 Technology + 1 Energy). Note the
9-of-10 case: enforcing the cap on holds can leave a slot unfilled, which raises per-name weight
(`stock_targets` divides exposure by `len(names)`), not cash. That is a real consequence to measure,
not a bug in the patch.

### The false equivalence in the docs (correction, measured)

Three separate claims are wrong and they compound:

1. **"T20" is not twenty stocks.** It is a **20-BAR tranche**: `hold_bars = 20`, `tranches = 4`,
   `step_bars = 5` (`config.py:67-69`). The stock count per tranche is `dynamic_count`, which has
   nothing to do with the 20. `.comms/astra-analysis-prompt-2026-09-06.md:216` — my own prompt to
   Astra — says "`MAX_PER_SECTOR = 5` sobre T20 = hasta 25% en un sector", which silently reads the
   "20" as a name count and divides 5/20. **There is no 20-name list anywhere in v9.**
2. **`dynamic_count` is clamped to `[6, 28]`**, not `[14, 28]` (`core/signals.py:288-291`,
   `HYDRA_ALGORITHM_SPEC.md:339`). `config.py:176-177` reasons about the cap "sobre una lista de
   14-28, 5 es como mucho un 36% en un sector" — 14 is the *base* before `aggression · compass_mult`,
   not the floor. At the real floor:

   | `dynamic_count` | 5 names as a share of the tranche's names | note |
   |---|---|---|
   | 6 (floor) | **83.3%** | one sector may be 5/6 of the tranche |
   | 14 (base) | 35.7% | the number `config.py` quotes |
   | 20 (the "T20" misreading) | 25.0% | the number in the prompt — **no basis** |
   | 28 (ceiling) | 17.9% | |

3. **There is no 25% weight guarantee anywhere, and no weight guarantee at all.** `stock_targets`
   (`core/portfolio_engine.py:132-149`) sets every name to `expo / len(names)` — equal weight over
   the *selected* names, scaled by `min(1, 0.15/σ63)`. The sector cap constrains a **count**, never
   a weight; and because the count it constrains is `len(names)` and not a fixed 20, the same cap
   of 5 is a 17.9% sector limit in a calm regime and an 83.3% one in the regime where
   `dynamic_count` hits its floor — i.e. the cap is loosest exactly when aggression is lowest.
   Measured share of a *tranche* (not the book): the stock sleeve is 50% of the book across 4
   tranches, so one renewed tranche is ~12.5% of NAV; 5 same-sector names at the floor are 83.3% of
   that tranche and ~10.4% of NAV, before vol-scaling.

Exact doc diffs I would apply (not applied here — `config.py` and the SPEC are rule-6 files, and
`.comms/astra-analysis-prompt-2026-09-06.md` is a historical artefact of what was actually sent to
Astra and should not be rewritten after the fact; **this section is the correction of record**):

```diff
--- a/hydra_screener_local/config.py
+++ b/hydra_screener_local/config.py
-# nombres tech). Sobre una lista de 14-28, 5 es como mucho un 36% en un sector — lejos del
-# 72% que motivó este control.
+# nombres tech). `dynamic_count` va de 6 a 28 (14 es la BASE, no el suelo): 5 nombres son el
+# 17.9% de la lista con 28 y el 83.3% con 6, asi que el cap es mas flojo justo cuando la
+# agresion es mas baja. El control es sobre CONTEO, no sobre peso: stock_targets reparte
+# expo/len(names) a partes iguales y no hay ninguna garantia de peso por sector.
```
```diff
--- a/hydra_screener_local/HYDRA_ALGORITHM_SPEC.md
+++ b/hydra_screener_local/HYDRA_ALGORITHM_SPEC.md
-The cap holds by construction, and still holds after the Downtrend Veto Gate (4.7),
-since vetoing names can only lower a sector's count.
+The cap holds by construction for the SELECTION in 4.5. It does NOT hold for a tranche the
+engine renews: `portfolio_engine.select_tranche_names()` keeps held names inside
+`stock_buffer * n` before the capped loop runs, so holdings reclassified into one sector can
+exceed it (Astra-10 / H-004..H-006, `.comms/astra-prereg-01-08-10.md`).
```

### Patch I would apply (NOT applied)

```diff
--- a/hydra_screener_local/core/portfolio_engine.py
+++ b/hydra_screener_local/core/portfolio_engine.py
     for name in order:
+        if len(picked) >= n:
+            break                                    # the keep zone is 2n wide: do not overfill
         if name in held and name in keep_zone:
-            picked.append(name); s = sectors.get(name, "Other"); counts[s] = counts.get(s, 0) + 1
+            s = sectors.get(name, "Other")
+            if s != "Other" and counts.get(s, 0) >= max_per_sector:
+                continue                             # the cap governs holds too, not only entries
+            picked.append(name); counts[s] = counts.get(s, 0) + 1
```

### Acceptance test

`test_astra_prereg_contracts.py::test_cap_holds_for_buffered_positions_after_sector_change` —
Astra's assertion verbatim (`count <= 5`), `xfail(strict=True)` today. Add: the overfill fixture
above asserting `len(picked) == n` and `counts["Technology"] <= 5`; and a test asserting that when
the cap binds and no eligible name is left, `len(picked) < n` and `stock_targets` still returns
weights summing to `expo` (the unfilled slot must not silently become cash).

### Class of change

**Selection.** Same category as the `MAX_PER_SECTOR = 5` decision itself, which is recorded as a
Lucas-approved scoring change (`HYDRA_ALGORITHM_SPEC.md:328-334`), so tightening its scope goes back
to him. The doc corrections are not a change of behaviour and should land regardless of the verdict.

### What must be MEASURED before Lucas can say yes

1. **Panel**: the OOS PIT panel with **point-in-time GICS sectors**, which is the crux — the whole
   finding is about sector *changes* over time. TASK-318/344 built the sector plumbing; if the panel
   only has today's GICS map, this measurement is not possible and the honest answer is "we cannot
   yet measure the reclassification case, only the entry-order case". Note the existing `config.py`
   caveat: the cap value was chosen on the same 2020-2026 sample that measured it.
2. **Comparison**: current `select_tranche_names` vs the capped keep loop, same engine driver, same
   panel. Report separately for the two mechanisms — (a) a holding reclassified into a full sector,
   (b) loop-1 overfill with `dynamic_count` near its floor — because they have different fixes and
   different frequencies.
3. **Paired statistic**: paired per-renewal difference in tranche return → `d_ann_net_pp`,
   `d_sharpe`, `d_maxDD`, with bootstrap p05/p95. Plus the frequency table that decides whether the
   cap is a risk control or cosmetic — Astra's actual question:
   - share of renewals where the current code held more than `MAX_PER_SECTOR` in one sector, and the
     max observed count;
   - share of renewals where the patch forces a sale purely on the cap (the turnover cost), and
     that turnover in bp/cycle for comparison against the −2.8 bp/cycle already measured for the
     cap itself (`config.py:177`);
   - share of renewals where `len(picked) < n` after the patch (the unfilled-slot case) and the
     per-name weight it implies;
   - the realised `max share of one sector in a tranche` distribution — current vs patched. This is
     the number that answers "¿qué concentración real ha habido?" and it is currently unanswered.
4. **Kill criterion.** Reject the patch if the forced-sale turnover exceeds **10 bp/cycle** with no
   improvement in `maxDD` (the cap would then be paying more than the concentration it prevents),
   or if `d_sharpe ≤ −0.05` with p95 below 0 on DEV. Accept it if the frequency table shows the cap
   was breached on more than **5%** of renewals and `d_maxDD` improves at return-parity
   (`|d_ann_net_pp| < 0.5 pp`). If the breach frequency is **0%** on the panel, close H-006 as
   WITHDRAWN and keep only the acceptance test and the doc corrections — the cap would be proven
   cosmetic, which is itself a publishable answer to Astra's question.

**Missing in a worktree**: items 1-3, and specifically the point-in-time GICS map. Reported, not
estimated.

---

## Cross-cutting notes

- **All three defects live in `core/`, which `ruff.toml` exempts from every lint rule** because the
  live path is frozen (`ruff.toml:24-26`). Nothing here was caught by lint and nothing would be.
- **The earlier test that hid ASTRA-01** fabricated `n = 0` instead of letting the real ranking
  produce `recommended = 0, dynamic_count = 22`. The lesson for the whole suite: a fixture that
  hand-builds the *output* of the stage under test can only confirm the stage's arithmetic. Both
  new fixtures here run `generate_daily_candidates` end to end for that reason.
- **`write_offs[].step` is always 0** in production state (`_book()` rebuilds the book every call,
  `core/portfolio_engine.py:56`). Not one of Astra's findings; worth a one-line fix whenever
  H-005 is decided, because it is the field you would sort write-offs by.
- **Freeze.** Nothing on this branch may merge before the first settle after the 2026-09-08 close is
  verified. It conflicts with any branch that edits `core/portfolio_engine.py`,
  `core/tranche_book.py` or `.comms/hypotheses.md` — in particular the `post-freeze-wiring` branch
  carrying TASK-363 (splits, H-003), which adds rows to the same register table.
