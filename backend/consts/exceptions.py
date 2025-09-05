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