/**
 * Error code definitions for the frontend.
 *
 * Format: XXYYZZ (6 digits string) - Must match backend/consts/error_code.py
 * - XX: Module code (01-99)
 * - YY: Sub module category (01-99)
 * - ZZ: Sequence in category (01-99)
 *
 * Module Numbers:
 * - 00: Common / 公共
 * - 01: Chat / 开始问答
 * - 02: QuickConfig / 快速配置
 * - 03: AgentSpace / 智能体空间
 * - 04: AgentMarket / 智能体市场
 * - 05: AgentDev / 智能体开发
 * - 06: Knowledge / 知识库
 * - 07: MCPTools / MCP 工具
 * - 08: MonitorOps / 监控与运维
 * - 09: Model / 模型管理
 * - 10: Memory / 记忆管理
 * - 11: Profile / 个人信息
 * - 12: TenantResource / 租户资源
 * - 13: External / 外部服务
 * - 14: Northbound / 北向接口
 * - 15: DataProcess / 数据处理
 * - 99: System / 系统级
 */

export const ErrorCode = {
  // ==================== 00 Common / 公共 ====================
  // 01 - Parameter & Validation
  VALIDATION_ERROR: "000101",
  PARAMETER_INVALID: "000102",
  MISSING_REQUIRED_FIELD: "000103",

  // 02 - Auth & Permission
  UNAUTHORIZED: "000201",
  FORBIDDEN: "000202",
  TOKEN_EXPIRED: "000203",
  TOKEN_INVALID: "000204",

  // 03 - External Service
  EXTERNAL_SERVICE_ERROR: "000301",
  RATE_LIMIT_EXCEEDED: "000302",

  // 04 - File
  FILE_NOT_FOUND: "000401",
  FILE_UPLOAD_FAILED: "000402",
  FILE_TOO_LARGE: "000403",
  FILE_TYPE_NOT_ALLOWED: "000404",
  FILE_PREPROCESS_FAILED: "000405",

  // 05 - Resource
  RESOURCE_NOT_FOUND: "000501",
  RESOURCE_ALREADY_EXISTS: "000502",
  RESOURCE_DISABLED: "000503",

  // ==================== 01 Chat / 开始问答 ====================
  // 01 - Conversation
  CONVERSATION_NOT_FOUND: "010101",
  MESSAGE_NOT_FOUND: "010102",
  CONVERSATION_SAVE_FAILED: "010103",
  CONVERSATION_TITLE_GENERATION_FAILED: "010104",

  // ==================== 02 QuickConfig / 快速配置 ====================
  // 01 - Configuration
  QUICK_CONFIG_INVALID: "020101",
  QUICK_CONFIG_SYNC_FAILED: "020102",

  // ==================== 03 AgentSpace / 智能体空间 ====================
  // 01 - Agent
  AGENT_NOT_FOUND: "030101",
  AGENT_DISABLED: "030102",
  AGENT_RUN_FAILED: "030103",
  AGENT_NAME_DUPLICATE: "030104",
  AGENT_VERSION_NOT_FOUND: "030105",

  // ==================== 04 AgentMarket / 智能体市场 ====================
  // 01 - Agent
  AGENTMARKET_AGENT_NOT_FOUND: "040101",

  // ==================== 05 AgentDev / 智能体开发 ====================
  // 01 - Configuration
  AGENTDEV_CONFIG_INVALID: "050101",
  AGENTDEV_PROMPT_INVALID: "050102",

  // ==================== 06 Knowledge / 知识库 ====================
  // 01 - Knowledge Base
  KNOWLEDGE_NOT_FOUND: "060101",
  KNOWLEDGE_UPLOAD_FAILED: "060102",
  KNOWLEDGE_SYNC_FAILED: "060103",
  INDEX_NOT_FOUND: "060104",
  KNOWLEDGE_SEARCH_FAILED: "060105",

  // ==================== 07 MCPTools / MCP 工具 ====================
  // 01 - Tool
  TOOL_NOT_FOUND: "070101",
  TOOL_EXECUTION_FAILED: "070102",
  TOOL_CONFIG_INVALID: "070103",

  // 02 - Connection
  MCP_CONNECTION_FAILED: "070201",
  MCP_CONTAINER_ERROR: "070202",

  // 03 - Configuration
  MCP_NAME_ILLEGAL: "070301",

  // ==================== 08 MonitorOps / 监控与运维 ====================
  // 01 - Monitoring
  MONITOROPS_METRIC_QUERY_FAILED: "080101",

  // 02 - Alert
  MONITOROPS_ALERT_CONFIG_INVALID: "080201",

  // ==================== 09 Model / 模型管理 ====================
  // 01 - Model
  MODEL_NOT_FOUND: "090101",
  MODEL_CONFIG_INVALID: "090102",
  MODEL_HEALTH_CHECK_FAILED: "090103",
  MODEL_PROVIDER_ERROR: "090104",
  MODEL_PROMPT_GENERATION_FAILED: "090105",
  // 02 - Model API errors
  MODEL_API_KEY_INVALID: "090201",
  MODEL_API_KEY_NO_PERMISSION: "090202",
  MODEL_RATE_LIMIT_EXCEEDED: "090203",
  MODEL_SERVICE_UNAVAILABLE: "090204",
  MODEL_CONNECTION_ERROR: "090205",

  // ==================== 10 Memory / 记忆管理 ====================
  // 01 - Memory
  MEMORY_NOT_FOUND: "100101",
  MEMORY_PREPARATION_FAILED: "100102",
  MEMORY_CONFIG_INVALID: "100103",

  // ==================== 11 Profile / 个人信息 ====================
  // 01 - User
  USER_NOT_FOUND: "110101",
  USER_UPDATE_FAILED: "110102",
  USER_ALREADY_EXISTS: "110103",
  INVALID_CREDENTIALS: "110104",

  // ==================== 12 TenantResource / 租户资源 ====================
  // 01 - Tenant
  TENANT_NOT_FOUND: "120101",
  TENANT_DISABLED: "120102",
  TENANT_CONFIG_ERROR: "120103",
  TENANT_RESOURCE_EXCEEDED: "120104",

  // ==================== 13 External / 外部服务 ====================
  // 01 - DataMate
  DATAMATE_CONNECTION_FAILED: "130101",

  // 02 - Dify
  DIFY_SERVICE_ERROR: "130201",
  DIFY_CONFIG_INVALID: "130202",
  DIFY_CONNECTION_ERROR: "130203",
  DIFY_AUTH_ERROR: "130204",
  DIFY_RATE_LIMIT: "130205",
  DIFY_RESPONSE_ERROR: "130206",

  // 03 - ME Service
  ME_CONNECTION_FAILED: "130301",

  // ==================== 14 Northbound / 北向接口 ====================
  // 01 - Request
  NORTHBOUND_REQUEST_FAILED: "140101",

  // 02 - Configuration
  NORTHBOUND_CONFIG_INVALID: "140201",

  // ==================== 15 DataProcess / 数据处理 ====================
  // 01 - Task
  DATA_PROCESS_FAILED: "150101",
  DATA_PARSE_FAILED: "150102",

  // ==================== 99 System / 系统级 ====================
  // 01 - System Errors
  UNKNOWN_ERROR: "990101",
  SERVICE_UNAVAILABLE: "990102",
  DATABASE_ERROR: "990103",
  TIMEOUT: "990104",
  INTERNAL_ERROR: "990105",

  // 02 - Config
  CONFIG_NOT_FOUND: "990201",
  CONFIG_UPDATE_FAILED: "990202",

  // ==================== Success Code ====================
  SUCCESS: "0",
} as const;

export type ErrorCodeType = typeof ErrorCode[keyof typeof ErrorCode];

/**
 * Check if an error code represents a success.
 */
export const isSuccess = (code: string | number): boolean => {
  return code === ErrorCode.SUCCESS || code === 0;
};

/**
 * Check if an error code represents an authentication error.
 */
export const isAuthError = (code: string | number): boolean => {
  const codeStr = String(code);
  return codeStr >= "000201" && codeStr < "000300";
};

/**
 * Check if an error code represents a session expiration.
 */
export const isSessionExpired = (code: string | number): boolean => {
  return code === ErrorCode.TOKEN_EXPIRED || code === ErrorCode.TOKEN_INVALID;
};
