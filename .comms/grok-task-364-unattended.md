# TASK-364 — Unattended mode, alert channel, Windows scheduled task (done by Claude, 2026-09-06)

Grok ran out of credits; Claude delivered it on branch `post-freeze-wiring` (commit `5f0350d`, worktree
`../HydraOmniCapital-wiring`). Main untouched until the merge after "first settle verified".

## What landed

- `utils/notify.py` — transports `file` (always on, `state/alerts.log`, append-only, ISO stamp + level +
  title, body indented), `discord` (webhook), `telegram` (bot token + chat id). `HYDRA_NOTIFY` picks the
  network transports; secrets only from env (`DISCORD_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_CHAT_ID`), never logged. `notify()` never raises: each transport's result is returned.
  `run_summary()` renders the one-screen message from `portfolio_v9.run`'s return dict.
- `daily.py --unattended` — exit **0** ok / **1** legacy screener failed but v9 ran / **2** refused to
  plan (preflight HARD or unknown schema: `SystemExit` from `run`) / **3** exception. Summary as `INFO`,
  `[v9] DEGRADED` as `WARN`, 2 and 3 as `ALERT`. Attended mode keeps the old codes and sends nothing.
- `evidence_review.py` — fired triggers (TASK-356) go through `notify("ALERT")`.
- `send_hydra_summary.py` — its Discord/Telegram senders delegate to the same transports (`plain=True`,
  message unchanged).
- `schedule/` — `run_daily.cmd` (loads `hydra.env`, runs `daily.py --v9 --unattended`, tees to
  `logs/daily_<yyyymmdd>.log`), `hydra.env.example`, `hydra_daily.xml` (Mon-Fri **16:45 local**; the
  machine is UTC-5 without DST, so that is 17:45 ET in summer and 16:45 ET in winter — always after the
  close), `install_task.cmd` (substitutes the folder, writes UTF-16, `schtasks /Create`),
  `uninstall_task.cmd`. `schedule/hydra.env` and `state/alerts.log` gitignored. README section.
- Never places orders.

## Tests

`test_notify.py` (6): env parsing, file transport always written, failures swallowed, Discord/Telegram
posts with a fake `requests.post`, secrets absent from the log, summary text.
`test_daily_unattended.py` (7): exit codes 0/1/2/3, WARN before INFO on DEGRADED, attended mode
unchanged, end-to-end ALERT line in the alerts log without the fake.

## Left for Lucas

Copy `schedule/hydra.env.example` to `schedule/hydra.env`, set `HYDRA_BACKUP_DIR` (also fixes the
preflight WARN) and optionally `HYDRA_NOTIFY=discord` with the webhook, then `schedule\install_task.cmd`
once — after the merge, not before.
