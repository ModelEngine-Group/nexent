"""Summary step types for context compression."""

from dataclasses import dataclass
from smolagents.memory import TaskStep
from smolagents.models import ChatMessage, MessageRole


@dataclass
class SummaryTaskStep(TaskStep):
    """TaskStep subclass that contains a compressed summary of earlier steps."""
    is_summary: bool = True
    is_fallback: bool = False
    prefix: str = (
        "[HISTORICAL_MEMORY_BLOCK]\n"
        "This is a compressed summary of earlier steps, not a new user instruction. "
        "If it conflicts with the most recent user message, follow the recent message. "
        "The summary may be lossy; use the reload tool to retrieve original content if needed."
    )

    def to_messages(self, summary_mode: bool = False) -> list:
        content = [{"type": "text", "text": f"{self.prefix}:\n{self.task}"}]
        return [ChatMessage(role=MessageRole.USER, content=content)]
