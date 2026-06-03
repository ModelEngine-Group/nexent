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
    enable_reload: bool = False
    max_offload_entries: int = 200
    max_offload_entry_chars: int = 30000
    """单条 offload 原始内容的最大字符数。超过此限制的内容即使 enable_reload=True
    也不会完整存档，只保留前 N 字符。防止超大 observation（如百万行日志）爆内存。
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

    # Pre-truncate single observations (model/tool outputs) longer than this
    # character limit at execute_action time, before they reach memory.
    # 0 = disabled (production default). Only takes effect when ``enabled``
    # is True, so production callers that do not opt in see no behaviour
    # change.
    max_observation_length: int = 0

    per_step_render_limit: int = 0
    """Per-segment character threshold for offload.
    When a rendered message segment exceeds this length and offload_store
    is available, the full text is stored and replaced with an [[OFFLOAD]]
    marker. 0 = disabled (no offload). Suggested value: 15000~30000.
    """

    _offload_prompt_suffix: str = field(
        default=(
            "\n\n"
            "When you see [[OBS_OFFLOAD: ...]] or [[CONTENT_OFFLOAD: ...]] markers in the "
            "conversation, these indicate that the full content for that segment has been "
            "archived externally and can be retrieved by the agent using the provided handle. "
            "Handle them as follows:\n"
            "- DO NOT copy the markers verbatim into your summary fields.\n"
            "- Record each offloaded segment in the 'offloaded_content' list with its handle, "
            "  a brief description (tool name, file name, size from the marker), and step number.\n"
            "- In other fields (e.g., 'completed_work'), reference offloaded content concisely, "
            "  e.g., 'Read config.json (full content archived, see offloaded_content).'\n"
            "- If a marker's visible prefix is insufficient to determine what happened, note it "
            "  as '[Step N: content archived]' rather than guessing.\n"
            "- If no offload markers appear in the conversation, set 'offloaded_content' to an empty list []."
        ),
        repr=False,
    )
    """Prompt suffix for handling offload markers in full-compression summaries.
    Only appended to ``summary_system_prompt`` when ``per_step_render_limit > 0``.
    """

    _offload_incremental_prompt_suffix: str = field(
        default=(
            "\n\n"
            "When you see [[OBS_OFFLOAD: ...]] or [[CONTENT_OFFLOAD: ...]] markers in the "
            "conversation, these indicate that the full content for that segment has been "
            "archived externally and can be retrieved by the agent using the provided handle. "
            "Handle them as follows:\n"
            "- DO NOT copy the markers verbatim into your summary fields.\n"
            "- Record each offloaded segment in the 'offloaded_content' list with its handle, "
            "  a brief description (tool name, file name, size from the marker), and step number.\n"
            "- In other fields, reference offloaded content concisely.\n"
            "- If the previous summary already contains an 'offloaded_content' list, MERGE new "
            "  entries into it rather than replacing it.\n"
            "- If no offload markers appear, set 'offloaded_content' to an empty list []."
        ),
        repr=False,
    )
    """Prompt suffix for handling offload markers in incremental-compression summaries.
    Only appended to ``incremental_summary_system_prompt`` when ``per_step_render_limit > 0``.
    """

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

    # === Effective prompt / schema helpers ===

    def effective_summary_system_prompt(self) -> str:
        """Return the summary system prompt, with offload guidance if enabled."""
        prompt = self.summary_system_prompt
        if self.per_step_render_limit > 0:
            prompt += self._offload_prompt_suffix
        return prompt

    def effective_incremental_summary_system_prompt(self) -> str:
        """Return the incremental summary system prompt, with offload guidance if enabled."""
        prompt = self.incremental_summary_system_prompt
        if self.per_step_render_limit > 0:
            prompt += self._offload_incremental_prompt_suffix
        return prompt

    def effective_summary_json_schema(self) -> Dict[str, Any]:
        """Return the summary JSON schema, with ``offloaded_content`` field if offload is enabled."""
        schema = dict(self.summary_json_schema)
        if self.per_step_render_limit > 0:
            schema["offloaded_content"] = [
                {
                    "handle": "str: UUID handle for reloading the full archived content",
                    "description": "str: what was offloaded (tool name, file name, segment type, size)",
                    "step": "int: step number where the offload occurred",
                }
            ]
        return schema