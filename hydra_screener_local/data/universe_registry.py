"""What each universe actually is (audit phase 7). Pure; no network.

The screener's `russell1000` and `russell2000` are **not** the FTSE Russell indices.
Their primary source is a NASDAQ market-capitalisation ranking — top 1000 by cap, and
ranks 1001-3000 — with Slickcharts and Barchart as secondary attempts. Calling that
"Russell 1000" in code, in console output and in results overstates what the data is:
real Russell membership is set by an annual reconstitution with float adjustment,
eligibility screens and banding rules, none of which a cap ranking reproduces.

This module is the single place that says so, and the single place that answers:
source, definition, date, membership method, exclusions, coverage, hash (phase 7.2),
plus which of the four kinds a universe is (phase 7.5) and which biases apply (7.6).

Nothing here changes membership. `exclude_non_common()` is a guard: measured against
the live `all` universe on 2026-09-06 (3002 names) it removes **zero** names, because
the sources already return common stock only. It exists so a warrant or a unit cannot
enter unnoticed later.
"""
from __future__ import annotations

import re

from core.baseline import sha256_json

# --- the four kinds (phase 7.5) --------------------------------------------------
PIT = "pit"                  # membership as it stood on a past date, from a snapshot
CURRENT = "current"          # membership as it stands today, from the index publisher
PROXY = "proxy"              # a reconstruction that stands in for an index we cannot get
FALLBACK = "fallback"        # a hardcoded list used when every source failed
KINDS = (PIT, CURRENT, PROXY, FALLBACK)

SURVIVORSHIP = (
    "survivorship: a current-membership list contains only names that survived to "
    "today. Backtesting on it flatters momentum, because the delisted and acquired "
    "names that momentum would have bought are absent."
)
LOOK_AHEAD = (
    "look-ahead: using today's membership for a past date lets the test hold names "
    "that were not in the index then, and index additions are themselves a momentum "
    "signal."
)
PROXY_BIAS = (
    "proxy: membership is a market-cap ranking, not the index's own reconstitution. "
    "It has no float adjustment, no eligibility screens and no banding, so the edges "
    "of the list differ from the real index by construction."
)
PIT_CLEAN = (
    "point-in-time: membership comes from a dated snapshot, so it carries neither "
    "survivorship nor look-ahead bias. Price coverage is a separate question."
)

_US_COMMON = re.compile(r"^[A-Z]{1,5}([.\-][A-Z])?$")

#: suffixes that mark something that is not common stock (phase 7.4)
NON_COMMON_SUFFIXES = {
    "warrant": (".WS", "-WT", ".WT", "-W", ".W", "+"),
    "unit": (".U", "-UN", ".UN", "-U", "=",),
    "right": (".R", "-RT", ".RT", "-R"),
    "preferred": ("-P", ".P", "-PR", ".PR"),
    "when_issued": (".WI", "-WI"),
    "note_or_bond": (".B0", "-CL"),
}

#: tickers that are funds the v9 stock sleeve must never hold. The ETF sleeve names
#: its own universe explicitly in config.V9["etf_universe"].
DISALLOWED_FUND_PREFIXES: tuple[str, ...] = ()


UNIVERSES: dict[str, dict] = {
    "sp500": {
        "label": "S&P 500",
        "kind": CURRENT,
        "source": "Wikipedia constituents table, with a Slickcharts fallback",
        "definition": "the 500-odd US large-cap common stocks in the S&P 500 index",
        "membership_method": (
            "scraped from the publisher's current constituents list; the committee's "
            "own selection, not a reconstruction"
        ),
        "exclusions": "none applied on top of the published list",
        "biases": (SURVIVORSHIP, LOOK_AHEAD),
        "caveats": (
            "the measurement harness (experiments/backtest_variant_sweep.py) uses "
            "current S&P 500 constituents over 2020-2026, so every number from it "
            "carries survivorship bias in the direction that flatters momentum",
        ),
    },
    "nasdaq100": {
        "label": "Nasdaq-100",
        "kind": CURRENT,
        "source": "Wikipedia constituents table",
        "definition": "the 100 largest non-financial companies on Nasdaq",
        "membership_method": "scraped from the publisher's current constituents list",
        "exclusions": "none applied on top of the published list",
        "biases": (SURVIVORSHIP, LOOK_AHEAD),
        "caveats": (),
    },
    "dow30": {
        "label": "Dow Jones Industrial Average",
        "kind": CURRENT,
        "source": "Wikipedia constituents table",
        "definition": "the 30 price-weighted DJIA components",
        "membership_method": "scraped from the publisher's current constituents list",
        "exclusions": "none applied on top of the published list",
        "biases": (SURVIVORSHIP, LOOK_AHEAD),
        "caveats": (),
    },
    "russell1000": {
        "label": "Russell 1000 proxy (top 1000 US by market cap)",
        "kind": PROXY,
        "source": "NASDAQ screener market-cap ranking; Slickcharts and Barchart as fallbacks",
        "definition": "the 1000 largest US-listed companies by market capitalisation",
        "membership_method": (
            "rank all US-listed names by market cap and take the top 1000. This is a "
            "reconstruction, NOT FTSE Russell membership: no float adjustment, no "
            "eligibility screens, no annual reconstitution, no banding"
        ),
        "exclusions": "non-common-stock symbol shapes (see exclude_non_common)",
        "biases": (PROXY_BIAS, SURVIVORSHIP, LOOK_AHEAD),
        "caveats": (
            "do not describe a result from this universe as a Russell 1000 result",
        ),
    },
    "russell2000": {
        "label": "Russell 2000 proxy (US market-cap ranks 1001-3000)",
        "kind": PROXY,
        "source": "NASDAQ screener market-cap ranking; Slickcharts and Barchart as fallbacks",
        "definition": "US-listed companies ranked 1001 to 3000 by market capitalisation",
        "membership_method": (
            "rank all US-listed names by market cap and take ranks 1001-3000. A "
            "reconstruction, NOT FTSE Russell membership; the real Russell 2000 is "
            "float-adjusted and reconstituted annually, so the small-cap edge of this "
            "list differs materially"
        ),
        "exclusions": "non-common-stock symbol shapes (see exclude_non_common)",
        "biases": (PROXY_BIAS, SURVIVORSHIP, LOOK_AHEAD),
        "caveats": (
            "do not describe a result from this universe as a Russell 2000 result",
            "small caps are where warrants, units and shell companies concentrate, so "
            "the symbol-shape exclusions matter most here",
        ),
    },
    "russell3000": {
        "label": "Russell 3000 proxy (top 3000 US by market cap)",
        "kind": PROXY,
        "source": "the russell1000 and russell2000 proxies combined",
        "definition": "the 3000 largest US-listed companies by market capitalisation",
        "membership_method": (
            "union of the two cap-ranking proxies above; NOT FTSE Russell membership"
        ),
        "exclusions": "non-common-stock symbol shapes (see exclude_non_common)",
        "biases": (PROXY_BIAS, SURVIVORSHIP, LOOK_AHEAD),
        "caveats": ("not FTSE Russell membership",),
    },
    "all": {
        "label": "combined US universe (S&P 500 + Nasdaq-100 + Dow 30 + cap-rank proxies)",
        "kind": PROXY,
        "source": "union of sp500, nasdaq100, dow30, russell1000 proxy, russell2000 proxy",
        "definition": (
            "roughly 3000 US-listed common stocks: three published index lists plus "
            "the market-cap ranking proxies"
        ),
        "membership_method": (
            "set union of the five sources above. Because two of them are cap-ranking "
            "proxies, the combined universe is a proxy too — it is not the union of "
            "three indices and two Russell indices"
        ),
        "exclusions": "non-common-stock symbol shapes (see exclude_non_common)",
        "biases": (PROXY_BIAS, SURVIVORSHIP, LOOK_AHEAD),
        "caveats": (
            "this is the production universe (config.UNIVERSE = \"all\")",
            "roughly two thirds of it is mid/small cap, while the regime is computed "
            "on SPY — a known weakness (audit R1)",
        ),
    },
    "custom": {
        "label": "hand-listed universe (config.INITIAL_UNIVERSE)",
        "kind": FALLBACK,
        "source": "config.INITIAL_UNIVERSE",
        "definition": "whatever is written in config",
        "membership_method": "hand-maintained list",
        "exclusions": "none",
        "biases": (SURVIVORSHIP, LOOK_AHEAD),
        "caveats": ("selection bias: the list was chosen by hand",),
    },
    "pit": {
        "label": "point-in-time membership from a dated snapshot",
        "kind": PIT,
        "source": "data_cache/pit/universe_<name>_<date>.json (see data/pit.py)",
        "definition": "membership as recorded on a past date",
        "membership_method": "read back from an immutable, content-addressed snapshot",
        "exclusions": "whatever the snapshot recorded",
        "biases": (PIT_CLEAN,),
        "caveats": (
            "the OOS panel (2004-2026) has real membership but only 53% price "
            "coverage in 2005 — never quote an absolute level without that caveat",
        ),
    },
}


def describe(key: str) -> dict:
    """The documented record for a universe (phase 7.2). Unknown key -> KeyError."""
    k = str(key).lower().strip()
    if k not in UNIVERSES:
        raise KeyError(f"unknown universe {key!r}; known: {', '.join(sorted(UNIVERSES))}")
    return dict(UNIVERSES[k], key=k)


def label(key: str) -> str:
    """The name to print. Never says "Russell 1000" for a cap-ranking proxy."""
    try:
        return describe(key)["label"]
    except KeyError:
        return str(key)


def kind(key: str) -> str:
    try:
        return describe(key)["kind"]
    except KeyError:
        return FALLBACK


def is_proxy(key: str) -> bool:
    return kind(key) == PROXY


def bias_notes(key: str) -> tuple[str, ...]:
    """Phase 7.6: the biases that apply to any number computed on this universe."""
    try:
        return tuple(describe(key)["biases"])
    except KeyError:
        return (SURVIVORSHIP, LOOK_AHEAD)


def classify_symbol(ticker: str) -> tuple[bool, str | None]:
    """(is US common stock, reason it is not). Phase 7.4.

    Shape-based, because the free sources carry no security-type field. Share-class
    suffixes (`BRK-B`, `BF.B`) are common stock and stay; warrants, units, rights,
    preferreds and when-issued lines do not.
    """
    t = str(ticker or "").strip().upper()
    if not t:
        return False, "empty symbol"
    for reason, suffixes in NON_COMMON_SUFFIXES.items():
        for suffix in suffixes:
            if t.endswith(suffix) and len(t) > len(suffix):
                return False, reason
    if not _US_COMMON.match(t):
        return False, "not a US common-stock symbol shape"
    if any(t.startswith(p) for p in DISALLOWED_FUND_PREFIXES):
        return False, "disallowed fund"
    return True, None


def exclude_non_common(tickers) -> tuple[list[str], dict[str, list[str]]]:
    """(kept, {reason: [dropped, ...]}). Phase 7.4.

    Measured on the live `all` universe (3002 names, 2026-09-06): zero removals. The
    guard is here so a warrant or a unit cannot enter unnoticed, not to change what
    the screener sees today.
    """
    kept: list[str] = []
    dropped: dict[str, list[str]] = {}
    for t in tickers or []:
        ok, reason = classify_symbol(t)
        if ok:
            kept.append(str(t).strip().upper())
        else:
            dropped.setdefault(str(reason), []).append(str(t))
    return sorted(set(kept)), {k: sorted(set(v)) for k, v in dropped.items()}


def duplicate_share_classes(tickers) -> dict[str, list[str]]:
    """Symbols that are the same security under two spellings, e.g. BRK-B and BRK.B.

    Yahoo uses `BRK-B`; the Wikipedia tables use `BRK.B`. Both in one universe is one
    company counted twice, and two price series for one position.
    """
    by_root: dict[str, set[str]] = {}
    for t in tickers or []:
        s = str(t).strip().upper()
        root = s.replace(".", "-")
        by_root.setdefault(root, set()).add(s)
    return {r: sorted(v) for r, v in sorted(by_root.items()) if len(v) > 1}


def universe_report(key: str, tickers, *, date=None, source: str | None = None,
                    fallback_used: bool = False, requested: int | None = None) -> dict:
    """The full documented record of one effective universe (phase 7.2/7.3/7.5/7.6).

    source, definition, date, membership method, exclusions, coverage and hash, plus
    the bias statements and whether this is a proxy.
    """
    try:
        meta = describe(key)
    except KeyError:
        meta = {"key": str(key), "label": str(key), "kind": FALLBACK,
                "source": "unknown", "definition": "unregistered universe",
                "membership_method": "unknown", "exclusions": "unknown",
                "biases": (SURVIVORSHIP, LOOK_AHEAD), "caveats": ("not in the registry",)}
    names = sorted({str(t).strip().upper() for t in (tickers or []) if str(t).strip()})
    kept, dropped = exclude_non_common(names)
    dupes = duplicate_share_classes(names)
    return {
        "key": meta["key"],
        "label": meta["label"],
        "kind": meta["kind"],
        "is_proxy": meta["kind"] == PROXY,
        "source": source or meta["source"],
        "definition": meta["definition"],
        "membership_method": meta["membership_method"],
        "exclusions": meta["exclusions"],
        "date": None if date is None else str(date),
        "n": len(names),
        "n_after_exclusions": len(kept),
        "excluded": dropped,
        "duplicate_share_classes": dupes,
        "coverage": None if not requested else round(len(names) / int(requested), 4),
        "sha256": sha256_json(names),
        "fallback_used": bool(fallback_used),
        "biases": list(meta["biases"]),
        "caveats": list(meta.get("caveats") or ()),
    }


def format_report(report: dict) -> str:
    lines = [
        f"universe: {report['label']}  [{report['kind']}]"
        + ("  (PROXY — not the index it is named after)" if report["is_proxy"] else ""),
        f"  key            {report['key']}",
        f"  source         {report['source']}",
        f"  definition     {report['definition']}",
        f"  method         {report['membership_method']}",
        f"  exclusions     {report['exclusions']}",
        f"  date           {report['date']}",
        f"  names          {report['n']}"
        + (f" ({report['n_after_exclusions']} after exclusions)"
           if report["n_after_exclusions"] != report["n"] else ""),
        f"  sha256         {report['sha256']}",
        f"  fallback used  {report['fallback_used']}",
    ]
    if report["coverage"] is not None:
        lines.append(f"  coverage       {report['coverage']:.1%}")
    for reason, names in sorted((report["excluded"] or {}).items()):
        lines.append(f"  excluded [{reason}] {len(names)}: {', '.join(names[:8])}")
    for root, spellings in sorted((report["duplicate_share_classes"] or {}).items()):
        lines.append(f"  duplicate share class {root}: {', '.join(spellings)}")
    for note in report["biases"]:
        lines.append(f"  BIAS  {note}")
    for note in report["caveats"]:
        lines.append(f"  NOTE  {note}")
    return "\n".join(lines)
