# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime AgentOS endpoint and event collection for prepared evaluations."""

import json
import logging

from contracts.agentos import (
    BODY_KEY,
    PRINCIPAL_KEY,
    AgentOperation,
    EvaluationAgentResult,
    PreparedEvaluationRun,
)
from fastapi import APIRouter, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from backend.http.server.agentos_lifecycle import run_until_disconnect

logger = logging.getLogger(__name__)


# Event types whose content participates in reclassify_step answer rebuilds.
_BODY_EVENT_TYPES = {"model_output_thinking", "model_output_code"}


def _event_invocation_key(data: dict) -> object:
    """Bucket key for per-invocation answer extraction.

    Root-level (non sub-agent) events carry no ``invocation_id`` field, which
    ``dict.get`` maps to None — matching the observer's own state keying.
    """
    return data.get("invocation_id")


def _collect_final_answer(events: list[dict]) -> str:
    """Rebuild the agent's final answer from the observed event stream.

    The final-answer protocol (since #4077) splits answers into
    ``answer_phase="delta"`` fragments plus one ``answer_phase="complete"``
    trailer; when the answer was already streamed the trailer's content is an
    empty string and the real answer lives only in observer state. The
    observer now carries it as ``accepted_answer`` metadata on the trailer.

    Extraction precedence per invocation:
      1. ``accepted_answer`` from the complete trailer (authoritative).
      2. Non-empty ``content`` on the complete trailer (rewritten answer
         overrides streamed deltas, avoiding duplicate concatenation).
      3. ``reclassify_step=True`` trailer: body events of the same
         ``(invocation_id, step_id)`` reclassified as the answer.
      4. Concatenated delta fragments (legacy events without
         ``answer_phase`` land here too, preserving old behavior).
    """
    # Per-invocation buckets.
    delta_parts: dict[object, list[str]] = {}
    complete_answers: dict[object, str] = {}
    # Body fragments keyed by (invocation_id, step_id) for rebuilds.
    body_parts: dict[tuple, list[str]] = {}
    # reclassify trailers keyed by (invocation_id, step_id).
    reclassify_steps: list[tuple] = []
    # Track trailer emission order per invocation for stable join order.
    invocation_order: list[object] = []

    def _touch(key: object) -> None:
        if key not in delta_parts and key not in complete_answers:
            invocation_order.append(key)

    for data in events:
        etype = data.get("type")
        if etype in _BODY_EVENT_TYPES:
            body_parts.setdefault(
                (_event_invocation_key(data), data.get("step_id")), []
            ).append(str(data.get("content") or ""))
        elif etype == "final_answer":
            key = _event_invocation_key(data)
            content = data.get("content")
            phase = data.get("answer_phase")
            if phase == "complete":
                _touch(key)
                accepted = data.get("accepted_answer")
                if isinstance(accepted, str) and accepted.strip():
                    # Authoritative value from the observer state.
                    complete_answers[key] = accepted
                elif isinstance(content, str) and content.strip():
                    # Un-streamed (or rewritten) answer carried by the trailer.
                    complete_answers[key] = content
                elif data.get("reclassify_step"):
                    # Answer is the reclassified body of this step; resolve
                    # after all events are consumed.
                    reclassify_steps.append((key, data.get("step_id")))
            elif isinstance(content, str):
                # Delta fragment, or a legacy event without answer_phase.
                _touch(key)
                delta_parts.setdefault(key, []).append(content)

    # Resolve reclassify rebuilds against accumulated body fragments.
    for key, step_id in reclassify_steps:
        if key not in complete_answers:
            complete_answers[key] = "".join(body_parts.get((key, step_id), []))

    answers: list[str] = []
    for key in invocation_order:
        if key in complete_answers:
            answers.append(complete_answers[key])
        else:
            answers.append("".join(delta_parts.get(key, [])))
    return "\n".join(a for a in answers if a.strip())


def create_evaluation_router() -> APIRouter:
    router = APIRouter()

    @router.post(AgentOperation.EVALUATION_CASE.value, include_in_schema=False)
    async def run_prepared_case(request: Request):
        actor = request.scope.get(PRINCIPAL_KEY)
        if actor is None:
            return JSONResponse({"code": "AGENTOS_UNAUTHORIZED"}, status_code=401)
        try:
            payload = PreparedEvaluationRun.model_validate_json(request.scope[BODY_KEY])
        except ValidationError:
            return JSONResponse({"code": "AGENTOS_INVALID_REQUEST"}, status_code=422)
        from runtime.agentos.prepared_evaluation import execute_prepared_evaluation

        return await run_until_disconnect(request, execute_prepared_evaluation(payload, actor))

    return router


async def collect_observer_output(agent_run_info, runner, thread_manager) -> EvaluationAgentResult:
    runtime_events: list[dict] = []

    def _consume(data: dict) -> None:
        runtime_events.append(data)

    async for chunk in runner(
        agent_run_info,
        thread_manager=thread_manager,
    ):
        try:
            data = json.loads(chunk)
            if isinstance(data, dict):
                _consume(data)
        except Exception:
            logger.debug(
                "Failed to parse observer chunk: %r", chunk[:200], exc_info=True
            )
    # Straggler messages flushed after the generator ends must flow through
    # the same extraction path — appending them to runtime_events alone would
    # silently drop an answer that only arrived in the final drain.
    for msg in agent_run_info.observer.get_cached_message():
        try:
            data = json.loads(msg)
            if isinstance(data, dict):
                _consume(data)
        except Exception:
            logger.debug(
                "Failed to parse straggler observer message", exc_info=True
            )
    return EvaluationAgentResult(
        answer=_collect_final_answer(runtime_events), events=runtime_events
    )
