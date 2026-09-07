"""TASK-390 follow-up — the three things the tier-2 commit (56d4b66) left undecided.

56d4b66 added the five tier-2 modules plus tools/precommit_gates.py to mypy.ini and
ratcheted the coverage floor 77 -> 80. What it did not settle, and what this file pins:

1. `core.portfolio_engine.settle()` was annotated `-> dict` and returns a LIST of fills.
   Every caller iterates it (portfolio_v9.py:484, experiments/engine_backtest.py:102,
   test_engine_golden.py, ...), so the annotation, not the code, was wrong.

2. The coverage measurement was not repeatable, so no floor decision was valid. The
   fixtures in test_volume_watchdog.py drew from the process-wide, unseeded np.random,
   which fed core/signals.py a different panel every run and executed a different set of
   core/meta_layer.py branches: 40 / 47 / 57 missed statements over 12 identical local
   runs (64% / 69% / 56% on that module), and 81.25 / 80.97 / 81.25 / 81.14 % whole-tree
   over four CI runs of ONE code tree. The fixture is seeded now; these tests keep it
   seeded, and keep any other root/experiments test from reintroducing the same noise.

3. Because of that spread the floor must NOT move until two runs on one commit agree.
   The boundary test below is the arithmetic: a floor of 81.0 fails the 80.97 % run of
   the very tree that also measured 81.25 %.

Nothing here asserts a scoring number: no formula, multiplier or gate threshold is read.
"""
import os
import re
import sys
from pathlib import Path
from typing import get_type_hints

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from config import V9  # noqa: E402
import core.portfolio_engine as E  # noqa: E402

CFG = dict(V9, tranches=2, step_bars=1, hold_bars=2, stock_cost_bp=0.0, etf_cost_bp=0.0)
DATES = pd.bdate_range("2026-01-05", periods=4)


def _ranking(names):
    return pd.DataFrame({"ticker": names, "rank": range(1, len(names) + 1),
                         "sector": ["Other"] * len(names),
                         "recommended": [True] * len(names),
                         "reason": [""] * len(names),
                         "recommended_count": len(names)})


def _prices(cols, rows):
    return pd.DataFrame(rows, index=DATES[:len(rows)], columns=cols, dtype=float)


# --------------------------------------------------------------- 1. settle() returns a list
def test_settle_annotation_is_the_list_it_actually_returns():
    """The money path books fills from the return value of settle() by iterating it.

    `-> dict` made every caller's `for f in fills` look like a loop over keys. Both the
    early return and the normal return are lists, so the annotation must be list[dict].
    """
    assert get_type_hints(E.settle)["return"] == list[dict]


def test_settle_returns_a_list_on_both_of_its_return_paths():
    st = E.new_state(800.0, str(DATES[0].date()), CFG)

    # early return: nothing pending -> nothing done. This is `return []`.
    assert st["pending"] == []
    empty = E.settle(st, str(DATES[1].date()), pd.Series(dtype=float), pd.Series(dtype=float), CFG)
    assert isinstance(empty, list) and empty == []

    # normal return: one buy booked at the execution close.
    px = _prices(["A"], [[10.0], [10.0]])
    epx = _prices(["SPY"], [[1.0], [1.0]])
    st, orders = E.plan(st, str(DATES[0].date()), _ranking(["A"]),
                        px.iloc[:1], epx.iloc[:1], 0.0, CFG)
    assert orders, "the fixture must produce at least one order for this to mean anything"
    fills = E.settle(st, str(DATES[1].date()), px.iloc[1], epx.iloc[1], CFG)
    assert isinstance(fills, list) and not isinstance(fills, dict)
    assert fills and all(isinstance(f, dict) for f in fills)
    # what a caller does with it: iterate rows, not keys
    assert {f["ticker"] for f in fills} >= {"A"}


# ------------------------------------------------- 2. the coverage measurement is repeatable
def test_volume_watchdog_fixture_is_byte_identical_across_calls():
    from test_volume_watchdog import _make_synthetic_data

    a_px, a_vol, a_spy, _ = _make_synthetic_data(n_tickers=20, nan_share=0.5)
    b_px, b_vol, b_spy, _ = _make_synthetic_data(n_tickers=20, nan_share=0.5)
    pd.testing.assert_frame_equal(a_px, b_px)
    pd.testing.assert_frame_equal(a_vol, b_vol)
    pd.testing.assert_series_equal(a_spy, b_spy)


def test_volume_watchdog_fixture_ignores_the_global_numpy_random_state():
    """The whole point: other tests seed np.random, so a fixture reading it is not
    reproducible on its own, and its coverage footprint moves with test order."""
    from test_volume_watchdog import _make_synthetic_data

    np.random.seed(1)
    first = _make_synthetic_data(n_tickers=10)[0]
    np.random.seed(999)
    second = _make_synthetic_data(n_tickers=10)[0]
    _ = np.random.uniform(0, 1, 5)          # move the global stream again
    third = _make_synthetic_data(n_tickers=10)[0]
    pd.testing.assert_frame_equal(first, second)
    pd.testing.assert_frame_equal(first, third)

    # and the seed is really used — the panel is drawn, not a constant
    other = _make_synthetic_data(n_tickers=10, seed=7)[0]
    assert not other.equals(first)


#: legacy global-state numpy API. `seed` and the Generator constructors are fine.
_LEGACY_NP_RANDOM = re.compile(r"np\.random\.(?!seed\b|default_rng\b|Generator\b|SeedSequence\b)[a-z_]+\s*\(")


def _test_sources():
    files = sorted(ROOT.glob("test_*.py"))
    files += sorted((ROOT / "experiments").glob("test_*.py"))
    return files


def test_no_test_module_draws_from_the_unseeded_global_numpy_random():
    """Regression guard for the coverage noise, not a style rule.

    A test that draws from np.random without seeding it makes the suite's coverage
    footprint depend on test order and on the OS entropy of the day, which is exactly
    what made the 4 CI runs disagree by 0.28 pp on one code tree. Either use a local
    np.random.default_rng(<fixed>) (preferred) or call np.random.seed().
    """
    offenders = []
    for path in _test_sources():
        src = path.read_text(encoding="utf-8")
        if _LEGACY_NP_RANDOM.search(src) and "np.random.seed(" not in src:
            offenders.append(path.name)
    assert offenders == [], (
        "these test modules draw from the global numpy random state without seeding it; "
        "give them a local np.random.default_rng(<fixed seed>): " + ", ".join(offenders)
    )


def test_volume_watchdog_uses_a_generator_and_not_the_global_stream():
    src = (ROOT / "test_volume_watchdog.py").read_text(encoding="utf-8")
    assert "np.random.default_rng(" in src
    assert not _LEGACY_NP_RANDOM.search(src), (
        "test_volume_watchdog.py is the fixture whose unseeded draws moved core/meta_layer.py "
        "by up to 17 statements between identical runs; it must not go back to np.random.*"
    )


# ------------------------------------------------------ 3. the floor arithmetic at the boundary
def _coverage_xml(tmp_path: Path, line_rate: float) -> Path:
    p = tmp_path / "coverage.xml"
    p.write_text(
        f'<?xml version="1.0" ?>\n<coverage line-rate="{line_rate}" version="7.6">\n'
        '  <packages>\n    <package name="core" line-rate="0.80"/>\n'
        '  </packages>\n</coverage>\n',
        encoding="utf-8",
    )
    return p


@pytest.mark.parametrize("measured,floor,expected", [
    # the four CI runs of one identical code tree, against the floor that is in place (80.0)
    (0.8125, 80.0, 0),
    (0.8097, 80.0, 0),
    (0.8114, 80.0, 0),
    # ...and against the floor a "coverage is 81%, ratchet it" reading would have set.
    # Same tree, same commit: two of the four runs go red. This is why the floor does not
    # move until two runs on one commit agree.
    (0.8125, 81.0, 0),
    (0.8097, 81.0, 1),
    (0.8114, 81.0, 0),
])
def test_coverage_floor_is_exact_at_the_boundary(tmp_path, measured, floor, expected):
    import check_coverage

    rc = check_coverage.main(["--min", str(floor), "--xml", str(_coverage_xml(tmp_path, measured))])
    assert rc == expected, f"{measured * 100:.2f}% against a {floor:.2f}% floor should exit {expected}"


def test_coverage_floor_reports_a_missing_xml_instead_of_passing():
    import check_coverage

    assert check_coverage.main(["--min", "80.0", "--xml", str(ROOT / "no_such_coverage.xml")]) == 1


# --------------------------------------------------------------- the type gate does not shrink
TIER_3 = (
    "core/tranche_book.py", "core/fills.py", "core/state_check.py", "core/portfolio_state.py",
    "core/regime.py", "reconcile.py", "utils/env.py", "utils/trading_calendar.py",
    "utils/display.py",
)
TIER_1_2 = (
    "core/numbers.py", "core/ledger.py", "core/commit.py", "core/baseline.py", "core/alerts.py",
    "data/quality.py", "data/universe_registry.py", "tools/check_coverage.py",
    "tools/check_skips.py", "tools/check_secrets.py", "tools/precommit_gates.py",
    "core/dividends.py", "core/journal.py", "core/state_migrations.py", "data/pit.py",
    "utils/runlog.py",
)


def _mypy_files():
    src = (ROOT / "mypy.ini").read_text(encoding="utf-8")
    body = src.split("files =", 1)[1].split("\n\n", 1)[0]
    out = []
    for line in body.splitlines():
        line = line.split(";", 1)[0].strip().rstrip(",")
        if line.endswith(".py"):
            out.append(line.replace(os.sep, "/"))
    return out


def test_mypy_ini_still_checks_every_module_that_was_made_clean():
    """A type gate that quietly loses modules is the same defect class as a floor that
    is lowered to make a build green. 25 modules were clean when this was written."""
    listed = _mypy_files()
    missing = [m for m in TIER_1_2 + TIER_3 if m not in listed]
    assert missing == [], f"mypy.ini no longer checks: {missing}"
    assert len(listed) >= 25, listed


def test_every_module_mypy_claims_to_check_exists():
    absent = [m for m in _mypy_files() if not (ROOT / m).exists()]
    assert absent == [], f"mypy.ini lists files that are not there: {absent}"
