# Multi-sleeve engine — design (TASK-366)

Status: **design only**. The production engine (`core/portfolio_engine.py`) is not edited.
No new sleeve is proposed (the mean-reversion sleeve was killed at pre-registration; Sharpe 0.21 DEV).
This note is the seam: how `plan` / `settle` / `mark` would iterate a registry of N sleeves with a
mix vector, once Claude reviews it and the live-path freeze lifts.

Adapters and the registry exist today (`sleeves/base.py`, `sleeves/registry.py`, `sleeves/stocks_t20.py`,
`sleeves/etf_trend.py::EtfTrend`) and are proven equal to the engine's `stock_targets` / `etf_targets`
on synthetic frames (`test_sleeve_registry.py`, atol 1e-12). Wiring them into the engine is a later
commit, behind a default that is byte-identical to the two-sleeve book.

## 1. What the engine does today

Hardcoded:

```
SLEEVES = ("stocks", "etf")
```

- `new_state` splits `capital` 50/50, then `/ tranches` into each sleeve's cash.
- `plan` on a renewal bar `k` (week mod 4) calls `stock_targets(ranking, held, stock_prices, cfg)` and
  `etf_targets(etf_closes, tb_daily, cfg)`, then sizes each renewed tranche to **half the pair's own
  value** (`tranche_target = (own_stocks_k + own_etf_k) / 2`).
- Transfers: `transfer_s = tranche_target - own_s`. The two legs are equal and opposite, so they
  net to zero. This is the TASK-347 fix: sizing each leg to `1/8` of the **whole book** created or
  destroyed cash whenever the pair was not worth `1/4` of the book (in-sample leak ≈ −0.9 pp/yr,
  corr(leak, net transfer) = 1.000).
- `settle` walks `("sell", "transfer_in", "transfer_out", "buy")` over the pending list, looking up
  a book and a price series by the hardcoded sleeve name.
- `mark` / `accrue_interest` loop `for sleeve in SLEEVES` with a matching price series and `cost_bp`.

`cfg["mix"]` is already `{"stocks": 0.5, "etf": 0.5}` but the engine does not read it; the 50/50 is
in the `/ 2.0`. Sleeve keys in state are already names, not positions.

## 2. The seam that landed in this task

```
MarketSlice(stock_prices, volumes, spy, etf_closes, tbill, ranking)
Sleeve.targets(market, held, cfg) -> pd.Series   # weights, sum <= 1
registry.build(cfg) -> {name: Sleeve}            # cfg["sleeves"] default ["stocks", "etf"]
```

`tbill` on the slice is the daily rate (annualised / 252), matching `etf_targets` today.
Unknown names raise `KeyError` listing the known ones. Adding a third sleeve later is a new
adapter class plus one line in `KNOWN` — not a fork of `plan()`.

## 3. How `plan()` would iterate N sleeves

Inputs stay the same plus the registry and a mix vector that sums to 1:

```
sleeves = registry.build(cfg)                  # insertion order = cfg["sleeves"]
mix = state["mix"]                             # e.g. {stocks: 0.5, etf: 0.5}
assert abs(sum(mix.values()) - 1.0) < 1e-12
```

On a non-renewal bar: mark, accrue, return `[]` (unchanged).

On renewal of slot `k`:

1. Mark every sleeve (see §5).
2. Build one `MarketSlice` from the frames already in hand.
3. **Bundle reset** (generalised TASK-347 rule — see §4).
4. For each `name, sleeve` in `sleeves.items()`:
   - `held = set(state["sleeves"][name]["tranches"][k]["units"])`
   - `targets = sleeve.targets(market, held, cfg)`  # empty -> park in T-bill
   - `own = value of tranche k`
   - `tranche_target = mix[name] * bundle_value`
   - `transfer = tranche_target - own`
   - sells / buys against `targets * tranche_target`, same dollar/unit rules as today
     (close=True when a name leaves; hold_no_price when there is no print)
   - emit `transfer_in` / `transfer_out` when `|transfer| > 1e-9`
   - emit `park` when `len(targets) == 0`
5. Stamp `cost_bp = sleeve.cost_bp` on each order (today this is a stocks-vs-etf ternary).

Default `cfg` with two sleeves and `mix = {stocks: 0.5, etf: 0.5}` is the current `plan()`.

## 4. Pair reset generalised to N

Let `k` be the renewed tranche index. Let `own[s]` be the marked value of sleeve `s`'s tranche `k`.
The **bundle** is those N tranches:

```
V = sum_s own[s]
target[s] = mix[s] * V
transfer[s] = target[s] - own[s]
```

Then `sum_s transfer[s] = V - V = 0`. The legs net to zero for any N and any mix that sums to 1.
That is the TASK-347 invariant, with `1/2` replaced by `mix[s]`.

**Do not** size a renewed tranche to `mix[s] / K` of the whole book. That is the pre-fix rule
that leaked: it only conserves cash when the bundle happens to be worth `1/K` of the book, which
stops being true as soon as any sleeve has drifted. The leak was exactly the net transfer; a
parity test of `sum(transfer legs signed) == 0` (atol 1e-9) would have caught it on week one.

Worked N=3, mix `(0.5, 0.3, 0.2)`, bundle worth 120: targets 60 / 36 / 24. If owns are 70 / 40 / 10,
transfers −10 / −4 / +14, sum 0.

Settlement order today is `transfer_in` then `transfer_out` so a sleeve that must pay can receive
first. With N>2 a sleeve may need to pay more than it currently holds in cash (units not yet sold
if we transferred before sells). **Keep today's order: sells, then all `transfer_in`, then all
`transfer_out`, then buys.** Sells free cash before any sleeve pays; the ins land before the outs,
so a two-or-more-way rotate still funds. Open question if a sleeve is all-units and the sale
does not print (`hold_no_price`): it cannot fund its out — same hole as today, just more names.

## 5. `settle()` and `mark()`

`settle` already keys books and prices by sleeve name. The N-sleeve version builds those dicts
from the registry instead of the two-tuple:

```
books = {name: _book(state, name, sleeve.cost_bp, cfg) for name, sleeve in sleeves.items()}
px    = {name: price_row_for(name, market)            for name in sleeves}
```

`price_row_for` is the one new mapping: stocks <- last stock row, etf <- last ETF row, a future
sleeve declares which frame it marks against (open question). Phases stay
`sell / transfer_in / transfer_out / buy`. `park` / `hold_no_price` stay no-ops in settle
(recorded, not dropped — TASK-341).

`mark` and `accrue_interest` loop `sleeves.items()` the same way. Write-offs and interest records
already carry a `sleeve` field.

## 6. State schema

Today (`schema_version = 1`):

```
sleeves: {stocks: {tranches: [...]}, etf: {tranches: [...]}}
mix:     not stored (lives in config.V9, unused by the engine)
```

Proposed (additive keys; bump is Claude's call, same rule as TASK-360):

```
sleeves: { <name>: {tranches: [...]} }   # already by name; N keys instead of 2
mix:     { <name>: float }               # copies cfg["mix"] at new_state; sums to 1
```

`new_state(capital, anchor, cfg)`:

```
sleeves = registry.build(cfg)
mix     = cfg.get("mix") or {n: 1.0/len(sleeves) for n in sleeves}
for name, sleeve in sleeves.items():
    cash_each = capital * mix[name] / cfg["tranches"]
    state["sleeves"][name] = {tranches: [{k, cash: cash_each, units: {}, ...} for k in range(K)]}
state["mix"] = mix
```

Two-sleeve default: `cash_each = capital * 0.5 / 4` — today's `half / k`.

Pending orders, ledger, transfers, interest, dividends already carry `sleeve` as a string.
No rename.

## 7. Migration

TASK-360's first migration only fills missing keys and leaves `schema_version` at 1. Same pattern:

- If `mix` is absent, set `{"stocks": 0.5, "etf": 0.5}` (today's implicit mix). Do not infer from
  current sleeve values — drift is real, the target mix is the policy.
- If a cfg-enabled sleeve name is missing from `state["sleeves"]`, that is a new sleeve: Claude
  decides whether `new_state`-style empty tranches are allowed mid-book or whether it waits for
  a version bump. Not this task.
- Removing a sleeve from cfg while it still holds units is a close-out, not a migration.

A schema bump is Claude's call. This note does not bump.

## 8. Parity test plan (against today's two-sleeve engine)

Once the engine is allowed to take a registry, the default path must be byte-identical to now.

Fixtures: every case in `test_portfolio_engine.py` that calls `plan` / `settle` / `mark`
(`test_reference_case_book_is_flat_and_reset_is_recorded`, zero-recommended park, veto/buffer,
idempotence, `test_reset_transfer_moves_cash_from_the_richer_sleeve`,
`test_reset_legs_offset_and_the_book_is_conserved_when_tranches_have_drifted`, fill/not_filled).

Method: run the **current** engine (no registry) and the **registry** engine with
`cfg = {**V9, "sleeves": ["stocks", "etf"], "mix": {"stocks": 0.5, "etf": 0.5}}` on the same
inputs. Assert:

| object | tolerance |
|---|---|
| order list (sleeve, tranche, ticker, side, dollars, est_units, close) | atol 1e-12 on floats, exact otherwise |
| signed transfer legs, sum | == 0, atol 1e-9 (the TASK-347 invariant) |
| `state["sleeves"]` after settle (cash, units) | atol 1e-12 |
| `summary_table` totals | atol 1e-12 |

Lab parity already in `test_parity_stock_targets_with_redesign_lab` /
`test_parity_etf_targets_with_sleeve_lab` stays; it talks to `stock_targets` / `target_weights`
directly. The adapters wrap those, so they inherit it.

A second, later test (not a default-path test): three synthetic sleeves with mix `(0.5, 0.3, 0.2)`
and the bundle-reset numbers in §4, asserting `sum(transfers) == 0`. That test needs a third
adapter; it is not a reason to invent a sleeve.

## 9. Open questions for Claude

1. **Price map.** Stocks mark on the stock row, ETF on the ETF row. A third sleeve that is neither
   (cash-only, futures) needs a declared mark series. Put it on the Sleeve protocol
   (`mark_frame: "stocks" | "etf" | "own"`) or keep a cfg table?
2. **Independent calendars.** Today every sleeve renews the same `k` each week. N sleeves with
   different `step_bars` would desynchronise the bundle and the reset would need a different
   definition (reset the subset that renews that day, or reset the whole book weekly). Recommend
   keeping one calendar until a hypothesis says otherwise.
3. **mix = 0.** A sleeve in the registry with weight 0: still allocate empty tranches (so it can
   be turned on later without a schema bump) or omit it from state?
4. **Mid-book mix change.** If Lucas changes mix from 50/50 to 60/40, does the next bundle reset
   walk there one tranche a week (current policy, ~4 weeks) or is that an H-00x with a TEST read?
5. **T-bill cash.** Per-sleeve idle cash (today) vs a book-level cash sleeve. Attribution (TASK-367)
   is simpler if cash stays per sleeve; a dedicated cash sleeve would be a real third sleeve and
   needs a hypothesis.
6. **`held` for non-stock sleeves.** The protocol passes it; ETF ignores it (no buffer). Keep the
   argument always so a future sleeve can use it, or make it optional?
7. **Settlement when a transfer_out cannot be funded** because the only holdings are `hold_no_price`.
   Today the cash goes negative until the next print (cash >= -1e-6 is the TASK-360 check). Same
   policy for N, or refuse the plan?
8. **Registry location.** `cfg["sleeves"]` as a name list (this task) vs a list of `{name, mix, cost_bp}`
   objects. The list-of-names plus `cfg["mix"]` matches V9 today. A structured list would let two
   instances of the same class run with different cost_bp; not needed until a second book (TASK-365).

## 10. What this task explicitly does not do

- Edit `core/portfolio_engine.py`, `core/tranche_book.py`, `core/signals.py`, `core/meta_layer.py`.
- Change `etf_trend.target_weights` / `eligible` / `tsmom_signal`.
- Propose a third sleeve or revive mean-reversion.
- Flip any production flag. `registry.build(V9)` returns the two adapters; nothing calls it from
  `plan()` yet.
