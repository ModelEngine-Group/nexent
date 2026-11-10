# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Materialize the request-owned NL2Agent and bind its signed tool callbacks."""

import logging
import threading
from typing import Annotated, Any

import httpx
from fastapi import HTTPException
from langchain_core.tools import StructuredTool
from pydantic import ConfigDict, Field, WithJsonSchema, create_model

from contracts.agentos import MAX_REQUEST_BYTES, ManagementOperation, NL2AgentToolCall, PreparedAgentCreatorRun
from contracts.constants.environment import MANAGEMENT_AGENTOS_URL
from infrastructure.agentos_identity import ServicePrincipal, sign_call
from runtime.agentos.agent_creator_config import create_nl2agent_agent_config
from infrastructure.nl2agent_tool_config import (
    NL2A_WRAPPER_NAME, RECOMMEND_RESOURCES_NAME, SAVE_AGENT_DRAFT_FIELDS_NAME,
    SEARCH_INSTALLED_RESOURCES_NAME, SEARCH_UNINSTALLED_RESOURCES_NAME, create_nl2agent_mcp_tool_configs,
)
from nexent.core.agents.agent_model import AgentHistory, AgentRunInfo
from nexent.core.agents.context import ContextItemInput, ContextItemType
from nexent.core.agents.context_input import build_authorized_context_input
from nexent.core.utils.observer import MessageObserver, ProcessType
from runtime.adapters.nexent.factory import build_run_info
from runtime.agentos.creator_context import apply_creator_budget
from runtime.agentos.prepared_attachments import materialize_evaluation_input
from runtime.agentos.prepared_evaluation import _materialize_model

_AGENT_ID = Annotated[int, Field(gt=0, strict=True)]
_OPTIONAL_STRINGS = Annotated[list[str] | None, WithJsonSchema({"type": "array", "items": {"type": "string"}, "nullable": True})]
_OPTIONAL_OBJECTS = Annotated[list[dict[str, Any]] | None, WithJsonSchema({
    "type": "array", "items": {"type": "object"}, "nullable": True,
})]
_OPTIONAL_OBJECT = Annotated[dict[str, Any] | None, WithJsonSchema({"type": "object", "nullable": True})]
_TOOL_INPUTS = {
    SEARCH_INSTALLED_RESOURCES_NAME: ("search_installed_resources", {"requirements": (list[dict[str, Any]], ...)}),
    SEARCH_UNINSTALLED_RESOURCES_NAME: ("search_uninstalled_resources", {
        "requirements": (list[dict[str, Any]], ...), "exclude_refs": (_OPTIONAL_STRINGS, None),
    }),
    RECOMMEND_RESOURCES_NAME: ("recommend_resources", {
        "candidates": (list[dict[str, Any]], ...), "recommended_refs": (list[str], ...),
    }),
    SAVE_AGENT_DRAFT_FIELDS_NAME: ("save_agent_draft_fields", {"fields": (dict[str, Any], ...)}),
    NL2A_WRAPPER_NAME: ("wrapper", {
        "subtype": (str, ...), "resource_result": (_OPTIONAL_OBJECT, None),
        "questions": (_OPTIONAL_OBJECTS, None),
    }),
}
logger = logging.getLogger(__name__)
_TIMEOUT = httpx.Timeout(180, connect=10)


def _invoke_tool(run_id, actor, tool, agent_id, **arguments):
    operation = ManagementOperation.NL2AGENT_TOOL
    call = NL2AgentToolCall(run_id=run_id, agent_id=agent_id, tool=tool, arguments=arguments)
    body = call.model_dump_json().encode()
    if len(body) > MAX_REQUEST_BYTES:
        raise ValueError("NL2Agent tool arguments are too large")
    token = sign_call(operation, body, actor)
    try:
        with httpx.Client(timeout=_TIMEOUT, trust_env=False, follow_redirects=False) as client:
            response = client.post(
                f"{MANAGEMENT_AGENTOS_URL}/api{operation.value}", content=body,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            response.raise_for_status()
            output = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("NL2Agent tool rejected run_id=%s tool=%s status=%d", run_id, tool, exc.response.status_code)
        raise RuntimeError("NL2Agent tool request was rejected by Management") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("NL2Agent tool service is unavailable") from exc
    if not isinstance(output, (dict, str)):
        raise ValueError("Invalid NL2Agent tool response")
    return output


def _callback_tools(payload, actor):
    for config in create_nl2agent_mcp_tool_configs():
        operation, fields = _TOOL_INPUTS[config.name]
        schema = create_model(
            config.name + "_input", __config__=ConfigDict(extra="forbid"), agent_id=(_AGENT_ID, ...), **fields,
        )

        def invoke(agent_id, _operation=operation, **arguments):
            if agent_id != payload.agent_id:
                return {"status": "error", "code": "agent_context_mismatch", "retryable": False}
            return _invoke_tool(payload.run_id, actor, _operation, agent_id, **arguments)

        tool = StructuredTool.from_function(
            func=invoke, name=config.name, description=config.description, args_schema=schema,
        )
        yield config.model_copy(update={"source": "langchain", "metadata": tool, "usage": None})


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
        if not agent_name and process_type == ProcessType.FINAL_ANSWER:
            return
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


def prepare_agent_creator_run(payload: PreparedAgentCreatorRun, actor: ServicePrincipal) -> AgentRunInfo:
    if payload.model.provider_body_revision is not None or payload.model.root_generation is not None:
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_RESOURCE_UNSUPPORTED"})
    model = _materialize_model(payload.model, actor, None)
    query, _, _ = materialize_evaluation_input(payload.input, actor, payload.language)
    agent = create_nl2agent_agent_config(payload.language, list(_callback_tools(payload, actor)))
    agent.model_name = model.cite_name
    agent.context_items.append(ContextItemInput(
        id="system:nl2agent_bound_resources", type=ContextItemType.SYSTEM, content={"text": payload.bound_resources},
        source=("database:agent_bindings",), priority=85, metadata={"authority": "tenant"},
    ))
    budget = apply_creator_budget(payload, agent)
    stop_event = threading.Event()
    info = build_run_info(
        language=payload.language, query=query, agent_config=agent, model_config_list=[model],
        observer=_Nl2AgentBoundaryObserver(lang=payload.language, stop_event=stop_event),
        stop_event=stop_event, enable_planning=False, sandbox_config=None, redis_client=None,
        capacity_snapshot=payload.capacity_snapshot, context_budget_snapshot=budget,
        workspace_run_id=payload.run_id, user_id=actor.user_id, tenant_id=actor.tenant_id,
        history=[AgentHistory(role=item.role, content=item.content) for item in payload.input.history],
    )
    info.context_input = build_authorized_context_input(info)
    return info
