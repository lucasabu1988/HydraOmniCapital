"""TASK-428: explicit list of columns the 423 cut cannot see.

The free Russell record does not take a name out mid-year, so last_membership_date
stays at 2027-06-25 for anyone still on the latest June list. A date cut cannot
separate two companies glued under one ticker. This file is the measured list,
not a heuristic.

Reviewed 2026-09-11 against the written panel and public filings. Five of Claude's
seven are ordinary 2026 M&A / ticker-change deaths (one company, last bar = event
date). Two are TASK-325 reuse. Those two come **out of the panel**.
"""
from __future__ import annotations

# ticker -> evidence. `drop` means the column is two companies; omit from prices.
REVIEWED = {
    "AVB": {
        "drop": False,
        "last_bar": "2026-08-14",
        "last_membership": "2027-06-25",
        "in_delisted_list": True,
        "why": "AvalonBay merged into VMRK 2026-08-17 (Form 25). Last trade 2026-08-14. "
               "One company, recent death. Keep.",
    },
    "EQR": {
        "drop": False,
        "last_bar": "2026-08-17",
        "last_membership": "2027-06-25",
        "in_delisted_list": True,
        "why": "Equity Residential merged into the same VMRK 2026-08-17. Last bar is "
               "the merger session. Keep.",
    },
    "WBS": {
        "drop": False,
        "last_bar": "2026-08-19",
        "last_membership": "2027-06-25",
        "in_delisted_list": True,
        "why": "Webster Financial acquired by SAN, delisted 2026-08-20. Last trade "
               "2026-08-19. Keep.",
    },
    "MDV": {
        "drop": False,
        "last_bar": "2026-08-12",
        "last_membership": "2027-06-25",
        "in_delisted_list": True,
        "why": "Modiv Industrial merged into GNL 2026-08-12. Last trade 2026-08-11. Keep.",
    },
    "ISSC": {
        "drop": False,
        "last_bar": "2026-08-17",
        "last_membership": "2027-06-25",
        "in_delisted_list": True,
        "why": "Innovative Aerosystems renamed ticker ISSC -> IA on 2026-08-18; CUSIP "
               "unchanged. Same company. Keep.",
    },
    "BBBY": {
        "drop": True,
        "last_bar": "2026-09-04",
        "last_membership": "2027-06-25",
        "in_delisted_list": True,
        "why": "Bed Bath & Beyond bankrupt; ticker reused (TASK-325). Drop.",
    },
    "SBNY": {
        "drop": True,
        "last_bar": "2026-09-10",
        "last_membership": "2027-06-25",
        "in_delisted_list": False,
        "why": "Signature Bank; ticker reused on PINK. Not on EODHD delisted list, "
               "which is why a delisted-list heuristic misses it. Drop.",
    },
}

DROP = frozenset(k for k, v in REVIEWED.items() if v["drop"])
KEEP = frozenset(k for k, v in REVIEWED.items() if not v["drop"])


def is_dropped(symbol: str) -> bool:
    return str(symbol) in DROP
