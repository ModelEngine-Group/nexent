"""
Error message mappings for error codes.

This module provides default English error messages.
Frontend should use i18n for localized messages.
"""

from .error_code import ErrorCode


class ErrorMessage:
    """Error code to message mapping."""

    _MESSAGES = {
        # ==================== System Level Errors ====================
        ErrorCode.UNKNOWN_ERROR: "An unknown error occurred. Please try again later.",
        ErrorCode.SERVICE_UNAVAILABLE: "Service is temporarily unavailable. Please try again later.",
        ErrorCode.DATABASE_ERROR: "Database operation failed. Please try again later.",
        ErrorCode.TIMEOUT: "Operation timed out. Please try again later.",
        ErrorCode.INTERNAL_ERROR: "Internal server error. Please try again later.",

        # ==================== Auth Level Errors ====================
        ErrorCode.UNAUTHORIZED: "You are not authorized to perform this action.",
        ErrorCode.TOKEN_EXPIRED: "Your session has expired. Please login again.",
        ErrorCode.TOKEN_INVALID: "Invalid token. Please login again.",
        ErrorCode.SIGNATURE_INVALID: "Request signature verification failed.",
        ErrorCode.FORBIDDEN: "Access forbidden.",

        # ==================== User Module Errors ====================
        ErrorCode.USER_NOT_FOUND: "User not found.",
        ErrorCode.USER_REGISTRATION_FAILED: "User registration failed. Please try again later.",
        ErrorCode.USER_ALREADY_EXISTS: "User already exists.",
        ErrorCode.INVALID_CREDENTIALS: "Invalid username or password.",

        # ==================== Tenant Module Errors ====================
        ErrorCode.TENANT_NOT_FOUND: "Tenant not found.",
        ErrorCode.TENANT_DISABLED: "Tenant is disabled.",
        ErrorCode.TENANT_CONFIG_ERROR: "Tenant configuration error.",

        # ==================== Agent Module Errors ====================
        ErrorCode.AGENT_NOT_FOUND: "Agent not found.",
        ErrorCode.AGENT_RUN_FAILED: "Failed to run agent. Please try again later.",
        ErrorCode.AGENT_NAME_DUPLICATE: "Agent name already exists.",
        ErrorCode.AGENT_DISABLED: "Agent is disabled.",
        ErrorCode.AGENT_VERSION_NOT_FOUND: "Agent version not found.",

        # ==================== Tool/MCP Module Errors ====================
        ErrorCode.TOOL_NOT_FOUND: "Tool not found.",
        ErrorCode.TOOL_EXECUTION_FAILED: "Tool execution failed.",
        ErrorCode.TOOL_CONFIG_INVALID: "Tool configuration is invalid.",
        ErrorCode.MCP_CONNECTION_FAILED: "Failed to connect to MCP service.",
        ErrorCode.MCP_NAME_ILLEGAL: "MCP name contains invalid characters.",
        ErrorCode.MCP_CONTAINER_ERROR: "MCP container operation failed.",

        # ==================== Conversation Module Errors ====================
        ErrorCode.CONVERSATION_NOT_FOUND: "Conversation not found.",
        ErrorCode.CONVERSATION_SAVE_FAILED: "Failed to save conversation.",
        ErrorCode.MESSAGE_NOT_FOUND: "Message not found.",
        ErrorCode.CONVERSATION_TITLE_GENERATION_FAILED: "Failed to generate conversation title.",

        # ==================== Memory Module Errors ====================
        ErrorCode.MEMORY_NOT_FOUND: "Memory not found.",
        ErrorCode.MEMORY_PREPARATION_FAILED: "Failed to prepare memory.",
        ErrorCode.MEMORY_CONFIG_INVALID: "Memory configuration is invalid.",

        # ==================== Knowledge Module Errors ====================
        ErrorCode.KNOWLEDGE_NOT_FOUND: "Knowledge base not found.",
        ErrorCode.KNOWLEDGE_SYNC_FAILED: "Failed to sync knowledge base.",
        ErrorCode.INDEX_NOT_FOUND: "Search index not found.",
        ErrorCode.KNOWLEDGE_SEARCH_FAILED: "Knowledge search failed.",
        ErrorCode.KNOWLEDGE_UPLOAD_FAILED: "Failed to upload knowledge.",

        # ==================== Model Module Errors ====================
        ErrorCode.MODEL_NOT_FOUND: "Model not found.",
        ErrorCode.MODEL_CONFIG_INVALID: "Model configuration is invalid.",
        ErrorCode.MODEL_HEALTH_CHECK_FAILED: "Model health check failed.",
        ErrorCode.MODEL_PROVIDER_ERROR: "Model provider error.",

        # ==================== Voice Module Errors ====================
        ErrorCode.VOICE_SERVICE_ERROR: "Voice service error.",
        ErrorCode.STT_CONNECTION_FAILED: "Failed to connect to speech recognition service.",
        ErrorCode.TTS_CONNECTION_FAILED: "Failed to connect to speech synthesis service.",
        ErrorCode.VOICE_CONFIG_INVALID: "Voice configuration is invalid.",

        # ==================== File Module Errors ====================
        ErrorCode.FILE_NOT_FOUND: "File not found.",
        ErrorCode.FILE_UPLOAD_FAILED: "Failed to upload file.",
        ErrorCode.FILE_TOO_LARGE: "File size exceeds limit.",
        ErrorCode.FILE_TYPE_NOT_ALLOWED: "File type not allowed.",
        ErrorCode.FILE_PREPROCESS_FAILED: "File preprocessing failed.",

        # ==================== Invitation Module Errors ====================
        ErrorCode.INVITE_CODE_NOT_FOUND: "Invite code not found.",
        ErrorCode.INVITE_CODE_INVALID: "Invalid invite code.",
        ErrorCode.INVITE_CODE_EXPIRED: "Invite code has expired.",

        # ==================== Group Module Errors ====================
        ErrorCode.GROUP_NOT_FOUND: "Group not found.",
        ErrorCode.GROUP_ALREADY_EXISTS: "Group already exists.",
        ErrorCode.MEMBER_NOT_IN_GROUP: "Member is not in the group.",

        # ==================== Data Process Module Errors ====================
        ErrorCode.DATA_PROCESS_FAILED: "Data processing failed.",
        ErrorCode.DATA_PARSE_FAILED: "Data parsing failed.",

        # ==================== External Service Errors ====================
        ErrorCode.ME_CONNECTION_FAILED: "Failed to connect to ME service.",
        ErrorCode.DATAMATE_CONNECTION_FAILED: "Failed to connect to DataMate service.",
        ErrorCode.DIFY_SERVICE_ERROR: "Dify service error.",
        ErrorCode.EXTERNAL_API_ERROR: "External API error.",

        # ==================== Dify Specific Errors ====================
        ErrorCode.DIFY_CONFIG_INVALID: "Dify configuration invalid. Please check URL and API key format.",
        ErrorCode.DIFY_CONNECTION_ERROR: "Failed to connect to Dify. Please check network connection and URL.",
        ErrorCode.DIFY_RESPONSE_ERROR: "Failed to parse Dify response. Please check API URL.",
        ErrorCode.DIFY_AUTH_ERROR: "Dify authentication failed. Please check your API key.",
        ErrorCode.DIFY_RATE_LIMIT: "Dify API rate limit exceeded. Please try again later.",

        # ==================== Validation Errors ====================
        ErrorCode.VALIDATION_ERROR: "Validation failed.",
        ErrorCode.PARAMETER_INVALID: "Invalid parameter.",
        ErrorCode.MISSING_REQUIRED_FIELD: "Required field is missing.",

        # ==================== Resource Errors ====================
        ErrorCode.RESOURCE_NOT_FOUND: "Resource not found.",
        ErrorCode.RESOURCE_ALREADY_EXISTS: "Resource already exists.",
        ErrorCode.RESOURCE_DISABLED: "Resource is disabled.",

        # ==================== Rate Limit Errors ====================
        ErrorCode.RATE_LIMIT_EXCEEDED: "Too many requests. Please try again later.",
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
