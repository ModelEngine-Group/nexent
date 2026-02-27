"""
Custom exception classes for the application.

This module provides a unified exception framework using ErrorCode enum.
Use AppException directly with ErrorCode to create exceptions.

Usage:
    from consts.error_code import ErrorCode
    from consts.exceptions import AppException
    
    raise AppException(ErrorCode.AGENT_NOT_FOUND)
    raise AppException(ErrorCode.MCP_CONNECTION_FAILED, "Connection timeout", details={"host": "localhost"})
"""

from .error_code import ErrorCode, ERROR_CODE_HTTP_STATUS
from .error_message import ErrorMessage


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


# Backward compatible aliases - these are just AppException with different names
# Usage: AppException(ErrorCode.NOT_FOUND) or NotFoundException(ErrorCode.NOT_FOUND)
# ==================== Common Aliases ====================
NotFoundException = AppException
UnauthorizedError = AppException
ValidationError = AppException
ParameterInvalidError = AppException
ForbiddenError = AppException
ServiceUnavailableError = AppException
DatabaseError = AppException
TimeoutError = AppException
UnknownError = AppException

# ==================== Domain Specific Aliases ====================
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

ConversationNotFoundError = AppException

MemoryNotFoundError = AppException
MemoryPreparationException = AppException

KnowledgeNotFoundError = AppException
KnowledgeSearchFailedError = AppException

ModelNotFoundError = AppException

# ==================== Voice Service Aliases ====================
VoiceServiceException = AppException
STTConnectionException = AppException
TTSConnectionException = AppException
VoiceConfigException = AppException

FileNotFoundError = AppException
FileUploadFailedError = AppException
FileTooLargeError = AppException

DifyServiceException = AppException
MEConnectionException = AppException
DataMateConnectionError = AppException
ExternalAPIError = AppException

LimitExceededError = AppException

# ==================== User Management Aliases ====================
NoInviteCodeException = AppException
IncorrectInviteCodeException = AppException
UserRegistrationException = AppException

# ==================== Invitation Aliases ====================
DuplicateError = AppException

# ==================== Signature Aliases ====================
SignatureValidationError = AppException


def raise_error(error_code: ErrorCode, message: str = None, details: dict = None):
    """Raise an AppException with the given error code."""
    raise AppException(error_code, message, details)
