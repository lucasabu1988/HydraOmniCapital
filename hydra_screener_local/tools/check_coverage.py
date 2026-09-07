"""Fail when line coverage drops below a floor (audit phase 10.4).

    python tools/check_coverage.py --min 80.0

A gradual floor, anchored on a measured number rather than an aspiration: 77.9% when
phase 10 wrote this, ratcheted to 80.0 once CI measured 81.22% on Linux (81.96% on
Windows — the platform difference is real, hence the headroom). Raise it when coverage
rises; it must never be lowered to make a red build green — that is what the floor is
for.

DO NOT MOVE THE FLOOR UNTIL TWO RUNS ON ONE COMMIT AGREE (TASK-390 follow-up).
The measurement was not repeatable when the 80.0 floor was set: four CI runs whose code
trees were identical measured 81.25 / 80.97 / 81.25 / 81.14 % on Linux 3.12, a 0.28 pp
spread. The cause was test_volume_watchdog.py drawing its fixtures from the process-wide,
unseeded np.random, which fed core/signals.py a different panel every run and executed a
different set of core/meta_layer.py branches (40 / 47 / 57 missed statements over 12
identical local runs). That fixture is seeded now and test_task_390_gates.py keeps it and
every other test module from going back to the global stream. But the 0.28 pp spread is a
measured fact about the four runs that produced the current headroom, so a floor of 81.0
would have failed two of them: the next ratchet needs two runs of the SAME commit
reporting the same number first. Until then 80.0 stands, headroom and all.

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
#: measured on 2026-09-06 over core/ data/ utils/ sleeves/ (Linux CI: 81.22)
BASELINE_PCT = 81.22


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
