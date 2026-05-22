"""
Agent Unavailable Reason Constants

Centralized definition of all possible reasons why an agent may be unavailable.
These values are returned to the frontend via the 'unavailable_reasons' field.
"""


class AgentUnavailableReason:
    """Reason codes for agent unavailability."""

    # Identity conflicts
    DUPLICATE_NAME = "duplicate_name"
    DUPLICATE_DISPLAY_NAME = "duplicate_display_name"

    # Model issues
    MODEL_NOT_CONFIGURED = "model_not_configured"
    MODEL_UNAVAILABLE = "model_unavailable"

    # Tool issues
    TOOL_UNAVAILABLE = "tool_unavailable"
    ALL_TOOLS_DISABLED = "all_tools_disabled"

    # Agent issues
    AGENT_NOT_FOUND = "agent_not_found"

    @classmethod
    def all_reasons(cls) -> list[str]:
        """Return all defined unavailable reason codes."""
        return [
            cls.DUPLICATE_NAME,
            cls.DUPLICATE_DISPLAY_NAME,
            cls.MODEL_NOT_CONFIGURED,
            cls.MODEL_UNAVAILABLE,
            cls.TOOL_UNAVAILABLE,
            cls.ALL_TOOLS_DISABLED,
            cls.AGENT_NOT_FOUND,
        ]

    @classmethod
    def is_valid_reason(cls, reason: str) -> bool:
        """Check if a reason string is a valid reason code."""
        return reason in cls.all_reasons()
