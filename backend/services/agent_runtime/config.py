"""Deployment-level agent runtime configuration."""

from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlparse

from consts import const


class OpenJiuwenSandboxConfigError(ValueError):
    """Raised when the deployment-level fixed sandbox config is invalid."""


@dataclass(frozen=True)
class OpenJiuwenSandboxSettings:
    """Validated settings for a predeployed shared AIO sandbox."""

    enabled: bool
    base_url: str
    provider: str
    execution_timeout_seconds: int
    request_timeout_seconds: int
    workspace_root: str

    def validate(self) -> "OpenJiuwenSandboxSettings":
        """Validate enabled sandbox settings and return this immutable value."""
        if not self.enabled:
            return self
        parsed_url = urlparse(self.base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise OpenJiuwenSandboxConfigError(
                "OPENJIUWEN_SANDBOX_BASE_URL must be an absolute HTTP(S) URL."
            )
        if self.provider != "aio":
            raise OpenJiuwenSandboxConfigError(
                "OPENJIUWEN_SANDBOX_PROVIDER must be 'aio' for the fixed sandbox."
            )
        if self.execution_timeout_seconds <= 0:
            raise OpenJiuwenSandboxConfigError(
                "OPENJIUWEN_SANDBOX_EXECUTION_TIMEOUT_SECONDS must be positive."
            )
        if self.request_timeout_seconds <= 0:
            raise OpenJiuwenSandboxConfigError(
                "OPENJIUWEN_SANDBOX_REQUEST_TIMEOUT_SECONDS must be positive."
            )
        workspace_root = PurePosixPath(self.workspace_root)
        if not workspace_root.is_absolute() or str(workspace_root) in {"/", "."}:
            raise OpenJiuwenSandboxConfigError(
                "OPENJIUWEN_SANDBOX_WORKSPACE_ROOT must be a non-root absolute path."
            )
        return self


def get_deployment_agent_runtime_provider() -> str:
    """Return the validated deployment-level runtime provider."""
    return const.AGENT_RUNTIME_PROVIDER


def resolve_agent_runtime_provider_for_request(requested_provider: str | None = None) -> str:
    """Resolve the runtime provider for a request.

    Runtime provider selection is deployment-level only. The optional argument
    exists so Runtime API Layer callers can pass request metadata without
    accidentally allowing request-scoped overrides.
    """
    return get_deployment_agent_runtime_provider()


def get_openjiuwen_sandbox_settings(
    *,
    validate: bool = True,
) -> OpenJiuwenSandboxSettings:
    """Return deployment-only fixed sandbox settings."""
    settings = OpenJiuwenSandboxSettings(
        enabled=const.OPENJIUWEN_SANDBOX_ENABLED,
        base_url=const.OPENJIUWEN_SANDBOX_BASE_URL,
        provider=const.OPENJIUWEN_SANDBOX_PROVIDER,
        execution_timeout_seconds=(
            const.OPENJIUWEN_SANDBOX_EXECUTION_TIMEOUT_SECONDS
        ),
        request_timeout_seconds=const.OPENJIUWEN_SANDBOX_REQUEST_TIMEOUT_SECONDS,
        workspace_root=const.OPENJIUWEN_SANDBOX_WORKSPACE_ROOT,
    )
    return settings.validate() if validate else settings
