"""ASTRA-03 — an execution price is a price that printed on that date, or there is no fill.

Ported from the external audit (Astra, 2026-09-06). The three probes below are the audit's own
assertions; the rest are regression guards for the three ways the settle path used to invent a
price: the `frame.iloc[-1]` fallback, the ETF forward fill, and a dividend that goes ex after the
execution bar. No network: every frame is synthetic.
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import portfolio_v9 as V                                    # noqa: E402
import preflight as PF                                      # noqa: E402
import utils.trading_calendar as TC                         # noqa: E402
from config import V9                                       # noqa: E402
from core import portfolio_engine as E                       # noqa: E402
from core.dividends import apply_dividends                   # noqa: E402
from data import fetch as F                                  # noqa: E402
from data.adjust import adjust, deadjust_factor, printed_close  # noqa: E402

ETF = list(V9["etf_universe"])


# ----------------------------------------------------------------- the three audit probes
def test_missing_historical_execution_row_never_uses_future():
    """Astra probe, verbatim. Rows 09-11 and 09-15; asking for 09-14 returned the 09-15 close."""
    frame = pd.DataFrame({'AAA': [20., 99.]}, index=pd.to_datetime(['2026-09-11', '2026-09-15']))
    assert pd.isna(V._row(frame, '2026-09-14').get('AAA')), V._row(frame, '2026-09-14').to_dict()


def test_historical_etf_gap_never_becomes_a_fill(monkeypatch):
    """Astra probe, verbatim. A ffilled ETF hole must not become a fill at the stale close."""
    idx = pd.to_datetime(['2026-09-11', '2026-09-14', '2026-09-15'])
    raw = pd.DataFrame({'AAA': [20., np.nan, 22.]}, index=idx)
    monkeypatch.setattr(F, '_download_close_batch', lambda *a, **kw: raw.copy())
    report = {}
    px = F._fetch_closes(['AAA'], '2y', auto_adjust=True, report=report, label='audit fixture')
    s = E.new_state(8000, '2026-09-11')
    s['pending'] = [dict(planned='2026-09-11', sleeve='etf', tranche=0,
                         ticker='AAA', side='buy', dollars=200., cost_bp=0.)]
    fills = E.settle(s, '2026-09-14', pd.Series(dtype=float), V._row(px, '2026-09-14'))
    assert fills[0]['status'] == 'not_filled', {'fill': fills[0], 'report': report}
    # the signal frame keeps the carried close: this fix must not change any ranking input
    assert px.loc['2026-09-14', 'AAA'] == pytest.approx(20.0)


def test_late_settlement_does_not_double_count_future_dividend():
    """Astra probe. Assertion kept verbatim; the execution price now comes from `V._row`, which
    is where production gets it — the probe hand-picked `adjusted.iloc[0]`, i.e. exactly the
    total-return close this fix refuses to book a fill at."""
    idx = pd.to_datetime(['2026-09-14', '2026-09-15'])
    raw = pd.Series([100., 99.], index=idx)
    adjusted = adjust(raw, dividends={'2026-09-15': 1.})
    assert adjusted.iloc[0] == pytest.approx(99.0)           # the price that never printed
    divs = [dict(ticker='AAA', ex_date='2026-09-15', dps=1.)]
    s = E.new_state(8000, '2026-09-11')
    s['last_run_date'] = '2026-09-11'
    s['pending'] = [dict(planned='2026-09-11', sleeve='stocks', tranche=0,
                         ticker='AAA', side='buy', dollars=1000., cost_bp=0.)]
    E.settle(s, '2026-09-14', V._row(adjusted.to_frame('AAA'), '2026-09-14', divs),
             pd.Series(dtype=float))
    apply_dividends(s, divs, '2026-09-15')
    tr = s['sleeves']['stocks']['tranches'][0]
    actual_value = tr['units']['AAA'] * 99. + tr['cash']
    assert actual_value == pytest.approx(1000.), (actual_value, tr)


# ----------------------------------------------------------------- _row regressions
def test_row_returns_the_bar_asked_for_and_nothing_else():
    idx = pd.to_datetime(['2026-09-11', '2026-09-14', '2026-09-15'])
    frame = pd.DataFrame({'AAA': [10., 11., 12.], 'BBB': [20., 21., 22.]}, index=idx)
    assert V._row(frame, '2026-09-14').to_dict() == {'AAA': 11.0, 'BBB': 21.0}
    # before the first bar, after the last bar, and a weekend in between: all NaN, never a
    # neighbouring row (the old code returned frame.iloc[-1] for every one of these)
    for date in ('2026-09-01', '2026-09-12', '2026-09-30'):
        row = V._row(frame, date)
        assert list(row.index) == ['AAA', 'BBB'], row
        assert row.isna().all(), (date, row.to_dict())


def test_row_on_an_empty_frame_is_nan_not_an_exception():
    row = V._row(pd.DataFrame(columns=['AAA'], dtype=float), '2026-09-14')
    assert list(row.index) == ['AAA'] and row.isna().all()


def test_row_masks_a_forward_filled_cell_but_keeps_the_prints():
    idx = pd.to_datetime(['2026-09-11', '2026-09-14'])
    frame = pd.DataFrame({'AAA': [20., 20.], 'BBB': [30., 31.]}, index=idx)
    F.attach_observed(frame, pd.DataFrame({'AAA': [True, False], 'BBB': [True, True]}, index=idx))
    row = V._row(frame, '2026-09-14')
    assert pd.isna(row['AAA'])                              # carried, not printed
    assert row['BBB'] == pytest.approx(31.0)                # printed


def test_observation_mask_survives_the_etf_column_reorder(monkeypatch):
    """fetch_etf_closes reorders columns after _fetch_closes; the provenance must ride along."""
    idx = pd.to_datetime(['2026-09-11', '2026-09-14'])
    raw = pd.DataFrame({t: [100.0, (np.nan if t == ETF[0] else 101.0)] for t in reversed(ETF)},
                       index=idx)
    monkeypatch.setattr(F, '_download_close_batch', lambda *a, **kw: raw.copy())
    px = F.fetch_etf_closes(ETF, period='2y', report={})
    assert list(px.columns) == ETF
    mask = F.observed_mask(px)
    assert mask is not None
    row = V._row(px, '2026-09-14')
    assert pd.isna(row[ETF[0]]) and row[ETF[1]] == pytest.approx(101.0)


def test_row_without_provenance_still_trusts_notna():
    """A hand-built frame (no attrs) keeps working: unknown provenance is not "nothing printed"."""
    idx = pd.to_datetime(['2026-09-11', '2026-09-14'])
    frame = pd.DataFrame({'AAA': [20., 21.], 'BBB': [30., np.nan]}, index=idx)
    row = V._row(frame, '2026-09-14')
    assert row['AAA'] == pytest.approx(21.0) and pd.isna(row['BBB'])


# ----------------------------------------------------------------- total-return de-adjustment
def test_execution_row_is_the_printed_close_not_the_total_return_close():
    idx = pd.to_datetime(['2026-09-11', '2026-09-14', '2026-09-15'])
    raw = pd.Series([98., 100., 99.], index=idx)
    frame = adjust(raw, dividends={'2026-09-15': 1.}).to_frame('AAA')
    divs = [dict(ticker='AAA', ex_date='2026-09-15', dps=1.)]
    assert V._row(frame, '2026-09-14', divs)['AAA'] == pytest.approx(100.0)
    assert V._row(frame, '2026-09-11', divs)['AAA'] == pytest.approx(98.0)
    # the ex-date bar itself was never adjusted, so it must come back untouched
    assert V._row(frame, '2026-09-15', divs)['AAA'] == pytest.approx(99.0)
    # no dividend table -> the pre-fix behaviour, so the caller can see what it is opting into
    assert V._row(frame, '2026-09-14')['AAA'] == pytest.approx(99.0)


def test_deadjust_round_trips_two_compounding_dividends():
    idx = pd.bdate_range('2024-01-01', periods=6)
    raw = pd.Series([100., 102., 101., 103., 104., 105.], index=idx)
    divs = {'2024-01-03': 2.04, '2024-01-05': 1.03}
    adjusted = adjust(raw, dividends=divs)
    for d in idx:
        assert printed_close(adjusted, d, divs) == pytest.approx(raw.loc[d]), d
    assert deadjust_factor(adjusted, idx[-1], divs) == pytest.approx(1.0)
    assert pd.isna(printed_close(adjusted, '2024-01-06', divs))     # Saturday: no bar -> NaN


def test_dividend_after_the_last_bar_is_not_undone():
    """Yahoo cannot have priced in an ex-date it has no bar for; correcting it would invent one."""
    idx = pd.to_datetime(['2026-09-14', '2026-09-15'])
    frame = pd.DataFrame({'AAA': [100., 99.]}, index=idx)
    divs = [dict(ticker='AAA', ex_date='2026-09-16', dps=1.)]
    assert V._row(frame, '2026-09-14', divs)['AAA'] == pytest.approx(100.0)


def test_two_ex_dates_between_execution_and_today_are_both_undone():
    """A fix that only handles the nearest ex-date would pass the audit probe and still be wrong."""
    idx = pd.to_datetime(['2026-09-14', '2026-09-15', '2026-09-16', '2026-09-17'])
    raw = pd.Series([100.0, 99.0, 101.0, 100.5], index=idx)
    divs_map = {'2026-09-15': 1.0, '2026-09-17': 0.5}
    frame = adjust(raw, dividends=divs_map).to_frame('AAA')
    divs = [dict(ticker='AAA', ex_date=d, dps=v) for d, v in divs_map.items()]
    assert frame.loc['2026-09-14', 'AAA'] < 99.0             # both factors sit on the exec bar
    for date, expected in zip(idx, raw.tolist(), strict=True):
        assert V._row(frame, date, divs)['AAA'] == pytest.approx(expected), date
    s = E.new_state(8000, '2026-09-11')
    s['last_run_date'] = '2026-09-14'
    s['pending'] = [dict(planned='2026-09-11', sleeve='stocks', tranche=0, ticker='AAA',
                         side='buy', dollars=1000., cost_bp=0.)]
    E.settle(s, '2026-09-14', V._row(frame, '2026-09-14', divs), pd.Series(dtype=float))
    apply_dividends(s, divs, '2026-09-17')
    tr = s['sleeves']['stocks']['tranches'][0]
    assert tr['units']['AAA'] == pytest.approx(10.0)
    # 10 units at the 09-17 print of 100.5 + 10.00 + 5.00 of dividends = 1020.00, price return
    # only. Nothing here is counted twice: 1000 -> 1020 is (100.5 + 1.5) / 100 on 10 units.
    assert tr['units']['AAA'] * 100.5 + tr['cash'] == pytest.approx(1020.0)


def test_no_execution_price_ever_comes_from_another_bar():
    """Property guard: over a frame where every bar has a distinct price, the row for a date is
    that date's prices or NaN — never any other bar's. Catches any new `iloc[...]` fallback."""
    rng = np.random.default_rng(11)
    idx = pd.bdate_range('2026-01-01', periods=40)
    frame = pd.DataFrame(
        {f"T{i}": np.round(np.cumsum(rng.normal(1.0, 5.0, len(idx))) + 500 + 1000 * i, 6)
         for i in range(6)}, index=idx)
    holes = [(idx[7], "T0"), (idx[20], "T3"), (idx[-1], "T5")]
    for d, t in holes:
        frame.loc[d, t] = np.nan
    valid = {(str(pd.Timestamp(d).date()), c): frame.loc[d, c] for d in idx for c in frame.columns}
    probes = list(idx) + [pd.Timestamp('2025-12-25'), pd.Timestamp('2026-01-03'),
                          pd.Timestamp('2026-06-01')]
    for probe in probes:
        row = V._row(frame, probe)
        key = str(pd.Timestamp(probe).date())
        for ticker, value in row.items():
            if pd.isna(value):
                continue
            assert value == pytest.approx(valid[(key, ticker)]), (key, ticker, value)


def test_dividend_rows_accept_a_dataframe_and_add_up_same_day():
    table = pd.DataFrame([{'ticker': 'AAA', 'ex_date': '2026-09-15', 'dps': 0.5},
                          {'ticker': 'AAA', 'ex_date': '2026-09-15', 'dps': 0.5},
                          {'ticker': 'BBB', 'ex_date': '2026-09-15', 'dps': 0.0}])
    assert V._dividend_rows(table) == {'AAA': {'2026-09-15': 1.0}}
    assert V._dividend_rows(None) == {}


# ----------------------------------------------------------------- through the CLI
def _late_market(_universe=None):
    """09-11 planned, 09-14 executable, 09-15 today; AAA pays 1.00 ex 09-15."""
    idx = pd.to_datetime(['2026-09-11', '2026-09-14', '2026-09-15'])
    raw = pd.Series([98.0, 100.0, 99.0], index=idx)
    prices = adjust(raw, dividends={'2026-09-15': 1.0}).to_frame('AAA')
    etf = pd.DataFrame({t: [100.0, 100.0, 101.0] for t in ETF}, index=idx)
    return dict(prices=prices, volumes=prices * 1000,
                spy=pd.Series([400.0, 401.0, 402.0], index=idx, name='SPY'),
                etf=etf, irx=pd.Series([5.25, 5.25, 5.20], index=idx),
                stock_report={}, etf_report={}, irx_report={})


def _rank(prices, spy, volumes):
    return pd.DataFrame({"ticker": ["AAA"], "rank": [1], "sector": ["Other"],
                         "recommended": [False], "reason": [""], "recommended_count": [0]})


def _seed_pending(state_dir: Path, dollars: float = 1000.0) -> Path:
    path = state_dir / V.STATE_NAME
    state = E.new_state(8000.0, '2026-09-04', V9)
    state["last_run_date"] = "2026-09-11"
    state["pending"] = [dict(planned='2026-09-11', sleeve='stocks', tranche=0, ticker='AAA',
                             side='buy', dollars=dollars, cost_bp=0.0)]
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def test_cli_late_settle_books_the_printed_close_and_credits_the_dividend_once(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "off"))
    _seed_pending(tmp_path)
    out = V.run(tmp_path, fetch_fn=_late_market, rank_fn=_rank, silent=True,
                dividend_fn=lambda _t: [dict(ticker='AAA', ex_date='2026-09-15', dps=1.0)])
    state = json.loads(Path(out["state_path"]).read_text(encoding="utf-8"))
    fill = [f for f in state["ledger"] if f.get("ticker") == "AAA" and f.get("side") == "buy"][0]
    assert fill["exec_date"] == "2026-09-14"
    assert fill["status"] == "filled"
    assert fill["price"] == pytest.approx(100.0)             # the close that printed on 09-14
    assert fill["units"] == pytest.approx(10.0)
    credited = state["dividends"]
    assert len(credited) == 1 and credited[0]["dollars"] == pytest.approx(10.0)
    tr = state["sleeves"]["stocks"]["tranches"][0]
    # 10 units marked at the 09-15 close of 99 + the 10.00 of cash dividend = the 1000 spent
    assert tr["units"]["AAA"] * 99.0 + 10.0 == pytest.approx(1000.0)


def test_cli_refuses_to_fill_a_ticker_with_no_print_on_the_execution_bar(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "off"))

    def gapped(_universe=None):
        m = _late_market()
        m["prices"] = m["prices"].copy()
        m["prices"].loc[pd.Timestamp("2026-09-14"), "AAA"] = np.nan
        m["volumes"] = m["prices"] * 1000
        return m

    _seed_pending(tmp_path)
    out = V.run(tmp_path, fetch_fn=gapped, rank_fn=_rank, silent=True,
                dividend_fn=lambda _t: [])
    state = json.loads(Path(out["state_path"]).read_text(encoding="utf-8"))
    fill = [f for f in state["ledger"] if f.get("ticker") == "AAA"][0]
    assert fill["status"] == "not_filled"
    assert fill["reason"] == "no price on execution day"
    assert state["sleeves"]["stocks"]["tranches"][0]["units"] == {}


# ----------------------------------------------------------------- the intraday-bar guard
def _clock(date: str, time: str) -> pd.Timestamp:
    return pd.Timestamp(f"{date} {time}", tz=TC.NYSE_TZ)


def _pf_frames(last="2026-09-04"):
    idx = pd.DatetimeIndex(["2026-09-03", last])
    prices = pd.DataFrame({f"T{i}": [10.0, 10.0] for i in range(10)}, index=idx)
    etf = pd.DataFrame({t: [100.0, 101.0] for t in ETF}, index=idx)
    irx = pd.Series([5.0, 5.1], index=idx)
    ranking = pd.DataFrame({"ticker": [f"T{i}" for i in range(10)], "rank": range(1, 11),
                            "sector": ["Technology"] * 10,
                            "recommended": [True] * 5 + [False] * 5, "recommended_count": 5})
    return prices, etf, irx, ranking, {"schema_version": 1, "pending": []}


def _status(result, check):
    return {r["check"]: r["status"] for r in result["rows"]}.get(check)


def test_preflight_hard_fails_on_an_unclosed_current_session():
    """The hole that let a run settle 30 real orders at an 11:00 partial bar."""
    prices, etf, irx, ranking, state = _pf_frames()
    r = PF.evaluate(prices, etf, irx, state=state, ranking=ranking,
                    backup_dir="/tmp/b", clock=_clock("2026-09-04", "11:00"))
    assert _status(r, "last bars") == "OK"                  # the date checks all pass...
    assert _status(r, "session closed") == "HARD"           # ...only the clock catches it
    assert r["hard"]
    with pytest.raises(SystemExit):
        PF.raise_if_hard(r)


def test_preflight_ok_after_the_close():
    prices, etf, irx, ranking, state = _pf_frames()
    r = PF.evaluate(prices, etf, irx, state=state, ranking=ranking,
                    backup_dir="/tmp/b", clock=_clock("2026-09-04", "16:20"))
    assert _status(r, "session closed") == "OK" and not r["hard"]


def test_preflight_intraday_override_is_a_warn_not_a_pass():
    prices, etf, irx, ranking, state = _pf_frames()
    r = PF.evaluate(prices, etf, irx, state=state, ranking=ranking, backup_dir="/tmp/b",
                    clock=_clock("2026-09-04", "11:00"), allow_intraday=True)
    assert _status(r, "session closed") == "WARN" and not r["hard"] and r["warn"]


def test_preflight_weekend_clock_is_a_closed_session():
    prices, etf, irx, ranking, state = _pf_frames()
    r = PF.evaluate(prices, etf, irx, state=state, ranking=ranking,
                    backup_dir="/tmp/b", clock=_clock("2026-09-05", "11:00"))
    assert _status(r, "session closed") == "OK" and not r["hard"]


def test_preflight_omits_the_check_when_no_clock_is_supplied():
    prices, etf, irx, ranking, state = _pf_frames()
    r = PF.evaluate(prices, etf, irx, state=state, ranking=ranking,
                    asof="2026-09-04", last_session="2026-09-04", backup_dir="/tmp/b")
    assert _status(r, "session closed") is None and not r["hard"]


def test_session_is_closed_across_the_bell_and_on_half_days():
    assert not TC.session_is_closed(_clock("2026-09-04", "15:59"))
    assert not TC.session_is_closed(_clock("2026-09-04", "16:10"))      # inside the buffer
    assert TC.session_is_closed(_clock("2026-09-04", "16:15"))
    assert TC.session_is_closed(_clock("2026-09-05", "09:00"))          # Saturday
    assert TC.session_is_closed(_clock("2026-09-07", "09:00"))          # Labor Day
    # 2026-11-27 is the Friday after Thanksgiving; 2026-12-24 a Thursday. Both close at 13:00.
    assert TC.session_close_et(pd.Timestamp("2026-11-27")) == TC.NYSE_EARLY_CLOSE_ET
    assert TC.session_close_et(pd.Timestamp("2026-12-24")) == TC.NYSE_EARLY_CLOSE_ET
    assert TC.session_close_et(pd.Timestamp("2026-09-04")) == TC.NYSE_CLOSE_ET
    assert not TC.session_is_closed(_clock("2026-11-27", "12:00"))
    assert TC.session_is_closed(_clock("2026-11-27", "13:20"))


def test_to_eastern_accepts_an_aware_clock_from_any_zone():
    utc = pd.Timestamp("2026-09-04 20:00", tz="UTC")         # 16:00 ET
    assert TC.to_eastern(utc).hour == 16
    assert not TC.session_is_closed(utc)                     # the bell, before the buffer
    assert TC.session_is_closed(pd.Timestamp("2026-09-04 20:30", tz="UTC"))
