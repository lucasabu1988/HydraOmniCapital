# Legacy agent docs (archived 2026-09-06)

These files described the **COMPASS cloud engine** era of the repo — `omnicapital_live.py`,
the Flask/Render dashboard, IBKR broker integration and the ML learning system. That system
was frozen when the project focus moved to the local screener (`hydra_screener_local/`, June
2026), and `omnicapital_live.py` / `omnicapital_broker.py` were deleted in the 2026-09-05
cleanup. Nothing in these documents describes the current project.

| File | Last meaningful edit | What it was |
|---|---|---|
| `CODEX.md` | 2026-03-15 | Task assignments for the Codex agent on the cloud engine |
| `GEMINI.md` | 2026-03-16 | Gemini agent guidance for the cloud engine |
| `PROJECT_STATE.md` | 2026-03-12 | State snapshot of the v8.3 → v8.4 engine refactor |

They are kept for history (moved with `git mv`, so `git log --follow` works). Their parameter
lists — 5 positions, max 3 per sector, 90d momentum with a 5-day skip, adaptive stops — belong to
the frozen engine and **must not be used as a reference for the screener**; doing so caused a
wrong change once (TASK-318, 2026-09-05).

Current guidance: `CLAUDE.md` and `AGENTS.md` at the repo root; task board `GROKBOARD.md`.
