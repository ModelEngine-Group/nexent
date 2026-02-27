# 错误码处理方案

## 1. 错误码格式设计

项目采用了统一的 **XYYZZZ** 格式的 6 位数字错误码：

| 位置 | 含义 | 取值范围 |
|------|------|----------|
| **X** | 错误级别 | 1=系统, 2=认证, 3=业务, 4=外部 |
| **YY** | 模块编号 | 01-22 (系统、认证、用户、租户、Agent、工具、对话、记忆、知识、模型、语音、文件、邀请、分组、数据、外部、验证、资源、限流等) |
| **ZZZ** | 错误序号 | 001-999 |

### 模块编号对照表

| 编号 | 模块 | 编号 | 模块 |
|------|------|------|------|
| 01 | System | 12 | File |
| 02 | Auth | 13 | Invitation |
| 03 | User | 14 | Group |
| 04 | Tenant | 15 | Data |
| 05 | Agent | 16 | External |
| 06 | Tool/MCP | 20 | Validation |
| 07 | Conversation | 21 | Resource |
| 08 | Memory | 22 | RateLimit |
| 09 | Knowledge | | |
| 10 | Model | | |
| 11 | Voice | | |

---

## 2. 后端错误码实现

### 核心文件

| 文件路径 | 职责 |
|----------|------|
| `backend/consts/error_code.py` | 错误码枚举定义 |
| `backend/consts/error_message.py` | 错误消息映射 |
| `backend/consts/exceptions.py` | 自定义异常类 |

### 错误码枚举定义

```python
# backend/consts/error_code.py
class ErrorCode(int, Enum):
    """Business error codes."""

    # ==================== System Level Errors (10xxxx) ====================
    UNKNOWN_ERROR = 101001
    SERVICE_UNAVAILABLE = 101002
    DATABASE_ERROR = 101003
    TIMEOUT = 101004
    INTERNAL_ERROR = 101005

    # ==================== Auth Level Errors (102xxx) ====================
    UNAUTHORIZED = 102001
    TOKEN_EXPIRED = 102002
    TOKEN_INVALID = 102003
    SIGNATURE_INVALID = 102004
    FORBIDDEN = 102005

    # ==================== User Module Errors (103xxx) ====================
    USER_NOT_FOUND = 103001
    USER_REGISTRATION_FAILED = 103002
    USER_ALREADY_EXISTS = 103003
    INVALID_CREDENTIALS = 103004

    # ==================== Tenant Module Errors (104xxx) ====================
    TENANT_NOT_FOUND = 104001
    TENANT_DISABLED = 104002
    TENANT_CONFIG_ERROR = 104003

    # ==================== Agent Module Errors (105xxx) ====================
    AGENT_NOT_FOUND = 105001
    AGENT_RUN_FAILED = 105002
    AGENT_NAME_DUPLICATE = 105003
    AGENT_DISABLED = 105004
    AGENT_VERSION_NOT_FOUND = 105005

    # ==================== Tool/MCP Module Errors (106xxx) ====================
    TOOL_NOT_FOUND = 106001
    TOOL_EXECUTION_FAILED = 106002
    TOOL_CONFIG_INVALID = 106003
    MCP_CONNECTION_FAILED = 106101
    MCP_NAME_ILLEGAL = 106102
    MCP_CONTAINER_ERROR = 106103

    # ==================== Conversation Module Errors (107xxx) ====================
    CONVERSATION_NOT_FOUND = 107001
    CONVERSATION_SAVE_FAILED = 107002
    MESSAGE_NOT_FOUND = 107003
    CONVERSATION_TITLE_GENERATION_FAILED = 107004

    # ==================== Memory Module Errors (108xxx) ====================
    MEMORY_NOT_FOUND = 108001
    MEMORY_PREPARATION_FAILED = 108002
    MEMORY_CONFIG_INVALID = 108003

    # ==================== Knowledge Module Errors (109xxx) ====================
    KNOWLEDGE_NOT_FOUND = 109001
    KNOWLEDGE_SYNC_FAILED = 109002
    INDEX_NOT_FOUND = 109003
    KNOWLEDGE_SEARCH_FAILED = 109004
    KNOWLEDGE_UPLOAD_FAILED = 109005

    # ==================== Model Module Errors (110xxx) ====================
    MODEL_NOT_FOUND = 110001
    MODEL_CONFIG_INVALID = 110002
    MODEL_HEALTH_CHECK_FAILED = 110003
    MODEL_PROVIDER_ERROR = 110004

    # ==================== Voice Module Errors (111xxx) ====================
    VOICE_SERVICE_ERROR = 111001
    STT_CONNECTION_FAILED = 111002
    TTS_CONNECTION_FAILED = 111003
    VOICE_CONFIG_INVALID = 111004

    # ==================== File Module Errors (112xxx) ====================
    FILE_NOT_FOUND = 112001
    FILE_UPLOAD_FAILED = 112002
    FILE_TOO_LARGE = 112003
    FILE_TYPE_NOT_ALLOWED = 112004
    FILE_PREPROCESS_FAILED = 112005

    # ==================== Invitation Module Errors (113xxx) ====================
    INVITE_CODE_NOT_FOUND = 113001
    INVITE_CODE_INVALID = 113002
    INVITE_CODE_EXPIRED = 113003

    # ==================== Group Module Errors (114xxx) ====================
    GROUP_NOT_FOUND = 114001
    GROUP_ALREADY_EXISTS = 114002
    MEMBER_NOT_IN_GROUP = 114003

    # ==================== Data Process Module Errors (115xxx) ====================
    DATA_PROCESS_FAILED = 115001
    DATA_PARSE_FAILED = 115002

    # ==================== External Service Errors (116xxx) ====================
    ME_CONNECTION_FAILED = 116001
    DATAMATE_CONNECTION_FAILED = 116002
    DIFY_SERVICE_ERROR = 116003
    EXTERNAL_API_ERROR = 116004
    DIFY_CONFIG_INVALID = 116101
    DIFY_CONNECTION_ERROR = 116102
    DIFY_AUTH_ERROR = 116103
    DIFY_RATE_LIMIT = 116104
    DIFY_RESPONSE_ERROR = 116105

    # ==================== Validation Errors (120xxx) ====================
    VALIDATION_ERROR = 120001
    PARAMETER_INVALID = 120002
    MISSING_REQUIRED_FIELD = 120003

    # ==================== Resource Errors (121xxx) ====================
    RESOURCE_NOT_FOUND = 121001
    RESOURCE_ALREADY_EXISTS = 121002
    RESOURCE_DISABLED = 121003

    # ==================== Rate Limit Errors (122xxx) ====================
    RATE_LIMIT_EXCEEDED = 122001


# HTTP status code mapping
ERROR_CODE_HTTP_STATUS = {
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.TOKEN_EXPIRED: 401,
    ErrorCode.TOKEN_INVALID: 401,
    ErrorCode.SIGNATURE_INVALID: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.RATE_LIMIT_EXCEEDED: 429,
    ErrorCode.DIFY_RATE_LIMIT: 429,
    ErrorCode.VALIDATION_ERROR: 400,
    ErrorCode.PARAMETER_INVALID: 400,
    ErrorCode.MISSING_REQUIRED_FIELD: 400,
    ErrorCode.FILE_TOO_LARGE: 413,
    ErrorCode.DIFY_CONFIG_INVALID: 400,
    ErrorCode.DIFY_AUTH_ERROR: 400,
    ErrorCode.DIFY_CONNECTION_ERROR: 502,
    ErrorCode.DIFY_RESPONSE_ERROR: 502,
}
```

### 自定义异常类

```python
# backend/consts/exceptions.py
class AppException(Exception):
    """Base application exception with error code."""

    def __init__(self, error_code: ErrorCode, message: str = None, details: dict = None):
        self.error_code = error_code
        self.message = message or ErrorMessage.get_message(error_code)
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {
            "code": self.error_code.value,
            "message": self.message,
            "details": self.details if self.details else None
        }

    @property
    def http_status(self) -> int:
        return ERROR_CODE_HTTP_STATUS.get(self.error_code, 500)


# Backward compatible aliases
NotFoundException = AppException
UnauthorizedError = AppException
ValidationError = AppException
ParameterInvalidError = AppException
ForbiddenError = AppException
ServiceUnavailableError = AppException
DatabaseError = AppException
TimeoutError = AppException
UnknownError = AppException

# Domain Specific Aliases
UserNotFoundError = AppException
UserAlreadyExistsError = AppException
InvalidCredentialsError = AppException

TenantNotFoundError = AppException
TenantDisabledError = AppException

AgentNotFoundError = AppException
AgentRunException = AppException
AgentDisabledError = AppException

ToolNotFoundError = AppException
ToolExecutionException = AppException

MCPConnectionError = AppException
MCPNameIllegal = AppException
MCPContainerError = AppException


def raise_error(error_code: ErrorCode, message: str = None, details: dict = None):
    """Raise an AppException with the given error code."""
    raise AppException(error_code, message, details)
```

### 使用示例

```python
from consts.error_code import ErrorCode
from consts.exceptions import AppException

# 方式1: 直接抛出
raise AppException(ErrorCode.AGENT_NOT_FOUND)

# 方式2: 带自定义消息和详情
raise AppException(
    ErrorCode.MCP_CONNECTION_FAILED, 
    "Connection timeout", 
    details={"host": "localhost", "port": 8080}
)

# 方式3: 使用别名
raise AgentNotFoundError(ErrorCode.AGENT_NOT_FOUND)

# 方式4: 使用辅助函数
from consts.exceptions import raise_error
raise_error(ErrorCode.USER_NOT_FOUND, "User ID not found", details={"user_id": 123})
```

---

## 3. 后端异常处理

### 全局异常处理中间件

```python
# backend/middleware/exception_handler.py
class ExceptionHandlerMiddleware(BaseHTTPMiddleware):
    """Global exception handler middleware."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate trace ID for request tracking
        trace_id = str(uuid.uuid4())
        request.state.trace_id = trace_id

        try:
            response = await call_next(request)
            return response
        except AppException as exc:
            # Handle AppException with error code
            logger.error(f"[{trace_id}] AppException: {exc.error_code.value} - {exc.message}")
            
            return JSONResponse(
                status_code=exc.http_status,
                content={
                    "code": exc.error_code.value,
                    "message": exc.message,
                    "trace_id": trace_id,
                    "details": exc.details if exc.details else None
                }
            )
        except HTTPException as exc:
            # Handle FastAPI HTTPException for backward compatibility
            error_code = _http_status_to_error_code(exc.status_code)
            
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "code": error_code.value,
                    "message": exc.detail,
                    "trace_id": trace_id
                }
            )
        except Exception as exc:
            # Handle unknown exceptions - return HTTP 500
            logger.error(f"[{trace_id}] Unhandled exception: {str(exc)}", exc_info=True)
            
            return JSONResponse(
                status_code=500,
                content={
                    "code": ErrorCode.INTERNAL_ERROR.value,
                    "message": ErrorMessage.get_message(ErrorCode.INTERNAL_ERROR),
                    "trace_id": trace_id,
                    "details": None
                }
            )
```

### HTTP 状态码与业务错误码映射

项目采用 **混合模式**：HTTP 状态码 + 业务错误码。

| 业务错误码 | HTTP 状态码 | 说明 |
|------------|-------------|------|
| 102001-102005 (认证错误) | 401 | 未授权 |
| 102005 (FORBIDDEN) | 403 | 禁止访问 |
| 122001 (RATE_LIMIT_EXCEEDED) | 429 | 请求过于频繁 |
| 120001-120003 (验证错误) | 400 | 请求参数错误 |
| 112003 (FILE_TOO_LARGE) | 413 | 请求实体过大 |
| 116102, 116105 (Dify 连接/响应错误) | 502 | 网关错误 |
| 其他 AppException | 使用映射表或默认 500 | 根据错误码映射 |
| 未知异常 | 500 | 服务器内部错误 |

### 响应格式

**成功响应：**
```json
{
    "code": 0,
    "message": "OK",
    "data": { ... },
    "trace_id": "uuid-string"
}
```

**错误响应：**

```http
HTTP/1.1 404 Not Found
Content-Type: application/json

{
    "code": 105001,
    "message": "Agent not found.",
    "trace_id": "uuid-string",
    "details": null
}
```

```http
HTTP/1.1 401 Unauthorized
Content-Type: application/json

{
    "code": 102002,
    "message": "Your session has expired. Please login again.",
    "trace_id": "uuid-string"
}
```

```http
HTTP/1.1 500 Internal Server Error
Content-Type: application/json

{
    "code": 101005,
    "message": "Internal server error. Please try again later.",
    "trace_id": "uuid-string"
}
```

### 辅助函数

```python
# backend/middleware/exception_handler.py
def create_error_response(
    error_code: ErrorCode,
    message: str = None,
    trace_id: str = None,
    details: dict = None,
    http_status: int = None
) -> JSONResponse:
    """
    Create a standardized error response with mixed mode.
    
    Args:
        error_code: The error code
        message: Optional custom message (defaults to standard message)
        trace_id: Optional trace ID for tracking
        details: Optional additional details
        http_status: Optional HTTP status code (defaults to mapping from error_code)
    
    Returns:
        JSONResponse with standardized error format
    """
    # Use provided http_status or get from error code mapping
    status = http_status if http_status else ERROR_CODE_HTTP_STATUS.get(error_code, 500)
    
    return JSONResponse(
        status_code=status,
        content={
            "code": error_code.value,
            "message": message or ErrorMessage.get_message(error_code),
            "trace_id": trace_id,
            "details": details
        }
    )


def create_success_response(
    data: any = None,
    message: str = "OK",
    trace_id: str = None
) -> JSONResponse:
    """Create a standardized success response."""
    return JSONResponse(
        status_code=200,
        content={
            "code": 0,
            "message": message,
            "data": data,
            "trace_id": trace_id
        }
    )
```

---

## 4. 前端错误码实现

### 核心文件

| 文件路径 | 职责 |
|----------|------|
| `frontend/const/errorCode.ts` | 错误码枚举（与后端一致） |
| `frontend/const/errorMessage.ts` | 默认错误消息（英文） |
| `frontend/const/errorMessageI18n.ts` | i18n 支持工具函数 |
| `frontend/hooks/useErrorHandler.ts` | 错误处理 Hook |

### TypeScript 错误码枚举

```typescript
// frontend/const/errorCode.ts
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

  // ... (与后端完全一致的其他模块错误码)

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
```

---

## 5. 前端错误处理

### API 层

```typescript
// frontend/services/api.ts
export class ApiError extends Error {
  constructor(
    public code: number,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// API request interceptor
export const fetchWithErrorHandling = async (
  url: string,
  options: RequestInit = {}
) => {
  try {
    const response = await fetch(url, options);

    // Handle HTTP errors
    if (!response.ok) {
      // Handle 401 - Session expired
      if (response.status === 401) {
        handleSessionExpired();
        throw new ApiError(
          STATUS_CODES.TOKEN_EXPIRED,
          "Login expired, please login again"
        );
      }

      // Handle 499 - Client closed connection
      if (response.status === 499) {
        handleSessionExpired();
        throw new ApiError(
          STATUS_CODES.TOKEN_EXPIRED,
          "Connection disconnected, session may have expired"
        );
      }

      // Handle 413 - Request entity too large
      if (response.status === 413) {
        throw new ApiError(
          STATUS_CODES.REQUEST_ENTITY_TOO_LARGE,
          "File size exceeds limit"
        );
      }

      // Other HTTP errors - try to parse JSON response for error code
      let errorCode = response.status;
      let errorMessage = `Request failed: ${response.status}`;
      const errorText = await response.text();

      try {
        const errorData = JSON.parse(errorText);
        if (errorData && errorData.code) {
          errorCode = errorData.code;
          errorMessage = errorData.message || errorMessage;
        }
      } catch {
        errorMessage = errorText || errorMessage;
      }

      throw new ApiError(errorCode, errorMessage);
    }

    return response;
  } catch (error) {
    // Handle network errors
    if (error instanceof TypeError && error.message.includes("NetworkError")) {
      throw new ApiError(
        STATUS_CODES.SERVER_ERROR,
        "Network connection error, please check your network connection"
      );
    }

    // Handle connection reset errors
    if (error instanceof TypeError && error.message.includes("Failed to fetch")) {
      // For user management related requests, it might be login expiration
      if (url.includes("/user/session") || url.includes("/user/current_user_id")) {
        handleSessionExpired();
        throw new ApiError(
          STATUS_CODES.TOKEN_EXPIRED,
          "Connection disconnected, session may have expired"
        );
      } else {
        throw new ApiError(
          STATUS_CODES.SERVER_ERROR,
          "Server connection error, please try again later"
        );
      }
    }

    throw error;
  }
};
```

### 错误处理 Hook

```typescript
// frontend/hooks/useErrorHandler.ts
export const useErrorHandler = () => {
  const { t } = useTranslation();

  /**
   * Get i18n error message by error code
   */
  const getI18nErrorMessage = useCallback((code: number): string => {
    // Try to get i18n key
    const i18nKey = `errorCode.${code}`;
    const translated = t(i18nKey);

    // If translation exists (not equal to key), return translated message
    if (translated !== i18nKey) {
      return translated;
    }

    // Fallback to default messages
    return (
      DEFAULT_ERROR_MESSAGES[code] ||
      DEFAULT_ERROR_MESSAGES[ErrorCode.UNKNOWN_ERROR]
    );
  }, [t]);

  /**
   * Handle API error
   */
  const handleError = useCallback(
    (error: unknown, options: ErrorHandlerOptions = {}) => {
      const { showMessage, onError, handleSession } = {
        ...DEFAULT_OPTIONS,
        ...options,
      };

      // Handle ApiError
      if (error instanceof ApiError) {
        // Handle session expiration
        if (handleSession && isSessionExpired(error.code)) {
          handleSessionExpired();
        }

        // Get localized message
        const errorMessage = getI18nErrorMessage(error.code);

        // Log error
        log.error(`API Error [${error.code}]: ${errorMessage}`, error);

        // Show message to user
        if (showMessage) {
          message.error(errorMessage);
        }

        // Call onError callback
        if (onError) {
          onError(error);
        }

        return {
          code: error.code,
          message: errorMessage,
          originalError: error,
        };
      }

      // Handle unknown error
      if (error instanceof Error) {
        log.error("Unknown error:", error);
        if (showMessage) {
          message.error(getI18nErrorMessage(ErrorCode.UNKNOWN_ERROR));
        }
        return {
          code: ErrorCode.UNKNOWN_ERROR,
          message: getI18nErrorMessage(ErrorCode.UNKNOWN_ERROR),
          originalError: error,
        };
      }

      return {
        code: ErrorCode.UNKNOWN_ERROR,
        message: getI18nErrorMessage(ErrorCode.UNKNOWN_ERROR),
        originalError: null,
      };
    },
    [getI18nErrorMessage]
  );

  /**
   * Wrap async function with error handling
   */
  const withErrorHandler = useCallback(
    (fn: () => Promise<any>, options: ErrorHandlerOptions = {}) => {
      return async (...args: any[]) => {
        try {
          return await fn(...args);
        } catch (error) {
          throw handleError(error, options);
        }
      };
    },
    [handleError]
  );

  return {
    getI18nErrorMessage,
    handleError,
    withErrorHandler,
  };
};
```

### i18n 工具函数

```typescript
// frontend/const/errorMessageI18n.ts
export const getI18nErrorMessage = (
  code: number,
  t?: (key: string) => string
): string => {
  // Try i18n translation first
  if (t) {
    const i18nKey = `errorCode.${code}`;
    const translated = t(i18nKey);
    if (translated !== i18nKey) {
      return translated;
    }
  }

  // Fall back to default message
  return (
    DEFAULT_ERROR_MESSAGES[code] ||
    DEFAULT_ERROR_MESSAGES[ErrorCode.UNKNOWN_ERROR]
  );
};

/**
 * Show error to user with i18n support.
 */
export const showErrorToUser = (
  error: any,
  t?: (key: string) => string,
  options: ShowErrorOptions = {}
): void => {
  const {
    handleSession = true,
    showMessage = true,
    customMessage,
    onError,
  } = options;

  // Get error code if available
  let errorCode: number | undefined;
  if (error && typeof error === "object" && "code" in error) {
    errorCode = error.code as number;
  }

  // Handle session expiration
  if (handleSession && errorCode && isSessionExpired(errorCode)) {
    handleSessionExpired();
  }

  // Get the error message
  let errorMessage: string;
  if (customMessage) {
    errorMessage = customMessage;
  } else if (errorCode) {
    errorMessage = getI18nErrorMessage(errorCode, t);
  } else if (error instanceof Error) {
    errorMessage = error.message;
  } else {
    errorMessage = getI18nErrorMessage(ErrorCode.UNKNOWN_ERROR, t);
  }

  // Log and show message
  log.error(`Error [${errorCode || "unknown"}]: ${errorMessage}`, error);
  if (showMessage) {
    message.error(errorMessage);
  }

  if (onError) {
    onError(error);
  }
};

/**
 * Wrap an async function with automatic error handling.
 */
export const withErrorHandler = (
  fn: () => Promise<any>,
  options: ShowErrorOptions = {}
) => {
  return async (...args: any[]) => {
    try {
      return await fn(...args);
    } catch (error) {
      showErrorToUser(error, undefined, options);
      throw error;
    }
  };
};
```

---

## 6. i18n 多语言支持

### 翻译文件位置

- `frontend/public/locales/en/common.json`
- `frontend/public/locales/zh/common.json`

### 翻译 key 格式

```json
{
  "errorCode.101001": "An unknown error occurred. Please try again later.",
  "errorCode.101002": "Service is temporarily unavailable. Please try again later.",
  "errorCode.102001": "You are not authorized to perform this action.",
  "errorCode.102002": "Your session has expired. Please login again.",
  "errorCode.105001": "Agent not found.",
  "errorCode.105002": "Failed to run agent. Please try again later.",
  "errorCode.120001": "Validation failed."
}
```

中文翻译示例：

```json
{
  "errorCode.101001": "发生未知错误，请稍后重试",
  "errorCode.101002": "服务暂时不可用，请稍后重试",
  "errorCode.102001": "您没有执行此操作的权限",
  "errorCode.102002": "您的登录已过期，请重新登录",
  "errorCode.105001": "智能体不存在",
  "errorCode.105002": "运行智能体失败，请稍后重试",
  "errorCode.120001": "验证失败"
}
```

---

## 7. 整体数据流

```
+-----------------------------------------------------------------+
|                         Backend                                 |
|  +--------------+  +--------------+  +----------------------+  |
|  | error_code   |  | error_message|  |     exceptions       |  |
|  |    .py       |  |     .py      |  |        .py           |  |
|  | ErrorCode    |  | ErrorMessage |  |   AppException       |  |
|  | (Enum)       |  | (Mapping)    |  |   (with aliases)     |  |
|  +--------------+  +--------------+  +----------------------+  |
|         |                 |                    |                |
|         +-----------------+--------------------+                |
|                           v                                     |
|              exception_handler.py                               |
|              (Middleware: converts to JSON response)            |
+-----------------------------------------------------------------+
                            |
                         HTTP Response
                            |
                            v
+-----------------------------------------------------------------+
|                         Frontend                                 |
|  +------------------------------------------------------+       |
|  |  api.ts                                              |       |
|  |  fetchWithErrorHandling -> ApiError                  |       |
|  +------------------------------------------------------+       |
|                           |                                      |
|         +-----------------+-----------------+                    |
|         v                 v                 v                    |
|  +------------+   +--------------+   +-------------+             |
|  | errorCode  |   | errorMessage |   | errorMessage|             |
|  |    .ts     |   |    .ts       |   | I18n.ts     |             |
|  +------------+   +--------------+   +-------------+             |
|       |                |                  |                      |
|       +----------------+------------------+                      |
|                        v                                         |
|              useErrorHandler.ts                                  |
|              (Hook: getI18nErrorMessage, handleError)           |
|                        |                                         |
|                        v                                         |
|         +-----------------------------+                          |
|         | public/locales/{lang}/     |                          |
|         | common.json                |                          |
|         | (i18n translations)        |                          |
|         +-----------------------------+                          |
+-----------------------------------------------------------------+
```

---

## 8. 方案总结

### 文件清单

| 层面 | 后端文件 | 前端文件 |
|------|----------|----------|
| **定义层** | `backend/consts/error_code.py` | `frontend/const/errorCode.ts` |
| **消息层** | `backend/consts/error_message.py` | `frontend/const/errorMessage.ts` |
| **异常层** | `backend/consts/exceptions.py` | - |
| **处理层** | `backend/middleware/exception_handler.py` | `frontend/hooks/useErrorHandler.ts` |
| **API层** | - | `frontend/services/api.ts` |
| **i18n层** | - | `frontend/const/errorMessageI18n.ts` |
| **翻译层** | - | `frontend/public/locales/{lang}/common.json` |

### 方案优点

1. **前后端统一** - 错误码在前后端完全一致，便于问题追踪
2. **i18n 支持** - 支持多语言错误消息
3. **统一响应格式** - 所有 API 响应采用相同结构
4. **可扩展性** - 支持 details 字段传递额外错误信息
5. **可追踪性** - 支持 trace_id 便于问题定位
6. **类型安全** - TypeScript 枚举与 Python Enum 一一对应

### 注意事项

- 项目采用 **混合模式**：HTTP 状态码 + 业务错误码
- 建议新增错误码时按照 XYYZZZ 格式依次递增，保持模块内连续性
- 所有新增错误码需要在 `common.json` 中添加对应的 i18n 翻译
