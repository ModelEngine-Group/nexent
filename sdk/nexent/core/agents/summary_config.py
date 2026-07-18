"""Configuration for agent context management and compression."""

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class ContextManagerConfig:
    """Configuration for context-history compression."""
    # === Compression Settings (existing) ===
    enabled: bool = False
    token_threshold: int = 10000
    soft_input_budget_tokens: int = 0
    hard_input_budget_tokens: int = 0
    keep_recent_steps: int = 4
    keep_recent_pairs: int = 2
    max_chunk_count: int = 0
    max_memory_step_length: int = 2000

    summary_system_prompt: str = (
        "You are a conversation summarization assistant. Compress the following "
        "conversation history into a structured summary, preserving all key information: "
        "user's core requirements, completed work, important findings and decisions, "
        "pending items, and context to preserve. Output strict JSON format without markdown blocks."
    )

    # Separate prompt for INCREMENTAL summary updates ("here is the previous
    # summary + new turns; produce an updated summary"). When empty the
    # incremental compression path falls back to summary_system_prompt for
    # backwards compatibility.
    incremental_summary_system_prompt: str = (
        "You are a conversation summarization assistant updating an existing "
        "structured summary. The input has two sections: '## Previous Summary' "
        "(the prior compaction) and '## New Conversations' or '## New Steps' "
        "(turns that occurred after the prior compaction). Produce an updated "
        "JSON summary that PRESERVES information from the previous summary "
        "(do not drop it unless clearly obsolete), MERGES the new turns into "
        "the appropriate fields, and KEEPS the same JSON schema. Do not include "
        "narration outside the JSON. No markdown code blocks."
    )

    summary_json_schema: Dict[str, Any] = field(default_factory=lambda: {
        "task_overview": "User's core request and success criteria (<=150 words)",
        "completed_work": "Work completed, files or results produced (<=200 words)",
        "key_decisions": "Important findings, decisions made and reasons (<=200 words)",
        "pending_items": "Specific steps pending, blockers (<=150 words)",
        "context_to_preserve": "User preferences, domain details, commitments (<=150 words)",
    })

    max_summary_input_tokens: int = 0
    max_summary_reduce_tokens: int = 0
    estimated_chunk_summary_tokens: int = 400
    chars_per_token: float = 1.5

    # Pre-truncate single observations (model/tool outputs) longer than this
    # character limit at execute_action time, before they reach memory.
    # 0 = disabled (production default). Only takes effect when ``enabled``
    # is True, so production callers that do not opt in see no behaviour
    # change.
    max_observation_length: int = 0
