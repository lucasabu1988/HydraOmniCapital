# TASK-389 — the duplicate share class, measured

**Done by Claude (Grok unavailable), 2026-09-06.** Script: `experiments/duplicate_classes.py`
(`--probe` for the provider check, `--oos` for T20 frequency, `--insample-ab` for the A/B).
Nothing in the live path was changed; this is the measurement the fix needs first.

## 1. The duplicate is real, and harmless today

One group in the live union, and only in the union:

```
union ('all')  n=3002  duplicate groups=1
  BRK-B: ['BRK-B', 'BRK.B']   from ['russell1000', 'sp500']
```

`BRK-B` comes from the Russell 1000 source (Yahoo spelling), `BRK.B` from the S&P 500 source
(Wikipedia spelling). No individual source contains a duplicate; the union creates it.

It has never double-counted anything, because **Yahoo does not resolve `BRK.B`**:

```
BF-B    bars= 23 avg_volume=1,993,278
BF.B    bars=  0 avg_volume=-
BRK-B   bars= 23 avg_volume=4,186,226
BRK.B   bars=  0 avg_volume=-
```

`BRK-A` resolves but averages **161 shares a day** — it fails `FILTERS.min_avg_volume` (100,000)
every day, so the "three Berkshires" never competed for a slot.

## 2. The spelling is the defect, not the duplicate

`BF.B` (Brown-Forman B) is dot-spelled **and has no dash twin in the union**. Nothing rescues it,
Yahoo will not serve it, and so **Brown-Forman cannot be scored by the live screener at all**.
Berkshire is only scoreable by luck: the Russell 1000 source happens to spell it `BRK-B`.

The same two names sit in the in-sample measurement panel as **all-NaN columns**:

```
in-sample (S&P 500, 2020-26): 503 columns, 2 all-NaN, 2 dot-spelled ['BF.B', 'BRK.B']
    BF.B   present, 0 bars   <- never eligible
    BRK.B  present, 0 bars   <- never eligible
OOS PIT (2004-26): 1209 columns, 429 all-NaN, 0 dot-spelled
    BF-B   present, 5705 bars
    BRK-B  present, 5705 bars
```

The OOS panel is clean: it goes through `data/universe.py::_yahoo_ticker`, which already
normalises the dot. The in-sample panel and the live universe do not.

## 3. What it costs — measured, not assumed

**OOS panel (2004-26, both names eligible), 1084 selection dates:**

```
BF-B   ranked on 1084 dates, recommended on   50 (4.6% of dates)
BRK-B  ranked on  832 dates, recommended on   17 (1.6% of dates)
dates where both were recommended together: 2
```

Those two dates are not a duplicate problem — they are two different companies.

**In-sample A/B** (pinned cache copied, dead columns filled from the spellings Yahoo resolves; the
pinned cache is never written to):

| panel | ann_net | sharpe | maxDD | cycles |
|---|---|---|---|---|
| as-is (2 dead columns) | 12.18 | 1.32 | -9.0 | 278 |
| filled | **12.24** | **1.33** | **-8.9** | 278 |

With the fill, `BRK-B` is ranked on all 279 selection dates and **recommended on 11**; `BF-B` is
ranked on all 279 and recommended on **0** — Brown-Forman never earns a T20 slot in 2020-26, so
the whole in-sample effect comes from Berkshire. Small, positive, and now known.

### The first run of this A/B was a no-op, and the script now refuses to repeat it

The first pass printed *identical* headlines. That looked like a clean answer and was not one:
`backtest_variant_sweep` is importable under two module names (with and without the
`experiments.` prefix), so `import backtest_variant_sweep as bvs; bvs.CACHE = tmp` set the cache
on a **different module object** than the one `redesign_lab` holds. The lab loaded the original
panel both times and the A/B compared a panel with itself.

What caught it was the ranking count added for exactly this reason: the filled panel reported
`BF.B ranked on 0/279 dates`, which is impossible for a column with 1678 bars. The script now
takes `L.bvs` (the module the lab actually uses) and asserts the fill reached the panel before it
runs anything. Any future lab script that patches `bvs.CACHE` has the same trap waiting.

## Recommendation (needs Lucas's call — it changes the recommended list)

Normalise at the universe-build boundary, where `_yahoo_ticker` already exists, and dedupe the
union afterwards. Consequences, all measured above:

1. `BRK.B` disappears from the universe — one wasted download per run, and one fewer entry in the
   "failed download" noise that hides real failures.
2. **`BF-B` becomes eligible for the first time.** That is a membership change: not scoring
   (CLAUDE.md rule 2), but it does change what can be recommended, so it is Lucas's call, not
   mine. Evidence for the size of it: never selected in 2020-26 in-sample, 4.6% of dates on the
   2004-26 OOS panel.
3. The in-sample pinned cache would have to be re-pinned to include the two names (headline
   12.18 → 12.24). Under TASK-387's rule that is a deliberate re-pin with the number recorded,
   never a silent rebuild.

Not recommended: deduping by dropping one spelling *after* the fetch. The dot spelling has no
data, so the dedupe would be cosmetic while Brown-Forman stayed invisible.
