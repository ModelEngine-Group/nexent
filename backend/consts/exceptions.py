"""
Custom exception classes for the application.

This module provides two types of exceptions:

1. New Framework (with ErrorCode):
   from consts.error_code import ErrorCode
   from consts.exceptions import AppException
   
   raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Validation failed")
   raise AppException(ErrorCode.MCP_CONNECTION_FAILED, "Connection timeout", details={"host": "localhost"})

2. Legacy Framework (simple exceptions):
   from consts.exceptions import ValidationError, NotFoundException, MCPConnectionError
   
   raise ValidationError("Tenant name cannot be empty")
   raise NotFoundException("Tenant 123 not found")
   raise MCPConnectionError("MCP connection failed")

The exception handler automatically maps legacy exception class names to ErrorCode.
"""

from .error_code import ErrorCode, ERROR_CODE_HTTP_STATUS
from .error_message import ErrorMessage


# ==================== New Framework: AppException with ErrorCode ====================

class AppException(Exception):
    """
    Base application exception with ErrorCode.

    Usage:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Validation failed")
        raise AppException(ErrorCode.MCP_CONNECTION_FAILED, "Timeout", details={"host": "x"})
    """

    def __init__(self, error_code: ErrorCode, message: str = None, details: dict = None):
        self.error_code = error_code
        self.message = message or ErrorMessage.get_message(error_code)
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {
            "code": str(self.error_code.value),  # Keep as string to preserve leading zeros
            "message": self.message,
            "details": self.details if self.details else None
        }

    @property
    def http_status(self) -> int:
        return ERROR_CODE_HTTP_STATUS.get(self.error_code, 500)


def raise_error(error_code: ErrorCode, message: str = None, details: dict = None):
    """Raise an AppException with the given error code."""
    raise AppException(error_code, message, details)


# ==================== Legacy Framework: Simple Exception Classes ====================
# These are simple exceptions that work with the old calling pattern.
# The exception handler automatically maps class names to ErrorCode.
#
# Usage (unchanged from before):
#     raise ValidationError("Invalid input")
#     raise NotFoundException("Resource not found")
#     raise MCPConnectionError("Connection failed")
#
# These do NOT require ErrorCode - they are simple Exception subclasses.
# Exception handler will infer ErrorCode from class name.

class AgentRunException(Exception):
    """Exception raised when agent run fails."""
    pass


class LimitExceededError(Exception):
    """Raised when an outer platform calling too frequently"""
    pass


class UnauthorizedError(Exception):
    """Raised when a user from outer platform is unauthorized."""
    pass


class SignatureValidationError(Exception):
    """Raised when X-Signature header is missing or does not match the expected HMAC value."""
    pass


class MemoryPreparationException(Exception):
    """Raised when memory preprocessing or retrieval fails prior to agent run."""
    pass


class MCPConnectionError(Exception):
    """Raised when MCP connection fails."""
    pass


class MCPNameIllegal(Exception):
    """Raised when MCP name is illegal."""
    pass


class McpNotFoundError(Exception):
    """Raised when MCP resource is not found."""
    pass


class McpValidationError(Exception):
    """Raised when MCP payload or runtime data is invalid."""
    pass


class McpNameConflictError(Exception):
    """Raised when MCP name conflicts with an existing enabled service."""
    pass


class NoInviteCodeException(Exception):
    """Raised when invite code is not found."""
    pass


class IncorrectInviteCodeException(Exception):
    """Raised when invite code is incorrect."""
    pass


class OfficeConversionException(Exception):
    """Raised when Office-to-PDF conversion via data-process service fails."""
    pass


class UnsupportedFileTypeException(Exception):
    """Raised when a file type is not supported for the requested operation."""
    pass


class FileTooLargeException(Exception):
    """Raised when a file exceeds the maximum allowed size for the requested operation."""
    pass


class UserRegistrationException(Exception):
    """Raised when user registration fails."""
    pass


class TimeoutException(Exception):
    """Raised when timeout occurs."""
    pass


class ValidationError(Exception):
    """Raised when validation fails."""
    pass


class NotFoundException(Exception):
    """Raised when not found exception occurs."""
    pass


class MEConnectionException(Exception):
    """Raised when ME connection fails."""
    pass


class VoiceServiceException(Exception):
    """Raised when voice service fails."""
    pass


class STTConnectionException(Exception):
    """Raised when STT service connection fails."""
    pass


class TTSConnectionException(Exception):
    """Raised when TTS service connection fails."""
    pass


class VoiceConfigException(Exception):
    """Raised when voice configuration is invalid."""
    pass


class ToolExecutionException(Exception):
    """Raised when mcp tool execution failed."""
    pass


class MCPContainerError(Exception):
    """Raised when MCP container operation fails."""
    pass


class DuplicateError(Exception):
    """Raised when a duplicate resource already exists."""
    pass


class DataMateConnectionError(Exception):
    """Raised when DataMate connection fails or URL is not configured."""
    pass


class SkillException(Exception):
    """Raised when skill operations fail."""
    pass


# ==================== Legacy Aliases (same as above, for compatibility) ====================
# These are additional aliases that map to the same simple exception classes above.
# They provide backward compatibility for code that uses these names.

# Common aliases
ParameterInvalidError = ValidationError
ForbiddenError = Exception  # Generic fallback
ServiceUnavailableError = Exception  # Generic fallback
DatabaseError = Exception  # Generic fallback
TimeoutError = TimeoutException
UnknownError = Exception  # Generic fallback

# Domain specific aliases
UserNotFoundError = NotFoundException
UserAlreadyExistsError = DuplicateError
InvalidCredentialsError = UnauthorizedError

TenantNotFoundError = NotFoundException
TenantDisabledError = Exception  # Generic fallback

AgentNotFoundError = NotFoundException
AgentDisabledError = Exception  # Generic fallback

ToolNotFoundError = NotFoundException

ConversationNotFoundError = NotFoundException

MemoryNotFoundError = NotFoundException
KnowledgeNotFoundError = NotFoundException

ModelNotFoundError = NotFoundException

# File aliases
FileNotFoundError = NotFoundException
FileUploadFailedError = Exception  # Generic fallback
FileTooLargeError = Exception  # Generic fallback

# External service aliases
DifyServiceException = Exception  # Generic fallback
ExternalAPIError = Exception  # Generic fallback

# Signature aliases
# SignatureValidationError already defined above
