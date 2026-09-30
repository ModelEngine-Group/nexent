"""D5 assets, command gates and timing helpers."""

from __future__ import annotations

import asyncio
import os
import signal
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from d3.assets import asset_path, get_test_asset
from shared.config import repo_root


def destructive_deployment_enabled() -> None:
    mutating = os.environ.get("D5_ENABLE_MUTATING_DEPLOYMENT", "").lower() in {"1", "true", "yes"}
    isolated = os.environ.get("D5_ISOLATED_ENVIRONMENT", "").lower() in {"1", "true", "yes"}
    if not (mutating and isolated):
        pytest.skip(
            "SKIPPED_BY_SAFETY: destructive D5 requires both "
            "D5_ENABLE_MUTATING_DEPLOYMENT=true and D5_ISOLATED_ENVIRONMENT=true"
        )


def require_command(name: str) -> str:
    path = shutil.which(name)
    if not path:
        pytest.skip(f"D5 requires command: {name}")
    return path


async def run_command(*args: str, timeout: float = 600, cwd: Path | None = None,
                      log_path: Path | None = None) -> tuple[int, str]:
    if log_path is None:
        process = await asyncio.create_subprocess_exec(
            *args, cwd=str(cwd or repo_root()), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise AssertionError(f"command timed out after {timeout}s: {args}")
        return int(process.returncode or 0), output.decode("utf-8", errors="replace")

    # Long deployment commands must stream evidence and terminate their entire tree on timeout.
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w+b") as log:
        options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                   else {"start_new_session": True})
        process = await asyncio.create_subprocess_exec(
            *args, cwd=str(cwd or repo_root()), stdout=log, stderr=asyncio.subprocess.STDOUT, **options,
        )
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except TimeoutError:
            if os.name == "nt":
                terminated = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                if terminated.returncode and process.returncode is None:
                    process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            await process.wait()
            raise AssertionError(f"command timed out after {timeout}s; inspect {log_path}")
        log.flush()
        log.seek(max(0, log.tell() - 8192))
        output = log.read()
    return int(process.returncode or 0), output.decode("utf-8", errors="replace")


def threshold_ms(key: str, default: int) -> int:
    value = get_test_asset("performance", key, required=False)
    return int(value or default)


@dataclass
class Stopwatch:
    started: float = 0

    def __enter__(self):
        self.started = time.perf_counter()
        return self

    def __exit__(self, *_):
        self.elapsed_ms = (time.perf_counter() - self.started) * 1000

    elapsed_ms: float = 0
