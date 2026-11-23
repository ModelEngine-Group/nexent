# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Bound Git synchronization and retain private, credential-redacted receipts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import uuid


NETWORK_ERRORS = (
    "could not resolve host", "failed to connect", "connection timed out",
    "connection reset", "remote end hung up", "early eof", "unexpected eof",
    "tls connection was non-properly terminated", "ssl_error_syscall",
    "http/2 stream", "http2 framing", "operation too slow", "operation timed out",
    "recv failure", "send failure", "empty reply from server",
)


def redact(value: str) -> str:
    value = re.sub(r"(https?://)[^/@\s]+@", r"\1[REDACTED]@", value)
    value = re.sub(r"(?im)((?:proxy-)?authorization\s*:)\s*[^\r\n]+", r"\1 [REDACTED]", value)
    return re.sub(r"(?i)([?&](?:access_token|token|password|secret)=)[^&\s]+", r"\1[REDACTED]", value)


def _text(value) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""


def _private_write(path: Path, content: str) -> None:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as output:
        output.write(redact(content))


def run_git(repo: Path, args, *, log_dir: Path | None = None,
            timeout: float = 120, executable: str = "git", attempts: int = 3) -> str:
    """Retry fetch transport failures only; never retry merge or integrity errors."""
    args = list(args)
    fetching = bool(args and args[0] == "fetch")
    count = attempts if fetching else 1
    deadline = time.monotonic() + timeout
    operation = re.sub(r"[^a-zA-Z0-9_-]", "_", args[0] if args else "git")
    identifier = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    for attempt in range(1, count + 1):
        command = [executable, "-C", str(repo)]
        if fetching:
            command += ["-c", "http.version=HTTP/1.1", "-c", "http.lowSpeedLimit=1",
                        "-c", "http.lowSpeedTime=20"]
        command += args
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Git synchronization exhausted its time budget")
        budget = min(30, max(0.1, remaining - 3)) if fetching else remaining
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        started = time.monotonic()
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=env, start_new_session=os.name != "nt")
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=budget)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            stdout, stderr = process.communicate(timeout=3)
        except BaseException:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            process.wait(timeout=3)
            raise
        stdout, stderr = _text(stdout), _text(stderr)
        code = 124 if timed_out else process.returncode
        prefix = f"{identifier}-{operation}-{attempt}"
        if log_dir is not None:
            _private_write(log_dir / f"{prefix}.stdout.log", stdout)
            _private_write(log_dir / f"{prefix}.stderr.log", stderr)
            _private_write(log_dir / f"{prefix}.json", json.dumps({
                "operation": operation, "attempt": attempt, "exit_code": code,
                "timed_out": timed_out, "duration_seconds": round(time.monotonic() - started, 3),
                "command": command, "stdout": f"{prefix}.stdout.log", "stderr": f"{prefix}.stderr.log",
            }, ensure_ascii=False, indent=2) + "\n")
        if code == 0:
            return stdout.strip()
        retryable = fetching and (timed_out or any(marker in stderr.lower() for marker in NETWORK_ERRORS))
        if not retryable or attempt == count:
            location = f"; evidence: {log_dir / (prefix + '.stderr.log')}" if log_dir is not None else ""
            detail = redact(stderr.strip())[:1500] or ("command timed out" if timed_out else "no stderr")
            raise RuntimeError(f"Git {operation} failed (exit {code}): {detail}{location}")
        delay = min(2 ** attempt, max(0, deadline - time.monotonic() - 4))
        if delay:
            time.sleep(delay)
    raise AssertionError("Git attempt loop did not return")
