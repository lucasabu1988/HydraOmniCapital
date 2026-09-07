"""Per-case accounting for `run_all_tests.py` (ASTRA-04).

Loaded into every pytest child as `-p tools.pytest_case_report`. It prints two
machine-readable shapes on stdout, outside pytest's per-test capture:

    [CASE-SKIP] <nodeid> :: <reason>
    [CASE-COUNTS] passed=<n> failed=<n> skipped=<n> xfailed=<n> xpassed=<n> errors=<n>

Why this exists: the runner used to detect only whole-file skips (a `[SKIP]` line) and
reported "64 passed, 0 skipped" while three pytest cases inside those files were
skipping. `tools/check_skips.py` then parsed that same summary and exited 0 -- a green
light that never looked at what it certified (audit ASTRA-04, defect 1).

pytest's own `-rs` short summary reports `file.py:line: reason`, which moves with every
edit above the test. A node id does not, so the allowlist in check_skips.py can be keyed
by test id + reason.
"""
from __future__ import annotations

_COUNTS: dict[str, int] = {
    "passed": 0, "failed": 0, "skipped": 0,
    "xfailed": 0, "xpassed": 0, "errors": 0,
}
_SKIPS: list[tuple[str, str]] = []


def _reason(report) -> str:
    """One-line skip reason, whatever shape pytest used to record it."""
    longrepr = getattr(report, "longrepr", None)
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        text = str(longrepr[2])
    elif longrepr is not None:
        text = str(longrepr)
    else:
        text = ""
    text = text.strip()
    if text.lower().startswith("skipped:"):
        text = text.split(":", 1)[1].strip()
    # Collapse to one line: these lines are parsed line-by-line downstream.
    return " ".join(text.split()) or "no reason given"


def pytest_runtest_logreport(report) -> None:
    if report.skipped:
        # A skip is reported once, in whichever phase raised it (setup for a
        # module-level or fixture skip, call for pytest.skip inside the body).
        if getattr(report, "wasxfail", None) is not None:
            _COUNTS["xfailed"] += 1
            return
        _COUNTS["skipped"] += 1
        _SKIPS.append((report.nodeid, _reason(report)))
        return
    if report.failed:
        _COUNTS["errors" if report.when != "call" else "failed"] += 1
        return
    if report.when == "call":
        if getattr(report, "wasxfail", None) is not None:
            _COUNTS["xpassed"] += 1
        else:
            _COUNTS["passed"] += 1


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    # pytest's progress line ends without a newline, so start on a fresh one: the runner
    # matches these markers at the start of a line.
    print()
    for nodeid, reason in _SKIPS:
        print(f"[CASE-SKIP] {nodeid} :: {reason}")
    print("[CASE-COUNTS] " + " ".join(f"{k}={v}" for k, v in _COUNTS.items()))
