"""EODHD All World BarProvider (TASK-403): the prices Yahoo does not have.

Lucas bought EOD Historical Data All World on 2026-09-11, which replaces the *price* half of the
Norgate requirement: a random sample of Russell names that left the index priced at 17-27% on
Yahoo (`.comms/russell-pit-free-record-2026-09-10.md`), and the ones that matter most - the dead
ones - are exactly the misses. Measured here on 2026-09-11: TWTR 2013-11-07..2022-10-27,
SIVB ..2023-03-09, LEH ..2008-09-17, AABA ..2019-10-02.

Two endpoints, both verified against the live API before this file was written:

    GET /eod/<CODE>.US?from&to&period=d     -> [{date, open, high, low, close, adjusted_close, volume}]
    GET /exchange-symbol-list/US?delisted=1 -> [{Code, Name, Country, Exchange, Currency, Type, Isin}]

`close` is as printed and `adjusted_close` carries splits and dividends, which is the
`close_raw` / `close_adj` pair `BarProvider` and the lab cache already speak.

What the delisted list does NOT carry is a delisting date, and EODHD has no entity suffix
(Norgate's `-YYYYMM`). So a code can be in the delisted list *and* still print today, because the
ticker was reused - measured: BBBY and SBNY both print to 2026-09-01 (TASK-325). Identity for
those comes from the list plus the last bar, never from the symbol, and the PIT builder refuses to
merge them; see `experiments/build_russell_pit.py`.

The token lives in `hydra_screener_local/.env` as `EODHD_API_TOKEN` (gitignored). It is never
logged: every error message here goes through `_redact`.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd

SOURCE = "eodhd"
BASE = "https://eodhd.com/api"
TIMEOUT = 45
PAUSE = 0.0                       # 100_000 calls/day on the paid plan; no throttle needed per name
COMMON_TYPES = ("Common Stock",)  # the panel is equities; FUND / ETF / preferred are not members


class EodhdError(RuntimeError):
    """A call failed. The message never contains the token."""


def _redact(text, token: str | None) -> str:
    out = str(text)
    if token:
        out = out.replace(token, "<redacted>")
    return out


def resolve_token(token: str | None = None) -> str | None:
    """Explicit token, else EODHD_API_TOKEN from the environment or `.env`. None if absent."""
    if token:
        return str(token).strip()
    env = os.environ.get("EODHD_API_TOKEN")
    if env:
        return env.strip()
    try:
        from utils.env import load_hydra_env
        load_hydra_env()
    except Exception:                                    # noqa: BLE001 — no .env is not an error
        return None
    env = os.environ.get("EODHD_API_TOKEN")
    return env.strip() if env else None


class EODHDProvider:
    """`fetch()` is the BarProvider contract; `delisted()` is EODHD-specific identity."""

    source = SOURCE

    def __init__(self, token: str | None = None, *, base: str = BASE, opener=None,
                 timeout: int = TIMEOUT, pause: float = PAUSE):
        self.token = resolve_token(token)
        self.base = base.rstrip("/")
        self._opener = opener                  # injected in tests; None means urllib
        self.timeout = int(timeout)
        self.pause = float(pause)
        self.calls = 0
        self.last_errors: dict[str, str] = {}  # ticker -> why it has no bars

    # --- transport -------------------------------------------------------------------
    def _url(self, path: str, **q) -> str:
        q.setdefault("api_token", self.token or "")
        q.setdefault("fmt", "json")
        return f"{self.base}/{path.lstrip('/')}?" + urllib.parse.urlencode(q)

    def get(self, path: str, **q):
        """One call. Raises EodhdError with the token redacted."""
        if not self.token:
            raise EodhdError(
                "EODHD_API_TOKEN is not set. The All World plan is paid for (Lucas, 2026-09-11); "
                "put the token in hydra_screener_local/.env as EODHD_API_TOKEN (gitignored)."
            )
        url = self._url(path, **q)
        self.calls += 1
        try:
            if self._opener is not None:
                body = self._opener(url)
            else:
                with urllib.request.urlopen(url, timeout=self.timeout) as r:
                    body = r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300] if hasattr(e, "read") else ""
            raise EodhdError(_redact(f"HTTP {e.code} on {path}: {detail}", self.token)) from None
        except Exception as e:                           # noqa: BLE001 — network, DNS, timeout
            raise EodhdError(_redact(f"{type(e).__name__} on {path}: {e}", self.token)) from None
        if isinstance(body, (bytes, bytearray)):
            body = body.decode("utf-8", errors="replace")
        try:
            return json.loads(body) if isinstance(body, str) else body
        except json.JSONDecodeError as e:
            raise EodhdError(_redact(f"non-JSON answer on {path}: {e}", self.token)) from None

    # --- bars ------------------------------------------------------------------------
    def eod(self, ticker: str, start=None, end=None, *, suffix: str = "US") -> list[dict]:
        """Raw EOD rows for one code, oldest first. `[]` when the code has no history."""
        q = {"period": "d"}
        if start is not None:
            q["from"] = str(pd.Timestamp(start).date())
        if end is not None:
            q["to"] = str(pd.Timestamp(end).date())
        code = ticker if "." in ticker else f"{ticker}.{suffix}"
        rows = self.get(f"eod/{code}", **q)
        return list(rows) if isinstance(rows, list) else []

    def fetch(self, tickers, start, end) -> pd.DataFrame:
        """BarProvider: long frame `ticker, date, close_adj, close_raw, volume`.

        One call per name (the plan allows 100k/day). A name that fails is recorded in
        `last_errors` and is simply absent from the frame: a fetch never raises for one ticker,
        because a panel build over thousands of dead names must not die on one of them.
        """
        frames = []
        self.last_errors = {}
        names = list(tickers or [])
        for i, t in enumerate(names):
            try:
                rows = self.eod(t, start, end)
            except EodhdError as e:
                self.last_errors[str(t)] = str(e)
                continue
            if not rows:
                self.last_errors[str(t)] = "no rows"
                continue
            df = pd.DataFrame(rows)
            if "date" not in df.columns:
                self.last_errors[str(t)] = f"unexpected columns {sorted(df.columns)}"
                continue
            out = pd.DataFrame({
                "ticker": str(t),
                "date": pd.to_datetime(df["date"], errors="coerce"),
                "close_adj": pd.to_numeric(df.get("adjusted_close"), errors="coerce"),
                "close_raw": pd.to_numeric(df.get("close"), errors="coerce"),
                "volume": pd.to_numeric(df.get("volume"), errors="coerce"),
            })
            frames.append(out.dropna(subset=["date"]))
            if self.pause and i + 1 < len(names):
                time.sleep(self.pause)
        if not frames:
            return pd.DataFrame(columns=["ticker", "date", "close_adj", "close_raw", "volume"])
        return pd.concat(frames, ignore_index=True).sort_values(
            ["ticker", "date"], ignore_index=True)

    # --- identity --------------------------------------------------------------------
    def delisted(self, *, types=COMMON_TYPES, exchange: str = "US") -> dict[str, dict]:
        """`{code: row}` for every delisted US name of `types` (all types when `types` is None).

        Measured 2026-09-11: 60_062 rows for the US exchange, fields
        `Code, Name, Country, Exchange, Currency, Type, Isin`. There is **no delisting date** in
        this payload: the last bar of the series is what dates the death.
        """
        rows = self.get(f"exchange-symbol-list/{exchange}", delisted=1)
        keep = set(types) if types else None
        out = {}
        for r in rows if isinstance(rows, list) else []:
            code = (r or {}).get("Code")
            if not code:
                continue
            if keep is not None and r.get("Type") not in keep:
                continue
            out[str(code)] = dict(r)
        return out
