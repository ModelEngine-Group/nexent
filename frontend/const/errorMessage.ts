/**
 * Error message utility functions.
 *
 * This module provides functions to get error messages by error code.
 * For i18n support, use the getI18nErrorMessage function which reads from translation files.
 */

import { ErrorCode } from "./errorCode";

/**
 * Default error messages (English).
 * These are fallback messages when i18n is not available.
 * Must match backend/consts/error_message.py
 */
export const DEFAULT_ERROR_MESSAGES: Record<string, string> = {
  // ==================== 00 Common / 公共 ====================
  // 01 - Parameter & Validation
  [ErrorCode.VALIDATION_ERROR]: "Validation error.",
  [ErrorCode.PARAMETER_INVALID]: "Invalid parameter.",
  [ErrorCode.MISSING_REQUIRED_FIELD]: "Required field is missing.",

  // 02 - Auth & Permission
  [ErrorCode.UNAUTHORIZED]: "You are not authorized to perform this action.",
  [ErrorCode.FORBIDDEN]: "Access forbidden.",
  [ErrorCode.TOKEN_EXPIRED]: "Your session has expired. Please login again.",
  [ErrorCode.TOKEN_INVALID]: "Invalid token. Please login again.",

  // 03 - External Service
  [ErrorCode.EXTERNAL_SERVICE_ERROR]: "External service error.",
  [ErrorCode.RATE_LIMIT_EXCEEDED]: "Too many requests. Please try again later.",

  // 04 - File
  [ErrorCode.FILE_NOT_FOUND]: "File not found.",
  [ErrorCode.FILE_UPLOAD_FAILED]: "Failed to upload file.",
  [ErrorCode.FILE_TOO_LARGE]: "File size exceeds limit.",
  [ErrorCode.FILE_TYPE_NOT_ALLOWED]: "File type not allowed.",
  [ErrorCode.FILE_PREPROCESS_FAILED]: "File preprocessing failed.",

  // 05 - Resource
  [ErrorCode.RESOURCE_NOT_FOUND]: "Resource not found.",
  [ErrorCode.RESOURCE_ALREADY_EXISTS]: "Resource already exists.",
  [ErrorCode.RESOURCE_DISABLED]: "Resource is disabled.",

  // ==================== 01 Chat / 开始问答 ====================
  // 01 - Conversation
  [ErrorCode.CONVERSATION_NOT_FOUND]: "Conversation not found.",
  [ErrorCode.MESSAGE_NOT_FOUND]: "Message not found.",
  [ErrorCode.CONVERSATION_SAVE_FAILED]: "Failed to save conversation.",
  [ErrorCode.CONVERSATION_TITLE_GENERATION_FAILED]:
    "Failed to generate conversation title.",

  // ==================== 02 QuickConfig / 快速配置 ====================
  // 01 - Configuration
  [ErrorCode.QUICK_CONFIG_INVALID]: "Invalid configuration.",
  [ErrorCode.QUICK_CONFIG_SYNC_FAILED]: "Sync configuration failed.",

  // ==================== 03 AgentSpace / 智能体空间 ====================
  // 01 - Agent
  [ErrorCode.AGENT_NOT_FOUND]: "Agent not found.",
  [ErrorCode.AGENT_DISABLED]: "Agent is disabled.",
  [ErrorCode.AGENT_RUN_FAILED]: "Failed to run agent. Please try again later.",
  [ErrorCode.AGENT_NAME_DUPLICATE]: "Agent name already exists.",
  [ErrorCode.AGENT_VERSION_NOT_FOUND]: "Agent version not found.",

  // ==================== 04 AgentMarket / 智能体市场 ====================
  // 01 - Agent
  [ErrorCode.AGENTMARKET_AGENT_NOT_FOUND]: "Agent not found in market.",

  // ==================== 05 AgentDev / 智能体开发 ====================
  // 01 - Configuration
  [ErrorCode.AGENTDEV_CONFIG_INVALID]: "Invalid agent configuration.",
  [ErrorCode.AGENTDEV_PROMPT_INVALID]: "Invalid prompt.",

  // ==================== 06 Knowledge / 知识库 ====================
  // 01 - Knowledge Base
  [ErrorCode.KNOWLEDGE_NOT_FOUND]: "Knowledge base not found.",
  [ErrorCode.KNOWLEDGE_UPLOAD_FAILED]: "Failed to upload knowledge.",
  [ErrorCode.KNOWLEDGE_SYNC_FAILED]: "Failed to sync knowledge base.",
  [ErrorCode.INDEX_NOT_FOUND]: "Search index not found.",
  [ErrorCode.KNOWLEDGE_SEARCH_FAILED]: "Knowledge search failed.",

  // ==================== 07 MCPTools / MCP 工具 ====================
  // 01 - Tool
  [ErrorCode.TOOL_NOT_FOUND]: "Tool not found.",
  [ErrorCode.TOOL_EXECUTION_FAILED]: "Tool execution failed.",
  [ErrorCode.TOOL_CONFIG_INVALID]: "Tool configuration is invalid.",

  // 02 - Connection
  [ErrorCode.MCP_CONNECTION_FAILED]: "Failed to connect to MCP service.",
  [ErrorCode.MCP_CONTAINER_ERROR]: "MCP container operation failed.",

  // 03 - Configuration
  [ErrorCode.MCP_NAME_ILLEGAL]: "MCP name contains invalid characters.",

  // ==================== 08 MonitorOps / 监控与运维 ====================
  // 01 - Monitoring
  [ErrorCode.MONITOROPS_METRIC_QUERY_FAILED]: "Metric query failed.",

  // 02 - Alert
  [ErrorCode.MONITOROPS_ALERT_CONFIG_INVALID]: "Invalid alert configuration.",

  // ==================== 09 Model / 模型管理 ====================
  // 01 - Model
  [ErrorCode.MODEL_NOT_FOUND]: "Model not found.",
  [ErrorCode.MODEL_CONFIG_INVALID]: "Model configuration is invalid.",
  [ErrorCode.MODEL_HEALTH_CHECK_FAILED]: "Model health check failed.",
  [ErrorCode.MODEL_PROVIDER_ERROR]: "Model provider error.",
  [ErrorCode.MODEL_PROMPT_GENERATION_FAILED]:
    "Model is unavailable. Please check the model status and try again.",
  // 02 - Model API errors
  [ErrorCode.MODEL_API_KEY_INVALID]:
    "Model API key is invalid or expired. Please check your API key configuration.",
  [ErrorCode.MODEL_API_KEY_NO_PERMISSION]:
    "Model API key does not have permission. Please check your API key permissions.",
  [ErrorCode.MODEL_RATE_LIMIT_EXCEEDED]:
    "Rate limit exceeded. Please try again later.",
  [ErrorCode.MODEL_SERVICE_UNAVAILABLE]:
    "Model service is temporarily unavailable. Please try again later.",
  [ErrorCode.MODEL_CONNECTION_ERROR]:
    "Failed to connect to model service. Please check your network and model configuration.",

  // ==================== 10 Memory / 记忆管理 ====================
  // 01 - Memory
  [ErrorCode.MEMORY_NOT_FOUND]: "Memory not found.",
  [ErrorCode.MEMORY_PREPARATION_FAILED]: "Failed to prepare memory.",
  [ErrorCode.MEMORY_CONFIG_INVALID]: "Memory configuration is invalid.",

  // ==================== 11 Profile / 个人信息 ====================
  // 01 - User
  [ErrorCode.USER_NOT_FOUND]: "User not found.",
  [ErrorCode.USER_UPDATE_FAILED]: "Profile update failed.",
  [ErrorCode.USER_ALREADY_EXISTS]: "User already exists.",
  [ErrorCode.INVALID_CREDENTIALS]: "Invalid username or password.",

  // ==================== 12 TenantResource / 租户资源 ====================
  // 01 - Tenant
  [ErrorCode.TENANT_NOT_FOUND]: "Tenant not found.",
  [ErrorCode.TENANT_DISABLED]: "Tenant is disabled.",
  [ErrorCode.TENANT_CONFIG_ERROR]: "Tenant configuration error.",
  [ErrorCode.TENANT_RESOURCE_EXCEEDED]: "Tenant resource exceeded.",

  // ==================== 13 External / 外部服务 ====================
  // 01 - DataMate
  [ErrorCode.DATAMATE_CONNECTION_FAILED]:
    "Failed to connect to DataMate service.",

  // 02 - Dify
  [ErrorCode.DIFY_SERVICE_ERROR]: "Dify service error.",
  [ErrorCode.DIFY_CONFIG_INVALID]:
    "Dify configuration invalid. Please check URL and API key format.",
  [ErrorCode.DIFY_CONNECTION_ERROR]:
    "Failed to connect to Dify. Please check network connection and URL.",
  [ErrorCode.DIFY_AUTH_ERROR]:
    "Dify authentication failed. Please check your API key.",
  [ErrorCode.DIFY_RATE_LIMIT]:
    "Dify API rate limit exceeded. Please try again later.",
  [ErrorCode.DIFY_RESPONSE_ERROR]:
    "Failed to parse Dify response. Please check API URL.",

  // 03 - ME Service
  [ErrorCode.ME_CONNECTION_FAILED]: "Failed to connect to ME service.",

  // ==================== 14 Northbound / 北向接口 ====================
  // 01 - Request
  [ErrorCode.NORTHBOUND_REQUEST_FAILED]: "Northbound request failed.",

  // 02 - Configuration
  [ErrorCode.NORTHBOUND_CONFIG_INVALID]: "Invalid northbound configuration.",

  // ==================== 15 DataProcess / 数据处理 ====================
  // 01 - Task
  [ErrorCode.DATA_PROCESS_FAILED]: "Data processing failed.",
  [ErrorCode.DATA_PARSE_FAILED]: "Data parsing failed.",

  // ==================== 99 System / 系统级 ====================
  // 01 - System Errors
  [ErrorCode.UNKNOWN_ERROR]: "An unknown error occurred. Please try again later.",
  [ErrorCode.SERVICE_UNAVAILABLE]:
    "Service is temporarily unavailable. Please try again later.",
  [ErrorCode.DATABASE_ERROR]:
    "Database operation failed. Please try again later.",
  [ErrorCode.TIMEOUT]: "Operation timed out. Please try again later.",
  [ErrorCode.INTERNAL_ERROR]: "Internal server error. Please try again later.",

  // 02 - Config
  [ErrorCode.CONFIG_NOT_FOUND]: "Configuration not found.",
  [ErrorCode.CONFIG_UPDATE_FAILED]: "Configuration update failed.",

  // ==================== Success ====================
  [ErrorCode.SUCCESS]: "Success",
};

/**
 * Get error message by error code.
 *
 * @param code - The error code (string or number)
 * @returns The error message
 */
export const getErrorMessage = (code: string | number): string => {
  const key = String(code);
  return (
    DEFAULT_ERROR_MESSAGES[key] || "An error occurred. Please try again later."
  );
};

/**
 * API Response interface.
 */
export interface ApiResponse<T = any> {
  code: number;
  message: string;
  data?: T;
  trace_id?: string;
  details?: any;
}

/**
 * Check if API response indicates success.
 *
 * @param response - The API response
 * @returns True if success
 */
export const isApiSuccess = (response: ApiResponse): boolean => {
  return response.code === 0;;
}
