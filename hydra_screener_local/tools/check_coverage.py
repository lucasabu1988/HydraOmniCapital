"""Fail when line coverage drops below a floor (audit phase 10.4).

    python tools/check_coverage.py --min 81.0

A gradual floor, anchored on a measured number rather than an aspiration: 77.9% when
phase 10 wrote this, ratcheted to 80.0 once CI measured 81.22% on Linux (TASK-390), then
to 81.0 (TASK-419) after the volume-watchdog fixture was seeded. Raise it when coverage
rises; it must never be lowered to make a red build green — that is what the floor is
for.

TASK-419 measured this commit twice on Windows / Python 3.14: **82.33%** then **82.35%**
(6572 statements, 1161 vs 1160 missed; the one-statement jitter is data/fetch.py).
Margin 1.33 pp under the lower figure covers the historical Linux-vs-Windows gap
(~1 pp) plus that hundredth. The unseeded 80.97% CI run that used to make 81.0
unsafe is no longer the measurement: the fixture is seeded and
test_task_390_gates.py keeps it that way.

Reads `coverage.xml`, which `run_all_tests.py --cov` writes.
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XML = ROOT / "coverage.xml"
#: TASK-422: two Windows runs of this tree, identical to the statement (6452 statements,
#: 5312 covered, 82.65% both, zero lines differing) once conftest stopped letting the
#: operator's gitignored runs/ decide which branches executed. Linux in CI measured 82.25%
#: on the same tree, a 0.40 pp gap, and the workflow floor is that minus a declared 1 pp.
BASELINE_PCT = 82.65


def read_line_rate(path: Path) -> float:
    root = ET.parse(path).getroot()
    rate = root.get("line-rate")
    if rate is None:
        raise ValueError(f"{path} has no line-rate attribute")
    return float(rate) * 100.0


def per_package(path: Path) -> list[tuple[str, float]]:
    root = ET.parse(path).getroot()
    out = []
    for pkg in root.iter("package"):
        name = pkg.get("name") or "?"
        rate = pkg.get("line-rate")
        if rate is not None:
            out.append((name, float(rate) * 100.0))
    return sorted(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="coverage floor")
    ap.add_argument("--min", type=float, default=BASELINE_PCT,
                    help=f"minimum line coverage percent (baseline {BASELINE_PCT})")
    ap.add_argument("--xml", type=str, default=str(DEFAULT_XML))
    args = ap.parse_args(argv)

    path = Path(args.xml)
    if not path.exists():
        print(f"coverage floor: {path} not found — run `python run_all_tests.py --cov` first")
        return 1
    try:
        pct = read_line_rate(path)
    except (ET.ParseError, ValueError) as e:
        print(f"coverage floor: cannot read {path}: {e}")
        return 1

    print(f"coverage: {pct:.2f}% line (floor {args.min:.2f}%, baseline {BASELINE_PCT}%)")
    for name, rate in per_package(path):
        print(f"  {name:<28} {rate:6.2f}%")

    if pct + 1e-9 < args.min:
        print(f"coverage floor FAILED: {pct:.2f}% < {args.min:.2f}%")
        return 1
    if pct > args.min + 3.0:
        print(f"note: coverage is {pct - args.min:.1f} pp above the floor — "
              f"consider raising --min in .github/workflows/test.yml")
    print("coverage floor ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
