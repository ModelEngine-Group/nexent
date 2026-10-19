"""Public observations and explicit Agent results, independent of engine memory."""

from typing import Literal, Self

from pydantic import Field, model_validator

from nexent.core.model_service.contracts import ModelError, TokenUsage
from nexent.core.model_service.profiles.contracts import NonBlankString, ProfileContract


class ContextCapacityObservation(ProfileContract):
    """Display metadata from the resolved Nexent ContextManager, independent of compaction mode."""

    context_window_tokens: int | None = Field(default=None, gt=0)
    token_threshold: int | None = Field(default=None, gt=0)
    effective_input_limit_tokens: int | None = Field(default=None, gt=0)
    context_processing_mode: Literal["passthrough", "adaptive_compact"] | None = None


class StepObservation(ProfileContract):
    turn_id: NonBlankString
    block_id: NonBlankString
    step_number: int = Field(ge=1)
    duration: float = Field(ge=0)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    finish_reason: str | None = None
    step_error: ModelError | None = None
    context_capacity: ContextCapacityObservation | None = None


class RunResult(ProfileContract):
    turn_id: NonBlankString
    status: Literal["completed", "failed", "stopped"]
    end_reason: NonBlankString
    final_content: str = ""
    final_block_ids: list[str] = Field(default_factory=list)
    error: ModelError | None = None

    @model_validator(mode="after")
    def validate_terminal(self) -> Self:
        if self.status != "completed" and (self.final_content or self.final_block_ids):
            raise ValueError("Unsuccessful runs cannot confirm final content")
        if self.status == "completed" and self.error is not None:
            raise ValueError("Completed runs cannot carry a run error")
        if len(self.final_block_ids) != len(set(self.final_block_ids)):
            raise ValueError("Final block identities must be unique")
        return self
