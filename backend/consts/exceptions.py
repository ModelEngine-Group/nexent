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
