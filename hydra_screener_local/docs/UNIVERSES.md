# Universes: what each one actually is

Generated from `data/universe_registry.py`, which is the source of truth. Audit
phase 7.

## The headline

**`russell1000` and `russell2000` are not the FTSE Russell indices.** Their primary
source is a NASDAQ market-capitalisation ranking — top 1000 by cap, and ranks
1001-3000. Slickcharts and Barchart are secondary attempts and are real membership
sources, but the cap ranking is what usually answers.

Real Russell membership comes from an annual reconstitution with float adjustment,
eligibility screens and banding rules. A cap ranking reproduces none of that, so the
edges of the list differ from the real index by construction. Before this audit the
code called the result "Russell 1000" in docstrings, in console output, and in a
comment asserting the method was "igual que la metodología FTSE Russell". It is not.

`all` — the production universe (`config.UNIVERSE = "all"`) — is the union of three
published index lists and those two proxies, so **`all` is a proxy universe too**.

## The four kinds (phase 7.5)

| kind | meaning | who has it |
|---|---|---|
| `pit` | membership as it stood on a past date, from an immutable snapshot | `data/pit.py` snapshots |
| `current` | membership as it stands today, from the index publisher | sp500, nasdaq100, dow30 |
| `proxy` | a reconstruction standing in for an index we cannot get | russell1000, russell2000, russell3000, **all** |
| `fallback` | a hardcoded list used when every source failed | custom, and the built-in backup lists |

A run records which kind it used and whether a fallback was hit
(`utils/runlog.py` -> `ctx.inputs()`, and `data.pit.inputs_manifest()["fallback_used"]`).

## The registry

Each entry carries source, definition, membership method, exclusions, the biases that
apply, and its caveats. `data.universe_registry.universe_report()` adds the effective
date, the name count, the coverage ratio and a **sha256 of the sorted membership**, so
a recommendation can be tied to the exact list it came from (phase 7.2).

```python
from data.universe_registry import universe_report, format_report
print(format_report(universe_report("all", tickers, date="2026-09-06")))
```

## Exclusions (phase 7.4)

`exclude_non_common()` drops, by symbol shape: warrants (`.WS`, `-WT`), units (`.U`,
`-UN`), rights (`.R`, `-RT`), preferreds (`-P`, `.PR`), when-issued lines (`.WI`), and
anything that is not a US common-stock symbol shape. Share classes (`BRK-B`, `BF.B`)
are common stock and stay.

**Measured effect on production: none.** Against the live `all` universe on 2026-09-06
(3002 names) it removes **zero** names, because the sources already return common
stock only. It is a guard against a warrant entering unnoticed, not a change to what
the screener sees today.

`duplicate_share_classes()` reports one real finding: the live universe contains
**`BRK-A`, `BRK-B` and `BRK.B`**. The last two are the same security under two
spellings (Yahoo uses `-`, the Wikipedia tables use `.`) — one company counted twice
and two price series for one position.

## Bias (phase 7.6)

Every number computed on a universe carries that universe's biases, and they travel
with the registry entry rather than living in someone's memory:

- **survivorship** — a current-membership list contains only the names that survived
  to today. Backtesting on it flatters momentum: the delisted and acquired names that
  momentum would have bought are absent.
- **look-ahead** — using today's membership for a past date lets the test hold names
  that were not in the index then, and index additions are themselves a momentum
  signal.
- **proxy** — membership is a cap ranking, not the index's own reconstitution.
- point-in-time membership carries neither survivorship nor look-ahead bias. Price
  *coverage* is a separate question: the OOS panel (2004-2026) has real membership but
  only **53% price coverage in 2005**, so an absolute level from it is never quoted
  without that caveat.

## The 10% net target (phase 7.7)

**Not demonstrated, and nothing in this branch attempts to demonstrate it.**

The verdict recorded in `.comms/claude-redesign-verdict-2026-09-06.md` stands: 10%
net was not reached. Production is v9 (50/50 T20 stocks + ETF trend) on its own
merits, not because a target was hit.

Presenting 10% net as achieved would require an out-of-sample test with frozen
inputs — a panel, sector map, config and code hash recorded before the test, and a
baseline bound to them (`core/baseline.py`). The in-sample harness cannot do it: it
is current S&P 500 constituents over 2020-2026, which is survivorship-biased in
exactly the direction that flatters momentum.
