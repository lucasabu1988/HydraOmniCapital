"""TASK-364 — alert channel for unattended runs.

Transports: ``file`` (always on: ``state/alerts.log``, append-only), ``discord`` (webhook),
``telegram`` (bot token + chat id). Which network transports are active comes from the env
variable ``HYDRA_NOTIFY`` (comma list, e.g. ``discord,telegram``); their secrets come from
``DISCORD_WEBHOOK_URL``, ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID``. Secrets are never
logged or echoed. Every failure is swallowed and reported in the return value: a notification
must never take down the ritual.

    from utils.notify import notify
    notify("INFO", "HYDRA v9 2026-09-08", "settled 30 fills, plan 0 orders")
    notify("ALERT", "preflight HARD", "last bar 2026-09-04 != session 2026-09-08")
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests  # optional; only the network transports need it
except Exception:  # pragma: no cover - environment without requests
    requests = None

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG = ROOT / "state" / "alerts.log"
LEVELS = ("INFO", "WARN", "ALERT")
ENV_TRANSPORTS = "HYDRA_NOTIFY"
KNOWN_TRANSPORTS = ("file", "discord", "telegram")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(level: str, title: str, body: str) -> str:
    return f"[{level}] {title}\n{body}".strip()


def send_file(level: str, title: str, body: str, *, path: Path | None = None) -> bool:
    p = Path(path) if path is not None else DEFAULT_LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(f"{_stamp()} {level:<5} {title}\n")
        for line in (body or "").rstrip().splitlines():
            f.write(f"    {line}\n")
    return True


def send_discord(level: str, title: str, body: str, *, webhook_url: str | None = None,
                 post=None, plain: bool = False) -> bool:
    """Discord webhook. Returns True on 200/204. Never raises."""
    url = webhook_url if webhook_url is not None else os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not url:
        return False
    poster = post or (requests.post if requests is not None else None)
    if poster is None:
        return False
    content = body if plain else _text(level, title, body)
    payload = {"content": content[:1900], "username": "HYDRA"}
    try:
        resp = poster(url, json=payload, timeout=10)
        return getattr(resp, "status_code", 0) in (200, 204)
    except Exception:
        return False


def send_telegram(level: str, title: str, body: str, *, bot_token: str | None = None,
                  chat_id: str | None = None, post=None, plain: bool = False) -> bool:
    """Telegram bot sendMessage. Returns True on 200. Never raises."""
    token = bot_token if bot_token is not None else os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = chat_id if chat_id is not None else os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        return False
    poster = post or (requests.post if requests is not None else None)
    if poster is None:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    text = body if plain else _text(level, title, body)
    payload = {"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True}
    try:
        resp = poster(url, json=payload, timeout=10)
        return getattr(resp, "status_code", 0) == 200
    except Exception:
        return False


def configured_transports(env: dict | None = None) -> list[str]:
    e = env if env is not None else os.environ
    raw = str(e.get(ENV_TRANSPORTS, "") or "")
    wanted = [x.strip().lower() for x in raw.split(",") if x.strip()]
    out = ["file"]
    for w in wanted:
        if w in KNOWN_TRANSPORTS and w not in out:
            out.append(w)
    return out


def notify(level: str, title: str, body: str = "", *, transports: list[str] | None = None,
           senders: dict | None = None, log_path: Path | None = None) -> dict:
    """Fan out one message. Returns {transport: ok}. `senders` lets tests inject fakes."""
    lvl = str(level).upper()
    if lvl not in LEVELS:
        lvl = "INFO"
    chosen = list(transports) if transports is not None else configured_transports()
    table = {
        "file": lambda: send_file(lvl, title, body, path=log_path),
        "discord": lambda: send_discord(lvl, title, body),
        "telegram": lambda: send_telegram(lvl, title, body),
    }
    if senders:
        for k, fn in senders.items():
            table[k] = (lambda fn=fn: fn(lvl, title, body))
    result = {}
    for t in chosen:
        fn = table.get(t)
        if fn is None:
            result[t] = False
            continue
        try:
            result[t] = bool(fn())
        except Exception:
            result[t] = False
    return result


def run_summary(out: dict, preflight_rows: list[dict] | None = None, run_id: str | None = None) -> str:
    """One-screen text for the end-of-run message (portfolio_v9.run's return dict)."""
    st = out.get("state") or {}
    summ = out.get("summary") or {}
    sleeves = summ.get("sleeves") or {}
    lines = []
    if preflight_rows:
        bad = [r for r in preflight_rows if r.get("status") in ("HARD", "WARN")]
        lines.append("preflight: " + ("OK" if not bad else "; ".join(f"{r['check']} {r['status']}" for r in bad)))
    lines.append(f"orders planned: {len(out.get('orders') or [])}   fills settled: {len(out.get('fills') or [])}")
    if summ.get("total") is not None:
        parts = [f"{k} {v.get('value', 0):,.0f}" for k, v in sleeves.items() if isinstance(v, dict)]
        lines.append(f"book: {float(summ.get('total') or 0):,.2f}  (" + ", ".join(parts) + ")")
    ix = st.get("interest") or []
    dv = st.get("dividends") or []
    last = st.get("last_run_date")
    lines.append(f"interest records: {len(ix)}   dividend records: {len(dv)}   last_run_date: {last}")
    if out.get("sector_warning"):
        lines.append(f"DEGRADED: {out['sector_warning']}")
    if out.get("instructions_md"):
        lines.append(f"sheet: {out['instructions_md']}")
    if out.get("journal_path"):
        lines.append(f"journal: {out['journal_path']}")
    if run_id or out.get("manifest_path"):
        lines.append(f"run: {run_id or out.get('manifest_path')}")
    return "\n".join(lines)
