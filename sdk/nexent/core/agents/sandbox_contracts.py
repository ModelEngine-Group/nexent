# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Deployment-owned sandbox identities and backend-neutral execution contracts."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Protocol, Sequence

DEFAULT_PNPM_STORE_PATH = '/mnt/nexent/workdir/.pnpm-store'


class SandboxBackendUnavailableError(RuntimeError):
    """The selected backend is not implemented; local fallback is forbidden."""


class SandboxGenerationChangedError(RuntimeError):
    """A borrowed connection no longer represents its original container."""


class SandboxPreExecutionError(RuntimeError):
    """Trusted preflight proved that this owner made no remote execution intent."""


@dataclass(frozen=True)
class SandboxOwner:
    deployment_id: str
    namespace: str
    pod_name: str
    pod_uid: str
    pod_ip: str
    epoch: str

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 253:
                raise ValueError(f"Invalid sandbox owner {name}")
        ipaddress.ip_address(self.pod_ip)

    @property
    def key(self) -> str:
        """Keep ownership stable across process epochs and Pod IP changes."""
        data = json.dumps([self.deployment_id, self.namespace, self.pod_uid], separators=(",", ":"))
        return hashlib.sha256(data.encode()).hexdigest()


@dataclass(frozen=True)
class SystemSandboxProfile:
    execution_image: str
    workspace_volume: str
    memory_limit_mb: int = 2048
    cpu_quota: float = 1.0
    network_disabled: bool = True
    workspace_mode: str = "bind"
    container_workspace_root: str = "/mnt/nexent/workdir"
    execution_uid: int = 1000
    execution_gid: int = 1000
    tls_enabled: bool = True

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (self.execution_image, self.workspace_volume)):
            raise ValueError("Sandbox profile requires an image and workspace volume")
        if type(self.memory_limit_mb) is not int or self.memory_limit_mb <= 0:
            raise ValueError("Sandbox profile memory must be positive")
        if type(self.cpu_quota) not in (int, float) or not math.isfinite(self.cpu_quota) or self.cpu_quota <= 0:
            raise ValueError("Sandbox profile CPU must be positive and finite")
        if (type(self.execution_uid) is not int or type(self.execution_gid) is not int
                or self.execution_uid <= 0 or self.execution_gid < 0 or self.tls_enabled is not True):
            raise ValueError("Sandbox profile requires non-root execution and TLS")
        if type(self.network_disabled) is not bool:
            raise ValueError("Sandbox profile network_disabled must be a boolean")
        object.__setattr__(self, 'cpu_quota', float(self.cpu_quota))
        from nexent.core.agents.resources.workspace import validate_container_root

        if self.workspace_mode != "bind":
            raise ValueError("Kubernetes sandbox profile requires a bind workspace")
        validate_container_root(self.container_workspace_root)

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def policy_defaults(self) -> dict[str, Any]:
        """Expose only policy fields, never owner identity or management credentials."""
        return {
            "docker_image": self.execution_image,
            **{name: getattr(self, name) for name in (
                "memory_limit_mb", "cpu_quota", "network_disabled", "workspace_mode", "container_workspace_root",
            )},
        }

    def validate_config(self, config: Any) -> None:
        conflicts = [name for name, value in self.policy_defaults().items() if getattr(config, name) != value]
        if conflicts:
            raise ValueError(f"Sandbox SYSTEM profile conflict: {', '.join(conflicts)}")


@dataclass(frozen=True)
class ScriptProcessResult:
    stdout: bytes
    stderr: bytes
    exit_code: int


class KernelConnection(Protocol):
    base_url: str
    tls_client: Any
    generation: str

    def create_kernel(self) -> str: ...
    def delete_kernel(self, kernel_id: str) -> None: ...


class SandboxBackend(Protocol):
    def ensure_system(self, owner: SandboxOwner, profile: SystemSandboxProfile) -> KernelConnection: ...
    def close_owner(self, owner: SandboxOwner) -> None: ...


class WorkspaceAccess(Protocol):
    def to_execution_path(self, path: str) -> str: ...
    def prepare_run(self, run_id: str) -> None: ...
    def cleanup_run(self, run_id: str) -> None: ...


class ScriptProcessAdapter(Protocol):
    def run(
        self, argv: Sequence[str], *, cwd: str, env: Mapping[str, str], timeout_seconds: float,
    ) -> ScriptProcessResult: ...
