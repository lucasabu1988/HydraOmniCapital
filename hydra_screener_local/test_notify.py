"""TASK-364 — alert channel."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import utils.notify as NT  # noqa: E402


class _Resp:
    def __init__(self, code):
        self.status_code = code


def test_transports_from_env():
    assert NT.configured_transports({}) == ["file"]
    assert NT.configured_transports({"HYDRA_NOTIFY": "discord, telegram"}) == ["file", "discord", "telegram"]
    assert NT.configured_transports({"HYDRA_NOTIFY": "pager,file"}) == ["file"]      # unknown ignored


def test_file_transport_always_written_and_fakes_called(tmp_path):
    log = tmp_path / "alerts.log"
    seen = []
    res = NT.notify("ALERT", "preflight HARD", "stale bar\nsecond line",
                    transports=["file", "discord"], senders={"discord": lambda l, t, b: seen.append((l, t, b)) or True},
                    log_path=log)
    assert res == {"file": True, "discord": True}
    assert seen == [("ALERT", "preflight HARD", "stale bar\nsecond line")]
    txt = log.read_text(encoding="utf-8")
    assert "ALERT preflight HARD" in txt and "    stale bar" in txt and "    second line" in txt


def test_failures_are_swallowed(tmp_path):
    def boom(l, t, b):
        raise RuntimeError("network down")
    res = NT.notify("INFO", "x", "y", transports=["file", "telegram"], senders={"telegram": boom},
                    log_path=tmp_path / "a.log")
    assert res == {"file": True, "telegram": False}


def test_discord_and_telegram_posts(monkeypatch):
    calls = []

    def post(url, json=None, timeout=None):
        calls.append((url, json))
        return _Resp(200)

    assert NT.send_discord("INFO", "t", "b", webhook_url="https://hook", post=post) is True
    assert calls[-1][0] == "https://hook" and calls[-1][1]["content"] == "[INFO] t\nb"
    assert NT.send_telegram("ALERT", "t", "b", bot_token="TOKEN", chat_id="42", post=post) is True
    assert "botTOKEN/sendMessage" in calls[-1][0] and calls[-1][1]["chat_id"] == "42"
    assert NT.send_discord("INFO", "t", "b", webhook_url="", post=post) is False       # unconfigured -> False
    assert NT.send_telegram("INFO", "t", "b", bot_token="", chat_id="", post=post) is False
    # plain keeps the legacy summary message untouched
    NT.send_discord("INFO", "t", "raw message", webhook_url="https://hook", post=post, plain=True)
    assert calls[-1][1]["content"] == "raw message"


def test_secrets_never_reach_the_log(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://hook/SECRET123")
    log = tmp_path / "alerts.log"
    NT.notify("INFO", "hello", "body", transports=["file"], log_path=log)
    assert "SECRET123" not in log.read_text(encoding="utf-8")


def test_run_summary_lines():
    out = {"today": "2026-09-08", "orders": [], "fills": [1] * 30,
           "summary": {"total": 100001.97, "sleeves": {"stocks": {"value": 49999.27}, "etf": {"value": 50002.71}}},
           "state": {"interest": [1, 2], "dividends": [], "last_run_date": "2026-09-08"},
           "instructions_md": "state/instructions_20260908.md", "manifest_path": "runs/x/manifest.json"}
    rows = [{"check": "last bars", "status": "OK", "detail": ""}, {"check": "HYDRA_BACKUP_DIR", "status": "WARN", "detail": ""}]
    text = NT.run_summary(out, preflight_rows=rows, run_id="20260908_164500_daily")
    assert "preflight: HYDRA_BACKUP_DIR WARN" in text
    assert "orders planned: 0   fills settled: 30" in text
    assert "book: 100,001.97" in text and "interest records: 2" in text
    assert "run: 20260908_164500_daily" in text
