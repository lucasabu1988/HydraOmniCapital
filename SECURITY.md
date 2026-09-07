# Security Policy

## Supported Versions

HYDRA v9 is the current production version (in production since 2026-09-05; first live orders 2026-09-07). Security updates are provided for:

| Version | Supported | Notes |
| ------- | --------- | ------ |
| 9.x     | ✅ Yes    | Current production — 50/50 portfolio (12-7 momentum sleeve + ETF trend sleeve) |
| < 9.0   | ❌ No     | Legacy archived in `archive/root-legacy-2026-09/`; do not revive |

## Reporting a Vulnerability

We take the security of HydraOmniCapital seriously. This is a **local screener with no cloud or broker integration**, but it handles trading strategy and portfolio state that must remain confidential.

**Please do NOT report security vulnerabilities through public GitHub issues.**

### How to Report

Send a detailed report using GitHub's private vulnerability reporting feature (Security tab > "Report a vulnerability").

> **If the Security tab shows no reporting form, private vulnerability reporting is not enabled on this repository.**
> (It is disabled as of 2026-09-06.) In that case open a public issue containing **only** "I have a security report,
> please open a private channel" — no details, no reproduction, no exploit — and wait for the private thread.
> This repository is **public**: never put the finding itself in a public issue.

Please include:

- A clear description of the vulnerability
- Steps to reproduce the issue
- Potential impact and severity assessment
- Any suggested fixes or mitigations (optional)

### What to Expect

- **Acknowledgement:** Within **48 hours** of your report
- **Status Updates:** Full response within **7 days**, including assessment and expected resolution timeline
- **Resolution:** Patch released as quickly as possible; you will be notified when deployed
- **Credit:** With your permission, we will acknowledge your contribution in the release notes

## Scope

### In Scope for Vulnerability Reports

- **Credential leakage**: Exposure of API keys, tokens, trading secrets, or state data
- **Code injection**: Injection vulnerabilities (SQL, command injection, etc.)
- **State file exposure**: Unintended disclosure of `state/` directory contents (portfolio positions, trading history)
- **Authentication and authorization flaws**
- **Data leakage or corruption**: Exposure of trading strategy, signals, or performance data
- **Logic errors affecting security**: Bugs that could compromise the integrity of scoring, portfolio selection, or signal generation
- **Dependency vulnerabilities with a known exploit** that directly impacts this project

### Out of Scope

- Issues in dependencies with no direct impact on HYDRA
- Vulnerabilities in forked or third-party repositories
- Social engineering or phishing attacks
- Physical security issues
- Information disclosure of publicly documented algorithms or parameters already in `HYDRA_ALGORITHM_SPEC.md`

## Critical Security Rules for Contributors

### 1. Credentials and Secrets — Never Commit

**This is non-negotiable.** The following are **gitignored** and must never be committed:

```
.env                             # Environment variables (API keys, credentials)
omnicapital_config.json          # Legacy trading configuration with secrets
hydra_screener_local/state/      # Live portfolio state, ledger, instruction sheets
hydra_screener_local/history/    # Historical signals and performance (single-disk record)
hydra_screener_local/output/     # Run outputs
hydra_screener_local/backtest/   # Backtest outputs
/state/                          # Legacy COMPASS state at the repo root
```

The **live state is `hydra_screener_local/state/`**, not a `state/` directory at the repo root — root `/state/`
is ignored only as a precaution (it holds nothing today). Do not trust a path because this file lists it:
`git check-ignore -q <path>` is the only answer that counts.

**Verify before every commit**: `git status` must not show any of the above. Use `git add <file>` for specific files, never `git add -A`.

If you accidentally commit credentials:
1. Immediately stop
2. Run `git reset HEAD~1 --soft`
3. Remove the secret from the index
4. Amend the commit
5. Force-push **only if you have not yet shared the branch**
6. Notify Lucas if others have pulled the branch

### 2. Portfolio State and Strategy — Keep Local

- `hydra_screener_local/state/portfolio_v9.json` contains **live portfolio positions** — backed up locally (`HYDRA_BACKUP_DIR`), not in git
- `hydra_screener_local/state/instructions_<date>.md` contains **executable trade instructions** for the weekly cycle
- `hydra_screener_local/history/` contains **complete performance history** and is a single-disk record — do not assume a fresh clone has it
- These files are **not for version control**; they are backed up separately by the user

### 3. Algorithm Integrity

- The scoring algorithm in `core/signals.py` and parameters in `config.py` are locked
- **Do not change formulas or thresholds without explicit approval** from Lucas (GROKBOARD rule 6)
- Test compliance via `test_spec_compliance.py` — it enforces both formulas and parameter values against `HYDRA_ALGORITHM_SPEC.md`
- Changes to the spec must be committed **together with the code and measured numbers**

### 4. Dependencies and Supply Chain

- Keep dependencies up to date and regularly audit them for known vulnerabilities
- Run `python run_all_tests.py` after any dependency change
- External calls (yfinance, HTTP) are wrapped; the scoring path stays pure and offline
- Do not accept pull requests that add unvetted dependencies

### 5. Code Review and Testing

- Review and test all changes before submitting a pull request
- Run the check that could fail: `python run_all_tests.py` must exit `0`
- Three times in one week tests have reported green without running — verify with real data where it exists
- CI (`.github/workflows/test.yml`) runs two jobs: `screener` on Python 3.12 **and** 3.13
  (`run_all_tests.py --cov --strict-console`, 30 s per-test `pytest-timeout`, 15-minute job
  timeout) and `lint` (ruff). A skip is not a pass, and CI green proves regression coverage —
  never financial validity

### 6. Privilege and Access

- Follow the principle of least privilege — only access the state/config you need
- Never use `git reset --hard` or force-push to discard someone else's uncommitted work
- Confirm with Lucas before deleting files or branches

### 7. Repository Settings — What Is NOT Enabled

This policy describes contributor discipline, **not** enforced controls. As of 2026-09-06 the repository is
**public** and every one of these is **disabled** (each needs an admin, i.e. Lucas):

| Control | Status |
| ------- | ------ |
| Private vulnerability reporting | disabled |
| Secret scanning + push protection | disabled |
| Dependabot security updates | disabled |
| Branch protection ruleset on `main` | documented in `hydra_screener_local/docs/BRANCH_PROTECTION.md`, **not applied** |

Until push protection exists, rule 1 is enforced by nothing but the person typing `git add`. Treat it that way.

## Data Handling

### Trading Strategy and Performance Data

- Never commit history of signals, performance metrics, or backtests to the public repo
- Gitignore rules enforce this: `hydra_screener_local/history/`, `hydra_screener_local/backtest/`, etc.
- Backtesting harnesses are in `experiments/` but the cached sweep results and performance numbers are gitignored

### Windows Console Encoding

- Code runs on Windows 11 with cp1252 encoding
- Never let a UTF-8 print take down a runner or test
- Use safe string handling for all console and log output

## Disclosure Policy

We follow a **coordinated disclosure** model:

1. Give us a **reasonable amount of time** to address a reported vulnerability before any public disclosure
2. We commit to working transparently with you throughout the resolution process
3. Once a patch is ready, we will coordinate on a release schedule
4. Public disclosure (CVE, blog post, etc.) happens only after the fix is deployed and users have had time to upgrade

## Questions?

For security-related questions that are not vulnerability reports, open a **private** GitHub discussion or contact Lucas directly. Do not post security concerns in public issues.

---

**Last Updated:** 2026-09-06
**HYDRA Version:** v9
**Repository:** lucasabu1988/HydraOmniCapital
