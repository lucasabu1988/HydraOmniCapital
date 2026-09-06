# TASK-353 — whole shares on the instruction sheet

Display-only. Engine orders and presumed fills stay in dollars / fractional
`est_units`. `confirm_fills` is still where whole units enter the book.

New columns on the markdown table:

- `shares = floor(dollars / est_price)`
- `$ at est` = shares × est_price
- `leftover` = dollars − $ at est

Buys are also summed leftover per (sleeve, tranche) so Lucas sees the cash
that stays unspent if he rounds down. Transfers / park / hold_no_price have
no share columns.

`whole_share_display()` is pure and tested. JSON payload still has the original
fractional orders.
