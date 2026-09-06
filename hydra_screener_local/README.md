# hydra_screener_local

HYDRA **v9** production package: local 50/50 portfolio (T20 US-equity momentum + ETF trend), operated from a weekly instruction sheet.

**Canonical docs (start here):**
- Root [`README.md`](../README.md) — product + weekly ritual
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — module map
- [`docs/RUNBOOK.md`](docs/RUNBOOK.md) — operator steps
- [`HYDRA_ALGORITHM_SPEC.md`](HYDRA_ALGORITHM_SPEC.md) — scoring / v9 spec (§9)

```bash
pip install -r requirements.txt
python warm_sectors.py    # once (sector cache)
python daily.py           # Friday after close → state/instructions_*.md
python dashboard_v9.py    # local read-only dashboard
python run_all_tests.py
```

Pine / TradingView hybrid tooling under `pine/` is **parked** (artifacts may still generate; not the production path). Do not treat hybrid CLIs or `HYBRID_USAGE` as current ops guidance.
