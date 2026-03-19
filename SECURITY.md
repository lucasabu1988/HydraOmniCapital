# Security Policy

## Supported Versions

The following versions of HydraOmniCapital are currently supported with security updates:

| Version | Supported |
| ------- | --------- |
| 1.x.x   | :white_check_mark: Yes |
| < 1.0   | :x: No |

## Reporting a Vulnerability

We take the security of HydraOmniCapital seriously. If you believe you have found a security vulnerability in this repository, please report it responsibly.

**Please do NOT report security vulnerabilities through public GitHub issues.**

### How to Report

Send a detailed report using GitHub's private vulnerability reporting feature (Security tab > "Report a vulnerability"). Please include the following:

- A clear description of the vulnerability
- Steps to reproduce the issue
- Potential impact and severity assessment
- Any suggested fixes or mitigations (optional)

### What to Expect

- **Acknowledgement:** You will receive an acknowledgement within **48 hours** of your report.
- **Status Updates:** We will keep you informed of our progress and aim to provide a full response within **7 days**, including our assessment and an expected resolution timeline.
- **Resolution:** Once the vulnerability is confirmed, we will work to release a patch as quickly as possible and notify you when it is deployed.
- **Credit:** With your permission, we will acknowledge your contribution in the release notes.

## Scope

The following are considered **in scope** for vulnerability reports:

- Authentication and authorization flaws
- Data exposure or leakage
- Injection vulnerabilities (SQL, XSS, etc.)
- Logic errors affecting security
- Dependency vulnerabilities with a known exploit

The following are **out of scope**:

- Issues in dependencies with no direct impact on this project
- Vulnerabilities in forked or third-party repositories
- Social engineering attacks
- Physical security issues

## Security Best Practices for Contributors

- Never commit secrets, API keys, tokens, or credentials to the repository
- Keep dependencies up to date and regularly audit them for known vulnerabilities
- Follow the principle of least privilege when writing code
- Review and test all changes before submitting a pull request

## Disclosure Policy

We follow a **coordinated disclosure** model. We ask that you give us a reasonable amount of time to address a reported vulnerability before any public disclosure. We are committed to working transparently with security researchers to verify and resolve any potential vulnerabilities.
