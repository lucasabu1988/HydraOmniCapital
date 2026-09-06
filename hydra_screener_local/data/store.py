"""TASK-361 — local SQLite bar store.

File: data_cache/bars.sqlite (gitignored). Nothing in production reads this until
config.USE_BAR_STORE is flipped; this module is the store, not the live fetch.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

_MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _MODULE_DIR.parent
DEFAULT_DB = PROJECT_ROOT / "data_cache" / "bars.sqlite"

_BARS_DDL = """
CREATE TABLE IF NOT EXISTS bars (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    close_adj REAL,
    close_raw REAL,
    volume REAL,
    source TEXT,
    fetched_at TEXT,
    PRIMARY KEY (ticker, date)
)
"""
_META_DDL = """
CREATE TABLE IF NOT EXISTS meta (
    ticker TEXT PRIMARY KEY,
    first TEXT,
    last TEXT,
    updated_at TEXT
)
"""
_ACTIONS_DDL = """
CREATE TABLE IF NOT EXISTS actions (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    dividend REAL,
    split REAL,
    PRIMARY KEY (ticker, date)
)
"""
_ACTCOV_DDL = """
CREATE TABLE IF NOT EXISTS actions_cov (
    ticker TEXT PRIMARY KEY,
    first TEXT,
    last TEXT,
    updated_at TEXT
)
"""
_ARCHIVE_DDL = """
CREATE TABLE IF NOT EXISTS bars_archive (
    snapshot TEXT NOT NULL,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    close_adj REAL,
    close_raw REAL,
    volume REAL,
    source TEXT,
    fetched_at TEXT,
    archived_at TEXT,
    reason TEXT,
    PRIMARY KEY (snapshot, ticker, date)
)
"""
_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    tickers_requested INTEGER,
    tail INTEGER,
    readjusted INTEGER,
    seconds REAL
)
"""


def _as_date_str(value) -> str:
    return str(_as_ts(value).date())


def _as_ts(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.normalize()


class BarStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else DEFAULT_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(_BARS_DDL)
        self._conn.execute(_META_DDL)
        self._conn.execute(_RUNS_DDL)
        self._conn.execute(_ACTIONS_DDL)      # TASK-385: dividends / splits from yfinance actions
        self._conn.execute(_ACTCOV_DDL)       # which date range each ticker's actions were asked for
        self._conn.execute(_ARCHIVE_DDL)      # audit phase 5.4: rollback for a destructive replace
        self._conn.execute("CREATE INDEX IF NOT EXISTS bars_date ON bars(date)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS archive_ticker ON bars_archive(ticker)")
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def upsert(self, long_frame: pd.DataFrame) -> int:
        """Insert-or-replace long bars (and actions + coverage when the frame carries them). Returns rows written."""
        rows = _rows_from_long(long_frame)
        if not rows:
            return 0
        self._upsert_actions(long_frame)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO bars "
                "(ticker, date, close_adj, close_raw, volume, source, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            tickers = sorted({r[0] for r in rows})
            placeholders = ",".join("?" * len(tickers))
            self._conn.execute(
                f"""
                INSERT INTO meta (ticker, first, last, updated_at)
                SELECT ticker, MIN(date), MAX(date), ? FROM bars
                WHERE ticker IN ({placeholders})
                GROUP BY ticker
                ON CONFLICT(ticker) DO UPDATE SET
                    first=excluded.first,
                    last=excluded.last,
                    updated_at=excluded.updated_at
                """,
                [now, *tickers],
            )
        return len(rows)

    def merge_ticker(self, ticker: str, long_frame: pd.DataFrame) -> int:
        """Upsert a ticker's bars without deleting anything (audit phase 5.3).

        The default backfill path: an existing range is extended, overlapping bars
        are refreshed, and bars outside the incoming frame are untouched. Returns
        rows written.
        """
        rows = _rows_from_long(long_frame)
        if not rows:
            return 0
        mine = [r for r in rows if r[0] == str(ticker)]
        if not mine:
            return 0
        return self.upsert(long_frame[long_frame[_ticker_col(long_frame)].astype(str) == str(ticker)])

    def stored_span(self, ticker: str) -> tuple[str | None, str | None, int]:
        """(first, last, n_bars) for a ticker, straight off the bars table."""
        row = self._conn.execute(
            "SELECT MIN(date), MAX(date), COUNT(*) FROM bars WHERE ticker=?", (str(ticker),)
        ).fetchone()
        if not row or not row[2]:
            return None, None, 0
        return row[0], row[1], int(row[2])

    def replace_ticker(self, ticker: str, long_frame: pd.DataFrame, *, min_bars: int = 10,
                       allow_shrink: bool = False, reason: str = "replace_ticker") -> int:
        """Replace a ticker's bars, archiving the old ones first.

        Refuses by default when the incoming frame does not cover the stored span.
        `min_bars` alone was not a guard: a 12-bar frame passed it and wiped 2800
        bars of history down to 12, silently (repro R-501). The old rows are copied
        into `bars_archive` inside the same transaction, so `restore_ticker()` can
        roll the change back (phase 5.4).

        Returns rows written, or 0 when the stored rows are kept.
        """
        t = str(ticker)
        rows = _rows_from_long(long_frame)
        dates = sorted({r[1] for r in rows})
        if len(dates) < int(min_bars):
            return 0
        first, last, n_bars = self.stored_span(t)
        if first is not None and not allow_shrink:
            # the incoming frame must cover at least the stored window
            if dates[0] > first or dates[-1] < last:
                return 0
        snapshot = None
        if n_bars:
            snapshot = self.archive_ticker(t, reason=reason)
        with self._conn:
            self._conn.execute("DELETE FROM bars WHERE ticker=?", (t,))
            self._conn.execute("DELETE FROM meta WHERE ticker=?", (t,))
            if _has_actions(long_frame):        # a full refetch with actions replaces the actions too
                self._conn.execute("DELETE FROM actions WHERE ticker=?", (t,))
                self._conn.execute("DELETE FROM actions_cov WHERE ticker=?", (t,))
        written = self.upsert(long_frame)
        if snapshot is not None:
            self._conn.execute(
                "UPDATE bars_archive SET reason=? WHERE snapshot=?",
                (f"{reason}; replaced {n_bars} bars ({first}..{last}) with {written}", snapshot))
            self._conn.commit()
        return written

    def replace_range(self, ticker: str, long_frame: pd.DataFrame, start, end, *,
                      reason: str = "replace_range") -> int:
        """Correct one window of a ticker's history, keeping everything outside it.

        Phase 5.5: fixing a bad stretch must not cost the rest of the series, nor the
        `actions` rows. The replaced window is archived first.
        """
        t = str(ticker)
        s, e = _as_date_str(start), _as_date_str(end)
        if e < s:
            raise ValueError(f"replace_range needs start <= end, got {s}..{e}")
        snapshot = self.archive_ticker(t, start=s, end=e, reason=reason)
        with self._conn:
            self._conn.execute("DELETE FROM bars WHERE ticker=? AND date>=? AND date<=?", (t, s, e))
        rows = _rows_from_long(long_frame)
        keep = [r for r in rows if r[0] == t and s <= r[1] <= e]
        if not keep:
            if snapshot:
                self.restore_ticker(snapshot)   # nothing usable arrived: put the window back
            return 0
        with self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO bars "
                "(ticker, date, close_adj, close_raw, volume, source, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                keep,
            )
        self._refresh_meta([t])
        return len(keep)

    def archive_ticker(self, ticker: str, *, start=None, end=None,
                       reason: str = "manual") -> str | None:
        """Copy a ticker's bars (optionally one window) into `bars_archive`.

        Returns the snapshot id, or None when there was nothing to archive.
        """
        t = str(ticker)
        snapshot = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + t
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        where = "ticker=?"
        params: list = [t]
        if start is not None:
            where += " AND date>=?"
            params.append(_as_date_str(start))
        if end is not None:
            where += " AND date<=?"
            params.append(_as_date_str(end))
        with self._conn:
            cur = self._conn.execute(
                f"INSERT INTO bars_archive "
                f"(snapshot, ticker, date, close_adj, close_raw, volume, source, fetched_at, archived_at, reason) "
                f"SELECT ?, ticker, date, close_adj, close_raw, volume, source, fetched_at, ?, ? "
                f"FROM bars WHERE {where}",
                [snapshot, now, str(reason), *params],
            )
        return snapshot if cur.rowcount else None

    def restore_ticker(self, snapshot: str) -> int:
        """Put an archived snapshot's bars back. The rollback half of phase 5.4."""
        rows = self._conn.execute(
            "SELECT ticker, date, close_adj, close_raw, volume, source, fetched_at "
            "FROM bars_archive WHERE snapshot=?", (str(snapshot),)
        ).fetchall()
        if not rows:
            return 0
        with self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO bars "
                "(ticker, date, close_adj, close_raw, volume, source, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        self._refresh_meta(sorted({r[0] for r in rows}))
        return len(rows)

    def archives(self, ticker: str | None = None) -> list[dict]:
        """What can be rolled back, newest first."""
        if ticker is None:
            cur = self._conn.execute(
                "SELECT snapshot, ticker, COUNT(*), MIN(date), MAX(date), MIN(archived_at), MIN(reason) "
                "FROM bars_archive GROUP BY snapshot, ticker ORDER BY snapshot DESC")
        else:
            cur = self._conn.execute(
                "SELECT snapshot, ticker, COUNT(*), MIN(date), MAX(date), MIN(archived_at), MIN(reason) "
                "FROM bars_archive WHERE ticker=? GROUP BY snapshot, ticker ORDER BY snapshot DESC",
                (str(ticker),))
        return [{"snapshot": r[0], "ticker": r[1], "n_bars": int(r[2]), "first": r[3],
                 "last": r[4], "archived_at": r[5], "reason": r[6]} for r in cur.fetchall()]

    def _refresh_meta(self, tickers: list[str]) -> None:
        if not tickers:
            return
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        placeholders = ",".join("?" * len(tickers))
        with self._conn:
            self._conn.execute(f"DELETE FROM meta WHERE ticker IN ({placeholders})", list(tickers))
            self._conn.execute(
                f"""
                INSERT INTO meta (ticker, first, last, updated_at)
                SELECT ticker, MIN(date), MAX(date), ? FROM bars
                WHERE ticker IN ({placeholders})
                GROUP BY ticker
                """,
                [now, *tickers],
            )

    def quality(self, tickers: list[str], *, calendar=None) -> pd.DataFrame:
        """Per-ticker data-quality metrics (audit phase 5.6).

        first, last, n_bars, gaps (missing sessions inside the stored span),
        duplicates, non-positive closes, provider and the last capture time. `calendar`
        is a DatetimeIndex of expected sessions; without one the gap count is measured
        against business days, which over-counts market holidays and is reported as
        such by `gap_basis`.
        """
        tickers = [str(t) for t in tickers]
        if not tickers:
            return pd.DataFrame(columns=[
                "ticker", "first", "last", "n_bars", "gaps", "duplicates",
                "non_positive", "sources", "last_fetched_at", "gap_basis"])
        placeholders = ",".join("?" * len(tickers))
        agg = {
            r[0]: r[1:]
            for r in self._conn.execute(
                f"SELECT ticker, MIN(date), MAX(date), COUNT(*), COUNT(DISTINCT date), "
                f"MAX(fetched_at), SUM(CASE WHEN close_adj IS NOT NULL AND close_adj <= 0 THEN 1 ELSE 0 END) "
                f"FROM bars WHERE ticker IN ({placeholders}) GROUP BY ticker", tickers)
        }
        srcs: dict[str, list[str]] = {}
        for tk, src in self._conn.execute(
            f"SELECT DISTINCT ticker, source FROM bars WHERE ticker IN ({placeholders})", tickers
        ):
            srcs.setdefault(str(tk), []).append("" if src is None else str(src))
        rows = []
        for t in tickers:
            first, last, n_rows, n_dates, fetched, non_pos = agg.get(t, (None, None, 0, 0, None, 0))
            gaps = None
            basis = "none"
            if first and last and n_dates:
                if calendar is not None:
                    idx = pd.DatetimeIndex(calendar).normalize()
                    expected = int(((idx >= pd.Timestamp(first)) & (idx <= pd.Timestamp(last))).sum())
                    basis = "calendar"
                else:
                    expected = len(pd.bdate_range(first, last))
                    basis = "bdays"
                gaps = max(0, expected - int(n_dates))
            rows.append({
                "ticker": t,
                "first": first,
                "last": last,
                "n_bars": int(n_dates or 0),
                "gaps": gaps,
                "duplicates": int((n_rows or 0) - (n_dates or 0)),
                "non_positive": int(non_pos or 0),
                "sources": ",".join(sorted({s for s in srcs.get(t, []) if s})) or None,
                "last_fetched_at": fetched,
                "gap_basis": basis,
            })
        return pd.DataFrame(rows)

    # ------------------------------------------------------------- actions (TASK-385)
    def _upsert_actions(self, long_frame: pd.DataFrame) -> int:
        """Non-zero dividends/splits -> `actions`; the frame's per-ticker date span -> `actions_cov`
        (asking Yahoo for actions over a range and getting none is coverage too)."""
        if not _has_actions(long_frame):
            return 0
        df = long_frame.copy()
        cols = {c.lower(): c for c in df.columns}
        tick = df[cols["ticker"]].astype(str)
        dates = pd.Series([_as_date_str(v) for v in df[cols["date"]]], index=df.index)
        div = pd.to_numeric(df[cols["dividend"]], errors="coerce").fillna(0.0) if "dividend" in cols else pd.Series(0.0, index=df.index)
        spl = pd.to_numeric(df[cols["split"]], errors="coerce").fillna(0.0) if "split" in cols else pd.Series(0.0, index=df.index)
        act_rows = [(t, d, float(dv) if dv else None, float(sp) if sp else None)
                    for t, d, dv, sp in zip(tick, dates, div, spl, strict=True) if (dv or sp)]
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        span = pd.DataFrame({"ticker": tick, "date": dates}).groupby("ticker")["date"].agg(["min", "max"])
        with self._conn:
            if act_rows:
                self._conn.executemany(
                    "INSERT OR REPLACE INTO actions (ticker, date, dividend, split) VALUES (?, ?, ?, ?)", act_rows)
            for t, row in span.iterrows():
                cur = self._conn.execute("SELECT first, last FROM actions_cov WHERE ticker=?", (str(t),)).fetchone()
                first = min(row["min"], cur[0]) if cur and cur[0] else row["min"]
                last = max(row["max"], cur[1]) if cur and cur[1] else row["max"]
                self._conn.execute(
                    "INSERT OR REPLACE INTO actions_cov (ticker, first, last, updated_at) VALUES (?, ?, ?, ?)",
                    (str(t), first, last, now))
        return len(act_rows)

    def dividends(self, tickers: list[str], start, end) -> dict[str, pd.Series]:
        """{ticker: Series ex_date -> dps} for dividends recorded in [start, end]."""
        return self._actions_col(tickers, start, end, "dividend")

    def splits(self, tickers: list[str], start, end) -> dict[str, pd.Series]:
        return self._actions_col(tickers, start, end, "split")

    def _actions_col(self, tickers, start, end, column) -> dict[str, pd.Series]:
        tickers = [str(t) for t in tickers]
        if not tickers:
            return {}
        placeholders = ",".join("?" * len(tickers))
        rows = self._conn.execute(
            f"SELECT ticker, date, {column} FROM actions WHERE ticker IN ({placeholders}) "
            f"AND date>=? AND date<=? AND {column} IS NOT NULL ORDER BY date",
            [*tickers, _as_date_str(start), _as_date_str(end)],
        ).fetchall()
        out: dict[str, dict] = {}
        for t, d, v in rows:
            out.setdefault(str(t), {})[pd.Timestamp(d)] = float(v)
        return {t: pd.Series(v, dtype=float).sort_index() for t, v in out.items()}

    def actions_coverage(self, tickers: list[str] | None = None) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
        if tickers is not None:
            tickers = [str(t) for t in tickers]
            if not tickers:
                return {}
            placeholders = ",".join("?" * len(tickers))
            cur = self._conn.execute(
                f"SELECT ticker, first, last FROM actions_cov WHERE ticker IN ({placeholders})", tickers)
        else:
            cur = self._conn.execute("SELECT ticker, first, last FROM actions_cov")
        return {str(t): (_as_ts(f), _as_ts(la)) for t, f, la in cur.fetchall() if f and la}

    def closes(
        self,
        tickers: list[str],
        start,
        end,
        adjusted: bool = True,
    ) -> pd.DataFrame:
        col = "close_adj" if adjusted else "close_raw"
        return self._wide(tickers, start, end, col)

    def volumes(self, tickers: list[str], start, end) -> pd.DataFrame:
        return self._wide(tickers, start, end, "volume")

    def coverage(self, tickers: list[str], asof) -> pd.DataFrame:
        tickers = [str(t) for t in tickers]
        asof_s = _as_date_str(asof)
        if not tickers:
            return pd.DataFrame(columns=["ticker", "first", "last", "n_bars", "has_asof"])
        placeholders = ",".join("?" * len(tickers))
        stats = {
            r[0]: r[1:]
            for r in self._conn.execute(
                f"SELECT ticker, MIN(date), MAX(date), COUNT(*) FROM bars "
                f"WHERE ticker IN ({placeholders}) GROUP BY ticker",
                tickers,
            )
        }
        present = {
            r[0]
            for r in self._conn.execute(
                f"SELECT ticker FROM bars WHERE date=? AND ticker IN ({placeholders})",
                [asof_s, *tickers],
            )
        }
        rows = []
        for t in tickers:
            first, last, n = stats.get(t, (None, None, 0))
            rows.append(
                {
                    "ticker": t,
                    "first": first,
                    "last": last,
                    "n_bars": int(n or 0),
                    "has_asof": t in present,
                }
            )
        return pd.DataFrame(rows)

    def last_dates(self, tickers: list[str] | None = None) -> dict[str, pd.Timestamp]:
        if tickers is not None:
            tickers = [str(t) for t in tickers]
            if not tickers:
                return {}
            placeholders = ",".join("?" * len(tickers))
            cur = self._conn.execute(
                f"SELECT ticker, MAX(date) FROM bars WHERE ticker IN ({placeholders}) GROUP BY ticker",
                tickers,
            )
        else:
            cur = self._conn.execute("SELECT ticker, MAX(date) FROM bars GROUP BY ticker")
        return {str(t): _as_ts(d) for t, d in cur.fetchall() if d}

    def overlap_start(self, ticker: str, n: int = 10) -> pd.Timestamp | None:
        """Earliest of the last `n` stored dates (the overlap window start)."""
        dates = [
            r[0]
            for r in self._conn.execute(
                "SELECT date FROM bars WHERE ticker=? ORDER BY date DESC LIMIT ?",
                (str(ticker), int(n)),
            )
        ]
        if not dates:
            return None
        return _as_ts(min(dates))

    def record_run(self, *, tickers_requested: int, tail: int, readjusted: int, seconds: float) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._conn:
            self._conn.execute(
                "INSERT INTO runs (date, tickers_requested, tail, readjusted, seconds) VALUES (?,?,?,?,?)",
                (now, int(tickers_requested), int(tail), int(readjusted), float(seconds)),
            )

    def last_run(self) -> dict | None:
        row = self._conn.execute(
            "SELECT date, tickers_requested, tail, readjusted, seconds FROM runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return {
            "date": row[0],
            "tickers_requested": int(row[1] or 0),
            "tail": int(row[2] or 0),
            "readjusted": int(row[3] or 0),
            "seconds": float(row[4] or 0.0),
        }

    def sample_tickers(self, n: int) -> list[str]:
        names = [r[0] for r in self._conn.execute("SELECT ticker FROM meta ORDER BY ticker")]
        if n >= len(names):
            return names
        import random
        return random.sample(names, int(n))

    def stats(self) -> dict:
        n_tickers = self._conn.execute("SELECT COUNT(*) FROM meta").fetchone()[0]
        n_bars, first, last = self._conn.execute(
            "SELECT COUNT(*), MIN(date), MAX(date) FROM bars"
        ).fetchone()
        size = self.path.stat().st_size if self.path.exists() else 0
        last_run = self.last_run()
        n_actions = self._conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
        n_cov = self._conn.execute("SELECT COUNT(*) FROM actions_cov").fetchone()[0]
        n_arch = self._conn.execute("SELECT COUNT(DISTINCT snapshot) FROM bars_archive").fetchone()[0]
        n_dupe = self._conn.execute(
            "SELECT COUNT(*) - COUNT(DISTINCT ticker || '|' || date) FROM bars").fetchone()[0]
        n_nonpos = self._conn.execute(
            "SELECT COUNT(*) FROM bars WHERE close_adj IS NOT NULL AND close_adj <= 0").fetchone()[0]
        return {
            "path": str(self.path),
            "tickers": int(n_tickers or 0),
            "bars": int(n_bars or 0),
            "actions": int(n_actions or 0),
            "actions_covered_tickers": int(n_cov or 0),
            "first": first,
            "last": last,
            "size_bytes": int(size),
            "readjusted_last_run": None if last_run is None else last_run["readjusted"],
            "last_run": last_run,
            "archived_snapshots": int(n_arch or 0),
            "duplicate_rows": int(n_dupe or 0),
            "non_positive_closes": int(n_nonpos or 0),
        }

    def vacuum(self) -> None:
        self._conn.execute("VACUUM")
        try:
            self._conn.execute("PRAGMA optimize")
        except sqlite3.Error:
            pass

    def _wide(self, tickers: list[str], start, end, column: str) -> pd.DataFrame:
        tickers = [str(t) for t in tickers]
        if not tickers:
            return pd.DataFrame()
        start_s, end_s = _as_date_str(start), _as_date_str(end)
        placeholders = ",".join("?" * len(tickers))
        rows = self._conn.execute(
            f"SELECT ticker, date, {column} FROM bars "
            f"WHERE ticker IN ({placeholders}) AND date>=? AND date<=? "
            f"ORDER BY date, ticker",
            [*tickers, start_s, end_s],
        ).fetchall()
        if not rows:
            return pd.DataFrame(columns=tickers)
        frame = pd.DataFrame(rows, columns=["ticker", "date", column])
        frame["date"] = pd.to_datetime(frame["date"])
        wide = frame.pivot(index="date", columns="ticker", values=column)
        wide.index = pd.DatetimeIndex(wide.index).tz_localize(None)
        ordered = [t for t in tickers if t in wide.columns]
        return wide.reindex(columns=ordered).sort_index()


def _ticker_col(long_frame: pd.DataFrame) -> str:
    for c in long_frame.columns:
        if str(c).lower() == "ticker":
            return c
    raise ValueError("long_frame needs a ticker column")


def _has_actions(long_frame: pd.DataFrame) -> bool:
    if long_frame is None or getattr(long_frame, "empty", True):
        return False
    cols = {str(c).lower() for c in long_frame.columns}
    return bool({"dividend", "split"} & cols)


def _rows_from_long(long_frame: pd.DataFrame) -> list[tuple]:
    if long_frame is None or getattr(long_frame, "empty", True):
        return []
    df = long_frame.copy()
    cols = {c.lower(): c for c in df.columns}
    if "ticker" not in cols or "date" not in cols:
        raise ValueError("long_frame needs ticker and date columns")

    def col(*names):
        for n in names:
            if n in cols:
                return df[cols[n]]
        return pd.Series([None] * len(df), index=df.index)

    tickers = df[cols["ticker"]].astype(str)
    dates = [_as_date_str(v) for v in df[cols["date"]]]
    adj = pd.to_numeric(col("close_adj"), errors="coerce")
    raw = pd.to_numeric(col("close_raw"), errors="coerce")
    vol = pd.to_numeric(col("volume"), errors="coerce")
    source = col("source")
    fetched = col("fetched_at")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for i in range(len(df)):
        t = tickers.iloc[i].strip()
        if not t or t in ("nan", "None"):
            continue
        a = adj.iloc[i]
        r = raw.iloc[i]
        if pd.isna(a) and pd.isna(r):
            continue
        src = source.iloc[i]
        fat = fetched.iloc[i]
        rows.append(
            (
                t,
                dates[i],
                None if pd.isna(a) else float(a),
                None if pd.isna(r) else float(r),
                None if pd.isna(vol.iloc[i]) else float(vol.iloc[i]),
                "" if src is None or (isinstance(src, float) and pd.isna(src)) else str(src),
                now if fat is None or (isinstance(fat, float) and pd.isna(fat)) or str(fat) in ("", "nan") else str(fat),
            )
        )
    return rows


def upsert(long_frame: pd.DataFrame, *, store: BarStore | None = None) -> int:
    return (store or BarStore()).upsert(long_frame)


def closes(tickers, start, end, adjusted: bool = True, *, store: BarStore | None = None) -> pd.DataFrame:
    return (store or BarStore()).closes(tickers, start, end, adjusted=adjusted)


def volumes(tickers, start, end, *, store: BarStore | None = None) -> pd.DataFrame:
    return (store or BarStore()).volumes(tickers, start, end)


def coverage(tickers, asof, *, store: BarStore | None = None) -> pd.DataFrame:
    return (store or BarStore()).coverage(tickers, asof)


def last_dates(tickers=None, *, store: BarStore | None = None) -> dict[str, pd.Timestamp]:
    return (store or BarStore()).last_dates(tickers)


def quality(tickers, *, calendar=None, store: BarStore | None = None) -> pd.DataFrame:
    return (store or BarStore()).quality(tickers, calendar=calendar)
