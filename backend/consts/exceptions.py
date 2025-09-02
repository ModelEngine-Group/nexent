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
