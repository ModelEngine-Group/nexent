"""Runtime adapter registry."""

import logging
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


logger = logging.getLogger(__name__)


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
        logger.debug(
            "Agent runtime lookup requested, provider=%s, has_capability_requirements=%s",
            name,
            requirements is not None,
        )
        try:
            runtime = self._runtimes[name]
        except KeyError as exc:
            available = ", ".join(self.list_providers()) or "<none>"
            raise UnknownAgentRuntimeProviderError(
                f"Unknown agent runtime provider '{name}'. Available providers: {available}."
            ) from exc
        validate_installation = getattr(runtime, "validate_installation", None)
        if callable(validate_installation):
            validate_installation()
        if requirements is not None:
            result = negotiate_runtime_capabilities(runtime.capabilities, requirements)
            if result.is_blocking:
                logger.error(
                    "Agent runtime provider rejected, provider=%s, runtime_class=%s, "
                    "missing_required=%s, required_capabilities=%s, optional_capabilities=%s",
                    name,
                    type(runtime).__name__,
                    result.missing_required,
                    _sorted_capabilities(requirements.required),
                    _sorted_capabilities(requirements.optional),
                )
                raise RuntimeCapabilityNegotiationError(name, result)
            logger.info(
                "Agent runtime provider selected, provider=%s, runtime_class=%s, "
                "capability_status=%s, required_capabilities=%s, optional_capabilities=%s, "
                "downgraded_optional=%s",
                name,
                type(runtime).__name__,
                result.status,
                _sorted_capabilities(requirements.required),
                _sorted_capabilities(requirements.optional),
                result.downgraded_optional,
            )
        else:
            logger.info(
                "Agent runtime provider selected, provider=%s, runtime_class=%s, capability_status=not_checked",
                name,
                type(runtime).__name__,
            )
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
    return AgentRuntimeRegistry(
        [
            SmolagentsRuntime(),
            OpenJiuwenRuntime(),
        ]
    )


agent_runtime_registry = build_default_agent_runtime_registry()


def get_configured_agent_runtime(
    requirements: RuntimeCapabilityRequirements | None = None,
) -> AgentRuntime:
    """Return the runtime selected by deployment configuration."""
    return agent_runtime_registry.get(
        get_deployment_agent_runtime_provider(), requirements
    )


def _sorted_capabilities(values: Iterable[str] | None) -> list[str]:
    return sorted(str(value) for value in (values or []))
