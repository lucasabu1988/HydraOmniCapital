"""Tests for the two CI gate scripts that had none (GM-002-R).

`tools/check_coverage.py` and `tools/check_secrets.py` decide whether a build is
allowed through, and until this file nothing tested them. A gate nobody tests is
exactly what the audit was about: the important tests here are the ones that prove
each gate can *fail* (a gate that cannot fail is not a gate) and that it does not
cry wolf over a placeholder.

Three traps this file is written around, all of them found while porting the task:

1. **Never rely on a default path.** `check_coverage.main` defaults `--xml` to the
   repo's real (gitignored) `coverage.xml`, and `check_secrets.main` defaults
   `--root` to the real repository. A test that omits either flag measures the
   developer's working tree instead of its fixture, and is green or red for
   reasons that have nothing to do with the assertion. Every call below passes the
   flag, and two tests assert those defaults still point at the repo so the reason
   stays documented.
2. **Credential literals are assembled at runtime.** `tools/check_secrets.py`
   scans every tracked text file, and this file's name is *not* in its
   `ALLOWLIST_NAMES`; a working credential literal spelled out here would make the
   secret gate fail on the test that tests the secret gate. Fragments that only
   become credential-shaped inside the fixture avoid that without weakening the
   assertion. (`test_packaging.py` is allowlisted instead, because its regexes have
   to spell the shapes out. Allowlisting is the fallback, not the first move.)
3. **No script entry point.** `run_all_tests.py` runs a discovered file as a plain
   script whenever the source contains the dunder-main marker, and a pytest-style
   module run that way executes nothing and exits 0 -- reported as [PASS] with zero
   assertions. The marker must not appear anywhere in this file; the last test
   asserts that it does not.
"""
from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))

import check_coverage  # noqa: E402
import check_secrets  # noqa: E402

HERE = Path(__file__).resolve().parent

# Same shape as the real coverage.xml that `run_all_tests.py --cov` writes: the
# overall rate on the root <coverage> element, per-directory rates on <package>.
_COVERAGE_XML = """<?xml version="1.0" ?>
<coverage version="7.13.5" timestamp="1788718054059" lines-valid="1000" \
lines-covered="{covered}" line-rate="{rate}" branches-covered="0" \
branches-valid="0" branch-rate="0" complexity="0">
  <sources><source>core</source></sources>
  <packages>
    <package name="core" line-rate="0.9000" branch-rate="0" complexity="0">
      <classes/>
    </package>
    <package name="data" line-rate="0.7000" branch-rate="0" complexity="0">
      <classes/>
    </package>
  </packages>
</coverage>
"""


def _coverage_xml(tmp_path: Path, rate: str, name: str = "coverage.xml") -> Path:
    """Write a coverage report whose overall line-rate is exactly `rate`."""
    path = tmp_path / name
    covered = int(round(float(rate) * 1000))
    path.write_text(_COVERAGE_XML.format(rate=rate, covered=covered), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# tools/check_coverage.py
# ---------------------------------------------------------------------------

def test_read_line_rate_returns_the_percentage_in_the_xml(tmp_path):
    path = _coverage_xml(tmp_path, "0.8193")
    assert check_coverage.read_line_rate(path) == pytest.approx(81.93)


def test_read_line_rate_rejects_a_report_with_no_line_rate(tmp_path):
    path = tmp_path / "coverage.xml"
    path.write_text('<?xml version="1.0" ?>\n<coverage version="7.13.5"/>\n', encoding="utf-8")
    with pytest.raises(ValueError):
        check_coverage.read_line_rate(path)


def test_per_package_returns_every_package_sorted_by_name(tmp_path):
    path = _coverage_xml(tmp_path, "0.8193")
    names = [n for n, _ in check_coverage.per_package(path)]
    rates = dict(check_coverage.per_package(path))
    assert names == ["core", "data"]
    assert rates["core"] == pytest.approx(90.0)
    assert rates["data"] == pytest.approx(70.0)


def test_coverage_gate_passes_when_coverage_is_above_the_floor(tmp_path):
    path = _coverage_xml(tmp_path, "0.8193")
    assert check_coverage.main(["--min", "80.0", "--xml", str(path)]) == 0


def test_coverage_gate_fails_when_coverage_is_below_the_floor(tmp_path):
    """The most important test in the file: the gate must be able to go red."""
    path = _coverage_xml(tmp_path, "0.7500")
    assert check_coverage.main(["--min", "80.0", "--xml", str(path)]) == 1


def test_coverage_gate_boundary_is_inclusive_at_the_floor(tmp_path):
    """`pct + 1e-9 < min` -- exactly at the floor passes, a hundredth below fails.

    The epsilon is load-bearing: `float("0.8123") * 100.0` is not exactly 81.23,
    so without it the gate would reject a report that is precisely at its floor.
    """
    at_floor = _coverage_xml(tmp_path, "0.8123", name="at.xml")
    below = _coverage_xml(tmp_path, "0.8122", name="below.xml")
    assert check_coverage.main(["--min", "81.23", "--xml", str(at_floor)]) == 0
    assert check_coverage.main(["--min", "81.23", "--xml", str(below)]) == 1


def test_coverage_gate_fails_when_the_report_is_absent(tmp_path):
    missing = tmp_path / "nowhere" / "coverage.xml"
    assert not missing.exists()
    assert check_coverage.main(["--min", "80.0", "--xml", str(missing)]) == 1


def test_coverage_gate_fails_when_the_report_is_malformed(tmp_path):
    path = tmp_path / "coverage.xml"
    path.write_text('<coverage line-rate="0.99"', encoding="utf-8")  # truncated on purpose
    with pytest.raises(ET.ParseError):
        check_coverage.read_line_rate(path)
    assert check_coverage.main(["--min", "80.0", "--xml", str(path)]) == 1


def test_coverage_default_xml_is_the_real_repo_report(tmp_path):
    """Why every test above passes --xml: the default is the developer's own file.

    `coverage.xml` is gitignored, so in a fresh checkout it does not exist and the
    default would make the gate return 1 for a reason unrelated to any assertion.
    """
    assert check_coverage.DEFAULT_XML == HERE / "coverage.xml"
    assert check_coverage.BASELINE_PCT > 0.0


# ---------------------------------------------------------------------------
# tools/check_secrets.py -- fixtures assembled at runtime (see trap 2 above)
# ---------------------------------------------------------------------------

def _aws_key() -> str:
    """An AWS-key-shaped literal: the prefix plus 16 upper-case characters."""
    return "AKIA" + "QWERTYUIOPASDFGH"


def _aws_key_line() -> str:
    return "AWS_ACCESS_KEY_ID = '" + _aws_key() + "'\n"


def _assigned_credential_line() -> str:
    """Matches the `assigned credential` pattern: a known name, then a long value."""
    return "api" + "_key" + ' = "' + "Zq7" + "TdKmR4vLp9Bs" + '"\n'


def _placeholder_line() -> str:
    """Credential-*shaped* but obviously not a credential: PLACEHOLDER vetoes it."""
    return "api" + "_key" + ' = "' + "your_" + "api_key_here" + '"\n'


def _boards_example_key_line() -> str:
    """The literal GM-002's own task text suggested as the positive fixture.

    It never alerts: the PLACEHOLDER veto fires on the word it ends with, so a test
    built on it would have asserted a clean scan while believing it proved the
    opposite. Kept as a regression test for that veto.
    """
    return "AWS_SECRET_ACCESS_KEY = \"" + "AKIA" + "IOSFODNN7" + "EXAMPLE" + "\"\n"


def _pattern(label: str):
    return next(rx for name, rx in check_secrets.PATTERNS if name == label)


def test_secret_sweep_is_clean_for_a_harmless_file(tmp_path):
    (tmp_path / "notes.md").write_text("# nothing to see\n\njust prose.\n", encoding="utf-8")
    assert check_secrets.scan(tmp_path) == []


def test_secret_sweep_reports_an_aws_key_shaped_literal(tmp_path):
    (tmp_path / "leaked.py").write_text(_aws_key_line(), encoding="utf-8")
    findings = check_secrets.scan(tmp_path)
    assert len(findings) == 1, findings
    assert "aws access key" in findings[0]
    assert "leaked.py:1" in findings[0]


def test_secret_sweep_reports_an_assigned_credential(tmp_path):
    (tmp_path / "settings.py").write_text(_assigned_credential_line(), encoding="utf-8")
    findings = check_secrets.scan(tmp_path)
    assert len(findings) == 1, findings
    assert "assigned credential" in findings[0]


def test_secret_sweep_stays_quiet_on_a_placeholder_the_pattern_does_match(tmp_path):
    """The veto, not a gap in the pattern: assert the pattern fires, scan does not."""
    line = _placeholder_line()
    assert _pattern("assigned credential").search(line), "fixture no longer matches"
    (tmp_path / ".env.template").write_text(line, encoding="utf-8")
    assert check_secrets.scan(tmp_path) == []


def test_secret_sweep_stays_quiet_on_the_documented_example_key(tmp_path):
    line = _boards_example_key_line()
    assert _pattern("aws access key").search(line), "fixture no longer matches"
    (tmp_path / "README.md").write_text(line, encoding="utf-8")
    assert check_secrets.scan(tmp_path) == []


def test_secret_sweep_skips_allowlisted_filenames(tmp_path):
    """Identical content: alerts under a normal name, allowlisted under `.env.example`."""
    leak = _aws_key_line()
    (tmp_path / ".env.example").write_text(leak, encoding="utf-8")
    (tmp_path / "config_notes.md").write_text(leak, encoding="utf-8")
    findings = check_secrets.scan(tmp_path)
    assert len(findings) == 1, findings
    assert "config_notes.md" in findings[0]
    assert ".env.example" not in findings[0]


def test_secret_sweep_skips_binary_suffixes_and_skipped_directories(tmp_path):
    leak = _aws_key_line()
    (tmp_path / "blob.bin").write_text(leak, encoding="utf-8")
    frozen = tmp_path / "archive"
    frozen.mkdir()
    (frozen / "old.py").write_text(leak, encoding="utf-8")
    assert "archive" in check_secrets.SKIP_DIRS
    assert ".bin" not in check_secrets.TEXT_SUFFIXES
    assert check_secrets.scan(tmp_path) == []


def test_env_files_reports_a_tracked_dotenv_but_not_the_example(tmp_path):
    (tmp_path / ".env").write_text("TOKEN=abc\n", encoding="utf-8")
    (tmp_path / ".env.production").write_text("TOKEN=abc\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("TOKEN=\n", encoding="utf-8")
    reported = set(check_secrets.env_files(tmp_path))
    assert reported == {".env", ".env.production"}


def test_secret_gate_returns_zero_when_clean_and_one_when_dirty(tmp_path):
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "notes.md").write_text("nothing here\n", encoding="utf-8")
    assert check_secrets.main(["--root", str(clean)]) == 0

    dirty = tmp_path / "dirty"
    dirty.mkdir()
    (dirty / "leaked.py").write_text(_aws_key_line(), encoding="utf-8")
    assert check_secrets.main(["--root", str(dirty)]) == 1

    env = tmp_path / "env"
    env.mkdir()
    (env / ".env").write_text("TOKEN=abc\n", encoding="utf-8")
    assert check_secrets.main(["--root", str(env)]) == 1


def test_secret_gate_default_root_is_the_real_repository(tmp_path):
    """Why every test above passes --root: the default sweeps the whole repo."""
    assert check_secrets.REPO_ROOT == HERE.parent
    assert (check_secrets.REPO_ROOT / "hydra_screener_local").is_dir()


# ---------------------------------------------------------------------------
# guards for the two traps this file was written around
# ---------------------------------------------------------------------------

def test_this_file_is_not_allowlisted_by_the_secret_gate():
    """Trap 2: so every credential fixture above must be assembled at runtime.

    If this ever has to be allowlisted, follow the `test_packaging.py` precedent and
    say why in `ALLOWLIST_NAMES` -- do not do it to make a spelled-out literal pass.
    """
    assert Path(__file__).name not in check_secrets.ALLOWLIST_NAMES
    assert "test_packaging.py" in check_secrets.ALLOWLIST_NAMES


def test_this_file_defines_no_script_entry_point():
    """Trap 3: with the dunder-main marker present, `run_all_tests.py` would run this
    file as a script, execute no assertion, and report [PASS]."""
    marker = "__" + "main" + "__"
    source = Path(__file__).read_text(encoding="utf-8")
    assert marker not in source, f"{marker} in {Path(__file__).name} disables every test above"


def test_the_gate_scripts_are_reachable_from_the_repo_root():
    """Both gates are invoked by path from CI and by `tools/precommit_gates.py`."""
    for name in ("check_coverage.py", "check_secrets.py", "check_skips.py",
                 "precommit_gates.py"):
        assert (HERE / "tools" / name).is_file(), name
