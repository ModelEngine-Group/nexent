/**
 * Error code definitions for the frontend.
 *
 * Format: XYYZZZ
 * - X: Error level (1=System, 2=Auth, 3=Business, 4=External)
 * - YY: Module number (01-99)
 * - ZZZ: Error sequence (001-999)
 *
 * Module Numbers:
 * - 01: System
 * - 02: Auth
 * - 03: User
 * - 04: Tenant
 * - 05: Agent
 * - 06: Tool/MCP
 * - 07: Conversation
 * - 08: Memory
 * - 09: Knowledge
 * - 10: Model
 * - 11: Voice
 * - 12: File
 * - 13: Invitation
 * - 14: Group
 * - 15: Data
 * - 16: External
 * - 20: Validation
 * - 21: Resource
 * - 22: RateLimit
 */

export enum ErrorCode {
  // ==================== System Level Errors (10xxxx) ====================
  UNKNOWN_ERROR = 101001,
  SERVICE_UNAVAILABLE = 101002,
  DATABASE_ERROR = 101003,
  TIMEOUT = 101004,
  INTERNAL_ERROR = 101005,

  // ==================== Auth Level Errors (102xxx) ====================
  UNAUTHORIZED = 102001,
  TOKEN_EXPIRED = 102002,
  TOKEN_INVALID = 102003,
  SIGNATURE_INVALID = 102004,
  FORBIDDEN = 102005,

  // ==================== User Module Errors (103xxx) ====================
  USER_NOT_FOUND = 103001,
  USER_REGISTRATION_FAILED = 103002,
  USER_ALREADY_EXISTS = 103003,
  INVALID_CREDENTIALS = 103004,

  // ==================== Tenant Module Errors (104xxx) ====================
  TENANT_NOT_FOUND = 104001,
  TENANT_DISABLED = 104002,
  TENANT_CONFIG_ERROR = 104003,

  // ==================== Agent Module Errors (105xxx) ====================
  AGENT_NOT_FOUND = 105001,
  AGENT_RUN_FAILED = 105002,
  AGENT_NAME_DUPLICATE = 105003,
  AGENT_DISABLED = 105004,
  AGENT_VERSION_NOT_FOUND = 105005,

  // ==================== Tool/MCP Module Errors (106xxx) ====================
  TOOL_NOT_FOUND = 106001,
  TOOL_EXECUTION_FAILED = 106002,
  TOOL_CONFIG_INVALID = 106003,

  // MCP specific errors (1061xx)
  MCP_CONNECTION_FAILED = 106101,
  MCP_NAME_ILLEGAL = 106102,
  MCP_CONTAINER_ERROR = 106103,

  // ==================== Conversation Module Errors (107xxx) ====================
  CONVERSATION_NOT_FOUND = 107001,
  CONVERSATION_SAVE_FAILED = 107002,
  MESSAGE_NOT_FOUND = 107003,
  CONVERSATION_TITLE_GENERATION_FAILED = 107004,

  // ==================== Memory Module Errors (108xxx) ====================
  MEMORY_NOT_FOUND = 108001,
  MEMORY_PREPARATION_FAILED = 108002,
  MEMORY_CONFIG_INVALID = 108003,

  // ==================== Knowledge Module Errors (109xxx) ====================
  KNOWLEDGE_NOT_FOUND = 109001,
  KNOWLEDGE_SYNC_FAILED = 109002,
  INDEX_NOT_FOUND = 109003,
  KNOWLEDGE_SEARCH_FAILED = 109004,
  KNOWLEDGE_UPLOAD_FAILED = 109005,

  // ==================== Model Module Errors (110xxx) ====================
  MODEL_NOT_FOUND = 110001,
  MODEL_CONFIG_INVALID = 110002,
  MODEL_HEALTH_CHECK_FAILED = 110003,
  MODEL_PROVIDER_ERROR = 110004,

  // ==================== Voice Module Errors (111xxx) ====================
  VOICE_SERVICE_ERROR = 111001,
  STT_CONNECTION_FAILED = 111002,
  TTS_CONNECTION_FAILED = 111003,
  VOICE_CONFIG_INVALID = 111004,

  // ==================== File Module Errors (112xxx) ====================
  FILE_NOT_FOUND = 112001,
  FILE_UPLOAD_FAILED = 112002,
  FILE_TOO_LARGE = 112003,
  FILE_TYPE_NOT_ALLOWED = 112004,
  FILE_PREPROCESS_FAILED = 112005,

  // ==================== Invitation Module Errors (113xxx) ====================
  INVITE_CODE_NOT_FOUND = 113001,
  INVITE_CODE_INVALID = 113002,
  INVITE_CODE_EXPIRED = 113003,

  // ==================== Group Module Errors (114xxx) ====================
  GROUP_NOT_FOUND = 114001,
  GROUP_ALREADY_EXISTS = 114002,
  MEMBER_NOT_IN_GROUP = 114003,

  // ==================== Data Process Module Errors (115xxx) ====================
  DATA_PROCESS_FAILED = 115001,
  DATA_PARSE_FAILED = 115002,

  // ==================== External Service Errors (116xxx) ====================
  ME_CONNECTION_FAILED = 116001,
  DATAMATE_CONNECTION_FAILED = 116002,
  DIFY_SERVICE_ERROR = 116003,
  EXTERNAL_API_ERROR = 116004,

  // Dify specific errors (1161xx)
  DIFY_CONFIG_INVALID = 116101,
  DIFY_CONNECTION_ERROR = 116102,
  DIFY_AUTH_ERROR = 116103,
  DIFY_RATE_LIMIT = 116104,
  DIFY_RESPONSE_ERROR = 116105,

  // ==================== Validation Errors (120xxx) ====================
  VALIDATION_ERROR = 120001,
  PARAMETER_INVALID = 120002,
  MISSING_REQUIRED_FIELD = 120003,

  // ==================== Resource Errors (121xxx) ====================
  RESOURCE_NOT_FOUND = 121001,
  RESOURCE_ALREADY_EXISTS = 121002,
  RESOURCE_DISABLED = 121003,

  // ==================== Rate Limit Errors (122xxx) ====================
  RATE_LIMIT_EXCEEDED = 122001,

  // ==================== Success Code ====================
  SUCCESS = 0,
}

/**
 * Check if an error code represents a success.
 */
export const isSuccess = (code: number): boolean => {
  return code === ErrorCode.SUCCESS;
};

/**
 * Check if an error code represents an authentication error.
 */
export const isAuthError = (code: number): boolean => {
  return code >= 102001 && code < 103000;
};

/**
 * Check if an error code represents a session expiration.
 */
export const isSessionExpired = (code: number): boolean => {
  return code === ErrorCode.TOKEN_EXPIRED || code === ErrorCode.TOKEN_INVALID;
};
