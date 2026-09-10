"""TASK-411 half (b) — H-005 on the LIVE path: how often production's forward fill would reset
the write-off clock, measured on the frame `data.fetch` actually hands the engine.

Half (a) (`stale_policy_ab.py`) measured the effect on the PIT panel by re-creating the fill.
This half uses the real thing: `portfolio_v9.fetch_v9_market()` downloads the production
universe over V9["price_period"] exactly as `daily.py` does, and `data.fetch` attaches the
per-cell `attrs["observed"]` mask (ASTRA-03) that says which closes printed and which were
carried by `ffill(limit=FFILL_LIMIT_BARS)`.

What is counted (per ticker, on the downloaded frame):
  * a GAP is a maximal run of bars with no print, between two prints or trailing at the end;
  * `hidden`   gaps of length <= FFILL_LIMIT_BARS: filled entirely, `age_stale` never sees a
               NaN, the write-off clock never starts (a "reset" per filled bar under H-005);
  * `delayed`  gaps longer than the limit: the first FFILL_LIMIT_BARS bars are filled, so the
               clock starts that many bars late and any write-off lands that many bars late;
  * `trailing` a gap that reaches the last bar (a name that stopped printing): the case where
               the delay is money, because the write-off books at `last_px`, which the fill
               has just rewritten to the last carried value.
  * for the names in the live book (held or pending) the same counts, separately.

Only measures. Changing the policy is rule 6 (it moves write-offs, history and cash).

Usage (network):
    python experiments/stale_policy_live.py --json experiments/_lab_scratch/task411b.json
Offline, from a saved frame:
    python experiments/stale_policy_live.py --from-pickle path/to/prices.pkl
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # TASK-380: cp1252 consoles

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from data.fetch import FFILL_LIMIT_BARS, observed_mask  # noqa: E402


def gaps_for(observed: pd.Series) -> list[dict]:
    """Maximal runs of non-prints in one ticker's observed mask, after its first print.

    Bars before the first print are not a gap (the name was not listed yet). A run that
    reaches the last bar is `trailing`.
    """
    obs = observed.fillna(False).astype(bool).to_numpy()
    if not obs.any():
        return []
    first = int(np.argmax(obs))
    out: list[dict] = []
    start = None
    for i in range(first, len(obs)):
        if not obs[i] and start is None:
            start = i
        elif obs[i] and start is not None:
            out.append(dict(start=start, length=i - start, trailing=False))
            start = None
    if start is not None:
        out.append(dict(start=start, length=len(obs) - start, trailing=True))
    return out


def classify(observed: pd.DataFrame, limit: int = FFILL_LIMIT_BARS,
             book_names: set[str] | None = None) -> dict:
    """Counts per class over the whole frame and over the live book's names."""
    book_names = set(book_names or ())
    totals = dict(tickers=int(observed.shape[1]), bars=int(observed.shape[0]),
                  cells=int(observed.size), printed=int(observed.fillna(False).astype(bool).to_numpy().sum()))

    def _bucket(names) -> dict:
        b = dict(tickers=len(names), tickers_with_gap=0, gaps=0, hidden=0, delayed=0, trailing=0,
                 filled_bars=0, resets=0, delay_bars_max=0, hidden_lengths={}, examples=[])
        for t in names:
            gs = gaps_for(observed[t])
            if gs:
                b["tickers_with_gap"] += 1
            for g in gs:
                b["gaps"] += 1
                filled = min(g["length"], limit)
                b["filled_bars"] += filled
                b["resets"] += filled                     # every carried bar rewrites last_px
                if g["trailing"]:
                    b["trailing"] += 1
                    b["delay_bars_max"] = max(b["delay_bars_max"], filled)
                    if len(b["examples"]) < 12:
                        b["examples"].append(dict(ticker=str(t), kind="trailing", length=g["length"],
                                                  filled=filled, from_bar=str(observed.index[g["start"]].date())))
                elif g["length"] <= limit:
                    b["hidden"] += 1
                    b["hidden_lengths"][str(g["length"])] = b["hidden_lengths"].get(str(g["length"]), 0) + 1
                else:
                    b["delayed"] += 1
                    b["delay_bars_max"] = max(b["delay_bars_max"], filled)
                    if len(b["examples"]) < 12:
                        b["examples"].append(dict(ticker=str(t), kind="delayed", length=g["length"],
                                                  filled=filled, from_bar=str(observed.index[g["start"]].date())))
        return b

    names = [str(c) for c in observed.columns]
    return dict(ffill_limit_bars=int(limit), totals=totals, universe=_bucket(names),
                book=_bucket([n for n in names if n in book_names]),
                book_names_missing_from_frame=sorted(book_names - set(names)))


def _book_names(state_path: str) -> set[str]:
    try:
        with open(state_path, encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        return set()
    names = {str(o.get("ticker")) for o in (st.get("pending") or []) if o.get("ticker")}
    for sl in (st.get("sleeves") or {}).values():
        for tr in sl.get("tranches") or []:
            names.update(str(t) for t in (tr.get("units") or {}))
    return names


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="TASK-411 half (b): production's forward fill vs the write-off clock")
    ap.add_argument("--from-pickle", default=None, help="measure a saved price frame (with attrs['observed']) instead of downloading")
    ap.add_argument("--save-pickle", default=None, help="save the downloaded frame here for offline re-runs")
    ap.add_argument("--state", default=os.path.join(ROOT, "state", "portfolio_v9.json"))
    ap.add_argument("--json", default=None, help="write the full result to this path")
    args = ap.parse_args(argv)

    if args.from_pickle:
        prices = pd.read_pickle(args.from_pickle)
        source = dict(kind="pickle", path=args.from_pickle)
    else:
        import portfolio_v9 as V
        data = V.fetch_v9_market()
        prices = data["prices"]
        source = dict(kind="fetch_v9_market", universe=data["universe_effective"],
                      tickers_requested=len(data["universe_tickers"]),
                      report={k: data["stock_report"].get(k) for k in ("source", "fetched_at", "ffill_limit_bars",
                                                                        "requested", "downloaded")})
        if args.save_pickle:
            prices.to_pickle(args.save_pickle)
    observed = observed_mask(prices)
    if observed is None:
        print("no attrs['observed'] on the frame: this data.fetch predates ASTRA-03; nothing to measure", flush=True)
        return 2
    result = dict(source=source, first_bar=str(prices.index[0].date()), last_bar=str(prices.index[-1].date()),
                  **classify(observed, book_names=_book_names(args.state)))
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, default=str)
    t, u, b = result["totals"], result["universe"], result["book"]
    print(f"frame {t['tickers']} tickers x {t['bars']} bars ({result['first_bar']} -> {result['last_bar']}), "
          f"printed {t['printed']}/{t['cells']} cells, ffill limit {result['ffill_limit_bars']}", flush=True)
    for label, x in (("universe", u), ("live book", b)):
        print(f"{label}: {x['tickers']} tickers, {x['tickers_with_gap']} with a gap, {x['gaps']} gaps: "
              f"{x['hidden']} hidden (<= limit, clock never starts), {x['delayed']} delayed, {x['trailing']} trailing; "
              f"{x['filled_bars']} carried bars = {x['resets']} last_px rewrites; max delay {x['delay_bars_max']} bars; "
              f"hidden lengths {x['hidden_lengths']}", flush=True)
    for ex in u["examples"]:
        print(f"  {ex['kind']:8} {ex['ticker']:8} gap {ex['length']:3d} bars from {ex['from_bar']}, {ex['filled']} carried", flush=True)
    if result["book_names_missing_from_frame"]:
        print(f"live-book names not in the downloaded universe: {result['book_names_missing_from_frame']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
