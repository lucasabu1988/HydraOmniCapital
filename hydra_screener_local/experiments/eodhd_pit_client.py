"""TASK-403: the EODHD half of the Russell PIT panel - three functions wide, like Norgate.

`build_russell_pit.py` was written against a client that is deliberately three functions wide
(`symbols`, `membership`, `prices`) so that a second data source is one class, not a rewrite.
This is that class. What changes with EODHD is not the shape, it is where each half comes from:

| half | Norgate Platinum (630 USD/yr, not bought) | this client |
|---|---|---|
| membership | `index_constituent_timeseries` per name | the free public record, `russell_free_membership.py` |
| prices | `price_timeseries` per name | EODHD All World (`EODHDProvider`, bought 2026-09-11) |
| delisted identity | the `-YYYYMM` entity suffix | the delisted symbol list + the last bar |

The third row is the one that needs care. Norgate names a dead entity `AABA-201910`, so identity is
in the symbol and `is_delisted_symbol()` can read it. EODHD has no suffix: a code is either in the
delisted list or not, and **a code can be in that list and still print today** because the ticker
was reused - measured 2026-09-11, BBBY and SBNY both print to 2026-09-01 while the list calls them
delisted. Gluing those two companies into one column is exactly the defect TASK-325 paid for, so
this client reports them as identity problems and the builder (strict by default) refuses to write
a panel that contains one.

Membership is a Russell 3000 record, not per-index: `membership(sym, index_name)` returns the same
series for "Russell 1000" and "Russell 2000", and the builder's union over the two indexes is then
the record itself. That is honest for the panel's purpose (production trades the union) and it is
written down here because the Norgate path means something narrower by the same call.
"""
from __future__ import annotations

import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

MEMBERSHIP_CSV = os.path.join(HERE, "_lab_scratch", "russell_free",
                              "russell3000_membership_free.csv")
PANEL_START = "2005-01-01"
#: A code the delisted list calls dead but that still prints after this date is a reused ticker.
REUSE_CUTOFF = "2026-06-01"


def load_membership_record(path: str = MEMBERSHIP_CSV) -> pd.DataFrame:
    """The dated record as a `date x ticker` boolean frame.

    Accepts the long table `russell_free_membership.py` writes (`date, ticker, member, source`)
    and an already-wide frame. The record is a sequence of reconstitution snapshots, not a daily
    series: the builder only ever asks "was this name a member on this date", so the snapshot
    dates are the panel's membership dates and nothing is interpolated between them here.
    """
    if isinstance(path, pd.DataFrame):
        table = path
    else:
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"no membership record at {path}. Build it first: "
                "python experiments/russell_free_membership.py --fetch "
                "(it writes russell3000_membership_free.csv into _lab_scratch/russell_free/)"
            )
        table = pd.read_csv(path)
    cols = {c.lower(): c for c in table.columns}
    if {"date", "ticker"} <= set(cols):
        member = cols.get("member")
        long = table.rename(columns={cols["date"]: "date", cols["ticker"]: "ticker"})
        long["date"] = pd.to_datetime(long["date"], errors="coerce")
        long = long.dropna(subset=["date"])
        # int, not bool: an object-dtype pivot with fill_value raises the pandas downcast warning.
        long["_m"] = (pd.to_numeric(long[member], errors="coerce").fillna(0).astype(int)
                      if member else 1)
        wide = (long.pivot_table(index="date", columns="ticker", values="_m",
                                 aggfunc="max", fill_value=0) > 0)
        wide.index = pd.DatetimeIndex(wide.index)
        return wide.sort_index()
    wide = table.copy()
    wide.index = pd.DatetimeIndex(wide.index)
    return wide.astype(bool).sort_index()


class EodhdClient:
    """Three functions wide, plus the two identity hooks the builder asks for optionally."""

    def __init__(self, provider, membership=None, *, delisted=None,
                 start: str = PANEL_START, end=None, reuse_cutoff: str = REUSE_CUTOFF,
                 symbols=None, hold_between_reconstitutions: bool = True):
        self.provider = provider
        self.record = load_membership_record(
            membership if membership is not None else MEMBERSHIP_CSV)
        self.start = start
        self.end = end
        self.reuse_cutoff = reuse_cutoff
        self._symbols = list(symbols) if symbols is not None else None
        self._delisted = dict(delisted) if delisted is not None else None
        self._last_bar: dict[str, pd.Timestamp] = {}
        self.hold_between_reconstitutions = bool(hold_between_reconstitutions)
        self._daily_index = None

    def _hold_index(self) -> pd.DatetimeIndex:
        """Business days from the first snapshot to one reconstitution past the last one."""
        if self._daily_index is None:
            first = self.record.index[0]
            last = self.record.index[-1] + pd.DateOffset(years=1)
            if self.end is not None:
                last = min(last, pd.Timestamp(self.end))
            self._daily_index = pd.bdate_range(first, max(last, first))
        return self._daily_index

    # --- the three functions ---------------------------------------------------------
    def symbols(self, watchlist=None) -> list[str]:
        """Every ticker that was ever a member in the record. `watchlist` is Norgate's word."""
        if self._symbols is not None:
            return list(self._symbols)
        return sorted(c for c in self.record.columns if bool(self.record[c].any()))

    def membership(self, symbol: str, index_name: str | None = None) -> pd.Series:
        """Boolean series for one name. The record is Russell 3000: `index_name` is ignored.

        The record holds 16 June snapshots, so it is stepped forward to business days: a name in
        the June 2022 list is a member until the June 2023 list says otherwise. Without this the
        panel would have ~16 eligible days per name per decade instead of ~252 a year - measured
        on the first bounded probe, `members_first_day` and `members_last_day` both came back 0.
        What the record cannot do is take a name out mid-year (M&A, bankruptcy: the June PDFs list
        reconstitution deletions only), and the panel does not pretend otherwise. A name that died
        in March still has no price after March, so it cannot be selected - it shows up as a
        missing cell in `cell_coverage`, which is exactly where an honest panel puts it.
        """
        if symbol not in self.record.columns:
            return pd.Series(dtype=bool)
        snaps = self.record[symbol].astype(bool)
        if not self.hold_between_reconstitutions:
            return snaps
        idx = self._hold_index()
        # float, not bool: reindexing a bool series makes it object, and ffill on object dtype
        # is the deprecated pandas downcast path.
        held = snaps.astype(float).reindex(idx.union(snaps.index)).ffill().fillna(0.0)
        return (held.reindex(idx) > 0).astype(bool)

    def prices(self, symbol: str) -> pd.DataFrame:
        """`Open / Close / Adjusted Close / Volume` indexed by date, the builder's column names.

        `Close` is as printed and `Adjusted Close` carries splits and dividends - the
        `close_raw` / `close` pair the lab cache stores, and the reason the `close_raw` trap
        (83.6% cell coverage, TASK-403) is measurable on this panel at all.
        """
        long = self.provider.fetch([symbol], self.start, self.end)
        if long is None or not len(long):
            return pd.DataFrame()
        long = long[long["ticker"] == symbol] if "ticker" in long.columns else long
        if not len(long):
            return pd.DataFrame()
        idx = pd.DatetimeIndex(pd.to_datetime(long["date"]))
        out = pd.DataFrame({
            "Close": pd.to_numeric(long["close_raw"], errors="coerce").to_numpy(),
            "Adjusted Close": pd.to_numeric(long["close_adj"], errors="coerce").to_numpy(),
            "Volume": pd.to_numeric(long["volume"], errors="coerce").to_numpy(),
        }, index=idx).sort_index()
        out["Open"] = out["Close"]        # EODHD returns open; the panel does not use it yet
        self._last_bar[symbol] = out.index[-1] if len(out.index) else None
        return out

    # --- identity (optional hooks the builder uses when the client has them) ---------
    def delisted_codes(self) -> dict:
        """`{code: row}` from EODHD's delisted list, fetched once."""
        if self._delisted is None:
            self._delisted = self.provider.delisted()
        return self._delisted

    def is_delisted(self, symbol: str) -> bool:
        """Identity from the delisted list, never from the shape of the symbol."""
        return str(symbol) in self.delisted_codes()

    def reused_tickers(self, close: pd.DataFrame, cutoff=None) -> list[str]:
        """Codes the delisted list calls dead that still print after `cutoff`.

        Two companies under one ticker. Norgate keeps them apart with `-YYYYMM`; EODHD cannot,
        so the panel must not pretend it can. Measured examples: BBBY, SBNY.
        """
        cut = pd.Timestamp(cutoff or self.reuse_cutoff)
        dead = self.delisted_codes()
        out = []
        for sym in close.columns:
            if str(sym) not in dead:
                continue
            series = close[sym].dropna()
            if len(series) and pd.Timestamp(series.index[-1]) > cut:
                out.append(str(sym))
        return sorted(out)

    def identity_problems(self, close: pd.DataFrame) -> list[str]:
        """The builder appends these to its own guard failures."""
        reused = self.reused_tickers(close)
        if not reused:
            return []
        shown = ", ".join(reused[:10]) + ("..." if len(reused) > 10 else "")
        return [
            f"{len(reused)} delisted code(s) still printing after {self.reuse_cutoff}: {shown}. "
            "EODHD has no entity suffix, so each of these columns is two companies (TASK-325). "
            "Split them by the delisting date or drop them; do not merge."
        ]
