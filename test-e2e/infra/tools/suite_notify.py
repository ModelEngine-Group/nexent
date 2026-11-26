# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Notify terminal Daily outcomes independently of publication and recovery success."""
import json
from pathlib import Path
import shutil

from suite_runtime import BatchLock, logged, now, save
from suite_terminal import current_report, notification_environment, notification_text, terminal_context, write_report

TERMINAL_STATES = frozenset({"PASSED", "FAILED", "INCOMPLETE", "INTERRUPTED", "CANCELLED"})


def snapshot(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def send_report(directory: Path, env):
    """Attempt one notification for every terminal state, including incomplete runs."""
    directory = Path(directory)
    marker = directory / "notification.json"
    try:
        with BatchLock(directory / "notification.lock"):
            if marker.exists():
                # A corrupt or uncertain receipt must never cause a blind resend.
                return snapshot(marker).get("status", "UNKNOWN")
            summary, state = snapshot(directory / "summary.json"), snapshot(directory / "status.json")
            if (summary.get("status") or state.get("status")) not in TERMINAL_STATES:
                return "NOT_TERMINAL"
            chat = env.get("FEISHU_REPORT_CHAT_ID", "").strip()
            cli = env.get("LARK_CLI") or shutil.which("lark-cli")
            if not chat or not cli:
                save(marker, {"status": "NOT_CONFIGURED", "at": now()})
                return "NOT_CONFIGURED"
            report = directory / "report.md"
            try:
                body = report.read_text(encoding="utf-8")
                if not body.strip():
                    raise ValueError("Empty report")
                ready = notification_text(current_report(body, directory, summary, environment=env), env)
                if ready != body:
                    write_report(report, ready)
            except (OSError, UnicodeError, ValueError):
                # A failed render/read cannot suppress the saved terminal outcome.
                report = directory / "notification-report.md"
                message = "# Nexent Daily 异常通知\n\n" + "\n".join(terminal_context(directory, summary))
                message += "\n详细报告未生成或不可读取；本通知依据已保存的终态记录，不能视为完整验收报告。\n"
                write_report(report, notification_text(message, env))
            save(marker, {"status": "SENDING", "at": now()})
            try:
                code = logged([cli, "im", "+messages-send", "--as", "bot", "--chat-id", chat,
                               "--file", "./" + report.name], directory, env,
                              directory / "logs/notification.log", 120)
                status = "SENT" if code == 0 else "UNKNOWN"
            except Exception:
                status = "UNKNOWN"
            save(marker, {"status": status, "at": now()})
            return status
    except Exception as exc:
        # Notification/receipt I/O must not erase the original test or recovery outcome.
        print("Terminal notification unavailable: " + type(exc).__name__, flush=True)
        return "UNKNOWN" if marker.exists() else "NOT_SENT"


def notify_launch(directory, home):
    """Cover failures before a batch exists; reuse its receipt once explicitly linked."""
    directory, home = Path(directory), Path(home)
    try:
        import yaml
        path = home / "config/pipeline.yaml"
        try:
            settings = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError, yaml.YAMLError):
            settings = None
        if isinstance(settings, dict) and not settings.get("notify", False):
            return "DISABLED"
        env = notification_environment(home)
        state = snapshot(directory / "status.json")
        if state.get("batch"):
            batch = Path(state["batch"]).resolve()
            if not batch.is_relative_to((home / "runs/repository-daily").resolve()):
                raise ValueError("Linked execution batch is outside the test home")
            summary = snapshot(batch / "summary.json")
            if (batch / "notification.json").exists() or summary.get("status") in TERMINAL_STATES:
                return send_report(batch, env)
        return send_report(directory, env)
    except Exception as exc:
        print("Launch notification unavailable: " + type(exc).__name__, flush=True)
        return "NOT_SENT"
