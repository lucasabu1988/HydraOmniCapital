# TASK-346 — off-disk state backups

After each `portfolio_v9.py` write, if `HYDRA_BACKUP_DIR` is set, copy
`portfolio_v9.json` and the day's instruction files to
`<HYDRA_BACKUP_DIR>/state_v9/<YYYYMMDD>/`. If the env var is missing, warn
once (same-disk `state/backup/` is not enough). `daily.py` prints the same
reminder next to the history backup note.
