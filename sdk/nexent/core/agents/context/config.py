"""Configuration for context management and compression."""

from dataclasses import dataclass, field
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
    soft_input_budget_tokens: int = 0
    hard_input_budget_tokens: int = 0
    keep_recent_steps: int = 4

    summary_system_prompt: str = (
        "You are a conversation summarization assistant. Compress the following "
        "conversation history into a structured Markdown summary, preserving all "
        "key information: user's core requirements, completed work, important "
        "findings and decisions, pending items, and context to preserve. "
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
