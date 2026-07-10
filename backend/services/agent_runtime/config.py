"""Deployment-level runtime provider resolution."""

from consts import const


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
