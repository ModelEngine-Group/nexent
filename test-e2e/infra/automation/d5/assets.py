"""D5 assets, command gates and timing helpers."""

from __future__ import annotations

import asyncio
import os
import signal
import shutil
import subprocess
import time
from uuid import uuid4
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
    if os.name == "nt" and name == "bash":
        git = shutil.which("git")
        if git:
            root = Path(git).resolve().parent.parent
            for candidate in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"):
                if candidate.is_file():
                    return str(candidate)
        pytest.skip("D5 shell contracts require Git Bash on Windows")
    path = shutil.which(name)
    if not path:
        pytest.skip(f"D5 requires command: {name}")
    return path


def bash_path(path: Path | str) -> str:
    """Translate host paths for the shell used by deployment contracts."""
    resolved = Path(path).resolve()
    if os.name == "nt":
        drive = resolved.drive
        if len(drive) != 2 or drive[1] != ":":
            raise ValueError("Git Bash contracts require a local drive path")
        return "/" + drive[0].lower() + resolved.as_posix()[2:]
    return str(resolved)


async def run_posix_contract(contract: Path, *, timeout: float = 1200) -> tuple[int, str]:
    """Use Linux filesystem semantics for backup contracts on Windows."""
    if os.name != "nt":
        return await run_command(require_command("bash"), str(contract), timeout=timeout)
    docker = require_command("docker")
    container = os.environ.get("NEXENT_TEST_CONFIG_CONTAINER", "nexent-config")
    code, image = await run_command(docker, "inspect", "--format", "{{.Image}}", container)
    if code or not image.strip().startswith("sha256:"):
        from shared.asset_registry import AssetDependencyError
        raise AssetDependencyError("services", "linux_shell_image",
                                   detail="A local Nexent config image is required for POSIX backup contracts")
    name = "nexent-test-shell-" + uuid4().hex
    relative = contract.relative_to(repo_root()).as_posix()
    try:
        return await run_command(
            docker, "run", "--rm", "--name", name, "--network", "none",
            "--cap-drop", "ALL", "--read-only", "--tmpfs", "/tmp:rw,exec,size=128m",
            "--mount", f"type=bind,source={repo_root()},target=/repo,readonly",
            "--entrypoint", "/bin/bash", image.strip(), f"/repo/{relative}", timeout=timeout,
        )
    finally:
        # The generated name identifies only this invocation's helper.
        await run_command(docker, "rm", "-f", name, timeout=30)


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
