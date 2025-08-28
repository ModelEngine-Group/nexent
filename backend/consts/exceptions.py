"""
Custom exception classes for the application.
"""


class BusinessException(Exception):
    """Base class for all business exceptions."""
    pass


class ValidationException(Exception):
    """Exception raised for validation errors."""
    pass


class NotFoundException(Exception):
    """Exception raised when a resource is not found."""
    pass


class UnauthorizedException(Exception):
    """Exception raised for unauthorized access."""
    pass


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
