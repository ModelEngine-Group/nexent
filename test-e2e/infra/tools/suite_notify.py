"""Send only finalized complete Daily reports, with conservative deduplication."""
import json
from pathlib import Path
import shutil

from suite_runtime import logged, now, save


def send_report(directory: Path, env):
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    if not summary.get("d6_complete") or not summary.get("execution_complete"):
        return "INCOMPLETE_NOT_SENT"
    marker = directory / "notification.json"
    if marker.exists():
        # SENDING/UNKNOWN may already have reached the provider. Never resend blindly.
        return json.loads(marker.read_text(encoding="utf-8"))["status"]
    chat = env.get("FEISHU_REPORT_CHAT_ID", "").strip()
    cli = env.get("LARK_CLI") or shutil.which("lark-cli")
    if not chat or not cli:
        save(marker, {"status": "NOT_CONFIGURED", "at": now()})
        return "NOT_CONFIGURED"
    save(marker, {"status": "SENDING", "at": now()})
    try:
        code = logged([cli, "im", "+messages-send", "--as", "bot", "--chat-id", chat,
                       "--file", "./report.md"], directory, env, directory / "logs/notification.log", 120)
        status = "SENT" if code == 0 else "UNKNOWN"
    except Exception:
        status = "UNKNOWN"
    save(marker, {"status": status, "at": now()})
    return status
