# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared Agent projections, system references and preparation values.

Constants used by agent execution and streaming.

Domain constants for agent marketplace repository listings.

Agent Unavailable Reason Constants

Centralized definition of all possible reasons why an agent may be unavailable.
These values are returned to the frontend via the 'unavailable_reasons' field.
"""

WORKBENCH_OFFICIAL_SKILL_NAMES = (
    "docx",
    "pdf",
    "pptx",
    "xlsx",
    "canvas-design",
    "analyze-image",
)


SAFE_AGENT_STREAM_ERROR_MESSAGE = "Agent execution failed. Please try again later."
SAFE_REASONING_CONFIGURATION_ERROR_MESSAGE = "思考挡位参数配置错误：当前模型或服务商不支持所选挡位，请在模型高级设置中关闭思考挡位开关或选择支持的挡位。"
REASONING_CONFIGURATION_ERROR_CODE = "MODEL_REASONING_CONFIG_INVALID"


# Listing status: not_shared (未共享), pending_review (待审核),
# rejected (审核驳回), shared (已共享)
STATUS_NOT_SHARED = "not_shared"
STATUS_PENDING_REVIEW = "pending_review"
STATUS_REJECTED = "rejected"
STATUS_SHARED = "shared"

VALID_REPOSITORY_STATUSES = frozenset(
    {
        STATUS_NOT_SHARED,
        STATUS_PENDING_REVIEW,
        STATUS_REJECTED,
        STATUS_SHARED,
    }
)

OWNERSHIP_ALL = "all"
OWNERSHIP_CREATED = "created"
OWNERSHIP_OTHERS = "others"

VALID_OWNERSHIP_FILTERS = frozenset(
    {
        OWNERSHIP_ALL,
        OWNERSHIP_CREATED,
        OWNERSHIP_OTHERS,
    }
)


class AgentUnavailableReason:
    """Reason codes for agent unavailability."""

    # Identity conflicts
    DUPLICATE_NAME = "duplicate_name"
    DUPLICATE_DISPLAY_NAME = "duplicate_display_name"

    # Model issues
    MODEL_NOT_CONFIGURED = "model_not_configured"
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_DELETED = "model_deleted"

    # Tool issues
    TOOL_UNAVAILABLE = "tool_unavailable"
    ALL_TOOLS_DISABLED = "all_tools_disabled"
    MCP_MODEL_UNAVAILABLE = "mcp_model_unavailable"

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
            cls.MODEL_DELETED,
            cls.TOOL_UNAVAILABLE,
            cls.ALL_TOOLS_DISABLED,
            cls.AGENT_NOT_FOUND,
            cls.MCP_MODEL_UNAVAILABLE,
        ]

    @classmethod
    def is_valid_reason(cls, reason: str) -> bool:
        """Check if a reason string is a valid reason code."""
        return reason in cls.all_reasons()


SOURCE_TYPE_NORMAL = "NORMAL"


SOURCE_TYPE_ROLLBACK = "ROLLBACK"


STATUS_RELEASED = "RELEASED"


STATUS_DISABLED = "DISABLED"


STATUS_ARCHIVED = "ARCHIVED"

# Response flag when system prompts are withheld from non-ASSET_OWNER callers.
AGENT_PROMPTS_HIDDEN_FLAG = "prompts_hidden"


DEFAULT_LLM_MAX_TOKENS = 4096

# Deep Thinking Constants
THINK_START_PATTERN = "<think>"
THINK_END_PATTERN = "</think>"


# Skill Creation Streaming Configuration
STREAMABLE_CONTENT_TYPES = frozenset(
    [
        "model_output_thinking",
        "model_output_code",
        "model_output_deep_thinking",
        "tool",
        "execution_logs",
    ]
)

# SSE streaming event type for status messages
STREAM_STATUS_EVENT = "event: stream_status\n"
