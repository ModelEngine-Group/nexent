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