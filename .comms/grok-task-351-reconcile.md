# TASK-351 — reconcile.py: broker vs state, read-only

`python reconcile.py positions.csv --cash-total 50000`
`--cash-stocks` / `--cash-etf` if two accounts. `--state` defaults to
`state/portfolio_v9.json`. Exit 0 always; writes nothing.

## Output

- Positions: state units aggregated across sleeves/tranches vs broker
  `ticker,units`. Rows tagged `match` / `missing` (state only) /
  `unknown` (broker only) / `quantity-diff`. Valued at the state's `last_px`.
- Cash: broker vs state (total, or split by sleeve). Residual = broker − state
  (raw). Known explanations are **listed, not subtracted**: interest recorded,
  dividends recorded (0 until 349; note that the broker pays on pay-date),
  fees on the ledger, pending buy/sell dollars.
- Equity at state last prices for both sides.

## Tests

Match, missing/unknown/qty-diff, split cash, dividends key absent → 0,
CLI exit 0 on missing state, CLI writes nothing.
