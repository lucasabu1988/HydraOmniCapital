"""Russell 3000 membership from the free public record - the MEMBERSHIP half of TASK-403, measured.

What this builds (Lucas's finding, 2026-09-10):
  * 2010-2023 (no 2013): the annual June reconstitution lists extracted from FTSE Russell's own
    constituent PDFs, `kact998/Russell3000Components` (Company, Ticker; ~3000 names each).
  * 2023-2026: FTSE Russell's official reconstitution additions / deletions PDFs (Company, Symbol,
    Industry), applied to the previous June list to roll membership forward one reconstitution at a
    time; plus the quarterly IPO additions document for the current quarter.
  * today: the iShares IWV holdings CSV (an ETF book, ~2575 of ~3000 names) as a cross-check of the
    rolled-forward 2026 list - never as the membership itself.

What this is NOT: a point-in-time PRICE panel. TASK-326 / TASK-334 already established that the
gap is delisted prices, and this tool measures that gap instead of hiding it: a random sample of the
names that left the index is priced at EODHD (TASK-425; Yahoo mixed "no price" with rate-limits).
"sin precio" and "el proveedor fallo" are counted separately; their sum is never called a hit rate.
A member without a close cannot be selected. Nothing here writes `_sweep_cache_russell/`; the
output goes to `_lab_scratch/russell_free/` (gitignored) as a dated table:

    date        ticker  member  source
    2010-06-28  AAON    1       kact998
    ...
    2026-06-26  ANRO    1       ftse-rollforward

Limits, written down: no CUSIP / entity id in any source, so the same ticker can be two companies
across years (TASK-326: AMR, AGL, ADPT, ...); intra-year deletions (M&A, bankruptcies) between
June reconstitutions are not in the record; the IPO additions cover the current quarter only.

    python experiments/russell_free_membership.py --fetch          # download everything, build, probe EODHD
    python experiments/russell_free_membership.py                  # rebuild from the files already on disk
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import random
import re
import sys
import urllib.request

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # TASK-380: cp1252 consoles

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
OUT = os.path.join(HERE, "_lab_scratch", "russell_free")

KACT_RAW = "https://raw.githubusercontent.com/kact998/Russell3000Components/main/{stamp}.csv"
KACT_STAMPS = ["20100628", "20110627", "20120625", "20140627", "20150626", "20160627", "20170626",
               "20180625", "20190701", "20200629", "20210628", "20220624", "20230623"]
FTSE_BASE = "https://www.lseg.com/content/dam/ftse-russell/en_us/documents/other/{name}.pdf"
#: (effective date, additions document, deletions document) - the file names FTSE Russell publishes
FTSE_RECON = [
    ("2023-06-23", "ru3000-additions-final-20230623", "ru3000-deletions-final-20230623"),
    ("2024-06-28", "ru3000-additions-final-20240628", "ru3000-deletions-final-20240628"),
    ("2025-06-27", "ru3000-additions-20250627", "ru3000-deletions-20250627"),
    ("2026-06-26", "ru3000-additions-20260626", "ru3000-deletions-20260626"),
]
FTSE_IPO = "final-ipo-additions-3-qtr-r3000"
ISHARES = {"IWV": "https://www.ishares.com/us/products/239714/ishares-russell-3000-etf/latest-holdings.csv",
           "IWB": "https://www.ishares.com/us/products/239707/ishares-russell-1000-etf/latest-holdings.csv"}
INDUSTRIES = ["Technology", "Health Care", "Financials", "Consumer Discretionary", "Consumer Staples",
              "Industrials", "Energy", "Basic Materials", "Real Estate", "Utilities", "Telecommunications"]
_SYM = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
_ONE_LINE = re.compile(r"^(.+?)\s+([A-Z]{1,5}(?:\.[A-Z])?)\s+(" + "|".join(INDUSTRIES) + r")\s*$")
_IPO_LINE = re.compile(r"^([A-Z]{1,5}(?:\.[A-Z])?)\s+(.+)$")
UA = {"User-Agent": "Mozilla/5.0 (HYDRA research; membership record)"}


# ----------------------------------------------------------------------------- fetch
def fetch(url: str, dest: str) -> str:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        f.write(r.read())
    return dest


def fetch_all(out: str = OUT) -> dict:
    got = {}
    for stamp in KACT_STAMPS:
        got[stamp] = fetch(KACT_RAW.format(stamp=stamp), os.path.join(out, "kact998", f"{stamp}.csv"))
    for _d, add, dele in FTSE_RECON:
        for name in (add, dele):
            got[name] = fetch(FTSE_BASE.format(name=name), os.path.join(out, "ftse", f"{name}.pdf"))
    got[FTSE_IPO] = fetch(FTSE_BASE.format(name=FTSE_IPO), os.path.join(out, "ftse", f"{FTSE_IPO}.pdf"))
    for k, url in ISHARES.items():
        got[k] = fetch(url, os.path.join(out, "ishares", f"{k}.csv"))
    return got


# ----------------------------------------------------------------------------- parse
def parse_kact_csv(text: str) -> pd.DataFrame:
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    df = pd.DataFrame({"company": [r.get("Company", "").strip() for r in rows],
                       "ticker": [r.get("Ticker", "").strip() for r in rows]})
    return df[df["ticker"] != ""].drop_duplicates("ticker").reset_index(drop=True)


def parse_ftse_lines(lines: list[str]) -> pd.DataFrame:
    """Both layouts FTSE Russell has used: one row per line (2025) and Company / Symbol / Industry on
    three lines (2023, 2024, 2026). Disclaimer fragments never match: the industry must be one of
    the eleven ICB names."""
    lines = [l.strip() for l in lines if l and l.strip()]
    rows, i = [], 0
    while i < len(lines):
        m = _ONE_LINE.match(lines[i])
        if m:
            rows.append((m.group(1).strip(), m.group(2), m.group(3)))
            i += 1
            continue
        if i + 2 < len(lines) and _SYM.match(lines[i + 1]) and not _SYM.match(lines[i]) and lines[i + 2] in INDUSTRIES:
            rows.append((lines[i], lines[i + 1], lines[i + 2]))
            i += 3
            continue
        i += 1
    return pd.DataFrame(rows, columns=["company", "symbol", "industry"]).drop_duplicates("symbol").reset_index(drop=True)


def parse_ipo_lines(lines: list[str]) -> pd.DataFrame:
    """The quarterly IPO additions document: `Ticker Company Name`, one per line, after the header."""
    lines = [l.strip() for l in lines if l and l.strip()]
    rows = []
    started = False
    for l in lines:
        if l.startswith("Ticker"):
            started = True
            continue
        if not started:
            continue
        m = _IPO_LINE.match(l)
        if m and not l.lower().startswith(("please see", "source", "ftse", "lseg")):
            rows.append((m.group(1), m.group(2).strip()))
    return pd.DataFrame(rows, columns=["symbol", "company"]).drop_duplicates("symbol").reset_index(drop=True)


def pdf_lines(path: str) -> list[str]:
    from pypdf import PdfReader
    return [l for p in PdfReader(path).pages for l in (p.extract_text() or "").splitlines()]


def parse_ishares_csv(text: str) -> pd.DataFrame:
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    asof = next((r[1] for r in rows if r and r[0].startswith("Fund Holdings as of")), None)
    hdr = next(i for i, r in enumerate(rows) if r and r[0] == "Ticker")
    cols = rows[hdr]
    body = [r for r in rows[hdr + 1:] if len(r) >= len(cols)]
    df = pd.DataFrame(body, columns=cols)
    df = df[(df["Asset Class"] == "Equity") & (df["Ticker"] != "-")]
    out = df[["Ticker", "Name", "Sector"]].rename(columns={"Ticker": "ticker", "Name": "company", "Sector": "sector"})
    out.attrs["as_of"] = asof
    return out.drop_duplicates("ticker").reset_index(drop=True)


# ----------------------------------------------------------------------------- assemble
def roll_forward(members: set, additions: set, deletions: set) -> set:
    """One reconstitution: drop the deletions, add the additions. Order matters only for a name in
    both lists (a re-entry): it ends up IN, as the additions document says."""
    return (set(members) - set(deletions)) | set(additions)


def assemble(kact: dict[str, pd.DataFrame], recon: list[tuple[str, pd.DataFrame, pd.DataFrame]],
             ipo: pd.DataFrame | None = None, ipo_effective: str | None = None) -> pd.DataFrame:
    """The dated membership table. `kact` maps YYYYMMDD stamps to (company, ticker) frames; `recon`
    is [(effective_date, additions, deletions), ...] in date order, applied to the last June list on
    or before each date (the 2023 official lists are applied to the 2022 kact list and then
    cross-checked against the 2023 kact list, which is the one measurement of the roll-forward)."""
    snaps: dict[pd.Timestamp, tuple[set, str]] = {}
    for stamp, df in sorted(kact.items()):
        snaps[pd.Timestamp(stamp)] = (set(df["ticker"]), "kact998")
    for eff, adds, dels in sorted(recon, key=lambda r: r[0]):
        eff_ts = pd.Timestamp(eff)
        prior = max(d for d in snaps if d < eff_ts)
        rolled = roll_forward(snaps[prior][0], set(adds["symbol"]), set(dels["symbol"]))
        if eff_ts in snaps:                                   # the same June exists as a kact list: keep it, record the check
            snaps[eff_ts] = (snaps[eff_ts][0], snaps[eff_ts][1] + f"|rollforward-check:{len(rolled ^ snaps[eff_ts][0])}-diff")
        else:
            snaps[eff_ts] = (rolled, "ftse-rollforward")
    if ipo is not None and ipo_effective and len(ipo):
        last = max(snaps)
        snaps[pd.Timestamp(ipo_effective)] = (snaps[last][0] | set(ipo["symbol"]), "ftse-rollforward+ipo")
    out = []
    for d in sorted(snaps):
        names, src = snaps[d]
        out.extend({"date": d.date().isoformat(), "ticker": t, "member": 1, "source": src} for t in sorted(names))
    return pd.DataFrame(out)


def churn(table: pd.DataFrame) -> pd.DataFrame:
    by = {d: set(g["ticker"]) for d, g in table.groupby("date")}
    dates = sorted(by)
    rows, prev = [], None
    for d in dates:
        s = by[d]
        rows.append({"date": d, "members": len(s), "added": len(s - prev) if prev is not None else 0,
                     "dropped": len(prev - s) if prev is not None else 0})
        prev = s
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- the price gap, measured
def yahoo_price_probe(gone: list[str], membership_years: dict[str, list[int]], *, n: int = 150, seed: int = 403,
                     provider=None) -> dict:
    """Random sample of names that left the index: how many does EODHD still price.

    `no_price` and `provider_failed` are separate (TASK-425). Their sum is not a hit rate.
    `reliable` is False when a control ticker has no price — then the numbers are not evidence.
    """
    rng = random.Random(seed)
    sample = rng.sample(sorted(gone), min(n, len(gone)))
    close, report = eodhd_closes(sample, since="2009-01-01", until="2026-09-01", provider=provider)
    out = {
        "sampled": len(sample),
        "reliable": report["reliable"],
        "priced": report["priced"],
        "no_price": len(report["no_price"]),
        "provider_failed": len(report["provider_failed"]),
        "control_hits": report["control_hits"],
    }
    if close.empty or not report["reliable"]:
        return out
    any_px = close.notna().any()
    live = close.loc["2026-01-01":].notna().any() if len(close.index) else any_px * False
    in_era = 0
    for t in sample:
        ys = membership_years.get(t) or []
        if not ys or t not in close.columns:
            continue
        seg = close[t].loc[f"{min(ys)}-06-01":f"{max(ys)}-12-31"]
        in_era += int(len(seg) and seg.notna().mean() > 0.5)
    out.update({
        "any_close": int(any_px.sum()),
        "covers_membership_era": in_era,
        "of_which_still_print_2026": int((any_px & live).sum()),
        "share_priced_in_era": round(in_era / len(sample), 3),
    })
    return out


# ----------------------------------------------------------------------------- the current list, pruned
def prune_dead(latest: set, printing: set) -> tuple[set, set]:
    """CURRENT membership only: the June documents list reconstitution deletions, never the names that
    left between reconstitutions (acquired, bankrupt, renamed). Measured 2026-09-10: 619 of the 3384
    names in the rolled-forward 2026 list had no print in Jun-Sep 2026, and 582 of those were already
    in the repository's "2023" file, which is therefore a projected list that kept the intra-year
    dead. For TODAY's universe a name that no longer prints is not a member; for a point-in-time
    panel it must stay, as dead, WITH its prices - which is exactly what the free record lacks.
    Returns (alive, dead)."""
    latest, printing = set(latest), set(printing)
    return latest & printing, latest - printing


CONTROLS = ("SPY", "AAPL", "MSFT")        # always listed: if THEY come back empty, the probe is not a fact about the names


def probe_reliable(control_hits: int, n_controls: int = len(CONTROLS)) -> bool:
    """A batch is trusted only if every control ticker returned data. Measured 2026-09-10: a
    Yahoo second run in the same hour returned 979 'alive' of 3417 and 3 of 150 in the price
    probe - throttling, not a fact about the names. TASK-425 keeps this valla on EODHD.
    """
    return control_hits == n_controls


def _classify_eodhd_error(msg: str) -> str:
    """404 / no rows = the code has no price. Timeouts, 5xx, non-JSON = the provider failed."""
    m = str(msg).lower()
    if "http 404" in m or m.strip() in {"no rows", ""}:
        return "no_price"
    return "provider_failed"


def _has_price(long: pd.DataFrame, ticker: str) -> bool:
    if long is None or not len(long) or "ticker" not in long.columns:
        return False
    return bool(long.loc[long["ticker"] == ticker, "close_adj"].notna().any())


def eodhd_closes(tickers: list, *, since: str, until: str, provider=None) -> tuple[pd.DataFrame, dict]:
    """Closes from EODHD. `no_price` and `provider_failed` are separate lists; never a summed hit rate.

    `reliable` is probe_reliable() on the control tickers (TASK-425: reuse, do not reinvent).
    """
    from data.providers.eodhd_provider import EODHDProvider
    tickers = list(dict.fromkeys(tickers))
    prov = provider if provider is not None else EODHDProvider()
    asked = list(tickers) + [c for c in CONTROLS if c not in tickers]
    long = prov.fetch(asked, since, until)
    errors = dict(getattr(prov, "last_errors", {}) or {})
    if long is None or not len(long):
        close = pd.DataFrame(columns=tickers)
    else:
        wide = long.pivot_table(index="date", columns="ticker", values="close_adj", aggfunc="last")
        close = wide.reindex(columns=tickers)
    no_price, failed = [], []
    for t in tickers:
        if _has_price(long, t):
            continue
        kind = _classify_eodhd_error(errors.get(t, "no rows"))
        (no_price if kind == "no_price" else failed).append(t)
    control_hits = int(sum(1 for c in CONTROLS if _has_price(long, c)))
    report = {
        "no_price": no_price,
        "provider_failed": failed,
        "control_hits": control_hits,
        "reliable": probe_reliable(control_hits),
        "priced": int(sum(1 for t in tickers if _has_price(long, t))),
    }
    return close, report


def printing_recently(tickers: list, *, since: str, until: str, provider=None) -> tuple[set, bool]:
    """Tickers with at least one EODHD close in [since, until], and whether the answer is
    trustworthy (every control printed)."""
    close, report = eodhd_closes(tickers, since=since, until=until, provider=provider)
    if not report["reliable"]:
        return set(), False
    if close.empty:
        return set(), True
    return set(close.columns[close.notna().any().to_numpy()]), True


# ----------------------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Russell 3000 membership from the free public record (membership only)")
    ap.add_argument("--fetch", action="store_true", help="download the sources (network); otherwise parse what is on disk")
    ap.add_argument("--no-probe", action="store_true", help="skip the Yahoo price-coverage probe (network)")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args(argv)
    if args.fetch:
        print("fetching sources...", flush=True)
        fetch_all(args.out)
    kact = {}
    for stamp in KACT_STAMPS:
        p = os.path.join(args.out, "kact998", f"{stamp}.csv")
        if os.path.exists(p):
            kact[stamp] = parse_kact_csv(open(p, encoding="utf-8", errors="replace").read())
    if not kact:
        print("no sources on disk; run with --fetch")
        return 1
    recon = []
    for eff, add, dele in FTSE_RECON:
        pa, pdl = (os.path.join(args.out, "ftse", f"{n}.pdf") for n in (add, dele))
        if os.path.exists(pa) and os.path.exists(pdl):
            recon.append((eff, parse_ftse_lines(pdf_lines(pa)), parse_ftse_lines(pdf_lines(pdl))))
            print(f"  {eff}: +{len(recon[-1][1])} / -{len(recon[-1][2])} (official FTSE Russell)", flush=True)
    ipo_p = os.path.join(args.out, "ftse", f"{FTSE_IPO}.pdf")
    ipo = parse_ipo_lines(pdf_lines(ipo_p)) if os.path.exists(ipo_p) else None
    if ipo is not None:
        print(f"  IPO additions (current quarter): {len(ipo)}", flush=True)
    table = assemble(kact, recon, ipo, ipo_effective="2026-09-21" if ipo is not None else None)
    os.makedirs(args.out, exist_ok=True)
    table.to_csv(os.path.join(args.out, "russell3000_membership_free.csv"), index=False)
    ch = churn(table)
    print("\nmembership table:", len(table), "rows,", table["date"].nunique(), "dates,", table["ticker"].nunique(), "distinct tickers", flush=True)
    print(ch.to_string(index=False), flush=True)
    # cross-checks against today's ETF books
    checks = {}
    for k in ISHARES:
        p = os.path.join(args.out, "ishares", f"{k}.csv")
        if os.path.exists(p):
            hold = parse_ishares_csv(open(p, encoding="utf-8", errors="replace").read())
            latest = set(table[table["date"] == table["date"].max()]["ticker"])
            h = set(hold["ticker"])
            checks[k] = {"as_of": hold.attrs.get("as_of"), "holdings": len(h),
                         "in_rolled_forward_list": len(h & latest), "share_of_holdings_covered": round(len(h & latest) / len(h), 3),
                         "rolled_forward_not_held": len(latest - h)}
            print(f"  {k} ({hold.attrs.get('as_of')}): {len(h)} holdings, {len(h & latest)} in the rolled-forward list "
                  f"({len(h & latest) / len(h):.1%}); {len(latest - h)} listed names the ETF does not hold", flush=True)
    result = {"dates": ch.to_dict(orient="records"), "checks": checks,
              "sources": {"kact998": KACT_STAMPS, "ftse": [r[0] for r in recon], "ipo": FTSE_IPO if ipo is not None else None}}
    if not args.no_probe:
        latest_date = table["date"].max()
        latest = set(table[table["date"] == latest_date]["ticker"])
        printing, reliable = printing_recently(sorted(latest), since="2026-06-01", until="2026-09-10")
        alive, dead = prune_dead(latest, printing)
        k23 = set(table[table["date"] == "2023-06-23"]["ticker"]) if "2023-06-23" in set(table["date"]) else set()
        result["current_list"] = {"reliable": reliable, "rolled_forward": len(latest), "alive": len(alive),
                                  "dead_no_print_since_june": len(dead), "dead_already_in_2023_file": len(dead & k23), "as_of": latest_date}
        if reliable:
            pd.DataFrame({"ticker": sorted(alive)}).to_csv(os.path.join(args.out, "russell3000_current_alive.csv"), index=False)
            pd.DataFrame({"ticker": sorted(dead)}).to_csv(os.path.join(args.out, "russell3000_current_dead.csv"), index=False)
        else:
            print("\nPROBE NOT RELIABLE (a control ticker came back empty): the alive/dead split below is NOT trustworthy and "
                  "was not written. Wait and rerun without --fetch.", flush=True)
        print(f"\ncurrent list {latest_date}: {len(latest)} rolled forward, {len(alive)} print at EODHD since June, "
              f"{len(dead)} do not ({len(dead & k23)} of them already in the 2023 file) -> russell3000_current_alive.csv", flush=True)
        by_ticker = table.groupby("ticker")["date"].apply(lambda s: sorted({int(d[:4]) for d in s})).to_dict()
        latest = set(table[table["date"] == table["date"].max()]["ticker"])
        gone = sorted(set(table["ticker"]) - latest)
        print(f"\nprice gap probe: {len(gone)} ever-members are not in the latest list; sampling 150 at EODHD...", flush=True)
        probe = yahoo_price_probe(gone, by_ticker)
        result["price_probe"] = probe
        print("  priced={priced}  no_price={no_price}  provider_failed={provider_failed}  "
              "reliable={reliable}".format(**{k: probe.get(k) for k in
                                             ("priced", "no_price", "provider_failed", "reliable")}),
              flush=True)
        print("  ", probe, flush=True)
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    print("wrote", os.path.join(args.out, "summary.json"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
