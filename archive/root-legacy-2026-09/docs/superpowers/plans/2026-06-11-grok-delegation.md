# Grok Delegation Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Claude ↔ Grok coordination channel (GROKBOARD.md) with a verified-green starting state, freeze the legacy TASKBOARD, and point AGENTS.md at the new queue.

**Architecture:** Pure docs/process change plus one verification gate. A new lightweight board file (`GROKBOARD.md`) becomes the single active queue; the 2,307-line Codex-era `TASKBOARD.md` gets a 6-line archive banner and is never edited again; `AGENTS.md`'s Task Board section redirects agents to the new board. A smoke test (test suite + real small-universe screener run) runs FIRST — if it fails, stop and fix before publishing the queue (per spec).

**Tech Stack:** Markdown, git, PowerShell, Python 3.14 (screener test suite).

**Spec:** `docs/superpowers/specs/2026-06-11-grok-delegation-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `GROKBOARD.md` | Create | Active Claude ↔ Grok queue: context, rules, messages, tasks 201–203 |
| `TASKBOARD.md` | Modify (top only) | Frozen Codex-era archive; gains a banner pointing to GROKBOARD.md |
| `AGENTS.md` | Modify (Task Board section) | Agent-facing docs point to the active queue |

No screener code is modified by this plan. Tasks 201–203 are *specified* in GROKBOARD.md for Grok to implement later.

---

### Task 1: Smoke test the current state (gate)

**Files:** none modified — verification only.

- [ ] **Step 1: Run the screener test suite**

```powershell
Set-Location C:\Users\caslu\Desktop\NuevoProyecto\hydra_screener_local
python run_all_tests.py
```

Expected: exit code 0, all discovered tests pass (`test_spec_compliance.py`, `test_generate_pine_watchlist.py`, `test_hybrid_integration.py`, `experiments/test_screener_logic.py`, `validate_pine_contract.py`, plus auto-discovered `test_*.py`).

**If any test fails: STOP the plan.** Report the failure to the user and fix it before publishing the queue (spec: "Smoke test failure: Claude halts the rollout").

- [ ] **Step 2: Run a real screener pass on a small universe, hybrid layer skipped**

```powershell
Set-Location C:\Users\caslu\Desktop\NuevoProyecto\hydra_screener_local
$env:UNIVERSE = 'nasdaq100'
$env:HYDRA_SKIP_HYBRID = '1'
python screener.py
```

Expected: completes with exit code 0, prints the ranked candidates table and a recommended list (count between 0 and 28), no Python traceback. Network fetch of ~100 tickers takes a few minutes.

- [ ] **Step 3: Revert any generated-artifact churn**

```powershell
Set-Location C:\Users\caslu\Desktop\NuevoProyecto
git status --short
```

Expected: untracked/modified entries only under `hydra_screener_local/` generated paths (`history/`, `output/`, `backtest/*.xlsx`, `pine/`), if any. For any **tracked** file modified by the smoke run (e.g. `hydra_screener_local/backtest/portfolio_cycles.xlsx`, `hydra_screener_local/pine/hydra_last_summary.json`):

```powershell
git restore <that-file>
```

Do NOT restore anything you did not just generate. Untracked files under gitignored paths can stay.

- [ ] **Step 4: Clear the env vars so they don't leak into later steps**

```powershell
Remove-Item Env:UNIVERSE, Env:HYDRA_SKIP_HYBRID -ErrorAction SilentlyContinue
```

---

### Task 2: Create GROKBOARD.md

**Files:**
- Create: `GROKBOARD.md` (repo root)

- [ ] **Step 1: Get the current timestamp for the welcome message**

```powershell
Get-Date -Format 'yyyy-MM-dd HH:mm'
```

Use this value as `<NOW>` in Step 2.

- [ ] **Step 2: Write `GROKBOARD.md` with exactly this content** (substitute `<NOW>`):

````markdown
# GROKBOARD — Claude ↔ Grok Coordination

Active task queue and async communication channel between **Claude** (architect/reviewer) and
**Grok** (implementer). Both agents work on the **same working tree**:
`C:\Users\caslu\Desktop\NuevoProyecto`.

**Project focus (since Jun 2026):** the local screener in `hydra_screener_local/`.
The old cloud system (COMPASS engine + Render dashboard) is **legacy — do not revive it**.
Historical task archive: [`TASKBOARD.md`](TASKBOARD.md) (frozen, Codex era, Mar 2026).

## Rules for Grok

1. Each task declares `Files:` — only touch those files while the task is active.
2. Shared working tree: stage with `git add <specific files>`. NEVER `git add .` or `git add -A`
   (Claude may have uncommitted changes in other files).
3. Conventional commits: `feat:`, `fix:`, `test:`, `refactor:`, `docs:`.
4. Before marking a task done: `cd hydra_screener_local && python run_all_tests.py` — must exit 0.
   New test files named `test_*.py` in `hydra_screener_local/` are auto-discovered by the runner.
5. Task states: `[ ]` open → `[~]` in progress (mark it when you claim it) → `[x]` done + commit
   hash. Blocked: `[!]` + message in the thread below.
6. NEVER modify `hydra_screener_local/HYDRA_ALGORITHM_SPEC.md` or scoring behavior (formulas in
   `core/signals.py`, multipliers in `core/meta_layer.py`, gate thresholds in `config.py`)
   without explicit approval from Claude in Messages. Adding logging/validation around them is
   fine; changing behavior is not.
7. If a file you need already has modifications you didn't make (`git status`): STOP, mark the
   task `[!]`, post in Messages. Do not resolve conflicts on your own.
8. Claude reviews every completed task and posts the verdict in Messages. A task is only closed
   after Claude's review note.

## Messages

Format: `[YYYY-MM-DD HH:MM] SENDER: message` — newest on top.

[<NOW>] CLAUDE: Welcome, Grok. This board replaces TASKBOARD.md (now a frozen archive).
Three tasks queued (TASK-201..203), all on the local screener. Priority: 201 → 202 → 203.
The current state passed a smoke test (full test suite + real nasdaq100 run) before this queue
was published — you start from green. Claim a task by marking it `[~]`, work only within its
`Files:`, and ping here if blocked.

## Queue

### TASK-201: Harden data/universe.py network layer [PRIORITY: HIGH]
**Status:** [ ]
**Assigned:** Grok
**Files:** `hydra_screener_local/data/universe.py`, `hydra_screener_local/test_universe_robustness.py` (new)

**What:** The universe fetch chain (Slickcharts → Wikipedia → GitHub → NASDAQ screener →
fallback) fails silently: ~30 `except Exception: pass` blocks with no logging. If sources fail,
the universe degrades without warning. Add observability + retry + cache fallback.

**How:**
1. Add a module logger (`logger = logging.getLogger(__name__)`). Replace every silent
   `except Exception: pass` (and any bare `except:`) with
   `except Exception as e: logger.warning("<source/step> failed: %s", e)` — preserve the existing
   control flow exactly (still fall through to the next source).
2. Add `_get_with_retry(url, timeout=20, attempts=3, backoff=2.0)` wrapping `requests.get` with
   exponential backoff (`time.sleep(backoff ** attempt)` between tries); use it in the HTTP
   fetchers.
3. Universe cache: on every successful universe resolution, write the ticker list + ISO date to
   `data_cache/universe_cache_<name>.json`. If ALL live sources fail, load that cache and emit a
   prominent warning (logger + console print):
   `"WARNING: using cached universe from <date> (<n> tickers) — all live sources failed"`.
   Raise only if there is no cache either.
4. Public API of `get_universe()` unchanged.

**Test (`test_universe_robustness.py`):** monkeypatch the network layer to always raise →
assert (a) warnings logged for failed sources, (b) cached universe returned when a cache file
exists, (c) the explicit fallback warning is emitted, (d) a successful run writes the cache file.

---

### TASK-202: Volume data watchdog [PRIORITY: MEDIUM]
**Status:** [ ]
**Assigned:** Grok
**Files:** `hydra_screener_local/core/signals.py`, `hydra_screener_local/config.py`,
`hydra_screener_local/screener.py`, `hydra_screener_local/test_volume_watchdog.py` (new)

**What:** When volume data is missing, `vol_ratio` is NaN and `passes_strict` silently fails for
those tickers — the +18% strict bonus quietly stops applying and nobody notices.

**How:**
1. `config.py`: add `VOL_NAN_WARN_THRESHOLD = 0.20` (max acceptable share of tickers with NaN
   `vol_ratio`).
2. In the short-term features path (`core/signals.py`), after computing `vol_ratio` across the
   universe, compute `nan_share = <vol_ratio series>.isna().mean()` and expose it to the caller.
3. `screener.py`: if `nan_share > VOL_NAN_WARN_THRESHOLD`, print a prominent console warning
   (`"⚠ {pct:.0%} of tickers have no usable volume data — strict filter coverage degraded"`) and
   include `"vol_ratio_nan_share": <float>` in the daily history JSON payload.
4. Observability only — do NOT change scoring behavior (rule 6).

**Test (`test_volume_watchdog.py`):** synthetic prices+volumes with 50% NaN volume →
`nan_share ≈ 0.5`, warning emitted, history payload includes the field. Clean case (0% NaN) →
no warning.

---

### TASK-203: Version the Pine contract [PRIORITY: MEDIUM]
**Status:** [ ]
**Assigned:** Grok
**Files:** `hydra_screener_local/send_hydra_summary.py`,
`hydra_screener_local/validate_pine_contract.py`,
`hydra_screener_local/test_hybrid_integration.py`

**What:** `pine/hydra_last_summary.json` has no version field. If the JSON shape changes, the
Pine table in TradingView breaks silently.

**How:**
1. `send_hydra_summary.py`: add `"contract_version": "1.2"` as the FIRST key of the summary dict
   (matches HYDRA_ALGORITHM_SPEC.md v1.2). Add a comment next to it: the version bumps ONLY when
   the JSON shape changes.
2. `validate_pine_contract.py`: validation fails with a clear message if `contract_version` is
   missing or not in the supported set `{"1.2"}`.

**Test (extend `test_hybrid_integration.py`):** generated summary contains `contract_version`
== "1.2"; validator rejects a summary without the field; validator accepts "1.2".

---

## Completed

(nothing yet — completed tasks move here with commit hash + Claude's review note)
````

- [ ] **Step 3: Commit**

```powershell
Set-Location C:\Users\caslu\Desktop\NuevoProyecto
git add GROKBOARD.md
git commit -m "feat: add GROKBOARD.md — active Claude<->Grok task queue (TASK-201..203)"
```

---

### Task 3: Freeze TASKBOARD.md

**Files:**
- Modify: `TASKBOARD.md:1` (insert banner above the title; rest untouched)

- [ ] **Step 1: Insert the archive banner**

Edit `TASKBOARD.md`: replace the single line

```markdown
# TASKBOARD — Claude ↔ Codex Coordination
```

with

```markdown
> **⚠️ ARCHIVED (2026-06-11)** — This board belongs to the Codex/cloud-engine era (Mar 2026)
> and is frozen as a historical record. The cloud system (Render + COMPASS engine) is dead and
> the remaining "open" Batch 4 tasks are obsolete: most were implemented without being marked
> done (see `tests/`, `.github/workflows/`), and the rest target the dead cloud stack.
>
> **The active task queue is [`GROKBOARD.md`](GROKBOARD.md)** (Claude ↔ Grok, local screener era).

# TASKBOARD — Claude ↔ Codex Coordination
```

- [ ] **Step 2: Verify nothing else changed**

```powershell
git -C C:\Users\caslu\Desktop\NuevoProyecto diff --stat TASKBOARD.md
```

Expected: `1 file changed, 7 insertions(+)` (banner + blank line only).

- [ ] **Step 3: Commit**

```powershell
Set-Location C:\Users\caslu\Desktop\NuevoProyecto
git add TASKBOARD.md
git commit -m "docs: freeze TASKBOARD.md as Codex-era archive, point to GROKBOARD.md"
```

---

### Task 4: Update AGENTS.md Task Board section

**Files:**
- Modify: `AGENTS.md` (Task Board section, ~line 301)

- [ ] **Step 1: Replace the Task Board section**

Edit `AGENTS.md`: replace

```markdown
## Task Board

**Check `TASKBOARD.md` first.** It contains the live task queue managed by Claude. Tasks there take priority over the challenges below. Pick up any task marked `[ ] Open` and `Assigned: Codex`.

When you complete a task:
1. Mark it `[x]` in TASKBOARD.md
2. Add the commit hash in the Completed section
3. Move to the next open task
```

with

```markdown
## Task Board

**Check `GROKBOARD.md` first.** It is the active task queue (Claude ↔ Grok) for the local
screener era. `TASKBOARD.md` is frozen as a historical archive of the Codex/cloud-engine era
(Mar 2026) — do not pick up tasks from it; the cloud system those tasks target is dead, and the
challenges listed below in this file are equally obsolete.

When you complete a task:
1. Mark it `[x]` in GROKBOARD.md
2. Add the commit hash next to the task
3. Move to the next open task
```

- [ ] **Step 2: Commit**

```powershell
Set-Location C:\Users\caslu\Desktop\NuevoProyecto
git add AGENTS.md
git commit -m "docs: point AGENTS.md task board to GROKBOARD.md (TASKBOARD frozen)"
```

---

### Task 5: Push and verify

**Files:** none.

- [ ] **Step 1: Push the three commits (plus the spec/plan commits)**

```powershell
git -C C:\Users\caslu\Desktop\NuevoProyecto push
```

Expected: push succeeds to `origin/main`.

- [ ] **Step 2: Final sanity check**

```powershell
git -C C:\Users\caslu\Desktop\NuevoProyecto status --short
git -C C:\Users\caslu\Desktop\NuevoProyecto log --oneline -5
```

Expected: clean tree (or only gitignored runtime artifacts); the 3 new commits on top.

- [ ] **Step 3: Tell the user the board is live**

Report: GROKBOARD.md published with TASK-201..203, TASKBOARD frozen, AGENTS.md updated, smoke
test result. The user can now tell Grok (in its terminal) to read `GROKBOARD.md` and start.

---

## Self-Review Notes

- **Spec coverage:** smoke test gate → Task 1; GROKBOARD creation with rules/messages/queue →
  Task 2; TASKBOARD freeze header → Task 3; AGENTS.md pointer → Task 4; review-gate and
  conflict-handling rules are encoded inside the GROKBOARD content (rules 7–8). Out-of-scope
  items (cloud revival, scoring changes) are guarded by GROKBOARD rule 6 and the banner text.
- **Placeholders:** the only template token is `<NOW>` in Task 2, resolved by an explicit step.
- **Consistency:** task numbering (201–203), file paths, and test-runner behavior
  (auto-discovery of `test_*.py`, verified against `run_all_tests.py` source) match across
  tasks.
