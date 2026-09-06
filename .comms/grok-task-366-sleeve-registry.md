# TASK-366 — Sleeve protocol + registry (engine untouched)

Live path not edited. `core/portfolio_engine.py`, `core/tranche_book.py`,
`core/signals.py`, `etf_trend.target_weights` unchanged. No new sleeve proposed
(MR stays dead).

## What landed

- `sleeves/base.py` — `MarketSlice` (stock_prices, volumes, spy, etf_closes, tbill, ranking)
  and `Sleeve` protocol: `name`, `cost_bp`, `targets(market, held, cfg) -> Series` with
  sum <= 1. `tbill` is the daily rate (ann / 252), same series `etf_targets` already takes.
- `sleeves/stocks_t20.py` — `StocksT20` adapter, delegates to `stock_targets`.
- `sleeves/etf_trend.py` — additive `EtfTrend` class, delegates to `etf_targets`.
  `eligible` / `tsmom_signal` / `target_weights` not changed.
- `sleeves/registry.py` — `build(cfg) -> {name: Sleeve}` from `cfg.get("sleeves", ["stocks", "etf"])`.
  Unknown name -> `KeyError` listing the known ones (`stocks`, `etf`).
- `docs/design/multi-sleeve-engine.md` — how `plan`/`settle`/`mark` would iterate N sleeves
  with a mix vector; bundle reset (`target[s] = mix[s] * V_bundle`, legs net to zero, the
  TASK-347 invariant); state (`mix` moves into state, sleeve keys already by name);
  migration (fill mix 50/50, no schema bump here); parity test plan against the current
  two-sleeve engine; eight open questions for Claude. Design only.

Nothing calls `build()` from `plan()`. Default path is unchanged.

## Tests (`test_sleeve_registry.py`, synthetic, no network)

7 passed: stock adapter == `stock_targets` (atol 1e-12, sum <= 1); zero recommended ->
empty on both; ETF adapter == `etf_targets` and the existing `target_weights`; all-ETFs-off
(T-bill 100% ann) -> empty on both; `build(V9)` is `{stocks, etf}` with V9 cost_bp;
unknown `'mr'` raises with the known list; cost_bp override.

`test_portfolio_engine.py` still 13 passed (existing functions + engine cases).

Suite: **36 passed, 2 skipped, exit 0**.

## Left for the hook-up (after the freeze + Claude's review of the design)

- `plan`/`settle`/`mark` iterate `registry.build(cfg)` instead of `SLEEVES = ("stocks", "etf")`.
- Default cfg (two names, mix 50/50) must pass the parity table in the design note
  (orders / transfers-sum-to-zero / state after settle, atol 1e-12) against today's engine.
- Schema: store `mix` on the state; bump is Claude's call.
