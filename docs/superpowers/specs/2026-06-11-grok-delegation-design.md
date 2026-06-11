# Grok Delegation Workflow — Design

**Date**: 2026-06-11
**Status**: Approved by user
**Authors**: Claude (architect) + Lucas

## Context

The project pivoted from the cloud trading system (COMPASS/Render, now legacy) to the local
screener (`hydra_screener_local/`). The old Claude ↔ Codex coordination channel (`TASKBOARD.md`)
is frozen at March 2026 and no longer reflects reality. Grok (xAI) now runs alongside Claude in a
terminal **on the same working tree** (`C:\Users\caslu\Desktop\NuevoProyecto`) and takes the
implementer role Codex used to have. Grok has prior history in this repo (fixes in May 2026, see
`BUGS_FIXED.md`, `REGIME_AWARE_CHANGES.md`).

## Decision

Create a new lightweight coordination file `GROKBOARD.md`; freeze `TASKBOARD.md` as a historical
artifact. (Option B — chosen by user over reviving TASKBOARD.md or per-task spec files.)

## Roles

- **Claude**: architect/reviewer. Writes task specs, runs the initial smoke test, reviews every
  Grok commit, posts review notes in Messages.
- **Grok**: implementer. Picks up open tasks from GROKBOARD.md, implements, tests, commits, marks
  done with commit hash.

## File Changes

| File | Change |
|---|---|
| `GROKBOARD.md` (new, repo root) | Active coordination channel: context, rules, message thread, task queue. |
| `TASKBOARD.md` (frozen) | Add ~10-line header at top: "ARCHIVED — Codex/cloud-engine era (Mar 2026). Active queue: GROKBOARD.md". Rest of the file untouched. |
| `AGENTS.md` | "Task Board" section points to GROKBOARD.md as the active queue. |

## GROKBOARD.md Structure

1. **Context** (~5 lines): screener is the active project; cloud engine is legacy; roles.
2. **Rules for Grok**:
   - Each task declares `Files:` — Grok only touches those files while the task is active.
   - Shared working tree: stage with `git add <specific files>`, never `git add .` / `git add -A`.
   - Conventional commits (`feat:`, `fix:`, `test:`, `refactor:`).
   - Run `python hydra_screener_local/run_all_tests.py` before marking a task done.
   - Task states: `[ ]` open → `[~]` in progress (mark when claiming) → `[x]` done + commit hash.
     Blocked: `[!]` + message in the thread.
   - Never modify `HYDRA_ALGORITHM_SPEC.md` or scoring logic without explicit approval.
3. **Messages**: async thread, format `[YYYY-MM-DD HH:MM] SENDER: message`, newest on top.
4. **Queue**: numbering starts at **TASK-201** (legacy board ended at TASK-110; no collisions).

## Initial Queue (assigned to Grok)

- **TASK-201 — Harden `data/universe.py`**: add logging to silent `except` blocks, retry with
  backoff on network calls, local universe cache with an explicit warning when a fallback source
  is used. `Files: hydra_screener_local/data/universe.py` + new test.
- **TASK-202 — Volume data watchdog**: visible warning when the share of NaN `vol_ratio` exceeds a
  configurable threshold (default 20%); also recorded in the daily history JSON.
  `Files: hydra_screener_local/core/signals.py, hydra_screener_local/data/fetch.py` + test.
- **TASK-203 — Version the Pine contract**: add `contract_version` to `hydra_last_summary.json`,
  validate it in `validate_pine_contract.py`, add a contract test.
  `Files: hydra_screener_local/send_hydra_summary.py, hydra_screener_local/validate_pine_contract.py` + test.

## Claude's Work (not in the queue)

1. **Smoke test first**: `run_all_tests.py` + a real `daily.py` run on a small universe, so Grok
   starts from a verified green base. If it fails, fix before publishing the queue.
2. Create/commit the three file changes above.
3. **Review gate**: when Grok marks `[x]`, Claude reviews the commit and posts a note in Messages
   (approved or with findings). Nothing is closed without review.

## Protocol Error Handling

- File conflict (someone else touched a task's files): Grok stops, marks `[!]`, posts in Messages.
  No self-served merge resolution.
- Smoke test failure: Claude halts the rollout and fixes before publishing the queue.

## Out of Scope

- Reviving the cloud engine or the legacy TASKBOARD queue (Batch 4 tasks are obsolete; the cloud
  system they target is dead).
- Changes to screener scoring logic (locked behind SPEC approval).
