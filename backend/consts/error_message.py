"""
Error message mappings for error codes.

This module provides default English error messages.
Frontend should use i18n for localized messages.
"""

from typing import Dict, Tuple

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
        ErrorCode.CHAT_METADATA_NOT_ALLOWED: "Runtime metadata input is disabled for this agent.",
        ErrorCode.CHAT_METADATA_INVALID: "Runtime metadata is invalid.",
        ErrorCode.CHAT_METADATA_TOO_LARGE: "Runtime metadata exceeds the maximum allowed size.",
        ErrorCode.CHAT_METADATA_VERSION_CONFLICT: "Runtime metadata was updated by another request.",

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
        ErrorCode.KNOWLEDGE_INDEX_WRITE_BLOCKED: "Knowledge base ingestion failed because storage space is insufficient.",
        ErrorCode.KNOWLEDGE_STORAGE_COMMIT_FAILED: "File upload failed because the storage service is unavailable.",
        ErrorCode.KNOWLEDGE_TASK_SUBMIT_FAILED: "The file was uploaded, but the ingestion service is unavailable.",
        ErrorCode.KNOWLEDGE_DELETE_BLOCKED: "Knowledge base deletion is blocked while files are being processed.",

        # ==================== 07 MCPTools / MCP 工具 ====================
        ErrorCode.MCP_TOOL_NOT_FOUND: "Tool not found.",
        ErrorCode.MCP_TOOL_EXECUTION_FAILED: "Tool execution failed.",
        ErrorCode.MCP_TOOL_CONFIG_INVALID: "Tool configuration is invalid.",
        ErrorCode.MCP_CONNECTION_FAILED: "Failed to connect to MCP service.",
        ErrorCode.MCP_CONTAINER_ERROR: "MCP container operation failed.",
        ErrorCode.MCP_NAME_ILLEGAL: "MCP name contains invalid characters.",
        ErrorCode.MCP_PARAM_CONSTRAINT_ERROR_MESSAGES: {
            "valid_type": "{tool_name} {param_name} must be a valid {value_type}",
            "integer": "{tool_name} {param_name} must be an integer",
            "ge": "{tool_name} {param_name} must be >= {value}",
            "gt": "{tool_name} {param_name} must be > {value}",
            "le": "{tool_name} {param_name} must be <= {value}",
            "lt": "{tool_name} {param_name} must be < {value}",
            "min_length": "{tool_name} {param_name} length must be >= {value}",
            "max_length": "{tool_name} {param_name} length must be <= {value}",
            # "multiple_of": "{tool_name} {param_name} must be a multiple of {value}",
        },

        # ==================== 08 MonitorOps / 监控与运维 ====================
        ErrorCode.MONITOROPS_METRIC_QUERY_FAILED: "Metric query failed.",
        ErrorCode.MONITOROPS_ALERT_CONFIG_INVALID: "Invalid alert configuration.",

        # ==================== 09 Model / 模型管理 ====================
        ErrorCode.MODEL_NOT_FOUND: "Model not found.",
        ErrorCode.MODEL_CONFIG_INVALID: "Model configuration is invalid.",
        ErrorCode.MODEL_HEALTH_CHECK_FAILED: "Model health check failed.",
        ErrorCode.MODEL_PROVIDER_ERROR: "Model provider error.",
        ErrorCode.MODEL_PROMPT_GENERATION_FAILED: "Model is unavailable. Please check the model status and try again.",
        # 02 - Model API errors
        ErrorCode.MODEL_API_KEY_INVALID: "Model API key is invalid or expired. Please check your API key configuration.",
        ErrorCode.MODEL_API_KEY_NO_PERMISSION: "Model API key does not have permission. Please check your API key permissions.",
        ErrorCode.MODEL_RATE_LIMIT_EXCEEDED: "Rate limit exceeded. Please try again later.",
        ErrorCode.MODEL_SERVICE_UNAVAILABLE: "Model service is temporarily unavailable. Please try again later.",
        ErrorCode.MODEL_CONNECTION_ERROR: "Failed to connect to model service. Please check your network and model configuration.",

        # ==================== 10 Memory / 记忆管理 ====================
        ErrorCode.MEMORY_NOT_FOUND: "Memory not found.",
        ErrorCode.MEMORY_PREPARATION_FAILED: "Failed to prepare memory.",
        ErrorCode.MEMORY_CONFIG_INVALID: "Memory configuration is invalid.",

        # ==================== 11 Profile / 个人信息 ====================
        ErrorCode.PROFILE_USER_NOT_FOUND: "User not found.",
        ErrorCode.PROFILE_UPDATE_FAILED: "Profile update failed.",
        ErrorCode.PROFILE_USER_ALREADY_EXISTS: "User already exists.",
        ErrorCode.PROFILE_INVALID_CREDENTIALS: "Invalid username or password.",
        # Profile - Password
        ErrorCode.PROFILE_PASSWORD_WEAK: "Password does not meet security requirements. Please use a stronger password.",
        ErrorCode.PROFILE_PASSWORD_SAME_AS_OLD: "New password cannot be the same as the old password.",

        # ==================== 12 TenantResource / 租户资源 ====================
        ErrorCode.TENANT_NOT_FOUND: "Tenant not found.",
        ErrorCode.TENANT_DISABLED: "Tenant is disabled.",
        ErrorCode.TENANT_CONFIG_ERROR: "Tenant configuration error.",
        ErrorCode.TENANT_RESOURCE_EXCEEDED: "Tenant resource exceeded.",
        ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED: "Personal knowledge base quota exceeded.",
        ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE: "Personal knowledge base quota usage is unavailable.",
        ErrorCode.TENANT_PERSONAL_KB_QUOTA_BELOW_USAGE: "Personal knowledge base quota cannot be lower than current usage.",

        # ==================== 13 External / 外部服务 ====================
        ErrorCode.DATAMATE_CONNECTION_FAILED: "Failed to connect to DataMate service.",
        ErrorCode.DIFY_SERVICE_ERROR: "Dify service error.",
        ErrorCode.DIFY_CONFIG_INVALID: "Dify configuration invalid. Please check URL and API key format.",
        ErrorCode.DIFY_CONNECTION_ERROR: "Failed to connect to Dify. Please check network connection and URL.",
        ErrorCode.DIFY_RESPONSE_ERROR: "Failed to parse Dify response. Please check API URL.",
        ErrorCode.DIFY_AUTH_ERROR: "Dify authentication failed. Please check your API key.",
        ErrorCode.DIFY_RATE_LIMIT: "Dify API rate limit exceeded. Please try again later.",
        ErrorCode.ME_CONNECTION_FAILED: "Failed to connect to ME service.",
        ErrorCode.IDATA_SERVICE_ERROR: "iData service error.",
        ErrorCode.IDATA_CONFIG_INVALID: "iData configuration invalid. Please check URL and API key format.",
        ErrorCode.IDATA_CONNECTION_ERROR: "Failed to connect to iData. Please check network connection and URL.",
        ErrorCode.IDATA_RESPONSE_ERROR: "Failed to parse iData response. Please check API URL.",
        ErrorCode.IDATA_AUTH_ERROR: "iData authentication failed. Please check your API key.",
        ErrorCode.IDATA_RATE_LIMIT: "iData API rate limit exceeded. Please try again later.",
        ErrorCode.AIDP_SERVICE_ERROR: "AIDP service error.",
        ErrorCode.AIDP_CONFIG_INVALID: "AIDP configuration invalid. Please check URL and API key format.",
        ErrorCode.AIDP_CONNECTION_ERROR: "Failed to connect to AIDP. Please check network connection and URL.",
        ErrorCode.AIDP_AUTH_ERROR: "AIDP authentication failed. Please check your API key.",
        ErrorCode.AIDP_RATE_LIMIT: "AIDP API rate limit exceeded. Please try again later.",
        ErrorCode.AIDP_RESPONSE_ERROR: "Failed to parse AIDP response. Please check API URL.",

        # ==================== 14 Northbound / 北向接口 ====================
        ErrorCode.NORTHBOUND_REQUEST_FAILED: "Northbound request failed.",
        ErrorCode.NORTHBOUND_CONFIG_INVALID: "Invalid northbound configuration.",

        # ==================== 15 DataProcess / 数据处理 ====================
        ErrorCode.DATAPROCESS_TASK_FAILED: "Data process task failed.",
        ErrorCode.DATAPROCESS_PARSE_FAILED: "Data parsing failed.",

        # ==================== 16 AgentEvaluation / 智能体评估 ====================
        ErrorCode.AGENT_EVALUATION_CONCURRENT_LIMIT: "Too many evaluation tasks running. Please wait for completion.",
        ErrorCode.AGENT_EVALUATION_TOTAL_LIMIT: "Evaluation task limit reached. Please delete old tasks and retry.",
        ErrorCode.AGENT_EVALUATION_EVALUATOR_COUNT: "Too many evaluators selected (max 5).",
        ErrorCode.AGENT_EVALUATION_EVALUATOR_NOT_FOUND: "Evaluator not found.",
        ErrorCode.AGENT_EVALUATION_EVALUATOR_NOT_PUBLISHED: "Evaluator is not published.",
        ErrorCode.AGENT_EVALUATION_SET_EMPTY: "Evaluation set has no cases.",
        ErrorCode.AGENT_EVALUATION_QUERY_COUNT_RANGE: "Query count must be between 1 and 50.",
        ErrorCode.AGENT_EVALUATION_AGENT_NOT_FOUND: "Agent not found.",
        ErrorCode.AGENT_EVALUATION_JUDGE_MODEL_REQUIRED: "Judge model ID is required.",
        ErrorCode.AGENT_EVALUATION_ONLY_CREATOR_CAN_DELETE: "Only the creator can delete this evaluation run.",
        ErrorCode.AGENT_EVALUATION_QUERY_GENERATION_FAILED: "Failed to generate test queries.",
        ErrorCode.AGENT_EVALUATION_QUERY_GENERATION_FORMAT: "AI returned invalid format for test queries.",
        ErrorCode.AGENT_EVALUATION_QUERY_GENERATION_EMPTY: "AI generated no valid test queries.",
        ErrorCode.AGENT_EVALUATION_CASE_GENERATION_FAILED: "Failed to generate evaluation cases.",
        ErrorCode.AGENT_EVALUATION_CASE_GENERATION_FORMAT: "AI returned invalid format for cases.",
        ErrorCode.AGENT_EVALUATION_CASE_GENERATION_EMPTY: "AI generated no valid cases.",
        ErrorCode.AGENT_EVALUATION_GENERATION_FAILED: "Generation failed.",
        ErrorCode.AGENT_EVALUATION_GENERATION_BAD_FORMAT: "Generation returned invalid format.",
        ErrorCode.AGENT_EVALUATION_GENERATION_NO_VALID_CASES: "No valid cases generated.",
        ErrorCode.AGENT_EVALUATION_SET_IN_USE: "Evaluation set is referenced by active runs and cannot be deleted.",
        ErrorCode.AGENT_EVALUATION_EVALUATOR_IN_USE: "Evaluator is referenced by active evaluation runs and cannot be deleted.",
        ErrorCode.AGENT_EVALUATION_VERSION_NOT_FOUND: "Evaluator version not found.",
        ErrorCode.AGENT_EVALUATION_ANALYSIS_FAILED: "Failed to generate analysis report.",
        ErrorCode.AGENT_EVALUATION_ANALYSIS_NOT_READY: "Evaluation is not complete. Analysis is only available for completed runs.",
        ErrorCode.AGENT_EVALUATION_ANNOTATION_SCHEMA_IN_USE: "Annotation schema is referenced by existing data and cannot be deleted.",
        ErrorCode.AGENT_EVALUATION_TURN_ORDER_MISMATCH: "Session turn_order mismatch.",
        ErrorCode.AGENT_EVALUATION_TURN_DELETE_NOT_LAST: "Can only delete the last turn.",
        ErrorCode.AGENT_EVALUATION_TURN_DELETE_NOT_CONTIGUOUS: "Turn deletion not contiguous.",

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
    def get_param_constraint_messages(cls) -> Dict[str, str]:
        """Get tool parameter constraint validation message templates."""
        return cls._MESSAGES.get(ErrorCode.MCP_PARAM_CONSTRAINT_ERROR_MESSAGES, {})

    @classmethod
    def get_message_with_code(cls, error_code: ErrorCode) -> Tuple[int, str]:
        """Get error code and message as tuple."""
        return (error_code.value, cls.get_message(error_code))

    @classmethod
    def get_all_messages(cls) -> Dict:
        """Get all error code to message mappings."""
        return {code.value: msg for code, msg in cls._MESSAGES.items()}
