# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Materialize the request-owned NL2Agent and bind its signed tool callbacks."""

import json
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
    DISCOVER_REQUIREMENTS_NAME, READ_CONFIGURATION_NAME, READ_GENERATION_CONTEXT_NAME,
    NL2AGENT_RECEIPT_KEY, SHOW_RESOURCE_CARD_NAME, VERIFY_REQUIREMENTS_NAME,
    SAVE_CONFIGURATION_NAME, VALIDATE_AGENT_GENERATION_COMPLETE_NAME,
    SEARCH_INSTALLED_RESOURCES_NAME, SEARCH_UNINSTALLED_RESOURCES_NAME, create_nl2agent_mcp_tool_configs,
)
from nexent.core.agents.contracts.run import AgentHistory, AgentRunInfo
from nexent.core.agents.context import ContextItemInput, ContextItemType
from nexent.core.agents.context.authorized_input import build_authorized_context_input
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
    VALIDATE_AGENT_GENERATION_COMPLETE_NAME: ("validate_agent_generation_complete", {}),
    DISCOVER_REQUIREMENTS_NAME: ("discover_requirements", {
        "requirements": (_OPTIONAL_OBJECTS, None), "purpose": (str, "generate"),
        "search_queries": (_OPTIONAL_OBJECT, None),
    }),
    VERIFY_REQUIREMENTS_NAME: ("verify_requirements", {
        "verification_batch_id": (str, ...), "checks": (list[dict[str, Any]], ...),
    }),
    SHOW_RESOURCE_CARD_NAME: ("show_resource_card", {}),
    READ_GENERATION_CONTEXT_NAME: ("read_generation_context", {"goal": (str, "prompt")}),
    READ_CONFIGURATION_NAME: ("read_agent_configuration", {"section": (str, ...)}),
    SAVE_CONFIGURATION_NAME: ("save_agent_configuration", {"section": (str, ...), "changes": (dict[str, Any], ...)}),
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


def _callback_tools(payload, actor, observer=None):
    for config in create_nl2agent_mcp_tool_configs():
        operation, fields = _TOOL_INPUTS[config.name]
        schema = create_model(
            config.name + "_input", __config__=ConfigDict(extra="forbid"), agent_id=(_AGENT_ID, payload.agent_id), **fields,
        )

        def invoke(agent_id=payload.agent_id, _operation=operation, **arguments):
            if agent_id != payload.agent_id:
                return {"status": "error", "code": "agent_context_mismatch", "retryable": False}
            output = _invoke_tool(payload.run_id, actor, _operation, agent_id, **arguments)
            if isinstance(output, dict) and output.get("agentos_tool_result") is True:
                if observer is not None:
                    observer.on_mcp_tool_result("nl2a_" + _operation, output.get("meta"))
                return "\n".join(item.get("text", "") for item in output["content"])
            return output

        tool = StructuredTool.from_function(
            func=invoke, name=config.name, description=config.description, args_schema=schema,
        )
        yield config.model_copy(update={"source": "langchain", "metadata": tool, "usage": None})


class _Nl2AgentBoundaryObserver(MessageObserver):
    """Stop an NL2Agent run after its first valid interactive payload."""

    manages_requirement_clarification = True
    _STOP_FINAL_ANSWER = "<user_break>"
    _STOP_ERROR = "Agent execution interrupted by external stop signal"

    def __init__(self, *, lang: str, stop_event: threading.Event, agent_id: int, run_id: str,
                 conversation_id: str):
        super().__init__(lang=lang)
        self._boundary_stop_event = stop_event
        self._boundary_reached = False
        self._boundary_lock = threading.Lock()
        self._target_agent_id = agent_id
        self._run_id = run_id
        self._conversation_id = conversation_id
        self._seen_receipt_ids: set[str] = set()

    def bind_conversation(self, conversation_id: str) -> None:
        self._conversation_id = conversation_id

    @property
    def boundary_reached(self) -> bool:
        with self._boundary_lock:
            return self._boundary_reached

    @property
    def turn_complete(self) -> bool:
        return self.boundary_reached

    def add_message(self, agent_name, process_type, content, **kwargs):
        if self.boundary_reached and (
            (process_type == ProcessType.FINAL_ANSWER and content == self._STOP_FINAL_ANSWER)
            or (process_type == ProcessType.WARNING and content == self._STOP_ERROR)
        ):
            return

        super().add_message(agent_name, process_type, content, **kwargs)

    def on_mcp_tool_result(self, tool_name: str, meta: dict[str, Any] | None) -> None:
        """Deliver a business receipt only from the run's local MCP connection."""
        receipt = meta.get(NL2AGENT_RECEIPT_KEY) if isinstance(meta, dict) else None
        if not isinstance(receipt, dict):
            return
        event_id = receipt.get("event_id")
        payload = receipt.get("payload")
        if (
            receipt.get("run_id") != self._run_id
            or receipt.get("conversation_id") != self._conversation_id
            or not isinstance(event_id, str)
            or not event_id
            or not isinstance(payload, dict)
            or type(payload.get("agent_id")) is not int
            or payload["agent_id"] != self._target_agent_id
        ):
            return
        is_legacy_card = tool_name == NL2A_WRAPPER_NAME and payload.get("subtype") in (
            "requirement_clarification", "suggested_resource_installation", "installed_resource_binding",
        )
        is_resource_card = (
            tool_name in {SHOW_RESOURCE_CARD_NAME, VERIFY_REQUIREMENTS_NAME}
            and payload.get("protocol_version") == 2
            and payload.get("run_id") == self._run_id
            and payload.get("conversation_id") == self._conversation_id
            and isinstance(payload.get("card_id"), str)
            and type(payload.get("state_version")) is int
        )
        is_prompt_card = (
            tool_name == SAVE_AGENT_DRAFT_FIELDS_NAME and payload.get("subtype") == "prompt_generation"
            and payload.get("run_id") == self._run_id
            and payload.get("conversation_id") == self._conversation_id
            and isinstance(payload.get("card_id"), str)
            and isinstance(payload.get("prompt_revision"), str)
            and isinstance(payload.get("proposed_prompt"), str)
            and payload.get("status") == "pending"
        )
        is_card = is_legacy_card or is_resource_card or is_prompt_card
        is_save = tool_name in {SAVE_AGENT_DRAFT_FIELDS_NAME, SAVE_CONFIGURATION_NAME} and payload.get("event") in (
            "agent_draft_fields_saved", "prompt_generation_failed",
        )
        is_completion = (
            tool_name == VALIDATE_AGENT_GENERATION_COMPLETE_NAME
            and payload.get("event") == "agent_generation_completed"
        )
        if not (is_card or is_save or is_completion):
            return

        with self._boundary_lock:
            if self._boundary_stop_event.is_set() or event_id in self._seen_receipt_ids:
                return
            self._seen_receipt_ids.add(event_id)
            super().add_message(
                "",
                ProcessType.NL2A if is_card else ProcessType.NL2A_STATE,
                json.dumps(payload, ensure_ascii=False),
            )
            if is_card:
                self._boundary_reached = True
            # Graceful turn completion must not cancel the SDK output consumer.
            # CoreAgent observes turn_complete between actions, after the card
            # has been queued, while agent_run drains output during cleanup.


def prepare_agent_creator_run(payload: PreparedAgentCreatorRun, actor: ServicePrincipal) -> AgentRunInfo:
    if payload.model.provider_body_revision is not None or payload.model.root_generation is not None:
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_RESOURCE_UNSUPPORTED"})
    model = _materialize_model(payload.model, actor, None)
    query, _, _ = materialize_evaluation_input(payload.input, actor, payload.language)
    from runtime.agentos.creator_definition import load_creator_definition

    stop_event = threading.Event()
    observer = _Nl2AgentBoundaryObserver(
        lang=payload.language, stop_event=stop_event, agent_id=payload.agent_id,
        run_id=payload.run_id, conversation_id=str(payload.conversation_id or ""),
    )
    agent = create_nl2agent_agent_config(payload.language, list(_callback_tools(payload, actor, observer)),
                                       snapshot=load_creator_definition(payload))
    agent.model_name = model.cite_name
    agent.context_items.append(ContextItemInput(
        id="system:nl2agent_bound_resources", type=ContextItemType.SYSTEM, content={"text": payload.bound_resources},
        source=("database:agent_bindings",), priority=85, metadata={"authority": "tenant"},
    ))
    budget = apply_creator_budget(payload, agent)
    info = build_run_info(
        language=payload.language, query=query, agent_config=agent, model_config_list=[model],
        observer=observer,
        stop_event=stop_event, enable_planning=False, sandbox_config=None, redis_client=None,
        capacity_snapshot=payload.capacity_snapshot, context_budget_snapshot=budget,
        workspace_run_id=payload.run_id, user_id=actor.user_id, tenant_id=actor.tenant_id,
        history=[
            AgentHistory(role=item.role, content=item.content)
            for item in payload.input.history if item.role != "attachment"
        ],
    )
    info.context_input = build_authorized_context_input(info)
    return info
