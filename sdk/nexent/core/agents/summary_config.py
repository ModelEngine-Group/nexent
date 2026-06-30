"""Configuration for agent context management and compression."""

from dataclasses import dataclass, field
from typing import Any, Dict, Literal


StrategyType = Literal["full", "token_budget", "buffered", "priority"]


@dataclass
class ContextManagerConfig:
    """Configuration for ContextManager - handles ALL context building.

    Extends existing compression config with:
    - Strategy selection for component selection algorithms
    - Injection flags to enable/disable individual context components
    - Per-component token budgets for fine-grained control
    """
    # === Compression Settings (existing) ===
    enabled: bool = False
    token_threshold: int = 10000
    soft_input_budget_tokens: int = 0
    hard_input_budget_tokens: int = 0
    keep_recent_steps: int = 4
    keep_recent_pairs: int = 2
    max_chunk_count: int = 0
    max_memory_step_length: int = 2000

    # === Offload Settings ===
    # Archives oversized step-render segments to an in-memory OffloadStore
    # so the LLM still sees compact context.  Requires **both** enable_reload
    # AND per_step_render_limit > 0.  The agent retrieves archived content
    # via the ``reload_original_context_messages`` tool.

    enable_reload: bool = False
    """Create an :class:`OffloadStore` and inject the reload tool into the agent.

    Offload is only *triggered* when ``per_step_render_limit > 0``.
    """

    per_step_render_limit: int = 0
    """Character threshold triggering offload **during compression**.

    Only applies to old steps outside the ``keep_recent`` window — recent
    steps are never offloaded.  When a step's rendered text exceeds this
    limit, the full content is archived and replaced with an
    ``[[OFFLOAD:handle:desc]]`` marker.  Unlike ``max_observation_length``
    this is **reversible**: the agent can reload archived content on demand.

    Set to 0 to disable (the default).  Suggested: 3000–10000.
    """

    max_offload_entries: int = 200
    """Max entries in the :class:`OffloadStore`.  Oldest evicted (FIFO) when full."""

    max_offload_entry_chars: int = 30000
    """Max characters per offload entry.  Oversized content is rejected by the
    store.  Safety cap against a single giant observation dominating memory.
    """

    max_offload_total_chars: int = 2_000_000
    """Cumulative character budget across all entries.  Oldest evicted (FIFO)
    when exceeded.  Together with ``max_offload_entries`` bounds total memory.
    """

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

    # Pre-truncate observations at source (before memory), keeping head+tail
    # around a truncation marker.  This is per-step, irreversible sanitation —
    # not a compression mechanism.  For reversible archiving of large content,
    # use offload (``per_step_render_limit``) instead.
    # 0 = disabled (default).  Takes effect only when ``enabled`` is True.
    max_observation_length: int = 0

    # === NEW: Strategy Selection ===
    strategy: StrategyType = "token_budget"
    """Context component selection strategy.

    Options:
    - 'full': Keep all components (for unlimited context models)
    - 'token_budget': Select components within token budget by priority
    - 'buffered': Keep last N components per type
    - 'priority': Weight by importance + relevance scores
    """

    # === NEW: Component Injection Flags ===
    inject_system_prompt: bool = True
    """Whether to inject system prompt into context."""

    inject_tools: bool = True
    """Whether to inject tool descriptions into system prompt."""

    inject_skills: bool = True
    """Whether to inject skill summaries into system prompt."""

    inject_memory: bool = True
    """Whether to search and inject long-term memory (mem0) into system prompt."""

    inject_knowledge_base: bool = True
    """Whether to inject knowledge base summaries into system prompt."""

    inject_agent_definitions: bool = True
    """Whether to inject sub-agent (managed_agents + external_a2a_agents) definitions."""

    inject_app_context: bool = True
    """Whether to inject APP_NAME, APP_DESCRIPTION, time, user_id."""

    # === NEW: Per-Component Token Budgets ===
    component_budgets: Dict[str, int] = field(default_factory=lambda: {
        "system_prompt": 4000,
        "tools": 3000,
        "skills": 1000,
        "memory": 2000,
        "knowledge_base": 1500,
        "managed_agents": 500,
        "external_a2a_agents": 500,
        "conversation_history": 4000,  # Reserved for conversation compression
    })
    """Token budget for each context component type.

    Used by token_budget strategy to allocate tokens across components.
    Total of all budgets should not exceed token_threshold.
    """

    # === NEW: Buffered Strategy Settings ===
    buffer_size_per_component: int = 10
    """Number of items to keep per component type for 'buffered' strategy."""
