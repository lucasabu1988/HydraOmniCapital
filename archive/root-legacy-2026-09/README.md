# Root legacy dump (2026-09-05)

Everything that used to live at the **repository root** and is not the local screener.

Moved here so the GitHub file listing is the product (`hydra_screener_local/`) instead of COMPASS, Render, IBKR paper-trading, experiment logs, and a parquet cache.

## What is here

- `compass_*.py`, `compass/`, `rattlesnake_*.py`, `catalyst_signals.py`, `viper_*.py`
- `hydra_capital.py`, `hydra_meta/`, `regime_os.py`, `regime.py`
- Root `tests/`, `conftest.py`, `pytest.ini`, `requirements.txt` (legacy engine)
- `scripts/`, `research/`, `backtests/`, `config/`
- Experiment logs (`exp40_*`, `exp42_*`), `logs/`, `results_v8_compass.pkl`, `stock_data.db`
- `data_cache_parquet/` (S&P price cache from the cloud engine)
- Frozen docs: `TASKBOARD.md`, manifesto, COMPASS design plans, `IMPLEMENTATION_GUIDE.md`

## Do not

- Import this from `hydra_screener_local/`
- Point CI at `tests/` in this folder
- Take screener parameters from COMPASS v8.4

History is intact (`git log --follow`). Restore a file with `git checkout HEAD -- archive/root-legacy-2026-09/<path>`.

Active system: `hydra_screener_local/`. Agent docs: `CLAUDE.md`, `AGENTS.md`, `GROKBOARD.md`.
