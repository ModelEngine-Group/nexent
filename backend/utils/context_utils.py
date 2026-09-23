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

# =============================================================================
# SECTION 1: Long-text format functions (expanded from Jinja2 templates)
# Each function accepts language and is_manager params for variant-specific text
# =============================================================================


# SECTION 2: Fixed prompt-section text builders
# =============================================================================


def _composer(language: str, is_manager: bool, prompt_bundle):
    """Create a run-local composer from an explicitly supplied prompt snapshot."""
    from nexent.core.agents.prompt import AgentPromptComposer

    if prompt_bundle is None:
        raise ValueError("prompt_bundle is required")
    if prompt_bundle.role != ("manager" if is_manager else "managed") or prompt_bundle.language != language:
        raise ValueError("Agent prompt bundle role or language does not match this run")
    return AgentPromptComposer(prompt_bundle)


def _build_header_text(language: str = "zh", *, prompt_bundle) -> str:
    return _composer(language, True, prompt_bundle).render_system_section("header")


def _build_duty_text(
    duty: str, language: str = "zh", is_manager: bool = True,
    priority: int = 80, *, prompt_bundle,
) -> str:
    return _composer(language, is_manager, prompt_bundle).render_system_section("duty", duty=duty)


def _build_execution_flow_text(
    memory_list: Optional[List[Any]] = None, language: str = "zh",
    is_manager: bool = True, enable_planning: bool = False,
    verification_enabled: bool = False,
    priority: int = 60, *, prompt_bundle,
) -> str:
    composer = _composer(language, is_manager, prompt_bundle)
    text = composer.render_system_section("execution_flow")
    if memory_list:
        text += "\n" + composer.render_system_section("memory_guidance")
    if enable_planning:
        text += "\n" + composer.render_system_section("planning_guidance")
    if verification_enabled:
        text += "\n" + composer.render_system_section("self_verification_guidance")
    return text


def _build_constraint_text(
    constraint: str, language: str = "zh", priority: int = 30, *, prompt_bundle,
) -> str:
    return _composer(language, True, prompt_bundle).render_system_section("constraint", constraint=constraint)


def _build_code_norms_text(
    language: str = "zh", is_manager: bool = True, priority: int = 20, *, prompt_bundle,
) -> str:
    return _composer(language, is_manager, prompt_bundle).render_system_section("code_norms")


def _build_restricted_python_execution_policy_text(
    authorized_imports: List[str], language: str = "zh", *, prompt_bundle, is_manager: bool = True,
) -> str:
    imports = ", ".join(
        f"`{name}`" for name in sorted({
            name.strip() for name in authorized_imports
            if isinstance(name, str) and name.strip()
        })
    )
    return _composer(language, is_manager, prompt_bundle).render_system_section(
        "restricted_python_execution", authorized_imports=imports,
    )


def _build_footer_text(
    few_shots: str, language: str = "zh", priority: int = 10, *, prompt_bundle,
) -> str:
    return _composer(language, True, prompt_bundle).render_system_section("footer", few_shots=few_shots)


def _build_available_resources_header_text(
    is_manager: bool = True, language: str = "zh", priority: int = 55, *, prompt_bundle,
) -> str:
    return _composer(language, is_manager, prompt_bundle).render_system_section("available_resources_header")


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
    managed_agents: Optional[Dict[str, Any]] = None,
    external_a2a_agents: Optional[Dict[str, Any]] = None,
    memory_list: Optional[List[Any]] = None,
    memory_search_query: Optional[str] = None,
    memory_tool_policy: Optional[str] = None,
    automation_tool_policy: Optional[str] = None,
    long_term_memory_items: Optional[List[dict[str, Any]]] = None,
    knowledge_base_summary: Optional[str] = None,
    kb_ids: Optional[List[str]] = None,
    knowledge_scope_policy: Optional[str] = None,
    knowledge_scope_resources: Optional[str] = None,
    restricted_python_authorized_imports: Optional[List[str]] = None,
    include_tools: bool = True,
    include_skills: bool = True,
    include_memory: bool = True,
    include_knowledge_base: bool = True,
    include_managed_agents: bool = True,
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
