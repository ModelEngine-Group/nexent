"""Agent-level runtime framework constants and normalization helpers."""

from enum import Enum


class AgentRuntimeFramework(str, Enum):
    """Execution framework persisted with every Agent version."""

    SMOLAGENTS = "smolagents"
    OPENJIUWEN = "openjiuwen"


DEFAULT_AGENT_RUNTIME_FRAMEWORK = AgentRuntimeFramework.SMOLAGENTS.value
SUPPORTED_AGENT_RUNTIME_FRAMEWORKS = frozenset(item.value for item in AgentRuntimeFramework)


def normalize_agent_runtime_framework(
    value: str | AgentRuntimeFramework | None,
    *,
    default: str | None = DEFAULT_AGENT_RUNTIME_FRAMEWORK,
) -> str | None:
    """Normalize a persisted or request value and reject unsupported frameworks."""
    if value is None:
        return default
    normalized = value.value if isinstance(value, AgentRuntimeFramework) else str(value).strip().lower()
    if normalized not in SUPPORTED_AGENT_RUNTIME_FRAMEWORKS:
        allowed = ", ".join(sorted(SUPPORTED_AGENT_RUNTIME_FRAMEWORKS))
        raise ValueError(f"Unsupported runtime_framework {value!r}; allowed values: {allowed}.")
    return normalized


__all__ = [
    "AgentRuntimeFramework",
    "DEFAULT_AGENT_RUNTIME_FRAMEWORK",
    "SUPPORTED_AGENT_RUNTIME_FRAMEWORKS",
    "normalize_agent_runtime_framework",
]
