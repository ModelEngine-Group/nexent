"""
Error code definitions for the application.

Format: XXYYZZ (6 digits, string)
- XX: Module code (01-99, based on sidebar)
    00: Common / 公共 - cross-module common errors
    01: Chat / 开始问答
    02: QuickConfig / 快速配置
    03: AgentSpace / 智能体空间
    04: AgentMarket / 智能体市场
    05: AgentDev / 智能体开发
    06: Knowledge / 知识库
    07: MCPTools / MCP 工具
    08: MonitorOps / 监控与运维
    09: Model / 模型管理
    10: Memory / 记忆管理
    11: Profile / 个人信息
    12: TenantResource / 租户资源
    13: External / 外部服务 (DataMate, Dify)
    15: Northbound / 北向接口
    17: DataProcess / 数据处理
    99: System / 系统级 - system internal errors
- YY: Sub module category (01-99)
- ZZ: Sequence in category (01-99)
"""

from enum import Enum


class ErrorCode(Enum):
    """Business error codes (stored as strings to preserve leading zeros)."""

    # ==================== 00 Common / 公共 ====================
    # 01 - Parameter & Validation
    COMMON_VALIDATION_ERROR = "000101"  # Validation error
    COMMON_PARAMETER_INVALID = "000102"  # Invalid parameter
    COMMON_MISSING_REQUIRED_FIELD = "000103"  # Missing required field

    # 02 - Auth & Permission
    COMMON_UNAUTHORIZED = "000201"  # Not logged in / unauthenticated
    COMMON_FORBIDDEN = "000202"  # No permission
    COMMON_TOKEN_EXPIRED = "000203"  # Token expired
    COMMON_TOKEN_INVALID = "000204"  # Invalid token

    # 03 - External Service
    COMMON_EXTERNAL_SERVICE_ERROR = "000301"  # External service error
    COMMON_RATE_LIMIT_EXCEEDED = "000302"  # Rate limit exceeded

    # 04 - File
    FILE_NOT_FOUND = "000401"  # File not found
    FILE_UPLOAD_FAILED = "000402"  # File upload failed
    FILE_TOO_LARGE = "000403"  # File too large
    FILE_TYPE_NOT_ALLOWED = "000404"  # File type not allowed
    FILE_PREPROCESS_FAILED = "000405"  # File preprocess failed

    # 05 - Resource
    COMMON_RESOURCE_NOT_FOUND = "000501"  # Resource not found
    COMMON_RESOURCE_ALREADY_EXISTS = "000502"  # Resource already exists
    COMMON_RESOURCE_DISABLED = "000503"  # Resource disabled

    # ==================== 01 Chat / 开始问答 ====================
    # 01 - Conversation
    CHAT_CONVERSATION_NOT_FOUND = "010101"  # Conversation not found
    CHAT_MESSAGE_NOT_FOUND = "010102"  # Message not found
    CHAT_CONVERSATION_SAVE_FAILED = "010103"  # Failed to save conversation
    CHAT_TITLE_GENERATION_FAILED = "010104"  # Failed to generate title

    # ==================== 02 QuickConfig / 快速配置 ====================
    # 01 - Configuration
    QUICK_CONFIG_INVALID = "020101"  # Invalid configuration
    QUICK_CONFIG_SYNC_FAILED = "020102"  # Sync configuration failed

    # ==================== 03 AgentSpace / 智能体空间 ====================
    # 01 - Agent
    AGENTSPACE_AGENT_NOT_FOUND = "030101"  # Agent not found
    AGENTSPACE_AGENT_DISABLED = "030102"  # Agent disabled
    AGENTSPACE_AGENT_RUN_FAILED = "030103"  # Agent run failed
    AGENTSPACE_AGENT_NAME_DUPLICATE = "030104"  # Duplicate agent name
    AGENTSPACE_VERSION_NOT_FOUND = "030105"  # Agent version not found

    # ==================== 04 AgentMarket / 智能体市场 ====================
    # 01 - Agent
    AGENTMARKET_AGENT_NOT_FOUND = "040101"  # Agent not found in market

    # ==================== 05 AgentDev / 智能体开发 ====================
    # 01 - Configuration
    AGENTDEV_CONFIG_INVALID = "050101"  # Invalid agent configuration
    AGENTDEV_PROMPT_INVALID = "050102"  # Invalid prompt

    # ==================== 06 Knowledge / 知识库 ====================
    # 01 - Knowledge Base
    KNOWLEDGE_NOT_FOUND = "060101"  # Knowledge not found
    KNOWLEDGE_UPLOAD_FAILED = "060102"  # Upload failed
    KNOWLEDGE_SYNC_FAILED = "060103"  # Sync failed
    KNOWLEDGE_INDEX_NOT_FOUND = "060104"  # Index not found
    KNOWLEDGE_SEARCH_FAILED = "060105"  # Search failed

    # ==================== 07 MCPTools / MCP 工具 ====================
    # 01 - Tool
    MCP_TOOL_NOT_FOUND = "070101"  # Tool not found
    MCP_TOOL_EXECUTION_FAILED = "070102"  # Tool execution failed
    MCP_TOOL_CONFIG_INVALID = "070103"  # Invalid tool configuration

    # 02 - Connection
    MCP_CONNECTION_FAILED = "070201"  # MCP connection failed
    MCP_CONTAINER_ERROR = "070202"  # MCP container error

    # 03 - Configuration
    MCP_NAME_ILLEGAL = "070301"  # Illegal MCP name

    # ==================== 08 MonitorOps / 监控与运维 ====================
    # 01 - Monitoring
    MONITOROPS_METRIC_QUERY_FAILED = "080101"  # Metric query failed

    # 02 - Alert
    MONITOROPS_ALERT_CONFIG_INVALID = "080201"  # Invalid alert configuration

    # ==================== 09 Model / 模型管理 ====================
    # 01 - Model
    MODEL_NOT_FOUND = "090101"  # Model not found
    MODEL_CONFIG_INVALID = "090102"  # Invalid model configuration
    MODEL_HEALTH_CHECK_FAILED = "090103"  # Health check failed
    MODEL_PROVIDER_ERROR = "090104"  # Model provider error

    # ==================== 10 Memory / 记忆管理 ====================
    # 01 - Memory
    MEMORY_NOT_FOUND = "100101"  # Memory not found
    MEMORY_PREPARATION_FAILED = "100102"  # Memory preparation failed
    MEMORY_CONFIG_INVALID = "100103"  # Invalid memory configuration

    # ==================== 11 Profile / 个人信息 ====================
    # 01 - User
    PROFILE_USER_NOT_FOUND = "110101"  # User not found
    PROFILE_UPDATE_FAILED = "110102"  # Profile update failed
    PROFILE_USER_ALREADY_EXISTS = "110103"  # User already exists
    PROFILE_INVALID_CREDENTIALS = "110104"  # Invalid credentials

    # ==================== 12 TenantResource / 租户资源 ====================
    # 01 - Tenant
    TENANT_NOT_FOUND = "120101"  # Tenant not found
    TENANT_DISABLED = "120102"  # Tenant disabled
    TENANT_CONFIG_ERROR = "120103"  # Tenant configuration error
    TENANT_RESOURCE_EXCEEDED = "120104"  # Tenant resource exceeded

    # ==================== 13 External / 外部服务 ====================
    # 01 - DataMate
    DATAMATE_CONNECTION_FAILED = "130101"  # DataMate connection failed

    # 02 - Dify
    DIFY_SERVICE_ERROR = "130201"  # Dify service error
    DIFY_CONFIG_INVALID = "130202"  # Invalid Dify configuration
    DIFY_CONNECTION_ERROR = "130203"  # Dify connection error
    DIFY_AUTH_ERROR = "130204"  # Dify auth error
    DIFY_RATE_LIMIT = "130205"  # Dify rate limit
    DIFY_RESPONSE_ERROR = "130206"  # Dify response error

    # 03 - ME Service
    ME_CONNECTION_FAILED = "130301"  # ME service connection failed

    # 04 - iData Service
    IDATA_SERVICE_ERROR = "130401"  # iData service error
    IDATA_CONFIG_INVALID = "130402"  # Invalid iData configuration
    IDATA_CONNECTION_ERROR = "130403"  # iData connection error
    IDATA_AUTH_ERROR = "130404"  # iData auth error
    IDATA_RATE_LIMIT = "130405"  # iData rate limit
    IDATA_RESPONSE_ERROR = "130406"  # iData response error

    # ==================== 14 Northbound / 北向接口 ====================
    # 01 - Request
    NORTHBOUND_REQUEST_FAILED = "140101"  # Northbound request failed

    # 02 - Configuration
    NORTHBOUND_CONFIG_INVALID = "140201"  # Invalid northbound configuration

    # ==================== 15 DataProcess / 数据处理 ====================
    # 01 - Task
    DATAPROCESS_TASK_FAILED = "150101"  # Data process task failed
    DATAPROCESS_PARSE_FAILED = "150102"  # Data parse failed

    # ==================== 99 System / 系统级 ====================
    # 01 - System Errors
    SYSTEM_UNKNOWN_ERROR = "990101"  # Unknown error
    SYSTEM_SERVICE_UNAVAILABLE = "990102"  # Service unavailable
    SYSTEM_DATABASE_ERROR = "990103"  # Database error
    SYSTEM_TIMEOUT = "990104"  # Timeout
    SYSTEM_INTERNAL_ERROR = "990105"  # Internal error

    # 02 - Config
    CONFIG_NOT_FOUND = "990201"  # Configuration not found
    CONFIG_UPDATE_FAILED = "990202"  # Configuration update failed


# HTTP status code mapping
ERROR_CODE_HTTP_STATUS = {
    # Common - Auth
    ErrorCode.COMMON_UNAUTHORIZED: 401,
    ErrorCode.COMMON_TOKEN_EXPIRED: 401,
    ErrorCode.COMMON_TOKEN_INVALID: 401,
    ErrorCode.COMMON_FORBIDDEN: 403,
    # Common - Validation
    ErrorCode.COMMON_VALIDATION_ERROR: 400,
    ErrorCode.COMMON_PARAMETER_INVALID: 400,
    ErrorCode.COMMON_MISSING_REQUIRED_FIELD: 400,
    # Common - Rate Limit
    ErrorCode.COMMON_RATE_LIMIT_EXCEEDED: 429,
    # Common - Resource
    ErrorCode.COMMON_RESOURCE_NOT_FOUND: 404,
    ErrorCode.COMMON_RESOURCE_ALREADY_EXISTS: 409,
    ErrorCode.COMMON_RESOURCE_DISABLED: 403,
    # Common - File
    ErrorCode.FILE_NOT_FOUND: 404,
    ErrorCode.FILE_UPLOAD_FAILED: 500,
    ErrorCode.FILE_TOO_LARGE: 413,
    ErrorCode.FILE_TYPE_NOT_ALLOWED: 400,
    ErrorCode.FILE_PREPROCESS_FAILED: 500,
    # System
    ErrorCode.SYSTEM_SERVICE_UNAVAILABLE: 503,
    ErrorCode.SYSTEM_TIMEOUT: 504,
    ErrorCode.SYSTEM_DATABASE_ERROR: 500,
    ErrorCode.SYSTEM_INTERNAL_ERROR: 500,
    # Dify (module 13)
    ErrorCode.DIFY_CONFIG_INVALID: 400,
    ErrorCode.DIFY_AUTH_ERROR: 401,
    ErrorCode.DIFY_CONNECTION_ERROR: 502,
    ErrorCode.DIFY_RESPONSE_ERROR: 502,
    ErrorCode.DIFY_RATE_LIMIT: 429,
    # iData (module 13)
    ErrorCode.IDATA_CONFIG_INVALID: 400,
    ErrorCode.IDATA_AUTH_ERROR: 401,
    ErrorCode.IDATA_CONNECTION_ERROR: 502,
    ErrorCode.IDATA_RESPONSE_ERROR: 502,
    ErrorCode.IDATA_RATE_LIMIT: 429,
}
