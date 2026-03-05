"""
Error message mappings for error codes.

This module provides default English error messages.
Frontend should use i18n for localized messages.
"""

from .error_code import ErrorCode


class ErrorMessage:
    """Error code to message mapping."""

    _MESSAGES = {
        # ==================== 00 Common / 公共 ====================
        # 00 - Parameter & Validation
        ErrorCode.COMMON_VALIDATION_ERROR: "Validation failed.",
        ErrorCode.COMMON_PARAMETER_INVALID: "Invalid parameter.",
        ErrorCode.COMMON_MISSING_REQUIRED_FIELD: "Required field is missing.",
        # 01 - Auth & Permission
        ErrorCode.COMMON_UNAUTHORIZED: "You are not authorized to perform this action.",
        ErrorCode.COMMON_FORBIDDEN: "Access forbidden.",
        ErrorCode.COMMON_TOKEN_EXPIRED: "Your session has expired. Please login again.",
        ErrorCode.COMMON_TOKEN_INVALID: "Invalid token. Please login again.",
        # 02 - External Service
        ErrorCode.COMMON_EXTERNAL_SERVICE_ERROR: "External service error.",
        ErrorCode.COMMON_RATE_LIMIT_EXCEEDED: "Too many requests. Please try again later.",
        # 03 - File
        ErrorCode.FILE_NOT_FOUND: "File not found.",
        ErrorCode.FILE_UPLOAD_FAILED: "Failed to upload file.",
        ErrorCode.FILE_TOO_LARGE: "File size exceeds limit.",
        ErrorCode.FILE_TYPE_NOT_ALLOWED: "File type not allowed.",
        ErrorCode.FILE_PREPROCESS_FAILED: "File preprocessing failed.",
        # 04 - Resource
        ErrorCode.COMMON_RESOURCE_NOT_FOUND: "Resource not found.",
        ErrorCode.COMMON_RESOURCE_ALREADY_EXISTS: "Resource already exists.",
        ErrorCode.COMMON_RESOURCE_DISABLED: "Resource is disabled.",

        # ==================== 01 Chat / 开始问答 ====================
        ErrorCode.CHAT_CONVERSATION_NOT_FOUND: "Conversation not found.",
        ErrorCode.CHAT_MESSAGE_NOT_FOUND: "Message not found.",
        ErrorCode.CHAT_CONVERSATION_SAVE_FAILED: "Failed to save conversation.",
        ErrorCode.CHAT_TITLE_GENERATION_FAILED: "Failed to generate conversation title.",

        # ==================== 02 QuickConfig / 快速配置 ====================
        ErrorCode.QUICK_CONFIG_INVALID: "Invalid configuration.",
        ErrorCode.QUICK_CONFIG_SYNC_FAILED: "Sync configuration failed.",

        # ==================== 03 AgentSpace / 智能体空间 ====================
        ErrorCode.AGENTSPACE_AGENT_NOT_FOUND: "Agent not found.",
        ErrorCode.AGENTSPACE_AGENT_DISABLED: "Agent is disabled.",
        ErrorCode.AGENTSPACE_AGENT_RUN_FAILED: "Failed to run agent. Please try again later.",
        ErrorCode.AGENTSPACE_AGENT_NAME_DUPLICATE: "Agent name already exists.",
        ErrorCode.AGENTSPACE_VERSION_NOT_FOUND: "Agent version not found.",

        # ==================== 04 AgentMarket / 智能体市场 ====================
        ErrorCode.AGENTMARKET_AGENT_NOT_FOUND: "Agent not found in market.",

        # ==================== 05 AgentDev / 智能体开发 ====================
        ErrorCode.AGENTDEV_CONFIG_INVALID: "Invalid agent configuration.",
        ErrorCode.AGENTDEV_PROMPT_INVALID: "Invalid prompt.",

        # ==================== 06 Knowledge / 知识库 ====================
        ErrorCode.KNOWLEDGE_NOT_FOUND: "Knowledge base not found.",
        ErrorCode.KNOWLEDGE_UPLOAD_FAILED: "Failed to upload knowledge.",
        ErrorCode.KNOWLEDGE_SYNC_FAILED: "Failed to sync knowledge base.",
        ErrorCode.KNOWLEDGE_INDEX_NOT_FOUND: "Search index not found.",
        ErrorCode.KNOWLEDGE_SEARCH_FAILED: "Knowledge search failed.",

        # ==================== 07 MCPTools / MCP 工具 ====================
        ErrorCode.MCP_TOOL_NOT_FOUND: "Tool not found.",
        ErrorCode.MCP_TOOL_EXECUTION_FAILED: "Tool execution failed.",
        ErrorCode.MCP_TOOL_CONFIG_INVALID: "Tool configuration is invalid.",
        ErrorCode.MCP_CONNECTION_FAILED: "Failed to connect to MCP service.",
        ErrorCode.MCP_CONTAINER_ERROR: "MCP container operation failed.",
        ErrorCode.MCP_NAME_ILLEGAL: "MCP name contains invalid characters.",

        # ==================== 08 MonitorOps / 监控与运维 ====================
        ErrorCode.MONITOROPS_METRIC_QUERY_FAILED: "Metric query failed.",
        ErrorCode.MONITOROPS_ALERT_CONFIG_INVALID: "Invalid alert configuration.",

        # ==================== 09 Model / 模型管理 ====================
        ErrorCode.MODEL_NOT_FOUND: "Model not found.",
        ErrorCode.MODEL_CONFIG_INVALID: "Model configuration is invalid.",
        ErrorCode.MODEL_HEALTH_CHECK_FAILED: "Model health check failed.",
        ErrorCode.MODEL_PROVIDER_ERROR: "Model provider error.",

        # ==================== 10 Memory / 记忆管理 ====================
        ErrorCode.MEMORY_NOT_FOUND: "Memory not found.",
        ErrorCode.MEMORY_PREPARATION_FAILED: "Failed to prepare memory.",
        ErrorCode.MEMORY_CONFIG_INVALID: "Memory configuration is invalid.",

        # ==================== 11 Profile / 个人信息 ====================
        ErrorCode.PROFILE_USER_NOT_FOUND: "User not found.",
        ErrorCode.PROFILE_UPDATE_FAILED: "Profile update failed.",
        ErrorCode.PROFILE_USER_ALREADY_EXISTS: "User already exists.",
        ErrorCode.PROFILE_INVALID_CREDENTIALS: "Invalid username or password.",

        # ==================== 12 TenantResource / 租户资源 ====================
        ErrorCode.TENANT_NOT_FOUND: "Tenant not found.",
        ErrorCode.TENANT_DISABLED: "Tenant is disabled.",
        ErrorCode.TENANT_CONFIG_ERROR: "Tenant configuration error.",
        ErrorCode.TENANT_RESOURCE_EXCEEDED: "Tenant resource exceeded.",

        # ==================== 13 External / 外部服务 ====================
        ErrorCode.DATAMATE_CONNECTION_FAILED: "Failed to connect to DataMate service.",
        ErrorCode.DIFY_SERVICE_ERROR: "Dify service error.",
        ErrorCode.DIFY_CONFIG_INVALID: "Dify configuration invalid. Please check URL and API key format.",
        ErrorCode.DIFY_CONNECTION_ERROR: "Failed to connect to Dify. Please check network connection and URL.",
        ErrorCode.DIFY_RESPONSE_ERROR: "Failed to parse Dify response. Please check API URL.",
        ErrorCode.DIFY_AUTH_ERROR: "Dify authentication failed. Please check your API key.",
        ErrorCode.DIFY_RATE_LIMIT: "Dify API rate limit exceeded. Please try again later.",
        ErrorCode.ME_CONNECTION_FAILED: "Failed to connect to ME service.",

        # ==================== 14 Northbound / 北向接口 ====================
        ErrorCode.NORTHBOUND_REQUEST_FAILED: "Northbound request failed.",
        ErrorCode.NORTHBOUND_CONFIG_INVALID: "Invalid northbound configuration.",

        # ==================== 15 DataProcess / 数据处理 ====================
        ErrorCode.DATAPROCESS_TASK_FAILED: "Data process task failed.",
        ErrorCode.DATAPROCESS_PARSE_FAILED: "Data parsing failed.",

        # ==================== 99 System / 系统级 ====================
        # 01 - System Errors
        ErrorCode.SYSTEM_UNKNOWN_ERROR: "An unknown error occurred. Please try again later.",
        ErrorCode.SYSTEM_SERVICE_UNAVAILABLE: "Service is temporarily unavailable. Please try again later.",
        ErrorCode.SYSTEM_DATABASE_ERROR: "Database operation failed. Please try again later.",
        ErrorCode.SYSTEM_TIMEOUT: "Operation timed out. Please try again later.",
        ErrorCode.SYSTEM_INTERNAL_ERROR: "Internal server error. Please try again later.",
        # 02 - Config
        ErrorCode.CONFIG_NOT_FOUND: "Configuration not found.",
        ErrorCode.CONFIG_UPDATE_FAILED: "Configuration update failed.",
    }

    @classmethod
    def get_message(cls, error_code: ErrorCode) -> str:
        """Get error message by error code."""
        return cls._MESSAGES.get(error_code, "An error occurred. Please try again later.")

    @classmethod
    def get_message_with_code(cls, error_code: ErrorCode) -> tuple[int, str]:
        """Get error code and message as tuple."""
        return (error_code.value, cls.get_message(error_code))

    @classmethod
    def get_all_messages(cls) -> dict:
        """Get all error code to message mappings."""
        return {code.value: msg for code, msg in cls._MESSAGES.items()}
