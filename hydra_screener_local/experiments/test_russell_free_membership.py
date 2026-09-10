"""Russell free-membership tool: parsers, the roll-forward and the table, on synthetic text. No network."""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import russell_free_membership as R  # noqa: E402


def test_kact_csv_parses_company_ticker_and_drops_blank_or_duplicate_tickers():
    text = "﻿Company,Ticker\nAAON INC,AAON\nAAR CORP,AIR\nDUPLICATE,AIR\nNO TICKER,\n"
    df = R.parse_kact_csv(text)
    assert list(df["ticker"]) == ["AAON", "AIR"]
    assert df.loc[0, "company"] == "AAON INC"


def test_ftse_three_line_layout_and_disclaimer_fragments():
    lines = ["Company", "Symbol", "Industry",
             "1STDIBS.COM", "DIBS", "Technology",
             "A K A BRANDS HOLDING", "AKA", "Consumer Discretionary",
             "Please see disclaimer", "BR", "�, �",          # footer garbage: no ICB industry
             "ACME UTD CORP", "ACU", "Health Care "]
    df = R.parse_ftse_lines(lines)
    assert list(df["symbol"]) == ["DIBS", "AKA", "ACU"]
    assert list(df["industry"]) == ["Technology", "Consumer Discretionary", "Health Care"]


def test_ftse_one_line_layout_2025():
    lines = ["Russell 3000 Index - Deletions", "Company Symbol Industry",
             "1STDIBS.COM DIBS Technology", "ALTO NEUROSCIENCE ANRO Health Care",
             "BAKKT HOLDINGS INC (A) BKKT Financials", "lseg.com/ftse-russell 2"]
    df = R.parse_ftse_lines(lines)
    assert list(df["symbol"]) == ["DIBS", "ANRO", "BKKT"]
    assert df.loc[2, "company"] == "BAKKT HOLDINGS INC (A)"


def test_ipo_document_layout():
    lines = ["Russell 3000 Index", "Final List of IPO Additions", "Effective September 21, 2026",
             "Ticker Company Name", "INIO Innio NV", "QNT Quantinuum Inc", "Please see disclaimer for important legal information."]
    df = R.parse_ipo_lines(lines)
    assert list(df["symbol"]) == ["INIO", "QNT"]


def test_ishares_csv_keeps_equity_rows_only_and_records_the_as_of_date():
    text = ('iShares Russell 3000 ETF\nFund Holdings as of,"Sep 09, 2026"\nStock,"-"\n\n'
            'Ticker,Name,Sector,Asset Class,Market Value,Weight (%)\n'
            '"NVDA","NVIDIA","Information Technology","Equity","1","7.1"\n'
            '"XTSLA","BLK CSH FND","Cash and/or Derivatives","Money Market","1","0.1"\n'
            '"-","USD CASH","Cash and/or Derivatives","Cash","1","0.1"\n')
    df = R.parse_ishares_csv(text)
    assert list(df["ticker"]) == ["NVDA"] and df.attrs["as_of"] == "Sep 09, 2026"


def test_roll_forward_drops_deletions_adds_additions_and_a_re_entry_ends_up_in():
    assert R.roll_forward({"A", "B", "C"}, additions={"D", "B"}, deletions={"B", "C"}) == {"A", "B", "D"}


def test_assemble_builds_dated_rows_and_checks_a_june_that_exists_in_both_sources():
    kact = {"20220624": pd.DataFrame({"company": ["a", "b", "c"], "ticker": ["A", "B", "C"]}),
            "20230623": pd.DataFrame({"company": ["a", "b", "d"], "ticker": ["A", "B", "D"]})}
    adds23 = pd.DataFrame({"company": ["d"], "symbol": ["D"], "industry": ["Technology"]})
    dels23 = pd.DataFrame({"company": ["c"], "symbol": ["C"], "industry": ["Energy"]})
    adds24 = pd.DataFrame({"company": ["e"], "symbol": ["E"], "industry": ["Technology"]})
    dels24 = pd.DataFrame({"company": ["a"], "symbol": ["A"], "industry": ["Energy"]})
    table = R.assemble(kact, [("2023-06-23", adds23, dels23), ("2024-06-28", adds24, dels24)],
                       ipo=pd.DataFrame({"symbol": ["Z"], "company": ["z"]}), ipo_effective="2024-09-20")
    by = {d: set(g["ticker"]) for d, g in table.groupby("date")}
    assert by["2022-06-24"] == {"A", "B", "C"}
    assert by["2023-06-23"] == {"A", "B", "D"}                     # the kact list is kept ...
    src23 = table[table["date"] == "2023-06-23"]["source"].iloc[0]
    assert "rollforward-check:0-diff" in src23                     # ... and the roll-forward reproduced it exactly
    assert by["2024-06-28"] == {"B", "D", "E"}                     # 2023 list - A + E
    assert by["2024-09-20"] == {"B", "D", "E", "Z"}                # + the IPO quarter
    assert set(table["member"]) == {1}
    ch = R.churn(table)
    assert list(ch["members"]) == [3, 3, 3, 4]
    assert list(ch["added"]) == [0, 1, 1, 1] and list(ch["dropped"]) == [0, 1, 1, 0]


def test_prune_dead_splits_the_current_list_by_whether_it_still_prints():
    alive, dead = R.prune_dead({"A", "B", "C", "D"}, printing={"A", "C", "ZZZ"})
    assert alive == {"A", "C"} and dead == {"B", "D"}


def test_a_probe_is_trusted_only_when_every_control_ticker_returned_data():
    assert R.probe_reliable(len(R.CONTROLS)) is True
    assert R.probe_reliable(len(R.CONTROLS) - 1) is False
    assert R.probe_reliable(0) is False

