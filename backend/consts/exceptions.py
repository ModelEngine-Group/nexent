"""
Custom exception classes for the application.
"""


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


class NoInviteCodeException(Exception):
    """Raised when invite code is not found."""
    pass


class IncorrectInviteCodeException(Exception):
    """Raised when invite code is incorrect."""
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
    """Raised when not found exception occurs."""
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
