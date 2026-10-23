class AgentAutomationError(Exception):
    """Base domain exception for agent automation."""

    error_code = "AUTOMATION_ERROR"

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AutomationCapabilityNotReadyError(AgentAutomationError):
    error_code = "AUTOMATION_CAPABILITY_NOT_READY"


class AutomationCapabilityUnavailableError(AgentAutomationError):
    error_code = "AUTOMATION_CAPABILITY_UNAVAILABLE"


class AutomationCapabilityBindingInvalidError(AgentAutomationError):
    error_code = "AUTOMATION_CAPABILITY_BINDING_INVALID"


class AutomationScheduleInvalidError(AgentAutomationError):
    error_code = "AUTOMATION_SCHEDULE_INVALID"


class AutomationNotFoundError(AgentAutomationError):
    error_code = "AUTOMATION_TASK_NOT_FOUND"


class AutomationConversationAlreadyBoundError(AgentAutomationError):
    error_code = "AUTOMATION_CONVERSATION_ALREADY_BOUND"
