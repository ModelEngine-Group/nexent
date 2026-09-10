"""AG-UI Protocol Event Encoder.

Converts Nexus's internal ``ProcessType``-based SSE chunks into
AG-UI protocol events (``RUN_STARTED``, ``TEXT_MESSAGE_CONTENT``,
``TOOL_CALL_START``, ``ACTIVITY_SNAPSHOT``, etc.) that ``useAgUiRuntime``
on the frontend can consume directly.

This is a **format-only** layer — it wraps existing observer emit calls
without touching SDK internals.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from nexent.core.utils.observer import ProcessType

# ---------------------------------------------------------------------------
# AG-UI Event Type constants (kept local to avoid coupling to @ag-ui/core)
# ---------------------------------------------------------------------------

AGUI_RUN_STARTED = "RUN_STARTED"
AGUI_RUN_FINISHED = "RUN_FINISHED"
AGUI_RUN_ERROR = "RUN_ERROR"

AGUI_TEXT_MESSAGE_START = "TEXT_MESSAGE_START"
AGUI_TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"
AGUI_TEXT_MESSAGE_END = "TEXT_MESSAGE_END"

AGUI_REASONING_MESSAGE_START = "REASONING_MESSAGE_START"
AGUI_REASONING_MESSAGE_CONTENT = "REASONING_MESSAGE_CONTENT"
AGUI_REASONING_MESSAGE_END = "REASONING_MESSAGE_END"

AGUI_TOOL_CALL_START = "TOOL_CALL_START"
AGUI_TOOL_CALL_ARGS = "TOOL_CALL_ARGS"
AGUI_TOOL_CALL_END = "TOOL_CALL_END"
AGUI_TOOL_CALL_RESULT = "TOOL_CALL_RESULT"

AGUI_ACTIVITY_SNAPSHOT = "ACTIVITY_SNAPSHOT"
AGUI_ACTIVITY_DELTA = "ACTIVITY_DELTA"

AGUI_STATE_SNAPSHOT = "STATE_SNAPSHOT"
AGUI_STATE_DELTA = "STATE_DELTA"

AGUI_SUBAGENT_STARTED = "SUBAGENT_STARTED"
AGUI_SUBAGENT_FINISHED = "SUBAGENT_FINISHED"
AGUI_SUBAGENT_ERROR = "SUBAGENT_ERROR"

AGUI_STEP_STARTED = "STEP_STARTED"
AGUI_STEP_FINISHED = "STEP_FINISHED"

AGUI_CUSTOM = "CUSTOM"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts_ms() -> int:
    """Current timestamp in milliseconds (AG-UI convention)."""
    return int(time.time() * 1000)


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _safe_json_dumps(obj: Any) -> str:
    """Best-effort JSON dumps; falls back to ``str`` for non-serializable objects."""
    try:
        return json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(obj)


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------

class AgUiEventEncoder:
    """Stateful encoder that converts Nexus SSE chunks → AG-UI events.

    Usage::

        encoder = AgUiEventEncoder(thread_id="conv_123")

        # Emit run boundary
        yield encoder.run_started_event(input_state={...})

        for chunk in raw_stream:
            for agui_event in encoder.encode(chunk):
                yield agui_event

        yield encoder.run_finished_event(outcome="success")
        # or: yield encoder.run_finished_event(outcome="interrupt", interrupts=[...])

    Each call to ``encode`` returns a **list** of AG-UI events because a
    single Nexus chunk (e.g. a full TOOL emit) may need to be expanded into
    multiple AG-UI events (TOOL_CALL_START + TOOL_CALL_ARGS + TOOL_CALL_END).
    """

    def __init__(self, thread_id: str, run_id: Optional[str] = None) -> None:
        self._thread_id = thread_id
        self._run_id = run_id or _gen_id("run")

        # ---- messageId pools ------------------------------------------------
        # Each content category (text / reasoning / tool / activity / step)
        # has its own messageId lifecycle.  The pool is created lazily when
        # the first chunk of that category arrives so we don't leak IDs for
        # categories that never emit.
        self._text_msg_id: Optional[str] = None
        self._reasoning_msg_id: Optional[str] = None
        self._current_step_msg_id: Optional[str] = None

        # ---- tool-call state ------------------------------------------------
        # AG-UI tool-call is a 3/4-part sequence:
        #   START → ARGS* → END → RESULT
        # Nexus emits everything in one ProcessType.TOOL chunk (name + full args)
        # and a separate ProcessType.EXECUTION_LOGS chunk for the result.
        # We track the "currently-open" tool so EXECUTION_LOGS can attach
        # to the right toolCallId.
        self._active_tool: Optional[Dict[str, str]] = None  # toolCallId, last args JSON

        # ---- sub-agent runId mapping ----------------------------------------
        # Nexus uses (agent_id, agent_name, invocation_id) tuples; AG-UI wants
        # a string subagentRunId per nested invocation.
        self._subagent_ids: Dict[str, str] = {}  # key: agent_id → AG-UI runId

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def thread_id(self) -> str:
        return self._thread_id

    # ------------------------------------------------------------------
    # Run boundary events
    # ------------------------------------------------------------------

    def run_started_event(self, input_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Emit a ``RUN_STARTED`` event.  Call before the first chunk."""
        return {
            "type": AGUI_RUN_STARTED,
            "threadId": self._thread_id,
            "runId": self._run_id,
            "timestamp": _ts_ms(),
            "input": input_state or {},
        }

    def run_finished_event(
        self,
        outcome: str = "success",
        interrupts: Optional[List[Dict[str, Any]]] = None,
        result: Any = None,
    ) -> Dict[str, Any]:
        """Emit a ``RUN_FINISHED`` event.  Call in ``finally:`` block."""
        outcome_obj: Dict[str, Any] = {"type": outcome}
        if outcome == "interrupt" and interrupts:
            outcome_obj["interrupts"] = interrupts

        return {
            "type": AGUI_RUN_FINISHED,
            "threadId": self._thread_id,
            "runId": self._run_id,
            "timestamp": _ts_ms(),
            "outcome": outcome_obj,
            "result": result,
        }

    # ------------------------------------------------------------------
    # Main encode entry point
    # ------------------------------------------------------------------

    def encode(self, chunk_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Convert a Nexus chunk dict (from ``Message.to_json()``) into AG-UI events.

        Returns an (possibly empty) list of AG-UI event dicts ready to be
        serialized and sent over SSE.
        """
        process_type = chunk_dict.get("type", "")
        content = chunk_dict.get("content")
        agent_id = chunk_dict.get("agent_id")
        invocation_id = chunk_dict.get("invocation_id")
        tool_name = chunk_dict.get("tool_name")
        tool_call_id = chunk_dict.get("tool_call_id")

        # Resolve subagentRunId for nested chunks
        subagent_run_id = None
        if agent_id is not None:
            subagent_run_id = self._subagent_ids.setdefault(
                f"{invocation_id or ''}:{agent_id}", _gen_id("subrun")
            )

        # ---- Dispatch by ProcessType ---------------------------------------
        events: List[Dict[str, Any]] = []

        if process_type == ProcessType.MODEL_OUTPUT_THINKING.value:
            events.extend(self._encode_reasoning_delta(content, subagent_run_id))

        elif process_type == ProcessType.MODEL_OUTPUT_DEEP_THINKING.value:
            events.extend(self._encode_reasoning_delta(content, subagent_run_id))

        elif process_type == ProcessType.MODEL_OUTPUT_CODE.value:
            events.extend(self._encode_text_delta(content, subagent_run_id))

        elif process_type == ProcessType.FINAL_ANSWER.value:
            events.extend(self._encode_text_delta(content, subagent_run_id))

        elif process_type == ProcessType.STEP_COUNT.value:
            events.append(self._step_started_event(subagent_run_id))

        elif process_type == ProcessType.TOOL.value:
            events.extend(self._encode_tool_start(chunk_dict, subagent_run_id))

        elif process_type == ProcessType.EXECUTION_LOGS.value:
            events.append(self._encode_tool_result(content, subagent_run_id))

        elif process_type == ProcessType.SUBAGENT_START.value:
            events.append(self._encode_subagent_start(chunk_dict, subagent_run_id))

        elif process_type == ProcessType.SUBAGENT_END.value:
            events.append(self._encode_subagent_end(subagent_run_id))

        elif process_type == ProcessType.ERROR.value:
            # If this is top-level (no agent_id), it's a run-level error
            if agent_id is None:
                events.append(self._run_error_event(content))
            else:
                events.append(self._subagent_error_event(subagent_run_id, content))

        elif process_type == ProcessType.A2UI.value:
            # content is already an AG-UI ACTIVITY_SNAPSHOT JSON string or dict
            events.extend(self._encode_activity_snapshot(content, subagent_run_id))

        elif process_type == ProcessType.PLAN.value:
            events.append(self._state_delta_event("plan", content, subagent_run_id))

        elif process_type == ProcessType.PLAN_STEP_UPDATE.value:
            events.append(self._state_delta_event("plan_step", content, subagent_run_id))

        elif process_type == ProcessType.NL2A_STATE.value:
            events.append(self._state_delta_event("nl2a_state", content, subagent_run_id))

        elif process_type == ProcessType.TOKEN_COUNT.value:
            events.append(self._custom_event("token_count", content, subagent_run_id))

        elif process_type == ProcessType.SEARCH_CONTENT.value:
            events.append(self._custom_event("search_content", content, subagent_run_id))

        elif process_type == ProcessType.PICTURE_WEB.value:
            events.append(self._custom_event("picture_web", content, subagent_run_id))

        elif process_type == ProcessType.CARD.value:
            events.append(self._custom_event("card", content, subagent_run_id))

        elif process_type == ProcessType.SKILL_ARTIFACT.value:
            events.append(self._custom_event("skill_artifact", content, subagent_run_id))

        elif process_type == ProcessType.FILE_ARTIFACT.value:
            events.append(self._custom_event("file_artifact", content, subagent_run_id))

        elif process_type == ProcessType.MEMORY_SEARCH.value:
            events.append(self._custom_event("memory_search", content, subagent_run_id))

        elif process_type == ProcessType.VERIFICATION.value:
            events.append(self._custom_event("verification", content, subagent_run_id))

        elif process_type == ProcessType.AUTOMATION_PROPOSAL.value:
            events.append(self._custom_event("automation_proposal", content, subagent_run_id))

        elif process_type == ProcessType.HISTORY_SUMMARY.value:
            events.append(self._custom_event("history_summary", content, subagent_run_id))

        elif process_type == ProcessType.MAX_STEPS_REACHED.value:
            events.append(self._custom_event("max_steps_reached", content, subagent_run_id))

        elif process_type == ProcessType.NL2A.value:
            events.append(self._custom_event("nl2a", content, subagent_run_id))

        elif process_type == ProcessType.PARSE.value:
            events.append(self._custom_event("parse", content, subagent_run_id))

        # AGENT_NEW_RUN / AGENT_FINISH / OTHER → skip (handled by run boundary)
        # STEP_COUNT already handled above

        return events

    # ------------------------------------------------------------------
    # Category-level helpers
    # ------------------------------------------------------------------

    def _ensure_text_message_start(self, subagent_run_id: Optional[str]) -> List[Dict[str, Any]]:
        """Lazily create the TEXT_MESSAGE_START event for the main answer channel."""
        if self._text_msg_id is not None:
            return []
        self._text_msg_id = _gen_id("msg")
        return [{
            "type": AGUI_TEXT_MESSAGE_START,
            "messageId": self._text_msg_id,
            "role": "assistant",
            "timestamp": _ts_ms(),
            **({"subagentRunId": subagent_run_id} if subagent_run_id else {}),
        }]

    def _ensure_reasoning_message_start(self, subagent_run_id: Optional[str]) -> List[Dict[str, Any]]:
        """Lazily create the REASONING_MESSAGE_START event."""
        if self._reasoning_msg_id is not None:
            return []
        self._reasoning_msg_id = _gen_id("msg")
        return [{
            "type": AGUI_REASONING_MESSAGE_START,
            "messageId": self._reasoning_msg_id,
            "timestamp": _ts_ms(),
            **({"subagentRunId": subagent_run_id} if subagent_run_id else {}),
        }]

    def _encode_text_delta(
        self, content: Any, subagent_run_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        if content is None:
            return []
        delta = str(content) if not isinstance(content, str) else content
        events = self._ensure_text_message_start(subagent_run_id)
        events.append({
            "type": AGUI_TEXT_MESSAGE_CONTENT,
            "messageId": self._text_msg_id,
            "delta": delta,
            "timestamp": _ts_ms(),
            **({"subagentRunId": subagent_run_id} if subagent_run_id else {}),
        })
        return events

    def _encode_reasoning_delta(
        self, content: Any, subagent_run_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        if content is None:
            return []
        delta = str(content) if not isinstance(content, str) else content
        events = self._ensure_reasoning_message_start(subagent_run_id)
        events.append({
            "type": AGUI_REASONING_MESSAGE_CONTENT,
            "messageId": self._reasoning_msg_id,
            "delta": delta,
            "timestamp": _ts_ms(),
            **({"subagentRunId": subagent_run_id} if subagent_run_id else {}),
        })
        return events

    # ------------------------------------------------------------------
    # Tool-call handling (Nexus single-chunk → AG-UI multi-event)
    # ------------------------------------------------------------------

    def _encode_tool_start(
        self, chunk_dict: Dict[str, Any], subagent_run_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        tool_name = chunk_dict.get("tool_name", "unknown")
        tool_call_id = chunk_dict.get("tool_call_id") or _gen_id("tc")
        tool_args = chunk_dict.get("tool_arguments")

        # Track active tool so EXECUTION_LOGS knows which toolCallId to attach
        self._active_tool = {"toolCallId": tool_call_id, "toolName": tool_name}

        events: List[Dict[str, Any]] = []
        events.append({
            "type": AGUI_TOOL_CALL_START,
            "toolCallId": tool_call_id,
            "toolCallName": tool_name,
            "timestamp": _ts_ms(),
            **({"subagentRunId": subagent_run_id} if subagent_run_id else {}),
        })

        # Nexus gives us full args in one shot; emit as single ARGS event
        args_delta = _safe_json_dumps(tool_args) if tool_args is not None else "{}"
        events.append({
            "type": AGUI_TOOL_CALL_ARGS,
            "toolCallId": tool_call_id,
            "delta": args_delta,
            "timestamp": _ts_ms(),
            **({"subagentRunId": subagent_run_id} if subagent_run_id else {}),
        })

        events.append({
            "type": AGUI_TOOL_CALL_END,
            "toolCallId": tool_call_id,
            "timestamp": _ts_ms(),
            **({"subagentRunId": subagent_run_id} if subagent_run_id else {}),
        })

        return events

    def _encode_tool_result(
        self, content: Any, subagent_run_id: Optional[str]
    ) -> Dict[str, Any]:
        """Attach EXECUTION_LOGS to the most recent active tool."""
        if self._active_tool is None:
            # No matching TOOL_START — emit as standalone tool result
            tool_call_id = _gen_id("tc")
        else:
            tool_call_id = self._active_tool["toolCallId"]
            self._active_tool = None  # consume it

        message_id = _gen_id("msg")
        result_text = content if isinstance(content, str) else _safe_json_dumps(content)

        return {
            "type": AGUI_TOOL_CALL_RESULT,
            "toolCallId": tool_call_id,
            "messageId": message_id,
            "content": str(result_text),
            "role": "tool",
            "timestamp": _ts_ms(),
            **({"subagentRunId": subagent_run_id} if subagent_run_id else {}),
        }

    # ------------------------------------------------------------------
    # Sub-agent
    # ------------------------------------------------------------------

    def _encode_subagent_start(
        self, chunk_dict: Dict[str, Any], subagent_run_id: Optional[str]
    ) -> Dict[str, Any]:
        agent_name = chunk_dict.get("agent_name") or chunk_dict.get("content") or "subagent"
        # If subagent_run_id wasn't pre-allocated, create one now
        if subagent_run_id is None:
            subagent_run_id = _gen_id("subrun")
            agent_id = chunk_dict.get("agent_id") or ""
            invocation_id = chunk_dict.get("invocation_id") or ""
            self._subagent_ids[f"{invocation_id}:{agent_id}"] = subagent_run_id

        return {
            "type": AGUI_SUBAGENT_STARTED,
            "subagentRunId": subagent_run_id,
            "subagentName": str(agent_name),
            "timestamp": _ts_ms(),
        }

    def _encode_subagent_end(
        self, subagent_run_id: Optional[str]
    ) -> Dict[str, Any]:
        return {
            "type": AGUI_SUBAGENT_FINISHED,
            "subagentRunId": subagent_run_id or _gen_id("subrun"),
            "status": "success",
            "timestamp": _ts_ms(),
        }

    def _subagent_error_event(
        self, subagent_run_id: Optional[str], content: Any
    ) -> Dict[str, Any]:
        return {
            "type": AGUI_SUBAGENT_ERROR,
            "subagentRunId": subagent_run_id or _gen_id("subrun"),
            "message": str(content) if content else "unknown subagent error",
            "timestamp": _ts_ms(),
        }

    # ------------------------------------------------------------------
    # Error / step / activity / state / custom
    # ------------------------------------------------------------------

    def _run_error_event(self, content: Any) -> Dict[str, Any]:
        return {
            "type": AGUI_RUN_ERROR,
            "message": str(content) if content else "unknown error",
            "timestamp": _ts_ms(),
        }

    def _step_started_event(self, subagent_run_id: Optional[str]) -> Dict[str, Any]:
        self._current_step_msg_id = _gen_id("step")
        event: Dict[str, Any] = {
            "type": AGUI_STEP_STARTED,
            "stepId": self._current_step_msg_id,
            "timestamp": _ts_ms(),
        }
        if subagent_run_id:
            event["subagentRunId"] = subagent_run_id
        return event

    def _encode_activity_snapshot(
        self, content: Any, subagent_run_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """A2UI chunk → AG-UI ACTIVITY_SNAPSHOT.

        The backend A2UI layer already wraps Nexus A2UI output into
        ``{"type": "ACTIVITY_SNAPSHOT", "messageId": "...", "activityType": "a2ui-surface",
           "content": {"a2ui_operations": [...]}, ...}``.  We may receive either the
        raw dict or a JSON string — normalise and forward.
        """
        # content might be:
        # 1. already a parsed AG-UI ACTIVITY_SNAPSHOT dict (from a2ui_to_agui)
        # 2. a JSON string of the same dict
        # 3. raw Nexus A2UI JSON (fallback — shouldn't happen after our a2ui_to_agui)
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                # Not valid JSON — emit as custom
                return [self._custom_event("a2ui_raw", content, subagent_run_id)]

        if not isinstance(content, dict):
            return [self._custom_event("a2ui_unknown", str(content), subagent_run_id)]

        # If content.type is already ACTIVITY_SNAPSHOT, it's already AG-UI-shaped
        if content.get("type") == AGUI_ACTIVITY_SNAPSHOT:
            event = dict(content)  # shallow copy
            # Ensure timestamp is present
            if "timestamp" not in event:
                event["timestamp"] = _ts_ms()
            if subagent_run_id and "subagentRunId" not in event:
                event["subagentRunId"] = subagent_run_id
            return [event]

        # Otherwise treat as unknown A2UI payload
        return [self._custom_event("a2ui_unwrapped", content, subagent_run_id)]

    def _state_delta_event(
        self, state_key: str, content: Any, subagent_run_id: Optional[str]
    ) -> Dict[str, Any]:
        return {
            "type": AGUI_STATE_DELTA,
            "messageId": _gen_id("state"),
            "delta": {state_key: content},
            "timestamp": _ts_ms(),
            **({"subagentRunId": subagent_run_id} if subagent_run_id else {}),
        }

    def _custom_event(
        self, source: str, content: Any, subagent_run_id: Optional[str]
    ) -> Dict[str, Any]:
        """Generic fallback for ProcessTypes without a first-class AG-UI mapping."""
        return {
            "type": AGUI_CUSTOM,
            "source": source,
            "event": content,
            "timestamp": _ts_ms(),
            **({"subagentRunId": subagent_run_id} if subagent_run_id else {}),
        }
