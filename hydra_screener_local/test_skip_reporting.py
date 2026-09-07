"""The green light must look at what it certifies (audit ASTRA-04).

Two independent defects are pinned here:

1. `run_all_tests.py` detected only whole-file skips (a `[SKIP]` line) and never read
   pytest's own `N passed, M skipped` summary; `tools/check_skips.py` parsed that same
   file-level summary and exited 0. Astra's run on merge-prepared-2026-09 reported
   "64 passed, 0 skipped" while three pytest cases were skipping (two in
   `test_portfolio_engine.py`, one in `test_review_341.py`). The probe assertion --
   `main(['--from-file', <that log>]) != 0` -- is preserved below against a log with the
   same shape, plus the new itemised format.

2. `test_spec_compliance.py` had tests that passed vacuously: with
   `generate_daily_candidates` replaced by an empty DataFrame,
   `test_4_5_composite_and_strict_bonus` still returned True. Astra's assertion
   (`assert not T.test_4_5_composite_and_strict_bonus()`) is preserved verbatim in
   intent below, extended to 4.2.

`test_spec_compliance` mutates `config` module globals on import, so it is imported
inside the tests that need it, not at module scope.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import run_all_tests as R  # noqa: E402
from tools.check_skips import EXPECTED_CASE_SKIPS, main as check_skips_main  # noqa: E402

# --- log fixtures ----------------------------------------------------------------

#: The shape Astra measured: every file [PASS], the runner's own summary reporting zero
#: skips, and pytest's per-file tail lines quietly carrying three skipped cases.
OLD_FORMAT_LOG_WITH_THREE_INTERNAL_SKIPS = """\
HYDRA Screener - All Tests Runner
==================================================

=== test_portfolio_engine.py ===  [via pytest]
...........ss                                                            [100%]
11 passed, 2 skipped in 1.16s
[PASS] test_portfolio_engine.py (2.63s)

=== test_review_341.py ===  [via pytest]
.......s                                                                 [100%]
7 passed, 1 skipped in 1.09s
[PASS] test_review_341.py (2.59s)

==================================================
RESULTS: 64 passed, 0 skipped in 218.84s (tests time: 218.80s)
All tests passed!
ruff (report-only): All checks passed!
"""

CLEAN_LOG = """\
=== test_adjust.py ===  [via pytest]
....                                                                     [100%]
4 passed in 1.00s
[CASES] test_adjust.py passed=4 skipped=0 failed=0 errors=0 xfailed=0
[PASS] test_adjust.py (1.20s)

==================================================
RESULTS: 1 passed, 0 skipped in 1.20s (tests time: 1.20s)
CASES: 4 passed, 0 skipped, 0 failed, 0 errors, 0 xfailed over 1 pytest file(s) (0 script file(s) report file level only)
CASE-SKIPS: 0
All tests passed!
"""

LAB_CACHE = "lab cache experiments/_sweep_cache/ not present"


def _itemised_log(skips: list[tuple[str, str]], *, declared: int | None = None,
                  file_skips: list[str] | None = None) -> str:
    """A runner log in the new format carrying `skips` as itemised case skips."""
    declared = len(skips) if declared is None else declared
    lines = ["=== test_portfolio_engine.py ===  [via pytest]",
             "...........ss                                                    [100%]",
             f"11 passed, {declared} skipped in 1.16s",
             f"[CASES] test_portfolio_engine.py passed=11 skipped={declared} "
             f"failed=0 errors=0 xfailed=0"]
    lines += [f"[CASE-SKIP] {nodeid} :: {reason}" for nodeid, reason in skips]
    lines.append("[PASS] test_portfolio_engine.py (2.63s)")
    for f in (file_skips or []):
        lines.append(f"[SKIP] {f} (0.50s)")
    lines.append("=" * 50)
    lines.append(f"RESULTS: 64 passed, {len(file_skips or [])} skipped in 218.84s "
                 f"(tests time: 218.80s)")
    lines.append(f"CASES: 500 passed, {declared} skipped, 0 failed, 0 errors, 0 xfailed "
                 f"over 40 pytest file(s) (24 script file(s) report file level only)")
    lines.append(f"CASE-SKIPS: {len(skips)}")
    return "\n".join(lines) + "\n"


def _gate(tmp_path: Path, log: str, name: str = "suite.log") -> int:
    path = tmp_path / name
    path.write_text(log, encoding="utf-8")
    return check_skips_main(["--from-file", str(path)])


# --- defect 1: the skip gate ------------------------------------------------------

def test_skip_gate_rejects_three_unexplained_pytest_skips(tmp_path):
    """Astra's assertion, preserved: that log must not exit 0."""
    assert _gate(tmp_path, OLD_FORMAT_LOG_WITH_THREE_INTERNAL_SKIPS) != 0


def test_skip_gate_accepts_a_log_with_no_skips_at_all(tmp_path):
    assert _gate(tmp_path, CLEAN_LOG) == 0


def test_skip_gate_accepts_allowlisted_case_skips(tmp_path):
    skips = [(nodeid, reason) for nodeid, reason in EXPECTED_CASE_SKIPS.items()]
    assert len(skips) == 3, "the baseline is three allowlisted case skips"
    assert _gate(tmp_path, _itemised_log(skips)) == 0


def test_skip_gate_rejects_a_case_skip_that_is_not_allowlisted(tmp_path):
    skips = [("test_portfolio_engine.py::test_something_new", "no fixture today")]
    assert _gate(tmp_path, _itemised_log(skips)) != 0


def test_skip_gate_rejects_an_allowlisted_case_skipping_for_a_new_reason(tmp_path):
    nodeid = "test_review_341.py::test_parity_stock_targets_reproduced"
    assert nodeid in EXPECTED_CASE_SKIPS
    skips = [(nodeid, "pandas 3 removed the API this test used")]
    assert _gate(tmp_path, _itemised_log(skips)) != 0


def test_skip_gate_rejects_skipped_cases_that_are_not_itemised(tmp_path):
    """The gate must not go blind if the case-report plugin stops reporting."""
    log = _itemised_log([], declared=3)
    assert "[CASE-SKIP]" not in log
    assert _gate(tmp_path, log) != 0


def test_skip_gate_still_rejects_an_unexplained_whole_file_skip(tmp_path):
    skips = list(EXPECTED_CASE_SKIPS.items())
    log = _itemised_log(skips, file_skips=["test_something.py"])
    assert _gate(tmp_path, log) != 0


def test_skip_gate_accepts_an_explained_whole_file_skip(tmp_path):
    log = _itemised_log(list(EXPECTED_CASE_SKIPS.items()),
                        file_skips=["validate_pine_contract.py"])
    assert _gate(tmp_path, log) == 0


def test_pytest_tail_witness_ignores_a_test_that_merely_prints_the_word(tmp_path):
    """`... skipped ...` in a test's own output must not be read as a skip count."""
    noisy = CLEAN_LOG.replace("[PASS] test_adjust.py (1.20s)",
                              "  cache miss: 7 skipped rows in the fixture\n"
                              "[PASS] test_adjust.py (1.20s)")
    assert _gate(tmp_path, noisy) == 0


# --- defect 1: the runner's own accounting ---------------------------------------

def test_runner_parses_case_report_and_normalises_node_ids():
    output = ("...s                                                     [100%]\n"
              "[CASE-SKIP] some/other/rootdir/test_x.py::test_a :: needs the lab cache\n"
              "[CASE-COUNTS] passed=3 failed=0 skipped=1 xfailed=0 xpassed=0 errors=0\n"
              "3 passed, 1 skipped in 0.10s\n")
    cases = R._parse_case_report("test_x.py", output)
    assert cases is not None
    assert cases["counts"]["passed"] == 3
    assert cases["counts"]["skipped"] == 1
    assert cases["skips"] == [("test_x.py::test_a", "needs the lab cache")]
    # The marker lines are not shown twice in the runner's own tail output.
    assert "[CASE-SKIP]" not in R._display_output(output)


def test_runner_reports_no_case_counts_for_a_script_file():
    assert R._parse_case_report("test_x.py", "ALL CHECKS PASSED\n") is None


def test_runner_tail_witness_reads_pytest_summaries_only():
    assert R._pytest_tail_skips("11 passed, 2 skipped in 1.16s\n") == 2
    assert R._pytest_tail_skips("4 passed in 1.00s\n") is None
    # A test printing the words must not be mistaken for pytest's summary.
    assert R._pytest_tail_skips("  cache miss: 7 skipped rows in the fixture\n") is None


#: The guard is assembled at runtime, never written literally in this file: TASK-380's
#: test_console_encoding.py greps the tree for the literal to find entry points, with the
#: same substring weakness the runner had, and would demand a stdout.reconfigure here.
_MAIN = "__main__"
MENTIONS_MAIN_TEST_FILE = f'GUARD = \'if __name__ == "{_MAIN}"\'\n\n\ndef test_x():\n    assert GUARD\n'
GUARDED_TEST_FILE = f'def test_x():\n    assert True\n\n\nif __name__ == "{_MAIN}":\n    test_x()\n'


def test_runner_only_treats_a_real_main_guard_as_a_script(tmp_path):
    """Mentioning the word is not having an entry point (found while porting ASTRA-04)."""
    mentions = tmp_path / "test_mentions_main.py"
    mentions.write_text(MENTIONS_MAIN_TEST_FILE, encoding="utf-8")
    assert R._invocation(str(mentions))[1] == "pytest"

    guarded = tmp_path / "test_guarded.py"
    guarded.write_text(GUARDED_TEST_FILE, encoding="utf-8")
    assert R._invocation(str(guarded))[1] == "script"


def test_console_encoding_runs_through_pytest():
    """It quotes the entry-point guard to scan other files; it is not a script itself.

    Under the old substring test the runner ran it as a script: [PASS] in 0.09s with its
    only assertion never executed.
    """
    assert (ROOT / "test_console_encoding.py").exists()
    assert R._invocation("test_console_encoding.py")[1] == "pytest"


SKIPPING_TEST_FILE = '''\
import pytest


def test_that_runs():
    assert 1 == 1


def test_that_skips():
    pytest.skip("synthetic fixture is absent")
'''


def test_runner_itemises_a_real_internal_skip_end_to_end(tmp_path):
    """The regression test for the fix: a file whose case skips is no longer a silent pass.

    Astra's log had this exact shape -- one file [PASS], one case skipped, nothing said.
    """
    target = tmp_path / "test_synthetic_internal_skip.py"
    target.write_text(SKIPPING_TEST_FILE, encoding="utf-8")

    cmd, how = R._invocation(str(target))
    assert how == "pytest", "a file with test_* and no __main__ must go through pytest"
    assert "tools.pytest_case_report" in cmd

    status, _duration, cases = R.run_test(str(target))
    assert status == "pass"
    assert cases is not None, "the case-report plugin did not load"
    assert cases["counts"] == {"passed": 1, "failed": 0, "skipped": 1,
                               "xfailed": 0, "xpassed": 0, "errors": 0}
    assert len(cases["skips"]) == 1
    nodeid, reason = cases["skips"][0]
    assert nodeid.endswith("::test_that_skips")
    assert reason == "synthetic fixture is absent"


def test_gate_rejects_a_log_the_runner_really_produced(tmp_path, capsys):
    """End to end: run a skipping file through the runner, feed its log to the gate."""
    target = tmp_path / "test_synthetic_internal_skip.py"
    target.write_text(SKIPPING_TEST_FILE, encoding="utf-8")
    R.run_test(str(target))
    log = capsys.readouterr().out
    assert "[CASE-SKIP]" in log, log
    # The skip is real, named, and not on the allowlist -> the gate must reject it.
    assert _gate(tmp_path, log, name="runner.log") != 0


def test_case_report_plugin_prints_one_line_per_skip(tmp_path):
    target = tmp_path / "test_synthetic_internal_skip.py"
    target.write_text(SKIPPING_TEST_FILE, encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(target), "-q",
         "-p", "tools.pytest_case_report"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=env, timeout=120,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    skip_lines = [ln for ln in out.splitlines() if ln.startswith("[CASE-SKIP]")]
    assert len(skip_lines) == 1, out
    assert skip_lines[0].endswith(":: synthetic fixture is absent"), skip_lines
    counts = [ln for ln in out.splitlines() if ln.startswith("[CASE-COUNTS]")]
    assert counts and "skipped=1" in counts[0], out


# --- defect 2: SPEC tests that passed on an empty implementation ------------------

def test_spec_strict_bonus_rejects_empty_implementation(monkeypatch):
    """Astra's probe, preserved: an empty implementation must not return True."""
    import test_spec_compliance as T
    monkeypatch.setattr(T, "generate_daily_candidates", lambda *a, **k: pd.DataFrame())
    assert not T.test_4_5_composite_and_strict_bonus()


def test_spec_short_term_and_strict_rejects_empty_implementation(monkeypatch):
    import test_spec_compliance as T
    monkeypatch.setattr(T, "generate_daily_candidates", lambda *a, **k: pd.DataFrame())
    assert not T.test_4_2_short_term_and_strict()


def test_spec_strict_bonus_rejects_a_run_without_the_forced_ticker(monkeypatch):
    """Candidates exist but the forced name is missing: nothing was verified either."""
    import test_spec_compliance as T
    fake = pd.DataFrame({"ticker": ["ZZZZ"], "passes_strict": [False],
                         "meta_score": [1.0], "short_boost": [0.0],
                         "composite_score": [1.0], "vol_ratio": [1.0],
                         "ret_5d_10d": [0.0], "dist_20d_high": [0.0]})
    monkeypatch.setattr(T, "generate_daily_candidates", lambda *a, **k: fake)
    assert not T.test_4_5_composite_and_strict_bonus()


def test_spec_strict_bonus_rejects_a_composite_without_the_bonus(monkeypatch):
    """Drop the +18% from the implementation and SPEC 4.5 must go red."""
    import test_spec_compliance as T
    real = T.generate_daily_candidates

    def no_bonus(*a, **k):
        df = real(*a, **k)
        strict = df["passes_strict"].astype(bool)
        df.loc[strict, "composite_score"] = (
            df.loc[strict, "meta_score"]
            * (1 + df.loc[strict, "short_boost"] * T.config.SHORT_TERM_BOOST)
        ).round(4)
        return df

    monkeypatch.setattr(T, "generate_daily_candidates", no_bonus)
    with pytest.raises(AssertionError):
        T.test_4_5_composite_and_strict_bonus()


def test_spec_regime_breadth_is_measured_not_defaulted(monkeypatch):
    """The regime test used 30 columns; the breadth branch needs more than 30."""
    import test_spec_compliance as T
    calls = []
    real = T.compute_rich_regime_scores

    def spy_on_widths(spy, prices=None, *a, **k):
        calls.append(0 if prices is None else len(prices.columns))
        return real(spy, prices, *a, **k)

    monkeypatch.setattr(T, "compute_rich_regime_scores", spy_on_widths)
    assert T.test_4_3_rich_regime()
    assert max(calls) > 30, f"breadth branch never exercised, widths={calls}"
