# TASK-416 — a degraded provider refresh has a name

2026-09-10, same tree, same close: 16:55 preflight passed (13 rows, provenance
WARN only); 19:36 the 10 ETFs had last bar 2026-09-09 and universe print share
7%. The HARD gate refused to plan — correct, `--force` was not used. The
operator at 20:00 could not tell "Yahoo degraded, retry" from "this session
has no data".

## What landed

- `config.PROVIDER_REFRESH_DEGRADE_SHARE = 0.20` (new observability constant).
- `data/fetch.py`: each frame carries print share + last bar in
  `attrs["print_quality"]`, using the observed mask so a 3-bar ffill does not
  count as a print. Sidecar `runs/last_ok_print_quality.json` records the last
  non-HARD run on that universe; TASK-359 manifests are the fallback.
- `portfolio_v9.py`: after preflight, before `raise_if_hard`, prints
  `provider refresh degraded: … retry later; this is not 'the session has no data'`
  when any group's share fell by more than the threshold vs last ok. A HARD run
  is never saved as last ok. `--force` is unchanged and never auto-applied.

## Tests

Mocked frames: observed-mask share, drop > threshold named, small drop silent,
no previous run silent, sidecar universe match, and a v9 CLI run that HARDs
still prints the name and does not write last_ok.
