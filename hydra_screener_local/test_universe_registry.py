"""Audit phase 7 — universe naming, documentation and bias reporting. No network.

Reproductions R-701..R-704 in docs/AUDIT_REPRODUCTIONS.md.
"""
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import data.universe_registry as UR  # noqa: E402

ROOT = Path(__file__).resolve().parent
PROXY_KEYS = ("russell1000", "russell2000", "russell3000", "all")


# ------------------------------------------------------------------ R-701 naming
def test_r701_no_cap_ranking_proxy_is_labelled_as_the_index_itself():
    """R-701 — phase 7.1/7.3. The primary source for `russell1000` / `russell2000`
    is a NASDAQ market-cap ranking, and the code called the result "Russell 1000"
    in docstrings, console output and a comment claiming it matched "la metodología
    FTSE Russell"."""
    for key in ("russell1000", "russell2000", "russell3000"):
        meta = UR.describe(key)
        assert meta["kind"] == UR.PROXY
        assert "proxy" in meta["label"].lower(), meta["label"]
        assert "NOT FTSE Russell" in meta["membership_method"] or \
               "not FTSE Russell" in meta["membership_method"] or \
               "NOT FTSE Russell membership" in meta["membership_method"]


def test_r701_the_combined_universe_is_a_proxy_too():
    """A union that contains a proxy is a proxy: `all` is the production universe."""
    meta = UR.describe("all")
    assert meta["kind"] == UR.PROXY
    assert UR.is_proxy("all") is True


def test_r701_the_published_index_lists_are_not_called_proxies():
    for key in ("sp500", "nasdaq100", "dow30"):
        assert UR.describe(key)["kind"] == UR.CURRENT
        assert UR.is_proxy(key) is False


def test_r701_the_source_file_no_longer_claims_russell_methodology():
    """Phase 7.3: the claim has to be gone from the code, not only from the registry."""
    text = (ROOT / "data" / "universe.py").read_text(encoding="utf-8", errors="replace")
    assert "igual que la metodología FTSE Russell" not in text
    for fn in ("get_russell1000_tickers", "get_russell2000_tickers"):
        i = text.index(f"def {fn}(")
        body = text[i:i + 700]
        assert "PROXY" in body, f"{fn} must announce itself as a proxy"


def test_r701_user_facing_output_says_proxy():
    text = (ROOT / "data" / "universe.py").read_text(encoding="utf-8", errors="replace")
    prints = re.findall(r'print\("([^"]*Russell[^"]*)"', text)
    assert prints, "the download messages should still exist"
    for line in prints:
        assert "PROXY" in line or "FALLBACK" in line, line


# ------------------------------------------------------------------ R-702 documentation
@pytest.mark.parametrize("key", sorted(UR.UNIVERSES))
def test_r702_every_universe_is_fully_documented(key):
    """R-702 — phase 7.2: source, definition, membership method, exclusions, biases."""
    meta = UR.describe(key)
    for field in ("label", "kind", "source", "definition", "membership_method",
                  "exclusions", "biases"):
        assert meta.get(field), f"{key} is missing {field}"
    assert meta["kind"] in UR.KINDS
    assert len(meta["biases"]) >= 1


def test_r702_the_report_carries_a_hash_and_a_date():
    rep = UR.universe_report("sp500", ["AAPL", "MSFT", "XOM"], date="2026-09-06",
                             requested=3)
    assert rep["sha256"]
    assert rep["date"] == "2026-09-06"
    assert rep["n"] == 3
    assert rep["coverage"] == pytest.approx(1.0)
    assert rep["kind"] == UR.CURRENT
    assert rep["is_proxy"] is False


def test_the_report_hash_is_content_addressed_not_order_dependent():
    a = UR.universe_report("sp500", ["AAPL", "MSFT"], date="2026-09-06")
    b = UR.universe_report("sp500", ["MSFT", "aapl"], date="2026-09-06")
    c = UR.universe_report("sp500", ["AAPL", "NVDA"], date="2026-09-06")
    assert a["sha256"] == b["sha256"]
    assert a["sha256"] != c["sha256"]


def test_the_formatted_report_shouts_when_the_universe_is_a_proxy():
    text = UR.format_report(UR.universe_report("russell2000", ["AAA"], date="2026-09-06"))
    assert "PROXY" in text
    assert "not the index it is named after" in text
    assert "BIAS" in text


def test_an_unregistered_universe_is_reported_as_such_not_guessed():
    rep = UR.universe_report("mystery", ["AAA"])
    assert rep["kind"] == UR.FALLBACK
    assert "not in the registry" in rep["caveats"]
    with pytest.raises(KeyError):
        UR.describe("mystery")


# ------------------------------------------------------------------ R-703 kinds
def test_r703_the_four_kinds_are_separate():
    """Phase 7.5: PIT, current, proxy and fallback are distinct, declared kinds."""
    assert set(UR.KINDS) == {UR.PIT, UR.CURRENT, UR.PROXY, UR.FALLBACK}
    kinds = {k: UR.kind(k) for k in UR.UNIVERSES}
    assert kinds["pit"] == UR.PIT
    assert kinds["sp500"] == UR.CURRENT
    assert kinds["all"] == UR.PROXY
    assert kinds["custom"] == UR.FALLBACK


def test_r703_biases_are_attached_to_the_kind():
    """Phase 7.6."""
    pit_notes = " ".join(UR.bias_notes("pit"))
    assert "neither survivorship nor look-ahead" in pit_notes

    cur = " ".join(UR.bias_notes("sp500"))
    assert "survivorship" in cur and "look-ahead" in cur

    prox = " ".join(UR.bias_notes("russell2000"))
    assert "proxy" in prox and "survivorship" in prox


def test_bias_notes_default_to_the_pessimistic_case():
    notes = " ".join(UR.bias_notes("something-unregistered"))
    assert "survivorship" in notes and "look-ahead" in notes


# ------------------------------------------------------------------ R-704 exclusions
@pytest.mark.parametrize("bad,reason", [
    ("ABCD.WS", "warrant"),
    ("ABCD-WT", "warrant"),
    ("ABCD.U", "unit"),
    ("ABCD-UN", "unit"),
    ("ABCD.R", "right"),
    ("ABCD-RT", "right"),
    ("ABCD-P", "preferred"),
    ("ABCD.PR", "preferred"),
    ("ABCD.WI", "when_issued"),
    ("", "empty symbol"),
])
def test_r704_non_common_stock_shapes_are_excluded(bad, reason):
    """R-704 — phase 7.4: nothing excluded warrants, units, rights or preferreds."""
    ok, got = UR.classify_symbol(bad)
    assert ok is False
    assert got == reason, f"{bad} -> {got}"


@pytest.mark.parametrize("good", ["AAPL", "MSFT", "F", "BRK-B", "BF.B", "GOOGL"])
def test_common_stock_and_share_classes_survive(good):
    ok, reason = UR.classify_symbol(good)
    assert ok is True, f"{good} rejected as {reason}"


@pytest.mark.parametrize("bad", ["TOOLONGSYM", "AB CD", "AB@C", "aapl.warrant"])
def test_malformed_symbols_are_excluded(bad):
    ok, _ = UR.classify_symbol(bad)
    assert ok is False


def test_exclude_non_common_groups_by_reason():
    kept, dropped = UR.exclude_non_common(
        ["AAPL", "MSFT", "SPAC.WS", "SPAC.U", "PFD-P", "BRK-B"])
    assert kept == ["AAPL", "BRK-B", "MSFT"]
    assert dropped["warrant"] == ["SPAC.WS"]
    assert dropped["unit"] == ["SPAC.U"]
    assert dropped["preferred"] == ["PFD-P"]


def test_exclude_non_common_is_a_guard_not_a_change_for_todays_universe():
    """Measured on the live `all` universe: zero removals. The guard must not quietly
    reshape production, and this pins that."""
    live = sorted({
        "AAPL", "MSFT", "NVDA", "BRK-A", "BRK-B", "BRK.B", "BF.B", "F", "GOOGL",
    })
    kept, dropped = UR.exclude_non_common(live)
    assert dropped == {}, dropped
    assert len(kept) == len(live)


def test_duplicate_share_classes_are_reported():
    """BRK-B and BRK.B are one security in two spellings, and both are in the live
    universe — one company counted twice, two price series for one position."""
    dupes = UR.duplicate_share_classes(["BRK-B", "BRK.B", "BF.B", "AAPL"])
    assert dupes == {"BRK-B": ["BRK-B", "BRK.B"]}


def test_the_report_surfaces_duplicates_and_exclusions():
    rep = UR.universe_report("all", ["AAPL", "BRK-B", "BRK.B", "SPAC.WS"],
                             date="2026-09-06")
    assert rep["excluded"]["warrant"] == ["SPAC.WS"]
    assert rep["duplicate_share_classes"] == {"BRK-B": ["BRK-B", "BRK.B"]}
    assert rep["n_after_exclusions"] == rep["n"] - 1
    text = UR.format_report(rep)
    assert "duplicate share class" in text
    assert "excluded [warrant]" in text


# ------------------------------------------------------------------ 7.7
def test_the_registry_carries_the_measurement_caveat():
    """Phase 7.7: no number may be presented without the caveat that produced it."""
    caveats = " ".join(UR.describe("sp500")["caveats"])
    assert "survivorship" in caveats
    assert "2020-2026" in caveats

    pit = " ".join(UR.describe("pit")["caveats"])
    assert "53%" in pit, "the 2005 coverage caveat must travel with the PIT universe"
