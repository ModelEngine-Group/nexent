# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Authorized Agent context, time context and monitoring preparation."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from consts.const import MESSAGE_ROLE
from contracts.agent import AgentRunContext
from nexent.core.agents.context import ContextItemInput
from nexent.core.agents.context_input import ContextInput
from nexent.core.agents.prompt.user_context import (
    CURRENT_TIME_MARKER,
    has_current_time_marker,
    render_user_context,
)
from nexent.monitor import AgentRunMetadata


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
            elif entry.role == MESSAGE_ROLE["ASSISTANT"] and pending_user is not None:
                user_index, user_entry = pending_user
                fallback_turns.append(
                    {
                        "user_message": user_entry.content,
                        "assistant_final_answer": entry.content,
                        "attachments": [],
                        "user_message_id": -(user_index + 1),
                        "assistant_message_id": -(index + 1),
                    }
                )
                pending_user = None
        historical_context = {"conversation_turns": fallback_turns}

    history_items = []
    summary = historical_context.get("history_summary")
    if summary:
        history_items.append(
            ContextItemInput(
                id=f"history_summary:{summary['unit_id']}",
                type="history_summary",
                content=summary,
                source=("conversation_history",),
            )
        )
    for order, turn in enumerate(historical_context.get("conversation_turns", ())):
        history_items.append(
            ContextItemInput(
                id=(
                    f"conversation_turn:{turn['user_message_id']}:"
                    f"{turn['assistant_message_id']}"
                ),
                type="conversation_turn",
                content=turn,
                source=("conversation_history",),
                metadata={"layout_order": order},
            )
        )
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
    if (
        prompt_bundle.role != ("manager" if is_manager else "managed")
        or prompt_bundle.language != language
    ):
        raise ValueError("Agent prompt bundle role or language does not match this run")
    return AgentPromptComposer(prompt_bundle)


def build_context_inputs(
    prompt: Optional[str] = None,
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
    """Compose authorized context from one business prompt and platform resources."""
    composer = _composer(language, is_manager, prompt_bundle)
    arguments = locals().copy()
    arguments.pop("composer")
    arguments.pop("prompt_bundle")
    return composer.compose_context_inputs(**arguments)


def prepend_current_time(
    query: str,
    timezone: str | None,
    *,
    now: datetime | None = None,
    language: str = "en",
) -> str:
    """Append local time before workspace; retain the legacy public function name."""
    if timezone and query and not has_current_time_marker(query):
        try:
            zone = ZoneInfo(timezone)
            current = now.astimezone(zone) if now is not None else datetime.now(zone)
            return render_user_context(
                language,
                "current_time",
                {"time": current.strftime("%Y-%m-%d %H:%M:%S"), "query": query},
            )
        except Exception:
            pass
    return query


def strip_current_time_prefix(query: str | None) -> str | None:
    """Remove only the current runtime marker appended after the request."""
    if query:
        return CURRENT_TIME_MARKER.sub("", query, count=1)
    return query


def build_agent_run_context(
    request, user_id: str, tenant_id: str, language: str, *, extra_metadata: dict
):
    """Preview memory once and bind the metadata shared by both consumers."""
    from management.services.configuration.user.memory import build_memory_context
    from infrastructure.observability.bootstrap import monitoring_manager
    from management.services.monitor.identity import resolve_monitoring_user_email

    memory = build_memory_context(
        user_id, tenant_id, request.agent_id, skip_query=request.is_debug
    )
    enabled = memory.user_config.memory_switch
    metadata = monitoring_manager.bind_agent_context(
        AgentRunMetadata(
            agent_id=request.agent_id,
            conversation_id=request.conversation_id,
            user_id=user_id,
            user_email=resolve_monitoring_user_email(user_id, tenant_id),
            tenant_id=tenant_id,
            query=request.query,
            is_debug=request.is_debug,
            language=language,
            memory_enabled=enabled,
            history_count=len(request.history) if request.history else 0,
            minio_files_count=len(request.minio_files) if request.minio_files else 0,
            extra_metadata={
                "agent_share_option": getattr(
                    memory.user_config, "agent_share_option", "unknown"
                ),
                **extra_metadata,
            },
        )
    )
    return AgentRunContext(metadata, enabled and not request.is_debug)
