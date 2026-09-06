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
        self._conn.execute("CREATE INDEX IF NOT EXISTS bars_date ON bars(date)")
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
        """Insert-or-replace long bars. Returns rows written."""
        rows = _rows_from_long(long_frame)
        if not rows:
            return 0
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

    def replace_ticker(self, ticker: str, long_frame: pd.DataFrame, *, min_bars: int = 10) -> int:
        """Replace a ticker's bars. Refuses empty or shorter-than-overlap frames
        so a bad Yahoo batch cannot wipe stored history (TASK-376). Returns 0
        when the stored rows are kept."""
        t = str(ticker)
        rows = _rows_from_long(long_frame)
        n_dates = len({r[1] for r in rows})
        if n_dates < int(min_bars):
            return 0
        with self._conn:
            self._conn.execute("DELETE FROM bars WHERE ticker=?", (t,))
            self._conn.execute("DELETE FROM meta WHERE ticker=?", (t,))
        return self.upsert(long_frame)

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
        return {
            "path": str(self.path),
            "tickers": int(n_tickers or 0),
            "bars": int(n_bars or 0),
            "first": first,
            "last": last,
            "size_bytes": int(size),
            "readjusted_last_run": None if last_run is None else last_run["readjusted"],
            "last_run": last_run,
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
