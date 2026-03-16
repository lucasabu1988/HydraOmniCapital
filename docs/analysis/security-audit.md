# Security Audit Report
**Date**: 2026-03-16
**Analyst**: Gemini
**Status**: Complete

## Executive Summary
This audit scanned the codebase for hardcoded credentials, sensitive information, and common web vulnerabilities. One **CRITICAL** finding (hardcoded API key) and one **MEDIUM** finding (privacy/placeholder) were identified.

## Findings

### 1. Hardcoded Tiingo API Key — [CRITICAL]
- **Location**: `omnicapital_v8_compass_tiingo.py:27`
- **Impact**: The Tiingo API key `2b4b5626b2849123c9dac0769e418f9b0ccd2a56` is visible in the source code. This key can be used by unauthorized parties to access paid data, potentially leading to account exhaustion or data limits being reached.
- **Risk**: High risk of theft if committed to a public repository.

### 2. SEC EDGAR Contact Placeholder — [MEDIUM]
- **Location**: `compass_dashboard_cloud.py:1260`
- **Issue**: The `User-Agent` string for SEC EDGAR uses the placeholder email `contact@omnicapital.com`.
- **Impact**: The SEC requires a real contact email for their automated systems. Using a placeholder or "fake" email could lead to the system being blocked by the SEC's servers.

### 3. State/Log Exposure in Dashboard — [LOW]
- **Status**: **Secure**.
- **Assessment**: The Flask dashboard (`compass_dashboard_cloud.py`) correctly uses `set_security_headers` to prevent frame hijacking (X-Frame-Options: DENY) and XSS (X-XSS-Protection: 1).
- **Observation**: The dashboard exposes `state/compass_state_latest.json` via `/api/state`. While intended for public showcase, this file contains information that could reveal position sizes and strategy logic.

### 4. GIT_TOKEN and Environment Secrets — [LOW]
- **Status**: **Secure**.
- **Assessment**: No occurrences of `GIT_TOKEN` or other GitHub secrets were found hardcoded in `.py` or `.md` files in the root directory. `omnicapital_config.json` is correctly sanitized (empty strings for passwords and keys).

## Recommendations
1. **Rotate Key**: Revoke the current Tiingo API key and issue a new one. Store it in a `.env` file or environment variable (`TIINGO_API_KEY`).
2. **Update User-Agent**: Change the SEC EDGAR email to a legitimate operational contact.
3. **Audit Showcase Mode**: In `compass_dashboard_cloud.py`, ensure that sensitive portfolio data (account value, exact share counts) is obfuscated if `HYDRA_MODE == 'showcase'`.

## Data Sources
- `omnicapital_v8_compass_tiingo.py`
- `compass_dashboard_cloud.py`
- `omnicapital_config.json`
- `git_sync.py`
- Codebase grep results (API_KEY, SECRET, TOKEN)
