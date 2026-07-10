"""Runtime adapter registry."""

from collections.abc import Iterable

from .base import AgentRuntime
from .config import get_deployment_agent_runtime_provider
from .models import (
    CapabilityNegotiationResult,
    RuntimeCapabilityRequirements,
    negotiate_runtime_capabilities,
)
from .openjiuwen_runtime import OpenJiuwenRuntime
from .smolagents_runtime import SmolagentsRuntime


class UnknownAgentRuntimeProviderError(ValueError):
    """Raised when a runtime provider is not registered."""


class DuplicateAgentRuntimeProviderError(ValueError):
    """Raised when a runtime provider is registered more than once."""


class RuntimeCapabilityNegotiationError(ValueError):
    """Raised when a runtime cannot satisfy required run capabilities."""

    def __init__(self, provider: str, result: CapabilityNegotiationResult):
        self.provider = provider
        self.result = result
        missing = ", ".join(result.missing_required)
        super().__init__(
            f"Agent runtime provider '{provider}' does not support required capabilities: {missing}."
        )


class AgentRuntimeRegistry:
    """In-memory registry of runtime adapters available in this deployment."""

    def __init__(self, runtimes: Iterable[AgentRuntime] | None = None):
        self._runtimes: dict[str, AgentRuntime] = {}
        for runtime in runtimes or []:
            self.register(runtime)

    def register(self, runtime: AgentRuntime, *, replace: bool = False) -> None:
        """Register a runtime adapter by its provider name."""
        name = runtime.name.strip().lower()
        if not name:
            raise ValueError("Runtime provider name cannot be empty.")
        if name in self._runtimes and not replace:
            raise DuplicateAgentRuntimeProviderError(
                f"Runtime provider '{name}' is already registered."
            )
        self._runtimes[name] = runtime

    def get(
        self,
        provider: str,
        requirements: RuntimeCapabilityRequirements | None = None,
    ) -> AgentRuntime:
        """Return a registered runtime adapter and optionally negotiate capabilities."""
        name = provider.strip().lower()
        try:
            runtime = self._runtimes[name]
        except KeyError as exc:
            available = ", ".join(self.list_providers()) or "<none>"
            raise UnknownAgentRuntimeProviderError(
                f"Unknown agent runtime provider '{name}'. Available providers: {available}."
            ) from exc
        if requirements is not None:
            result = self.negotiate(name, requirements)
            if result.is_blocking:
                raise RuntimeCapabilityNegotiationError(name, result)
        return runtime

    def negotiate(
        self,
        provider: str,
        requirements: RuntimeCapabilityRequirements,
    ) -> CapabilityNegotiationResult:
        """Check a provider's capabilities against run requirements."""
        runtime = self.get(provider)
        return negotiate_runtime_capabilities(runtime.capabilities, requirements)

    def list_providers(self) -> list[str]:
        """List registered runtime provider names."""
        return sorted(self._runtimes)


def build_default_agent_runtime_registry() -> AgentRuntimeRegistry:
    """Build the deployment's default runtime registry."""
    return AgentRuntimeRegistry([
        SmolagentsRuntime(),
        OpenJiuwenRuntime(),
    ])


agent_runtime_registry = build_default_agent_runtime_registry()


def get_configured_agent_runtime(
    requirements: RuntimeCapabilityRequirements | None = None,
) -> AgentRuntime:
    """Return the runtime selected by deployment configuration."""
    return agent_runtime_registry.get(get_deployment_agent_runtime_provider(), requirements)
