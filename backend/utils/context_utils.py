"""Build authorized, serializable context item inputs for an agent run."""

from typing import Any, Dict, List, Optional

from nexent.core.agents.context import ContextItemInput
from nexent.core.agents.context_input import ContextInput

from consts.const import MESSAGE_ROLE


def build_authorized_context_input(
    agent_run_info,
    historical_context=None,
) -> ContextInput:
    """Freeze configured context and authorized history into one item snapshot."""
    if historical_context is None:
        fallback_turns = []
        pending_user = None
        for index, entry in enumerate(agent_run_info.history or ()):
            if entry.role == MESSAGE_ROLE["USER"]:
                pending_user = (index, entry)
            elif (
                entry.role == MESSAGE_ROLE["ASSISTANT"]
                and pending_user is not None
            ):
                user_index, user_entry = pending_user
                fallback_turns.append({
                    "user_message": user_entry.content,
                    "assistant_final_answer": entry.content,
                    "attachments": [],
                    "user_message_id": -(user_index + 1),
                    "assistant_message_id": -(index + 1),
                })
                pending_user = None
        historical_context = {"conversation_turns": fallback_turns}

    history_items = []
    summary = historical_context.get("history_summary")
    if summary:
        history_items.append(ContextItemInput(
            id=f"history_summary:{summary['unit_id']}",
            type="history_summary",
            content=summary,
            source=("conversation_history",),
        ))
    for order, turn in enumerate(
        historical_context.get("conversation_turns", ())
    ):
        history_items.append(ContextItemInput(
            id=(
                f"conversation_turn:{turn['user_message_id']}:"
                f"{turn['assistant_message_id']}"
            ),
            type="conversation_turn",
            content=turn,
            source=("conversation_history",),
            metadata={"layout_order": order},
        ))
    return ContextInput(
        items=(
            tuple(agent_run_info.agent_config.context_items or ())
            + tuple(history_items)
        ),
    )


def _composer(language: str, is_manager: bool, prompt_bundle):
    """Create a run-local composer from an explicitly supplied prompt snapshot."""
    from nexent.core.agents.prompt import AgentPromptComposer

    if prompt_bundle is None:
        raise ValueError("prompt_bundle is required")
    if prompt_bundle.role != ("manager" if is_manager else "managed") or prompt_bundle.language != language:
        raise ValueError("Agent prompt bundle role or language does not match this run")
    return AgentPromptComposer(prompt_bundle)


def build_context_inputs(
    duty: Optional[str] = None,
    constraint: Optional[str] = None,
    few_shots: Optional[str] = None,
    language: str = "zh",
    is_manager: bool = True,
    enable_planning: bool = False,
    verification_enabled: bool = False,
    tools: Optional[Dict[str, Any]] = None,
    skills: Optional[List[Dict[str, str]]] = None,
    worker_agents: Optional[Dict[str, Any]] = None,
    external_a2a_agents: Optional[Dict[str, Any]] = None,
    memory_list: Optional[List[Any]] = None,
    memory_search_query: Optional[str] = None,
    enable_memory_tool_policy: bool = False,
    enable_automation_tool_policy: bool = False,
    long_term_memory_items: Optional[List[dict[str, Any]]] = None,
    knowledge_base_summaries: Optional[List[dict[str, Any]]] = None,
    knowledge_base_no_indexes: bool = False,
    knowledge_scope: Optional[Dict[str, Any]] = None,
    restricted_python_authorized_imports: Optional[List[str]] = None,
    include_tools: bool = True,
    include_skills: bool = True,
    include_memory: bool = True,
    include_knowledge_base: bool = True,
    include_worker_agents: bool = True,
    include_external_agents: bool = True,
    include_app_context: bool = True,
    sandbox_workspace_enabled: bool = False,
    *,
    prompt_bundle,
) -> List[ContextItemInput]:
    """Adapt legacy Backend callers to the SDK-owned prompt composer."""
    composer = _composer(language, is_manager, prompt_bundle)
    arguments = locals().copy()
    arguments.pop("composer")
    arguments.pop("prompt_bundle")
    return composer.compose_context_inputs(**arguments)
