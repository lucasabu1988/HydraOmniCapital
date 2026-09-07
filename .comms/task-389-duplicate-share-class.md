# TASK-389 — The duplicate share class, measured before anyone dedupes it

Claude, 2026-09-07. Branch `docs/task-389-duplicate-share-class` (base `origin/main` @ `965d22c`).
**Measurement only.** Nothing in `core/`, `config.py`, `data/` or the live path is touched: a dedupe
changes the universe and therefore the recommended list, which is rule 6 and Lucas's call. The
recommendation in section 6 is a recommendation, not a change.

**Headline.** The duplicate is real (90 issuer groups, 218 of 3002 tickers, 19 groups with two or
more spellings eligible today) and it is **worth nothing today**: the best-ranked duplicate spelling
sits at rank **#370 of 2420** while the list is the top **22**. Running the real pipeline with the
dedupe applied gives a T22 selection **identical, name for name and in order**, to the un-deduped
run. The eligible universe moves 2525 -> 2504 (-21, -0.83%) and the sector cap displaces the same 13
names either way. So this is a latent defect with a measured cost of zero on 2026-09-04 — fix it for
correctness, not for return, and do not expect the numbers to move.

---

## 0. Inputs — exactly what was read, so this can be reproduced

Everything below comes from the production tree, opened read-only (sqlite via
`file:...?mode=ro` with `uri=True`). No file under
`C:\Users\caslu\HydraOmniCapital\hydra_screener_local\` was written and no CLI was run.

| file | bytes | mtime | what it gave |
|---|---|---|---|
| `data_cache/pit/universe_all_20260905.json` | 37,719 | 2026-09-06 00:08 | the live `all` universe: 3002 tickers, `source: union:sp500+nasdaq100+dow30+russell1000+russell2000`, `fetched_at 2026-09-06T00:08:16` |
| `data_cache/universe_cache_sp500.json` | 6,232 | 2026-09-05 12:10 | 503 tickers, source Slickcharts |
| `data_cache/universe_cache_nasdaq100.json` | 1,392 | 2026-09-05 17:40 | 102 tickers, source Slickcharts |
| `data_cache/universe_cache_dow30.json` | 454 | 2026-09-05 17:40 | 30 tickers, source Slickcharts |
| `data_cache/universe_cache_russell1000.json` | 12,405 | 2026-09-06 08:31 | 1000 tickers, source "NASDAQ marketcap top-1000" |
| `data_cache/universe_cache_russell2000.json` | 25,343 | 2026-09-06 08:31 | 2000 tickers, source "NASDAQ marketcap 1001-3000" |
| `data_cache/bars.sqlite` | 1,724,514,304 | 2026-09-06 10:10 | `meta` = 3011 tickers; last bar 2026-09-04 |
| `data_cache/sector_cache.json` | 86,730 | 2026-09-06 08:11 | 2903 of the 3002 carry a sector string |
| `data_cache/sp500_pit.json` | 12,161,538 | 2026-09-05 15:25 | 2718 S&P snapshots, 1996-01-02 .. 2026-06-30 |
| `state/instructions_20260904.json` / `.md` | 18,585 / 2,205 | 2026-09-05 23:05 | the live sheet: 22 stock + 8 ETF orders pending the 2026-09-08 close |
| `state/discarded_firstrun_20260904/instructions_20260904.md` | 2,207 | 2026-09-05 20:19 | the discarded first run, 22 stock names |
| `archive/paper-trading-2026-02-19_2026-04-02/state/compass_state_latest.json` | — | (archived) | legacy COMPASS book — checked for a held duplicate |

The union of the five index caches is **set-identical** to the PIT `all` snapshot (3002 = 3002), so
the snapshot is a faithful record of what the live run saw.

Issuer identity was resolved with `yfinance.Ticker(t).get_info()` (`longName` / `shortName`,
`quoteType`, `exchange`) for **all 3002** tickers on 2026-09-07 — the repo holds no name map, so this
is the only issuer source available. 2998 of 3002 resolved. The four that did not:
`BF.B` (`quoteType: MUTUALFUND`, exchange `YHD`), `BRK.B` (name `None`, exchange `None`), and two
genuine new listings Yahoo has no name for, `ASBA` and `DCBG`.

**Pipeline replication (this is what makes the section-3/5 numbers trustworthy).** The scoring path
was run offline against `bars.sqlite`: `close_adj` and `volume` for the 3000 post-blacklist tickers,
last 505 bars (`V9["price_period"] = "2y"`), the same `apply_practical_filters` /
`apply_data_quality_filter` / `remove_zombie_tickers`, the sector map from `sector_cache.json`, then
the real `core.signals.generate_daily_candidates(..., momentum_window=V9["stock_momentum_window"])`
and the real `core.portfolio_engine.select_tranche_names`. Result:

```
offline select_tranche_names: ['SLAB','DBRG','ANRO','WBD','GSAT','SNDK','AES','IBRX','IMMX','BLTE',
                               'MAZE','LITE','ZIM','EFXT','AG','OUT','PUMP','CENX','ENLT','USAS',
                               'SII','GOLD']
live sheet 2026-09-04       : ['SLAB','DBRG','ANRO','WBD','GSAT','SNDK','AES','IBRX','IMMX','BLTE',
                               'MAZE','LITE','ZIM','EFXT','AG','OUT','PUMP','CENX','ENLT','USAS',
                               'SII','GOLD']
identical: True
```

Byte-identical, in order, to the sheet holding the 30 pending orders. Every ranking number below is
from that run. (Running the same code with the *screener's* default `period="1y"` and the 90-day
momentum window gives a completely different list — the v9 sheet comes from
`portfolio_v9.build_ranking`, not from `screener.main`. Worth knowing before anyone else tries to
reproduce a v9 list.)

---

## 1. Every duplicate or ambiguous pair actually in the live `all` universe

### 1a. Separator collisions — the same security under two spellings: exactly **one**

Non-alphanumeric tickers, per index cache:

| index | n | tickers that are not `[A-Z0-9]+` |
|---|---|---|
| sp500 (Slickcharts) | 503 | `BF.B`, `BRK.B` |
| nasdaq100 (Slickcharts) | 102 | — |
| dow30 (Slickcharts) | 30 | — |
| russell1000 (NASDAQ) | 1000 | `BRK-A`, `BRK-B` |
| russell2000 (NASDAQ) | 2000 | — |

Normalising by stripping `[-./]` and looking for collisions across the whole 3002-name union yields
**one** group:

| normalised | spellings | comes from |
|---|---|---|
| `BRKB` | `BRK-B`, `BRK.B` | `BRK-B` from russell1000, `BRK.B` from sp500 |

That is the item the September audit reported (D4) and did not fix, confirmed at full scale. The
audit predicted more (`PBR.A`, `LEN.B`, `UHAL.B`, `HEI.A` …); the measured answer is that **today
none of those dot-spellings is in the universe** — Slickcharts' S&P 500 page carries only two
dot-tickers, and the NASDAQ-screener Russell feeds carry dashes. So D4's blast radius on
2026-09-06 is two tickers, not a class of them. It is bounded by the sources' current formatting,
not by any code.

**`BF.B` is the more damaging half, and it is not a duplicate at all — it is a deletion.**
`BF-B` is *not* in the universe (checked: no `BF`, no `BF-B`, no `BF.B` alternative). `BF.B` is
blacklisted, so Brown-Forman — an S&P 500 constituent — is **absent from the entire 3002-name
universe and from every ranking**. `BRK.B` is harmless by luck: the Russell feed supplies `BRK-B`
independently. Nobody chose that asymmetry; the sources did.

### 1b. Same-issuer groups: **90 groups, 218 of 3002 tickers (7.3%)**

Grouping the 2998 resolved names by identical Yahoo `longName` gives **83 groups / 200 tickers**.
One of those is a false positive of the name test and is excluded: `FBP` = "First BanCorp." (PR) vs
`FBNC` = "First Bancorp" (NC) — different companies that collide once the trailing period is
stripped. Added to that are 14 groups the name test cannot see because the name carries the
instrument or the paired entity; each was verified one at a time against `longName`, `quoteType`
and exchange. Consolidated: **90 groups, 218 tickers**.

The 19 groups where **more than one spelling passes `config.FILTERS` today** (`min_avg_volume`
100,000 shares, `min_dollar_volume` $5M, `min_price` $5, plus the >100% trailing-252 jump filter),
measured on the 20-bar window ending 2026-09-04:

| issuer | spelling | last | vol20 (sh) | ADV$20 | sector (cache) | filters |
|---|---|---|---|---|---|---|
| Alphabet Inc. | `GOOGL` | 338.46 | 22,245,200 | 7,633,830,546 | Communication Services | PASS |
| | `GOOG` | 335.31 | 15,149,400 | 5,156,719,566 | Communication Services | PASS |
| | `GOOGN` (Ser. B mand. conv. pref. dep. sh.) | 47.94 | 1,091,765 | 53,153,506 | *(lookup failed)* | PASS |
| | `GOOGM` (Ser. A mand. conv. pref. dep. sh.) | 48.22 | 1,075,275 | 52,667,109 | *(lookup failed)* | PASS |
| Fox Corporation | `FOXA` | 65.42 | 5,120,920 | 343,655,574 | Communication Services | PASS |
| | `FOX` | 58.42 | 981,650 | 58,669,702 | Communication Services | PASS |
| News Corporation | `NWSA` | 30.39 | 3,546,800 | 106,635,126 | Communication Services | PASS |
| | `NWS` | 33.90 | 1,121,420 | 38,120,989 | Communication Services | PASS |
| Zillow Group, Inc. | `Z` | 34.59 | 3,292,275 | 115,107,549 | Communication Services | PASS |
| | `ZG` | 35.32 | 947,020 | 33,749,491 | Communication Services | PASS |
| Under Armour, Inc. | `UAA` | 5.25 | 8,332,635 | 44,096,643 | Consumer Cyclical | PASS |
| | `UA` | 5.12 | 2,501,818 | 12,805,234 | Consumer Cyclical | PASS |
| Bel Fuse Inc. | `BELFB` | 243.79 | 152,375 | 40,152,439 | Technology | PASS |
| | `BELFA` | 202.42 | 144,310 | 31,856,703 | Technology | PASS |
| Central Garden & Pet | `CENTA` | 36.07 | 306,690 | 11,584,462 | Consumer Defensive | PASS |
| | `CENT` | 41.71 | 120,360 | 5,262,161 | Consumer Defensive | PASS |
| Formula One Group | `FWONK` | 95.50 | 1,823,640 | 185,792,139 | Communication Services | PASS |
| | `FWONA` | 88.38 | 119,170 | 11,137,808 | Communication Services | PASS |
| Liberty Live Holdings | `LLYVK` | 99.00 | 253,000 | 26,509,572 | Communication Services | PASS |
| | `LLYVA` | 95.62 | 135,000 | 13,707,352 | Communication Services | PASS |
| Liberty Global Ltd. | `LBTYA` | 10.62 | 2,058,340 | 21,706,419 | Communication Services | PASS |
| | `LBTYK` | 10.43 | 1,176,570 | 12,137,015 | Communication Services | PASS |
| Strategy Inc | `MSTR` | 142.80 | 27,782,120 | 3,315,751,890 | Technology | PASS |
| | `STRC` (preferred) | 97.75 | 1,461,290 | 140,180,848 | Technology | PASS |
| Super Micro Computer | `SMCI` | 39.59 | 54,843,980 | 2,030,022,397 | Technology | PASS |
| | `SMCIP` (preferred) | 66.68 | 602,180 | 38,035,916 | Technology | PASS |
| Microchip Technology | `MCHP` | 74.17 | 8,077,955 | 613,238,059 | Technology | PASS |
| | `MCHPP` (preferred) | 64.04 | 281,585 | 17,981,229 | Technology | PASS |
| The Southern Company | `SO` | 88.11 | 5,428,850 | 488,048,247 | Utilities | PASS |
| | `SOMN` (notes, first bar 2025-11-04) | 47.76 | 201,530 | 9,707,288 | Utilities | PASS |
| PPL Corporation | `PPL` | 35.11 | 8,060,135 | 282,687,266 | Utilities | PASS |
| | `PPLC` (first bar 2026-02-24) | 46.29 | 256,325 | 11,996,328 | Utilities | PASS |
| Strive, Inc. | `ASST` | 27.14 | 8,841,850 | 185,370,810 | Financial Services | PASS |
| | `SATA` | 100.01 | 315,550 | 31,410,571 | Financial Services | PASS |
| Brookfield Renewable | `BEPC` (Corporation) | 31.75 | 1,597,625 | 52,937,889 | Utilities | PASS |
| | `BEP` (Partners L.P.) | 31.41 | 783,420 | 25,504,000 | Utilities | PASS |
| Brookfield Infrastructure | `BIPC` (Corporation) | 37.35 | 1,030,515 | 39,603,315 | Utilities | PASS |
| | `BIP` (Partners L.P.) | 37.13 | 709,980 | 26,952,708 | Utilities | PASS |
| Sunoco | `SUNC` (SunocoCorp LLC, first bar 2025-11-06) | 79.55 | 461,085 | 35,405,041 | Energy | PASS |
| | `SUN` (Sunoco LP) | 75.60 | 417,630 | 31,391,718 | Energy | PASS |

40 eligible spellings across those 19 groups; a keep-one rule removes **21**.

The three "paired" groups (`BEP`/`BEPC`, `BIP`/`BIPC`, `SUN`/`SUNC`) are legally distinct issuers
whose units are exchangeable and whose price series track each other to within a few percent — the
same bet twice, even though a name test alone would not call them duplicates. They are listed
because the exposure question in section 4 does not care about legal form.

The remaining 71 groups are the same issuer with **only one eligible spelling** — overwhelmingly
common stock plus preferred / baby-bond lines that the ADV$ filter already stops. The largest:
`AGNC` + 6 preferred lines, `ADAM` + 4, `AFG` + 4, `HBAN` + 4, `BHF` + 3, `MBIN` + 3, `VLY` + 3,
`CMS` + 3, `ACGL` + 2, `LBTYB` (fails on 7,505 shares/day), `RUSHB`, `WLYB` (322 shares/day),
`SENEA`+`SENEB` (both fail), `BATRA`, `GLIBA`, `LILA`, `AQNB`, `DUKB`, `SFB`, `UNMA`, `STRD`,
`STRF`, `STRK`. Full machine-readable dump: the throwaway scripts in section 0 print it; nothing was
committed to the repo but this note.

**Control, to show the name test is not merging everything.** `PRU` "Prudential Financial, Inc." and
`PUK` "Prudential plc" — both eligible, both Financial Services, ranked #1995 and #951 — are **not**
one issuer and are not counted. Likewise excluded after checking the full names: `KO`/`CCEP`/`COKE`/`KOF`
(separate bottlers), `SAN`/`BSBR`/`BSAC` (parent + listed subsidiaries), `OWL`/`OBDC` (manager +
managed BDC), `CNS`/`RQI` (manager + closed-end fund), `LNG`/`CQP` (parent + subsidiary MLP),
`INDB`/`IBCP`, `NHC`/`NHP`, `FBP`/`FBNC`.

---

## 2. Which spellings have price history, and what the fetch layer does with the empty one

`bars.sqlite` `meta` holds 3011 tickers: the 3000 requested plus the 11 benchmark symbols
(`SPY IWM QQQ EFA EEM TLT IEF GLD DBC VNQ ^IRX`).

Of the 3002 universe members, **exactly two have no row in `meta` at all** and **zero have a `meta`
row with no bars**:

```
universe members with NO row in meta: 2 -> ['BF.B', 'BRK.B']
universe members present in meta but 0 bars: 0
```

Every other spelling of every duplicate group does have history, and the series are genuinely
different securities — `BRK-A` last close 759,350.00 on 165 shares/day vs `BRK-B` 506.03 on
4,226,795 (same 5031 bars, 2006-09-06 .. 2026-09-04, same `updated_at`), `SENEA` 195.71 vs `SENEB`
208.53 on 250 shares/day. No mis-mapping, no shared series.

### The empty one never reaches the fetch — the blacklist eats it first

`BF.B` and `BRK.B` do not "return nothing and get dropped". They are removed **before** the request,
by `config.DELISTED_OR_BAD_TICKERS`, in **both** fetch paths:

`hydra_screener_local/data/fetch.py:36-42` (the live path today, `USE_BAR_STORE = False`):

```python
    original_count = len(tickers)
    clean_tickers = [t for t in tickers if t not in DELISTED_OR_BAD_TICKERS]
    removed = original_count - len(clean_tickers)

    if removed > 0:
        bad_removed = [t for t in tickers if t in DELISTED_OR_BAD_TICKERS]
        print(f"   [DATA QUALITY] Filtrados {removed} tickers problemáticos/delisted: {bad_removed}")
```

`hydra_screener_local/data/fetch.py:417-420` (the bar-store path, TASK-361):

```python
    original_count = len(tickers)
    clean = [t for t in tickers if t not in DELISTED_OR_BAD_TICKERS]
    if original_count - len(clean):
        print(f"   [DATA QUALITY] Filtrados {original_count - len(clean)} tickers problemáticos/delisted")
```

and `config.py:269-276`:

```python
DELISTED_OR_BAD_TICKERS = {
    # "SNDK",    # Dejamos activo para que aparezca en el analisis general
    "BRK.B",     # A menudo falla o se confunde con BRK-B. Usar BRK-B en listas.
    "BF.B",      # Brown-Forman clase B - problemas de mapeo comunes.
    "FB",        # Viejo ticker de Meta, ahora META.
    "TWTR",      # Delisted 2022 (adquirida por X).
    "SCTY",      # SolarCity - delisted.
}
```

Measured effect: `universe=3002 -> after config blacklist=3000, removed=['BF.B','BRK.B']`.

**And the D1 guard cannot see it.** In both paths `requested` is computed *after* the blacklist
(`tickers = clean_tickers`, then `requested = len(tickers)`), so a blacklisted name is not counted
as missing and never contributes to `missing_share` — the very metric TASK-335 added so that names
could not "vanish with nothing but a print". Brown-Forman's disappearance is therefore invisible to
`FETCH_MISSING_WARN_SHARE`. That is a real observability hole, and it is the blacklist's design, not
a bug in the guard.

### Where an actually-empty series would be dropped, for the record

Since nothing empty reaches the fetch today, the code paths that would drop it are these. Legacy /
live yfinance path, `data/fetch.py:102`:

```python
    prices = pd.concat(all_prices, axis=1).dropna(axis=1, how='all')
```

Bar-store path, `data/fetch.py:449-456` — this one at least records the loss:

```python
            full = provider.fetch(missing, start, end)
            got = set()
            if full is not None and not getattr(full, "empty", True) and "ticker" in full.columns:
                store.upsert(full)
                got = set(full["ticker"].astype(str))
            for t in missing:
                if t not in got:
                    report["failed_tickers"].append(t)
                    report.setdefault("failed_reasons", {})[t] = "fetch_empty"
```

The audit's D4 sentence — "llega a yfinance en formato incorrecto, falla, y se pierde vía
`dropna(how='all')` — alimentando D1 en silencio" — is right about the mechanism and wrong about
which line does it today: the blacklist gets there first, and that is *quieter* than `dropna`,
because `dropna` at least leaves the name in `requested`.

### The normaliser that would fix this already exists and is not wired to the live path

`data/universe.py:1482-1484`:

```python
def _yahoo_ticker(sym: str) -> str:
    s = str(sym).strip().upper().replace(".", "-")
    return s
```

Every caller is in the point-in-time payload path (`data/universe.py` lines 1517, 1518, 1560, 1587,
1653, 1681). **No live universe fetcher calls it** — not `get_sp500_tickers`, not `get_universe`.
The consequence is measurable: across the 2718 S&P PIT snapshots (1996-01-02 .. 2026-06-30) there
are **zero** pure separator collisions, while the live union has one. The PIT path is clean because
it normalises; the live path is dirty because it does not.

---

## 3. Could any of these reach a recommended list today? And did one ever?

### 3a. Today: no, and not remotely

The filter funnel, from the replicated run (2026-09-04 bar):

| stage | names |
|---|---|
| `all` universe (PIT snapshot) | 3002 |
| after `config.DELISTED_OR_BAD_TICKERS` | 3000 |
| after `apply_practical_filters` (volume -276, dollar_volume -122, min_price -63) | 2539 |
| after `apply_data_quality_filter` (jump >100% in 252 bars, -14) | 2525 |
| after `remove_zombie_tickers` (-0) | 2525 |
| rows in the scored ranking (rest lack the bars `mom12_7` needs) | 2420 |
| `dynamic_count` (`clamp(round(14 x 1.166 x compass), 6, 28)`, regime 0.698) | **22** |
| flagged `recommended` after the sector cap and the downtrend gate | 15 |
| names actually selected by `select_tranche_names(ranking, 22, ...)` | 22 |

Where the 40 eligible duplicate spellings landed in that 2420-row ranking:

| issuer | ranks |
|---|---|
| Sunoco | `SUN` #370, `SUNC` dropped (208 bars < the 252 `mom12_7` needs) |
| Brookfield Infrastructure | `BIP` #381, `BIPC` #604 |
| Brookfield Renewable | `BEP` #498, `BEPC` #573 |
| Alphabet | `GOOGL` #520, `GOOG` #525, `GOOGM` / `GOOGN` dropped (66 bars) |
| Bel Fuse | `BELFA` #648, `BELFB` #802 |
| Under Armour | `UA` #778, `UAA` #789 |
| The Southern Company | `SO` #832, `SOMN` dropped (210 bars) |
| PPL | `PPL` #903, `PPLC` dropped (135 bars) |
| Strategy Inc | `STRC` #1072, `MSTR` #2307 |
| Liberty Global | `LBTYA` #1156, `LBTYK` #1298 |
| Microchip | `MCHP` #1343, `MCHPP` #1399 |
| Liberty Live | `LLYVA` #1401, `LLYVK` #1433 |
| Fox | `FOXA` #1413, `FOX` #1418 |
| Central Garden & Pet | `CENT` #1423, `CENTA` #1604 |
| Super Micro | `SMCI` #1716, `SMCIP` dropped (60 bars) |
| Zillow | `ZG` #2285, `Z` #2317 |
| Formula One | `FWONA` #2072, `FWONK` #2130 |
| News Corp | `NWS` #2082, `NWSA` #2127 |
| Strive | `ASST` #2415, `SATA` dropped |

**Best-ranked duplicate spelling: `SUN` at #370 of 2420, against a list of 22.** Nothing here is
within an order of magnitude of selection. Two independent reasons: these are mostly large, slow
names in a momentum ranking that today favours small caps, and the newer duplicate lines
(`GOOGM`, `GOOGN`, `SMCIP`, `SOMN`, `PPLC`, `SUNC`, `SATA`) fail out of the *ranking* rather than the
filters, because `mom12_7 = close[t-126]/close[t-252] - 1` needs 252 bars and they have 60-210.
That is a lucky guard, not a designed one: it expires as those series age. `SUNC` will have 252 bars
around 2026-11.

**A related non-finding worth recording.** 99 of the 3002 universe members have no sector in the
cache, become `"Other"`, and `"Other"` is **exempt** from `MAX_PER_SECTOR` by design
(`core/filters.py`). Almost all 99 are preferred / note lines of issuers whose common stock is also
in the universe (`AFGB`, `AFGC`, `AFGD`, `AFGE`, `AQNB`, `BEPH`, `BEPI`, `BEPJ`, `BIPH`, `BIPJ`,
`BHFAL`, `CMSA`, `CMSC`, `CMSD`, `DUKB`, `SFB`, `UNMA` …) — i.e. exactly the names that could pile
onto an issuer already at its sector cap. Measured: **0 of the 99 pass `config.FILTERS` today.** The
ADV$ filter is doing that work. `GOOGM` / `GOOGN` are the exception that proves the risk — sector
lookup failed for both, they *do* pass the filters, and only the momentum window keeps them out.

### 3b. Ever? There is no `history/` to grep, and the two lists that exist are clean

`core/history.py` has `HISTORY_DIR = "history"`, relative to cwd. **There is no
`hydra_screener_local/history/` in the production tree** (only `test_fixtures/history_min`). So the
daily-run archive the task assumed does not exist on this machine right now; there is nothing to
grep. What does exist:

- `state/instructions_20260904.md` — the live sheet, 22 stock names (`SLAB DBRG ANRO WBD GSAT SNDK
  AES IBRX IMMX BLTE MAZE LITE ZIM EFXT AG OUT PUMP CENX ENLT USAS SII GOLD`) + 8 ETFs. **No
  duplicate-group member.** Intersection with the 218 duplicate tickers: empty.
- `state/discarded_firstrun_20260904/instructions_20260904.md` — the discarded first run, 22 names
  (`… RVMD PEN ROIV TYRA ALMS GLUE KOD RLAY …`). **No duplicate-group member.**
- Book state: `state/portfolio_v9.json` is all cash with 30 pending orders, so nothing is *held*.

Searching every `.json`/`.md`/`.csv`/`.txt` under `state/`, `output/`, `archive/`,
`hydra_screener_local/docs/` and `.comms/` for the 218 duplicate tickers, the only hits that are
holdings-shaped are in the archived legacy COMPASS paper-trading book — and there `GOOG` and `GOOGL`
appear **only** inside `current_universe`, never in `positions` (last state's positions: `DBC`,
`EFA`, `GEV`, `GLD`, `JNJ`). So: **no recorded HYDRA list has ever contained two spellings of one
issuer**, on the evidence that exists.

### 3c. The PIT record, for the S&P half of the universe

Across the 2718 S&P snapshots in `sp500_pit.json`, genuine same-issuer pairs co-present on the same
date (shape rule + hand verification; the shape rule's false positives such as `BA`+`BAC`,
`FIS`+`FISV`, `MET`+`META` are excluded):

| pair | snapshot dates co-present | range |
|---|---|---|
| `GOOG` + `GOOGL` | 680 | 2014-04-03 .. 2026-06-30 |
| `DISCA` + `DISCK` | 574 | 2014-08-07 .. 2022-04-04 |
| `TMC` + `TMC-A` | 546 | 1996-01-02 .. 2000-06-09 |
| `FOX` + `FOXA` | 525 | 2015-09-21 .. 2026-06-30 |
| `NWS` + `NWSA` | 525 | 2015-09-21 .. 2026-06-30 |
| `UA` + `UAA` | 384 | 2016-04-08 .. 2022-06-09 |
| `CMCSA` + `CMCSK` | 31 | 2015-09-21 .. 2015-12-09 |

Pure separator collisions across all 2718 snapshots: **0** (section 2 explains why).

---

## 4. If both spellings were selected, would the book hold the same company twice? Yes.

There is **no issuer-level de-duplication anywhere in the pipeline**. The only dedupe that exists is
on the ticker *string*, and only for the history record — `screener.py:53-54`:

```python
    if 'ticker' in candidates.columns:
        candidates = candidates.drop_duplicates(subset='ticker', keep='first')   # one row per ticker (review 336)
```

`'BRK-B' != 'BRK.B'` and `'GOOG' != 'GOOGL'` as strings, so that line sees nothing.

The cap in `core/filters.py:216-289` is per **sector**, and it counts spellings, not issuers:

```python
    max_per = max_per_sector or MAX_PER_SECTOR
    picked, skipped, counts = [], [], {}
    for idx, sector in df["sector"].items():
        if len(picked) >= n_pool:
            break
        if sector != UNKNOWN_SECTOR and counts.get(sector, 0) >= max_per:
            skipped.append(idx)
            continue
        picked.append(idx)
        counts[sector] = counts.get(sector, 0) + 1
```

Two Alphabet lines are two of Communication Services' five slots. The selection the live sheet
actually uses, `core/portfolio_engine.py:105-129`, does the same:

```python
def select_tranche_names(ranking: pd.DataFrame, n: int, held: set, buffer: float,
                         max_per_sector: int = MAX_PER_SECTOR) -> List[str]:
    ...
    for name in order:
        if len(picked) >= n:
            break
        if name in picked:
            continue
        s = sectors.get(name, "Other")
        if s != "Other" and counts.get(s, 0) >= max_per_sector:
            continue
        picked.append(name); counts[s] = counts.get(s, 0) + 1
    return picked[:n]
```

and the weights, `core/portfolio_engine.py:145-150`:

```python
    rets = prices[names].pct_change(fill_method=None).iloc[-63:]
    basket = rets.mean(axis=1)
    rv = float(basket.std(ddof=1)) * math.sqrt(252) if len(basket) > 2 else 0.0
    expo = min(1.0, cfg["stock_target_vol"] / rv) if rv > 0 else 1.0
    return pd.Series(expo / len(names), index=names)
```

`expo / len(names)` per **name**. Two spellings of one issuer therefore receive `2 * expo / n` —
double the intended per-issuer weight — and the vol-target basket treats two near-identical series
as two independent names, so the measured basket vol is understated and `expo` comes out *higher*
than it should. The error compounds in the same direction.

Sized on the live sheet: the renewed stock tranche is `tranche_target = pair value / 2` (spec 9.3,
`core/portfolio_engine.py:238-241`) = $12,500 of a $100,000 book, and the sheet's 22 buys are
$323.88 each, i.e. $7,125.36, so `expo` was 0.57. A duplicated issuer in that tranche would be
**$647.76 instead of $323.88 — 0.65% of the book per tranche, and up to 2.59% if it survived in all
four tranches.** For the paired Brookfield/Sunoco groups it is the same economic exposure twice, not
merely the same issuer; for `SOMN`/`PPLC`/`MCHPP`/`SMCIP`/`STRC` it is worse than a share class — a
bond or preferred line sitting in a momentum *equity* sleeve, and no code in the tree distinguishes
`quoteType` beyond price and volume.

---

## 5. What a dedupe would change, in names and in numbers

Two candidate rules, both applied to the universe *before* filtering, both measured through the
verified pipeline:

- **Rule L — keep the highest ADV$20 spelling per issuer.** Drops 21:
  `BELFA BEP BIP CENT FOX FWONA GOOG GOOGM GOOGN LBTYK LLYVA MCHPP NWS PPLC SATA SMCIP SOMN STRC
  SUN UA ZG`
- **Rule C — keep the ordinary/common line, ADV$ as tiebreak.** Drops 21:
  `BELFA BEPC BIPC CENT FOX FWONA GOOG GOOGM GOOGN LBTYK LLYVA MCHPP NWS PPLC SATA SMCIP SOMN STRC
  SUNC UA ZG`

The two rules differ on exactly three groups, and the difference matters: rule L drops the S&P 500
parents `BEP`, `BIP` and `SUN` in favour of the newer, more liquid paired corporations. A
liquidity-only tiebreak silently replaces the primary listing. Rule C is the safer instrument.

| measurement | baseline (= live) | rule L | rule C |
|---|---|---|---|
| universe fed to the filters | 3000 | 2979 (-21) | 2979 (-21) |
| eligible after `config.FILTERS` + jump | **2525** | **2504 (-21, -0.83%)** | **2504 (-21, -0.83%)** |
| rows in the scored ranking | 2420 | 2405 (-15) | 2406 (-14) |
| `dynamic_count` | 22 | 22 | 22 |
| names flagged `recommended` | 15 | 15 | 15 |
| names displaced by `MAX_PER_SECTOR=5` | 13 | 13 | 13 |
| `select_tranche_names` T22 | see below | **identical, in order** | **identical, in order** |
| `recommended` set | — | **identical** | **identical** |

```
rule L: eligible 2525 -> 2504 (-21); ranking rows 2420 -> 2405 (-15); dynamic n 22 -> 22;
        T-n identical to baseline: True; recommended set identical: True
        T-n symmetric difference: []
rule C: eligible 2525 -> 2504 (-21); ranking rows 2420 -> 2406 (-14); dynamic n 22 -> 22;
        T-n identical to baseline: True; recommended set identical: True
        T-n symmetric difference: []
```

So, precisely:

1. **Which names disappear:** the 21 listed above, none of them within 348 ranks of selection.
2. **Does the recommended count move?** No, and it structurally cannot: `dynamic_count =
   clamp(round(14 x aggression x compass_mult), 6, 28)` (`core/signals.py:288-292`) depends on the
   regime, not on universe size. Only the *identities* could change, and today they do not.
3. **What does it do to the sector cap?** Nothing today — 13 names displaced in all three runs, the
   same 13. The cap's exposure to this is structural rather than current: a duplicated issuer
   consumes two of five slots in its sector, which on 2026-09-04 never happened because no duplicate
   ranked high enough to be walked past.

The honest summary is that a dedupe on 2026-09-04 is a **no-op on the output** and a -0.83% trim of
the eligible universe. Anyone who claims it improves returns has to show it on a panel this
measurement cannot reach (see Appendix).

---

## 6. Is the blacklist in `config.py` the right instrument? No — and it should not be edited

Not changed here. The assessment:

**It is the wrong instrument, for four measurable reasons.**

1. **It normalises by exception rather than by rule.** Two entries cover the two dot-tickers that
   happen to be in Slickcharts' S&P 500 page today. `_yahoo_ticker` — the one-line normaliser that
   solves the whole class — already exists in the same package and is wired only to the PIT path.
   Measured proof it works: 0 separator collisions in 2718 PIT snapshots vs 1 in the live union.
2. **It deletes the issuer instead of fixing the spelling.** `BRK.B` is harmless only because the
   Russell feed independently supplies `BRK-B`. `BF.B` has no such twin, so blacklisting it removes
   **Brown-Forman entirely** from a 3002-name universe. A denylist cannot tell "wrong spelling of a
   name we want" from "name we do not want"; a normaliser can.
3. **It hides the loss from the guard built to catch exactly this.** `requested` is computed after
   the blacklist in both fetch paths, so blacklisted names never enter `missing_share` and
   `FETCH_MISSING_WARN_SHARE` cannot fire. The audit's D1 fix is blind here by construction.
4. **It does nothing about the actual duplicate.** All 218 duplicate tickers except `BRK.B` and
   `BF.B` are correctly spelled, fetchable, and genuinely distinct securities. No blacklist entry
   could address `GOOG`/`GOOGL` or `SO`/`SOMN` without deleting a real name by hand, forever, with
   no rule behind it — which is how the list grows to 3000 entries and nobody dares touch it.

**What the right instruments are** (both parked for Lucas; neither applied):

- **Normalisation at the universe boundary:** apply `_yahoo_ticker` in the live fetchers, so `BF.B`
  becomes `BF-B` and Brown-Forman comes back. This is a *universe* change and therefore changes the
  recommended list (rule 2 at minimum, and it re-adds an S&P 500 name) — Lucas's call. The two
  blacklist entries would then be dead and could be removed in the same change, not before.
- **Issuer-level dedupe at selection:** a `duplicate_share_classes()`-style helper feeding
  `select_tranche_names`, keeping the ordinary line (rule C). This is what TASK-389's board entry
  calls for. Note the board names `data/universe_registry.duplicate_share_classes()` as the thing to
  call — **that module does not exist** in the tree.

Do **not** add `GOOG`, `SOMN`, `BIP` or anything else to `DELISTED_OR_BAD_TICKERS`. Using a
delisting denylist as a dedupe would make the third defect above permanent: the names would vanish
from `requested` and no counter would show it.

---

## Appendix — what was NOT measured, and why

- **The board's items (2) and (3).** `TASK-389` on `GROKBOARD.md` also asks how often a group
  contributes two names to the same T20 across the OOS panel, and what keeping the more liquid
  spelling does to ann_net / Sharpe / maxDD against main's 20260905 headline (7.1 / 0.75 / -17.8).
  Not measured, and it cannot honestly be measured on that panel: the OOS panel is **S&P 500 only**
  (`sp500_pit.json` is the only PIT payload in the tree), while 16 of the 19 currently-duplicated
  groups live in the Russell 1000/2000 half of the universe. It needs TASK-324's Russell PIT
  membership panel, which does not exist yet. Quoting an S&P-only ann_net delta as "the cost of the
  duplicate" would be exactly the kind of number this project keeps auditing. Section 3c is the
  closest honest substitute: the S&P membership history of the duplicate pairs.
- **`data/universe_registry.duplicate_share_classes()`** — does not exist; there is no
  `hydra_screener_local/data/universe_registry.py` on `origin/main` @ `965d22c`. The measurement was
  done with throwaway scripts against the caches, which is why section 0 lists every input.
- **`history/`** — no such directory in the production tree (section 3b). Nothing to grep.
- **Issuer names for 4 of 3002 tickers** (`ASBA`, `DCBG`, `BF.B`, `BRK.B`). None can hide a
  duplicate group: `BF.B`/`BRK.B` are handled explicitly, and `ASBA`/`DCBG` have no ticker-shape
  sibling in the universe.
- **Forward-looking exposure.** Section 3a notes that `SUNC`, `SOMN`, `PPLC`, `SMCIP`, `GOOGM`,
  `GOOGN` and `SATA` are currently excluded by the 252-bar `mom12_7` window rather than by any
  rule. Their eligibility dates are arithmetic, not measurement, and are not quoted as measured
  numbers.
