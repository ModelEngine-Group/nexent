"""Configuration for context management and compression."""

import logging
from dataclasses import InitVar, dataclass, field
from typing import Any, Callable, Dict, Mapping

from .policy import PolicyLayers


@dataclass
class ContextManagerConfig:
    """Configuration for context-history compression."""
    token_threshold: int = 10000
    # Stable, model-level combined input/output context capacity. Unlike the
    # compression threshold and request budgets, this value is intended for
    # user-facing context-window usage displays.
    context_window_tokens: int = 10000
    effective_input_limit_tokens: int = 0
    compaction_trigger_threshold_tokens: int = 0
    compaction_target_tokens: int = 0
    compaction_trigger_ratio: float = 0.8
    compaction_target_ratio: float = 0.6
    minimum_history_reduction_ratio: float = 0.05
    minimum_history_reduction_tokens: int = 32
    # Compatibility-only constructor inputs. They are normalized immediately
    # and are intentionally not retained as runtime attributes.
    soft_input_budget_tokens: InitVar[int | None] = None
    hard_input_budget_tokens: InitVar[int | None] = None
    keep_recent_steps: int = 4
    enable_long_term_memory_selection: bool = True

    summary_system_prompt: str = (
        "You are a conversation summarization assistant. Compress the following "
        "conversation history into a structured Markdown summary, preserving all "
        "key information: user's core requirements, completed work, important "
        "findings and decisions, unresolved issues, pending items, next steps, "
        "and context to preserve. "
        "Output the summary as Markdown with a top-level heading "
        "'# Compact Result of History' and one '## Section' heading per field. "
        "Do not wrap the output in code fences."
    )

    incremental_summary_system_prompt: str = (
        "You are a conversation summarization assistant updating an existing "
        "structured summary. The input has two sections: '## Previous Summary' "
        "(the prior compaction) and '## New Conversations' or '## New Steps' "
        "(turns that occurred after the prior compaction). Produce an updated "
        "Markdown summary that PRESERVES information from the previous summary "
        "(do not drop it unless clearly obsolete), MERGES the new turns into "
        "the appropriate sections, and KEEPS the same section headings. "
        "Do not wrap the output in code fences."
    )

    summary_json_schema: Dict[str, Any] = field(default_factory=lambda: {
        "task_overview": "User's core request and success criteria (<=150 words)",
        "completed_work": "Work completed, files or results produced (<=200 words)",
        "key_decisions": "Important findings, decisions made and reasons (<=200 words)",
        "unresolved_issues": "Problems, errors, or questions encountered but not yet resolved (<=150 words)",
        "pending_items": "Specific steps pending, blockers (<=150 words)",
        "next_steps": "Concrete planned next actions and their expected outcomes (<=150 words)",
        "context_to_preserve": "User preferences, domain details, commitments (<=150 words)",
    })

    max_summary_input_tokens: int = 0
    max_summary_reduce_tokens: int = 0
    estimated_chunk_summary_tokens: int = 400
    chars_per_token: float = 1.5

    # Processing policy only decides whether adaptive compaction is enabled.
    policy_layers: PolicyLayers | Mapping[str, Any] = field(default_factory=PolicyLayers)
    # Narrow callback injected by Backend; SDK never imports database services.
    history_summary_sink: Callable[[Any], Any] | None = None
    # Runtime-only notification used by the Agent stream. Candidate content is
    # never sent through this callback.
    history_summary_status_sink: Callable[[dict[str, Any]], Any] | None = None

    def __post_init__(
        self,
        soft_input_budget_tokens: int | None,
        hard_input_budget_tokens: int | None,
    ) -> None:
        if soft_input_budget_tokens:
            logging.getLogger("agent_context").warning(
                "legacy context threshold normalized to Compaction Trigger Threshold"
            )
            if not self.compaction_trigger_threshold_tokens:
                self.compaction_trigger_threshold_tokens = soft_input_budget_tokens
            if not self.effective_input_limit_tokens:
                self.effective_input_limit_tokens = max(
                    soft_input_budget_tokens,
                    int(soft_input_budget_tokens / self.compaction_trigger_ratio),
                )
        if hard_input_budget_tokens:
            logging.getLogger("agent_context").warning(
                "legacy context rejection limit is deprecated and ignored"
            )
        if self.effective_input_limit_tokens > 0:
            if not self.compaction_trigger_threshold_tokens:
                self.compaction_trigger_threshold_tokens = max(
                    1, int(self.effective_input_limit_tokens * self.compaction_trigger_ratio)
                )
            if not self.compaction_target_tokens:
                self.compaction_target_tokens = max(
                    1, int(self.effective_input_limit_tokens * self.compaction_target_ratio)
                )
