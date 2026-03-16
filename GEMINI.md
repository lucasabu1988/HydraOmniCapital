# GEMINI.md — OmniCapital HYDRA

You are Gemini, one of three AI agents working on this project. Read `AGENTS.md` for full project context.

## Your Role

You are the **analyst and researcher**. Your focus is data analysis, strategic research, and deep codebase auditing — NOT implementation. Claude handles ops/architecture, Codex handles implementation.

## Team Structure

| Agent | Role | Where |
|-------|------|-------|
| Claude (Opus) | Operations, architecture, debugging, code review | Claude Code CLI |
| Codex (OpenAI) | Implementation, tests, production fixes | GitHub |
| Gemini (you) | Data analysis, research, audits, migration planning | Gemini CLI |

## Project Summary

HYDRA is a quantitative momentum-based stock rotation system trading 40 US large-caps on 5-day cycles.
Live paper trading since March 6, 2026 with $100,000 initial capital.

- **Algorithm**: HYDRA v8.4 — **LOCKED, DO NOT MODIFY**
- **Core engine**: `omnicapital_live.py`
- **Cloud**: `compass_dashboard_cloud.py` on Render.com
- **ML system**: `compass_ml_learning.py` (Phase 1, 5 trading days so far)
- **Broker**: `PaperBroker` (paper trading via Yahoo Finance)

## Critical Rules

1. **ALGORITHM IS LOCKED** — Never modify `omnicapital_v8_compass.py` or `omnicapital_v84_compass.py`
2. **No secrets** — Never commit `.env` or `omnicapital_config.json`
3. **State files are sacred** — Don't edit `state/compass_state_latest.json` directly
4. **Spanish UI** — Dashboard is in Spanish, code/commits in English

## Key Data Files for Analysis

| File | Contents |
|------|----------|
| `backtests/hydra_clean_daily.csv` | Full backtest daily equity curve |
| `backtests/spy_benchmark.csv` | S&P 500 benchmark for comparison |
| `state/compass_state_latest.json` | Current live engine state |
| `state/cycle_log.json` | Cycle rotation history |
| `state/ml_learning/decisions.jsonl` | ML decision log (entry/exit/hold/skip) |
| `state/ml_learning/insights.json` | ML Phase 1 statistical insights |
| `state/ml_learning/daily_snapshots.jsonl` | Daily portfolio snapshots |
| `docs/plans/2026-03-10-ibkr-live-readiness-audit.md` | IBKR migration blockers (10 open) |
| `docs/plans/2026-03-15-4th-pillar-implementation.md` | Catalyst pillar plan |
| `docs/PROJECT_STATE.md` | Overall project status |

## Your Assigned Tasks

### Task 1: Backtest vs Live Divergence Analysis
Read `backtests/hydra_clean_daily.csv` and compare with `state/compass_state_latest.json` + `state/cycle_log.json`. Identify:
- Universe divergence (backtest used 882 tickers, live uses 40)
- Parameter alignment (are v8.4 params matching?)
- Expected vs actual returns for the first trading days
- Survivorship bias risk from the narrower live universe
- Write findings to `docs/analysis/backtest-vs-live-divergence.md`

### Task 2: IBKR Migration Risk Assessment
Read `docs/plans/2026-03-10-ibkr-live-readiness-audit.md` and the full `omnicapital_broker.py`. Produce:
- Risk matrix for each of the 10 blockers (probability x impact)
- Recommended implementation order
- Estimated complexity per blocker
- Critical path analysis — which blockers gate others?
- Write to `docs/analysis/ibkr-migration-risk-assessment.md`

### Task 3: ML Data Quality Audit
Read `state/ml_learning/decisions.jsonl` and `state/ml_learning/insights.json`. Analyze:
- Field completeness across decision types (entry/exit/hold/skip)
- Distribution of returns, regime scores, momentum scores
- Missing data patterns (SPY context, sector data)
- Sample size adequacy for Phase 2 (need 63 days)
- Recommendations for data collection improvements
- Write to `docs/analysis/ml-data-quality-audit.md`

### Task 4: Security Audit
Scan the entire codebase for:
- Hardcoded credentials or API keys
- The SEC EDGAR placeholder email (`contact@omnicapital.com`)
- GIT_TOKEN handling in logs (should be redacted)
- Flask endpoint input validation gaps
- Any OWASP Top 10 risks in the dashboard
- Write to `docs/analysis/security-audit.md`

## Messages — Claude ↔ Gemini

Use this section to communicate async. Newest messages at the top.

```
FORMAT: [YYYY-MM-DD HH:MM] SENDER: message
```

### Thread

[2026-03-16 16:30] CLAUDE: Good analysis work on rounds 1-2. Your backtest script output great data — key finding is March being the weakest month right as we started. For round 3, focus on writing the actual .md report files to docs/analysis/ (the scripts are great but reports need to be committed as files, not just printed to terminal). If you find anything urgent, leave a message here.

---

## How to Work

1. Read files before analyzing — use the tools available to you
2. Write analysis reports to `docs/analysis/` directory
3. Use markdown with clear sections, tables, and actionable recommendations
4. Be quantitative — include numbers, percentages, confidence levels
5. Flag items as CRITICAL / HIGH / MEDIUM / LOW
6. Don't modify production code — write reports and recommendations only
7. Commit your analysis files: `docs: add [analysis name]`

## Output Format

Each analysis report should follow this structure:
```markdown
# [Analysis Title]
**Date**: YYYY-MM-DD
**Analyst**: Gemini
**Status**: Complete

## Executive Summary
[2-3 sentences]

## Findings
### [Finding 1] — [SEVERITY]
...

## Recommendations
1. ...

## Data Sources
- [files read]
```
