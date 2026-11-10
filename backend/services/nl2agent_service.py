# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Transitional assembly and execution of an ephemeral NL2Agent run."""

import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator
from typing import Any

from backend.http.client import create_httpx_client
from contracts.agent import NL2AgentRunRequest
from contracts.authentication import AuthenticatedIdentity
from contracts.constants.constants import MODEL_CONFIG_MAPPING
from contracts.constants.environment import MCP_REQUEST_TIMEOUT_SECONDS, TOKEN
from contracts.conversation import HistoryItem
from management.services.agent.context import build_authorized_context_input
from management.services.agent.creation import create_nl2agent_agent_config
from management.services.agent.nl2agent import (
    Nl2AgentDraftSaveError, _build_verified_bound_resources_context, _parse_nl2agent_card_action_agent_id,
    _requires_policy_clarification,
)
from management.services.agent.preparation.inputs import join_minio_file_description_to_query
from management.services.configuration.tenant.settings import tenant_config_manager
from management.services.mcp.addressing import get_tenant_local_mcp_server
from management.services.model.run_bindings import create_model_config_list
from management.services.model.run_budget import _resolve_context_budget, _resolve_input_budget
from management.services.model.run_controls import preflight_turn_controls, resolve_creator_model
from nexent.core.agents.agent_model import AgentHistory, AgentRunInfo
from nexent.core.agents.context import ContextManagerConfig
from nexent.core.utils.observer import MessageObserver, ProcessType
from runtime.adapters.nexent.runner import agent_run
from runtime.thread_management import runtime_thread_manager
from tool_collection.mcp.nl2agent_mcp_tools import NL2AGENT_AGENT_ID_HEADER, NL2AGENT_POLICY_CLARIFICATION_HEADER

logger = logging.getLogger(__name__)


class _Nl2AgentBoundaryObserver(MessageObserver):
    """Stop an NL2Agent run after its first valid interactive payload."""

    _STOP_FINAL_ANSWER = "<user_break>"
    _STOP_ERROR = "Agent execution interrupted by external stop signal"

    def __init__(self, *, lang: str, stop_event: threading.Event):
        super().__init__(lang=lang, enable_nl2a_wrapper=True)
        self._boundary_stop_event = stop_event
        self._boundary_reached = False
        self._boundary_lock = threading.Lock()

    @property
    def boundary_reached(self) -> bool:
        with self._boundary_lock:
            return self._boundary_reached

    def add_message(self, agent_name, process_type, content, **kwargs):
        if self.boundary_reached and (
            (process_type == ProcessType.FINAL_ANSWER and content == self._STOP_FINAL_ANSWER)
            or (process_type == ProcessType.WARNING and content == self._STOP_ERROR)
        ):
            return

        nl2a_content = None
        if process_type == ProcessType.EXECUTION_LOGS:
            nl2a_content, _ = self._extract_nl2a_wrapper(content)

        super().add_message(agent_name, process_type, content, **kwargs)

        if nl2a_content is not None:
            with self._boundary_lock:
                if self._boundary_reached:
                    return
                self._boundary_reached = True
            self._boundary_stop_event.set()


def _convert_history(history: list[HistoryItem] | None) -> list[AgentHistory]:
    if not history:
        return []
    return [
        AgentHistory(role=item.role, content=item.content)
        for item in history
        if item.role in {"user", "assistant"}
    ]


async def build_nl2agent_run_info(
    request: NL2AgentRunRequest,
    tenant_id: str,
    language: str,
    authorization: str | None = None,
    *,
    identity: AuthenticatedIdentity,
) -> AgentRunInfo:
    """Build all request-scoped NL2Agent runtime objects in memory."""

    action_agent_id = _parse_nl2agent_card_action_agent_id(request.query)
    if action_agent_id is not None and request.agent_id != action_agent_id:
        raise Nl2AgentDraftSaveError("agent_context_mismatch")
    if identity.tenant_id != tenant_id:
        raise PermissionError("tenant mismatch")
    user_id = identity.user_id
    if not user_id or not tenant_id:
        raise PermissionError("Authenticated user and tenant are required")
    preflight_turn_controls(request, tenant_id)
    binding_context = await _build_verified_bound_resources_context(
        agent_id=request.agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    final_query = await join_minio_file_description_to_query(
        minio_files=request.minio_files,
        query=request.query,
        history=request.history,
        language=language,
    )
    model_config_list = await create_model_config_list(tenant_id)
    agent_config = create_nl2agent_agent_config(language)
    agent_config.context_items = [
        *(agent_config.context_items or []),
        binding_context,
    ]
    default_model = tenant_config_manager.get_model_config(
        key=MODEL_CONFIG_MAPPING["llm"],
        tenant_id=tenant_id,
    )
    if request.model_id is not None or request.generation_config is not None:
        default_model = resolve_creator_model(
            model_config_list, agent_config, tenant_id, request.model_id,
            request.generation_config.model_dump(exclude_unset=True) if request.generation_config else None,
            default_model,
        )
    input_budget, capacity_snapshot, resolved_capacity_snapshot = (
        _resolve_input_budget(default_model)
    )
    context_budget_snapshot = _resolve_context_budget(
        capacity_snapshot=resolved_capacity_snapshot,
        tenant_id=tenant_id,
        agent_requested_output_tokens=None,
        request_requested_output_tokens=None,
    )
    if context_budget_snapshot is not None:
        effective_input_limit_tokens = context_budget_snapshot.effective_input_limit_tokens
        compaction_trigger_threshold_tokens = (
            context_budget_snapshot.compaction_trigger_threshold_tokens
        )
        compaction_target_tokens = context_budget_snapshot.compaction_target_tokens
        token_threshold = compaction_trigger_threshold_tokens
    else:
        effective_input_limit_tokens = 0
        compaction_trigger_threshold_tokens = 0
        compaction_target_tokens = 0
        token_threshold = input_budget

    context_window_tokens = (
        resolved_capacity_snapshot.context_window_tokens
        if resolved_capacity_snapshot is not None
        and resolved_capacity_snapshot.context_window_tokens is not None
        else input_budget
    )
    agent_config.context_manager_config = ContextManagerConfig(
        token_threshold=token_threshold,
        context_window_tokens=context_window_tokens,
        effective_input_limit_tokens=effective_input_limit_tokens,
        compaction_trigger_threshold_tokens=compaction_trigger_threshold_tokens,
        compaction_target_tokens=compaction_target_tokens,
    )
    agent_config.capacity_snapshot = capacity_snapshot
    agent_config.context_budget_snapshot = context_budget_snapshot
    mcp_config: dict[str, Any] = {
        "url": get_tenant_local_mcp_server(tenant_id),
        "transport": "sse",
        "httpx_client_factory": create_httpx_client,
        "bypass_proxy": True,
    }
    mcp_headers: dict[str, str] = {}
    if authorization:
        mcp_headers["Authorization"] = authorization
    mcp_headers[NL2AGENT_AGENT_ID_HEADER] = str(request.agent_id)
    mcp_headers[NL2AGENT_POLICY_CLARIFICATION_HEADER] = (
        "true" if _requires_policy_clarification(request.query) else "false"
    )
    mcp_headers["X-Tenant-ID"] = str(tenant_id)
    mcp_headers["X-Nexent-Internal-Token"] = TOKEN
    if mcp_headers:
        mcp_config["headers"] = mcp_headers

    stop_event = threading.Event()
    run_info = AgentRunInfo(
        query=final_query,
        model_config_list=model_config_list,
        observer=_Nl2AgentBoundaryObserver(
            lang=language,
            stop_event=stop_event,
        ),
        agent_config=agent_config,
        mcp_host=[mcp_config],
        mcp_request_timeout_seconds=MCP_REQUEST_TIMEOUT_SECONDS,
        history=_convert_history(request.history),
        stop_event=stop_event,
        capacity_snapshot=capacity_snapshot,
        context_budget_snapshot=context_budget_snapshot,
        enable_planning=False,
        sandbox_config=None,
        redis_client=None,
    )
    run_info.context_input = build_authorized_context_input(run_info)
    return run_info


async def create_nl2agent_stream(
    request: NL2AgentRunRequest,
    tenant_id: str,
    language: str,
    authorization: str | None = None,
    *,
    identity: AuthenticatedIdentity,
) -> AsyncIterator[str]:
    """Create an SSE-compatible stream for one ephemeral NL2Agent run."""

    run_info = await build_nl2agent_run_info(
        request=request,
        tenant_id=tenant_id,
        language=language,
        identity=identity,
        authorization=authorization,
    )

    async def generate() -> AsyncIterator[str]:
        boundary_delivered = False
        try:
            async for chunk in agent_run(
                run_info,
                thread_manager=runtime_thread_manager,
            ):
                if boundary_delivered:
                    continue
                yield f"data: {chunk}\n\n"
                try:
                    boundary_delivered = (
                        json.loads(chunk).get("type") == ProcessType.NL2A.value
                    )
                except (AttributeError, TypeError, json.JSONDecodeError):
                    boundary_delivered = False
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("NL2Agent execution failed")
            from management.services.agent.stream import sampling_configuration_error_payload
            sampling_error = sampling_configuration_error_payload(exc)
            error_payload = json.dumps(
                sampling_error or {
                    "type": "error",
                    "content": "NL2Agent execution failed.",
                },
                ensure_ascii=False,
            )
            yield f"data: {error_payload}\n\n"
        finally:
            run_info.stop_event.set()

    return generate()
