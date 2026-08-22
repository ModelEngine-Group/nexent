from .utils.observer import MessageObserver, ProcessType

__all__ = ["MessageObserver", "ProcessType"]

# Lazy imports to avoid circular dependencies
def get_core_agent():
    from .agents import CoreAgent
    return CoreAgent

def get_openai_model():
    from .models import OpenAIModel
    return OpenAIModel
