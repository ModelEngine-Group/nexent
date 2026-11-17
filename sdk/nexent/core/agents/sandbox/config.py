# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared sandbox configuration; no executor construction or environment reads."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from nexent.core.agents.resources.workspace import SandboxWorkspace, validate_container_root


class SandboxLevel(str, Enum):
    """Sandbox isolation level, ordered by increasing security."""

    LOCAL = "local"
    DOCKER = "docker"
    WASM = "wasm"


class SandboxScope(str, Enum):
    """
    Container lifecycle scope — controls when a sandbox container is created
    and destroyed.

    - SESSION (default): one container per agent_run, destroyed when the run ends.
      Provides strict multi-tenant isolation between concurrent runs.

    - SYSTEM: a persistent Docker container shared by all agent runs system-wide.
      Each run receives a dedicated Jupyter kernel in that container, so kernel
      state is isolated between concurrent runs while container cold-start is
      avoided. The container remains until application shutdown or failure.
    """

    SESSION = "session"
    SYSTEM = "system"


class ShellPolicy(str, Enum):
    """
    Shell command execution policy inside the sandbox container.

    - DISABLED (recommended default): blocks ``subprocess`` and ``os`` shell
      invocations at AST-parse time before they reach the container.

    - RESTRICTED: V2 — allows only an explicit command allowlist.

    - BOXED: no interception; container filesystem isolation is the only
      guard.  NOT recommended for multi-tenant deployments.
    """

    DISABLED = "disabled"
    RESTRICTED = "restricted"
    BOXED = "boxed"


@dataclass
class SandboxConfig:
    """
    Sandbox execution configuration, injected by the backend service layer.

    Every field is optional; defaults match the existing process-local behaviour
    so that an all-None / all-default config is equivalent to leaving sandboxing
    disabled.
    """

    level: SandboxLevel = SandboxLevel.LOCAL
    scope: SandboxScope = SandboxScope.SESSION
    docker_image: str = "nexent/nexent-sandbox:latest"
    memory_limit_mb: int = 2048
    cpu_quota: float = 1.0
    network_disabled: bool = True
    timeout_seconds: int = 120
    host_tool_timeout_seconds: Optional[float] = None
    shell_policy: ShellPolicy = ShellPolicy.DISABLED
    output_dir: str = "/home/sandbox/workdir/output"
    auto_sync_outputs: bool = True
    extra_kwargs: dict[str, Any] = field(default_factory=dict)
    workspace_mode: str = "legacy"
    container_workspace_root: str = ""
    failure_policy: str = "local"

    def __post_init__(self) -> None:
        if self.workspace_mode not in {"legacy", "bind"}:
            raise ValueError("Unknown sandbox workspace mode")
        if self.failure_policy not in {"local", "error"}:
            raise ValueError("Unknown sandbox failure policy")
        if self.workspace_mode == "bind":
            validate_container_root(self.container_workspace_root)

    def bind_workspace(self) -> Optional[SandboxWorkspace]:
        """Build the explicit mount mapping; never infer a mode from the host OS."""
        if self.workspace_mode != "bind":
            return None
        root = self.extra_kwargs.get("workspace_root")
        if not root or not Path(root).is_absolute():
            raise ValueError("bind workspace requires an absolute host workspace_root")
        return SandboxWorkspace(Path(root), validate_container_root(self.container_workspace_root))

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> "SandboxConfig":
        """Build a SandboxConfig from a plain dict (e.g. from AgentConfig.sandbox_policy)."""
        if not data:
            return cls()
        host_tool_timeout_raw = data.get("host_tool_timeout_seconds")
        host_tool_timeout_seconds = None
        if host_tool_timeout_raw not in (None, ""):
            parsed_timeout = float(host_tool_timeout_raw)
            if parsed_timeout > 0:
                host_tool_timeout_seconds = parsed_timeout
        return cls(
            level=SandboxLevel(data.get("level", "local")),
            scope=SandboxScope(data.get("scope", "session")),
            docker_image=data.get("docker_image", "nexent/nexent-sandbox:latest"),
            memory_limit_mb=int(data.get("memory_limit_mb", 2048)),
            cpu_quota=float(data.get("cpu_quota", 1.0)),
            network_disabled=bool(data.get("network_disabled", True)),
            timeout_seconds=int(data.get("timeout_seconds", 120)),
            host_tool_timeout_seconds=host_tool_timeout_seconds,
            shell_policy=ShellPolicy(data.get("shell_policy", "disabled")),
            output_dir=data.get("output_dir", "/home/sandbox/workdir/output"),
            auto_sync_outputs=bool(data.get("auto_sync_outputs", True)),
            extra_kwargs=data.get("extra_kwargs", {}),
            workspace_mode=data.get("workspace_mode", "legacy"),
            container_workspace_root=data.get("container_workspace_root", ""),
            failure_policy=data.get("failure_policy", "local"),
        )
