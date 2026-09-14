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
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

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
AGUI_RAW = "RAW"

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

        # ---- FINAL_ANSWER A2UI tag buffer -----------------------------------
        # The model emits A2UI as <a2ui-json>...</a2ui-json> embedded inside
        # FINAL_ANSWER text.  Tags may be split across streaming deltas, so
        # we accumulate and scan for complete open/close pairs.  Plain text
        # goes out as TEXT_MESSAGE_CONTENT; captured JSON becomes
        # ACTIVITY_SNAPSHOT events that useAgUiRuntime consumes natively.
        self._final_answer_buffer: str = ""

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
        """Emit a ``RUN_STARTED`` event.  Call before the first chunk.

        ``input`` is optional in the AG-UI schema and requires the full
        RunAgentInput shape (threadId, runId, messages, tools, context...).
        Nexus only has a partial picture here, so we deliberately omit it
        to avoid Zod validation failures on the frontend.
        """
        event: Dict[str, Any] = {
            "type": AGUI_RUN_STARTED,
            "threadId": self._thread_id,
            "runId": self._run_id,
            "timestamp": _ts_ms(),
        }
        if input_state:
            # Wrap Nexus input as a plain metadata field instead of
            # pretending it's a RunAgentInput.
            event["metadata"] = {"nexus_input": input_state}
        return event

    def run_finished_event(
        self,
        outcome: str = "success",
        interrupts: Optional[List[Dict[str, Any]]] = None,
        result: Any = None,
    ) -> Dict[str, Any]:
        """Emit a ``RUN_FINISHED`` event.  Call in ``finally:`` block.

        IMPORTANT: Call ``_drain_open_step_events()`` *before* this, otherwise
        AG-UI client will reject RUN_FINISHED with "steps still active".
        This method does NOT emit STEP_FINISHED itself.
        """
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

    def _drain_open_step_events(self) -> List[Dict[str, Any]]:
        """If a step is still open, emit STEP_FINISHED and clear state.

        Called before text-finalising events (FINAL_ANSWER) and before
        RUN_FINISHED so AG-UI state machine never sees a stray open step.
        """
        if self._current_step_msg_id is None:
            return []
        step_name = self._current_step_msg_id
        self._current_step_msg_id = None
        return [{
            "type": AGUI_STEP_FINISHED,
            "stepName": step_name,
            "timestamp": _ts_ms(),
        }]

    def _drain_open_message_events(self) -> List[Dict[str, Any]]:
        """Close any open TEXT_MESSAGE or REASONING_MESSAGE with *_END events.

        AG-UI client rejects RUN_FINISHED while any message is still active.
        """
        events: List[Dict[str, Any]] = []
        if self._text_msg_id is not None:
            events.append({
                "type": AGUI_TEXT_MESSAGE_END,
                "messageId": self._text_msg_id,
                "timestamp": _ts_ms(),
            })
            self._text_msg_id = None
        if self._reasoning_msg_id is not None:
            events.append({
                "type": AGUI_REASONING_MESSAGE_END,
                "messageId": self._reasoning_msg_id,
                "timestamp": _ts_ms(),
            })
            self._reasoning_msg_id = None
        return events

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

        if process_type == ProcessType.STEP_COUNT.value:
            # Drain previous step before opening a new one
            events.extend(self._drain_open_step_events())
            events.append(self._step_started_event(subagent_run_id))

        elif process_type == ProcessType.FINAL_ANSWER.value:
            # Final answer closes the active step.
            # NOTE: A2UI content should arrive via ProcessType.A2UI natively.
            # _encode_a2ui_tagged_text() is kept as fallback for old clients.
            events.extend(self._drain_open_step_events())
            events.extend(self._encode_a2ui_tagged_text(content, subagent_run_id))

        elif process_type == ProcessType.MODEL_OUTPUT_THINKING.value:
            events.extend(self._encode_reasoning_delta(content, subagent_run_id))

        elif process_type == ProcessType.MODEL_OUTPUT_DEEP_THINKING.value:
            events.extend(self._encode_reasoning_delta(content, subagent_run_id))

        elif process_type == ProcessType.MODEL_OUTPUT_CODE.value:
            events.extend(self._encode_text_delta(content, subagent_run_id))

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
            logger.debug(
                "[AgUiEncoder] ProcessType.A2UI received, content_type=%s, content_len=%d",
                type(content).__name__, len(str(content)),
            )
            events.extend(self._encode_activity_snapshot(content, subagent_run_id))
            logger.debug(
                "[AgUiEncoder] ProcessType.A2UI → %d events, types=%s",
                len(events), [e.get("type") for e in events],
            )

        elif process_type == ProcessType.CARD.value:
            # CARD can be either Nexus custom cards or A2UI surface payloads.
            # Route through _encode_activity_snapshot so A2UI-shaped content
            # produces proper AG-UI ACTIVITY_SNAPSHOT events that useAgUiRuntime
            # can consume natively; raw custom cards fall through to RAW.
            events.extend(self._encode_activity_snapshot(content, subagent_run_id))

        elif process_type == ProcessType.PLAN.value:
            events.append(self._state_delta_event("plan", content, subagent_run_id))

        elif process_type == ProcessType.NL2A_STATE.value:
            events.append(self._state_delta_event("nl2a_state", content, subagent_run_id))

        elif process_type == ProcessType.TOKEN_COUNT.value:
            events.append(self._raw_event("token_count", content, subagent_run_id))

        elif process_type == ProcessType.SEARCH_CONTENT.value:
            events.append(self._raw_event("search_content", content, subagent_run_id))

        elif process_type == ProcessType.PICTURE_WEB.value:
            events.append(self._raw_event("picture_web", content, subagent_run_id))

        elif process_type == ProcessType.SKILL_ARTIFACT.value:
            events.append(self._raw_event("skill_artifact", content, subagent_run_id))

        elif process_type == ProcessType.FILE_ARTIFACT.value:
            events.append(self._raw_event("file_artifact", content, subagent_run_id))

        elif process_type == ProcessType.MEMORY_SEARCH.value:
            events.append(self._raw_event("memory_search", content, subagent_run_id))

        elif process_type == ProcessType.VERIFICATION.value:
            events.append(self._raw_event("verification", content, subagent_run_id))

        elif process_type == ProcessType.AUTOMATION_PROPOSAL.value:
            events.append(self._raw_event("automation_proposal", content, subagent_run_id))

        elif process_type == ProcessType.HISTORY_SUMMARY.value:
            events.append(self._raw_event("history_summary", content, subagent_run_id))

        elif process_type == ProcessType.MAX_STEPS_REACHED.value:
            events.append(self._raw_event("max_steps_reached", content, subagent_run_id))

        elif process_type == ProcessType.NL2A.value:
            events.append(self._raw_event("nl2a", content, subagent_run_id))

        elif process_type == ProcessType.PARSE.value:
            events.append(self._raw_event("parse", content, subagent_run_id))

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
            "role": "reasoning",
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

    # ------------------------------------------------------------------
    # FINAL_ANSWER: streaming <a2ui-json> tag detector
    # ------------------------------------------------------------------

    _A2UI_OPEN = "<a2ui-json>"
    _A2UI_CLOSE = "</a2ui-json>"

    def _encode_a2ui_tagged_text(
        self, content: Any, subagent_run_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Split FINAL_ANSWER text by ``<a2ui-json>...</a2ui-json>`` tags.

        Tags may be split across streaming deltas (the model emits token by
        token), so we accumulate into ``_final_answer_buffer`` and emit as
        soon as a complete open/close pair is found.  Plain prefix text goes
        out as ``TEXT_MESSAGE_CONTENT``; captured JSON becomes an
        ``ACTIVITY_SNAPSHOT`` with ``activityType="a2ui-surface"`` and
        ``content.a2ui_operations``.

        Any trailing text after the last closed tag (or an incomplete tag
        spanning into the next chunk) stays in the buffer for the next call.
        """
        events: List[Dict[str, Any]] = []
        if content is None:
            return events

        self._final_answer_buffer += (
            str(content) if not isinstance(content, str) else content
        )

        loop_count = 0
        while True:
            loop_count += 1
            buf = self._final_answer_buffer
            open_idx = buf.find(self._A2UI_OPEN)

            if open_idx == -1:
                # No open tag at all — whole buffer is plain text.
                if buf:
                    events.extend(self._encode_text_delta(buf, subagent_run_id))
                    self._final_answer_buffer = ""
                logger.debug(
                    "[AgUiEncoder] _encode_a2ui_tagged_text: no open tag, "
                    "emit %d text events, buffer cleared",
                    len(events),
                )
                return events

            # Emit plain text before the open tag (if any)
            if open_idx > 0:
                events.extend(
                    self._encode_text_delta(buf[:open_idx], subagent_run_id)
                )
                buf = buf[open_idx:]
                open_idx = 0  # buf[0] is now '<' of the open tag

            # Find matching close tag after the open tag
            close_idx = buf.find(
                self._A2UI_CLOSE, len(self._A2UI_OPEN)
            )
            if close_idx == -1:
                # Tag opened but not yet closed — leave in buffer, wait for
                # more deltas (or flush_final_answer_buffer on run end).
                self._final_answer_buffer = buf
                logger.debug(
                    "[AgUiEncoder] _encode_a2ui_tagged_text: open tag found at loop#%d "
                    "but close tag missing — buffering %d chars, return %d events",
                    loop_count, len(buf), len(events),
                )
                return events

            # Complete <a2ui-json>...</a2ui-json> pair — extract inner JSON
            inner = buf[len(self._A2UI_OPEN):close_idx]
            logger.debug(
                "[AgUiEncoder] _encode_a2ui_tagged_text: complete pair at loop#%d, "
                "inner=%d chars",
                loop_count, len(inner),
            )
            events.extend(
                self._encode_a2ui_json_content(inner, subagent_run_id)
            )

            # Continue with the text after this close tag (may contain more
            # plain text + another <a2ui-json> block — loop again)
            self._final_answer_buffer = buf[
                close_idx + len(self._A2UI_CLOSE):
            ]

    def _encode_a2ui_json_content(
        self, json_inner: str, subagent_run_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Parse the inner text of an ``<a2ui-json>`` block into an
        ``ACTIVITY_SNAPSHOT`` event.

        The model emits a stream of independent JSON objects, each on its
        own "logical line" — but those objects may be pretty-printed with
        internal newlines (indentation), so naive ``splitlines()`` breaks
        on the first ``{`` that spans multiple lines.  We use
        ``json.JSONDecoder().raw_decode`` instead: it finds the next
        complete JSON object at any offset and returns the remaining index,
        which lets us walk the string extracting one object at a time
        regardless of whitespace layout.
        """
        decoder = json.JSONDecoder()
        operations: List[Dict[str, Any]] = []
        pos = 0
        n = len(json_inner)

        while pos < n:
            # Skip whitespace between objects (newlines, spaces, commas)
            while pos < n and json_inner[pos] in " \t\r\n,":
                pos += 1
            if pos >= n:
                break

            try:
                obj, end = decoder.raw_decode(json_inner, pos)
                if isinstance(obj, dict):
                    operations.append(obj)
                else:
                    logger.debug(
                        "[AgUiEncoder] a2ui JSON block parsed but not dict: "
                        "type=%s",
                        type(obj).__name__,
                    )
                pos = end
            except json.JSONDecodeError as e:
                logger.debug(
                    "[AgUiEncoder] a2ui JSON raw_decode failed at pos=%d: %s",
                    pos, e,
                )
                # Advance past this character so we don't infinite-loop
                pos += 1

        logger.debug(
            "[AgUiEncoder] a2ui parse: collected %d ops, "
            "first keys=%s",
            len(operations),
            list(operations[0].keys()) if operations else [],
        )

        if not operations:
            logger.debug("[AgUiEncoder] NO operations → emit RAW a2ui_empty_block")
            return [self._raw_event(
                "a2ui_empty_block", json_inner, subagent_run_id
            )]

        # ---- Format conversion: Nexus A2UI → AG-UI runtime A2UI ----------
        # The model emits Nexus-specific operation names and a nested version
        # field.  AG-UI's applyA2uiOperations reducer expects:
        #   - operation keys: createSurface / updateComponents / updateDataModel / deleteSurface
        #   - version at TOP level with "v" prefix: "v0.9" or "v1.0"
        # We translate the Nexus format to the AG-UI format here.
        agui_ops = [
            self._convert_nexus_a2ui_op(op) for op in operations
        ]

        # ---- P2: Auto-complete Button action context from dataModel ------
        # Nexus model often emits Button actions without `context`, so the
        # backend never receives the form values.  As a fallback, collect
        # every path from updateDataModel ops and wire them into every
        # Button action that is missing context.  The frontend converter
        # (convert.js) resolves these paths to actual form values at click
        # time, so the agent sees complete data regardless of whether the
        # model emits context or not.
        agui_ops = self._ensure_button_action_context(agui_ops)

        logger.debug(
            "[AgUiEncoder] a2ui converted: %d ops, "
            "first keys=%s",
            len(agui_ops),
            list(agui_ops[0].keys()) if agui_ops else [],
        )

        # DUMP the full AG-UI format operations so we can verify the component
        # structure matches what applyA2uiOperations / convertSurfaceToUISpec
        # expect (children as string ID refs, flat component list).
        logger.debug(
            "[AgUiEncoder] AGUI_OPS_DUMP=%s",
            json.dumps(agui_ops, ensure_ascii=False)[:3000],
        )

        return self._encode_activity_snapshot(
            {"a2ui_operations": agui_ops}, subagent_run_id
        )

    # ------------------------------------------------------------------
    # Nexus → AG-UI A2UI operation format adapter
    # ------------------------------------------------------------------

    _NEXUS_TO_AGUI_OP = {
        "beginRendering": "createSurface",
        "createSurface": "createSurface",
        "surfaceUpdate": "updateComponents",
        "updateComponents": "updateComponents",
        "dataModelUpdate": "updateDataModel",
        "updateDataModel": "updateDataModel",
        "deleteSurface": "deleteSurface",
    }

    def _convert_nexus_a2ui_op(
        self, op: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Translate one Nexus-format A2UI operation to AG-UI format.

        Nexus shape::

            {"beginRendering": {"surfaceId": "foo", "version": "0.9", ...}}

        AG-UI shape::

            {"version": "v0.9", "createSurface": {"surfaceId": "foo", ...}}

        The AG-UI reducer also validates that ``version`` has the ``"v"``
        prefix and lives at the top level (not nested inside the payload).
        Component entries also need flattening: Nexus nests the full
        component tree under ``entry.component`` while AG-UI expects the
        component *type name* as ``entry.component`` with props/children
        lifted to the sibling level.
        """
        if not isinstance(op, dict):
            return {"version": "v0.9", "_unknown": str(op)}

        # Find the single operation key (ignoring a stray top-level "version"
        # if the model sometimes emits it there too).
        op_keys = [k for k in op.keys() if k != "version"]
        if len(op_keys) != 1:
            return {"version": "v0.9", "_unknown": op}

        op_key = op_keys[0]
        payload = op.get(op_key)
        if not isinstance(payload, dict):
            return {"version": "v0.9", "_unknown": op}

        # Translate operation name
        agui_key = self._NEXUS_TO_AGUI_OP.get(op_key, op_key)

        # Extract version from payload and promote to top-level with "v" prefix
        raw_version = payload.pop("version", None)
        if raw_version is None and "version" in op:
            raw_version = op["version"]
        if isinstance(raw_version, str):
            v_normalized = raw_version if raw_version.startswith("v") else f"v{raw_version}"
        else:
            v_normalized = "v0.9"

        # Flatten Nexus components: model uses nested component tree with
        # children as inline objects, but AG-UI reducer expects children as
        # string ID references.  We walk the tree, collect every component
        # node into a flat list, and replace each child object with its "id".
        if "components" in payload and isinstance(payload["components"], list):
            flat_components: List[Dict[str, Any]] = []
            for root_comp in payload["components"]:
                self._flatten_and_collect(root_comp, flat_components)
            payload["components"] = flat_components
            logger.debug(
                "[AgUiEncoder] FLATTENED components: %d nodes. "
                "Sample root: id=%s, component=%s, children=%s",
                len(flat_components),
                flat_components[0].get("id") if flat_components else None,
                flat_components[0].get("component") if flat_components else None,
                flat_components[0].get("children") if flat_components else None,
            )

        return {
            "version": v_normalized,
            agui_key: payload,
        }

    def _flatten_and_collect(
        self, comp: Any, collected: List[Dict[str, Any]]
    ) -> str | None:
        """Flatten one Nexus A2UI component and recursively collect its children.

        Nexus components nest the full tree inline::

            {"id": "root", "component": {"type": "Card", "props": {...},
              "children": [{"id": "name-field", "component": {"type": "TextField", ...}}]}}

        AG-UI reducer expects a **flat list** of every component, with
        ``children`` as **string ID references**::

            {"id": "root", "component": "Card", "props": {...},
             "children": ["name-field"]}    ← ID only, no objects

        Returns the component's ``id`` so the caller can use it as a child
        reference.  The node is appended to ``collected`` as a side effect.
        """
        if not isinstance(comp, dict):
            return None

        node_id = comp.get("id")
        if not isinstance(node_id, str) or not node_id:
            # Skip nodes without an id — we can't reference them
            return None

        inner = comp.get("component")
        if not isinstance(inner, dict):
            # Already flat — still process children to convert to ID refs
            flat_node: Dict[str, Any] = {k: v for k, v in comp.items()}
            self._resolve_nexus_bindings(flat_node.get("props"))
        else:
            flat_node = {"id": node_id}
            if "type" in inner:
                flat_node["component"] = inner["type"]
            if "props" in inner:
                flat_node["props"] = self._resolve_nexus_bindings(inner["props"])
            # Preserve any other top-level fields (explicitList, gap, etc.)
            for k, v in comp.items():
                if k not in ("id", "component"):
                    flat_node[k] = v

        # --- Extract child refs from Nexus props into top-level children ---
        # Nexus stashes child IDs in several places inside props:
        #   props.child          → single string ID (Card, Button, Text etc.)
        #   props.children       → {"explicitList": [...], ...} object wrapper
        #   props.children       → plain string[] array (some Columns)
        # AG-UI reducer/converter expects top-level children: string[].
        props = flat_node.get("props", {})
        if isinstance(props, dict):
            child_ids: List[str] = []

            # 1. Singular "child" string → ["child"]
            singular_child = props.get("child")
            if isinstance(singular_child, str):
                child_ids.append(singular_child)
                props.pop("child", None)
            elif isinstance(singular_child, dict):
                # Nested child object — recurse to flatten, use its id
                child_id = self._flatten_and_collect(singular_child, collected)
                if child_id:
                    child_ids.append(child_id)
                props.pop("child", None)

            # 2. "children" — could be explicitList wrapper, plain string[],
            #    or array of nested component objects
            children_raw = props.get("children")
            if children_raw is not None:
                props.pop("children", None)
                if isinstance(children_raw, dict):
                    # explicitList wrapper — extract the array
                    explicit = children_raw.get("explicitList")
                    if isinstance(explicit, list):
                        for item in explicit:
                            if isinstance(item, str):
                                child_ids.append(item)
                            elif isinstance(item, dict):
                                child_id = self._flatten_and_collect(item, collected)
                                if child_id:
                                    child_ids.append(child_id)
                elif isinstance(children_raw, list):
                    for item in children_raw:
                        if isinstance(item, str):
                            child_ids.append(item)
                        elif isinstance(item, dict):
                            child_id = self._flatten_and_collect(item, collected)
                            if child_id:
                                child_ids.append(child_id)

            if child_ids:
                flat_node["children"] = child_ids

        # Also handle top-level children (rare, but Nexus might emit them).
        top_children = flat_node.get("children")
        if isinstance(top_children, list) and top_children and not all(
            isinstance(c, str) for c in top_children
        ):
            # Mixed — recurse any object children
            flat_node["children"] = [
                c if isinstance(c, str) else (self._flatten_and_collect(c, collected) or "")
                for c in top_children
            ]
            flat_node["children"] = [c for c in flat_node["children"] if c]

        collected.append(flat_node)
        return node_id

    # ------------------------------------------------------------------
    # Nexus binding resolution: convert {literalString: "xxx"} → "xxx",
    # but preserve {path: "..."} runtime bindings for the frontend.
    # ------------------------------------------------------------------

    _BINDING_UNWRAP_KEYS = frozenset({
        "literalString", "valueString", "valueNumber", "valueBoolean",
    })

    def _resolve_nexus_bindings(
        self, obj: Any
    ) -> Any:
        """Walk a props dict (arbitrarily nested) and unfold Nexus binding
        objects that carry a literal value, while leaving runtime ``path``
        bindings intact so the frontend converter can resolve them.

        Input::

            {"text": {"literalString": "r101 标准间"},
             "user": {"path": "/form/user_name"},
             "action": {"name": "submit", "context": {"a": {"literalString": "x"}}}}

        Output::

            {"text": "r101 标准间",
             "user": {"path": "/form/user_name"},
             "action": {"name": "submit", "context": {"a": "x"}}}

        Mutates the dict in place and returns it for chaining.
        """
        if isinstance(obj, dict):
            for key in list(obj.keys()):
                val = obj[key]
                if isinstance(val, dict):
                    # Is this a Nexus binding with a literal value?
                    literal_key = None
                    for lk in self._BINDING_UNWRAP_KEYS:
                        if lk in val and len(val) == 1:
                            literal_key = lk
                            break
                    if literal_key is not None:
                        obj[key] = val[literal_key]
                    elif "path" in val and len(val) == 1:
                        # Runtime binding — leave as-is for frontend to resolve
                        pass
                    else:
                        # Nested object (e.g. Button action.context) — recurse
                        self._resolve_nexus_bindings(val)
                elif isinstance(val, list):
                    for i, item in enumerate(val):
                        obj[key][i] = self._resolve_nexus_bindings(item)
            return obj
        if isinstance(obj, list):
            return [self._resolve_nexus_bindings(item) for item in obj]
        return obj

    # ------------------------------------------------------------------
    # P2: Button action context auto-completion (fallback for models that
    # don't emit context).
    # ------------------------------------------------------------------

    def _ensure_button_action_context(
        self, agui_ops: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Patch Button action context by auto-collecting dataModel paths.

        Nexus-model A2UI specs frequently omit the ``context`` field on
        Button actions, which means the frontend has nothing to resolve and
        the backend never receives form values on interaction.  This helper
        walks the ops *after* Nexus→AG-UI conversion, collects every path
        from ``updateDataModel`` entries, and injects them as context on
        every Button that lacks one.

        The frontend ``convert.js`` ``mappedAction`` callback already knows
        how to resolve ``{"path": "/foo/bar"}`` bindings against the live
        DataModel, so once we wire the paths here the click payload will
        automatically carry real values.
        """
        # 1. Collect all dataModel paths across every updateDataModel op
        all_paths: List[str] = []
        for op in agui_ops:
            payload = op.get("updateDataModel")
            if not isinstance(payload, dict):
                continue
            for dm_entry in payload.get("contents", []):
                if isinstance(dm_entry, dict):
                    self._collect_datamodel_paths(dm_entry, "", all_paths)

        # DEBUG: Always print what P2 sees
        has_button = any(
            c.get("component") == "Button"
            for op in agui_ops
            if isinstance(op.get("updateComponents"), dict)
            for c in op["updateComponents"].get("components", [])
            if isinstance(c, dict)
        )
        logger.debug(
            "[AgUiEncoder-P2] input: ops=%d, "
            "dataModel_paths=%s, has_Button=%s",
            len(agui_ops), all_paths, has_button,
        )

        if not all_paths:
            logger.debug("[AgUiEncoder-P2] skip: no dataModel paths found")
            return agui_ops

        # 2. Walk every updateComponents op and patch Button actions
        patched_count = 0
        fixed_count = 0
        for op in agui_ops:
            payload = op.get("updateComponents")
            if not isinstance(payload, dict):
                continue
            for comp in payload.get("components", []):
                if not isinstance(comp, dict):
                    continue
                if comp.get("component") != "Button":
                    continue
                props = comp.get("props") or {}
                action = props.get("action")
                if not isinstance(action, dict):
                    continue
                existing_ctx = action.get("context")

                if isinstance(existing_ctx, dict) and existing_ctx:
                    # Model emitted context — but paths may not match dataModel!
                    # e.g. model says "/form/name" but dataModel has "/name".
                    # Try to fix paths by matching the last segment against
                    # known dataModel paths.
                    fixed_ctx = self._fix_context_paths(existing_ctx, all_paths)
                    if fixed_ctx != existing_ctx:
                        action["context"] = fixed_ctx
                        fixed_count += 1
                        logger.debug(
                            "[AgUiEncoder-P2] FIXED context paths for Button %s: "
                            "before=%s → after=%s",
                            comp.get("id"), existing_ctx, fixed_ctx,
                        )
                    continue

                # No context at all — build from all dataModel paths
                new_context: Dict[str, Any] = {}
                for p in all_paths:
                    key = p.split("/")[-1] if p else "field"
                    if not key:
                        key = "field"
                    if key in new_context:
                        key = p.strip("/").replace("/", "_")
                    new_context[key] = {"path": p}
                action["context"] = new_context
                patched_count += 1

        if patched_count or fixed_count:
            logger.debug(
                "[AgUiEncoder-P2] SUMMARY: patched=%d, "
                "fixed_paths=%d, "
                "dataModel_paths=%s",
                patched_count, fixed_count, all_paths,
            )

        # DEBUG: Dump final Button actions to confirm P2 fix propagated
        try:
            for op in agui_ops:
                payload = op.get("updateComponents")
                if not isinstance(payload, dict):
                    continue
                for comp in payload.get("components", []):
                    if isinstance(comp, dict) and comp.get("component") == "Button":
                        action = (comp.get("props") or {}).get("action", {})
                        logger.debug(
                            "[AgUiEncoder-P2-FINAL] Button=%s "
                            "action.context=%s",
                            comp.get("id"),
                            json.dumps(action.get("context"), ensure_ascii=False),
                        )
        except Exception:
            pass

        return agui_ops

    @staticmethod
    def _fix_context_paths(
        context: Dict[str, Any], known_paths: List[str]
    ) -> Dict[str, Any]:
        """Fix model-emitted context paths to match actual dataModel paths.

        Nexus models frequently guess the path prefix (e.g. emit
        ``/form/name`` when the dataModel actually has ``/name``).  This
        helper walks every binding in the context and, if the referenced
        path doesn't exist in ``known_paths``, tries to find a match by
        stripping leading segments until it hits a known path.

        If no match is found, the original path is kept as-is (better to
        send a slightly-wrong path than to drop the field entirely).
        """
        if not known_paths:
            return context

        # Build a lookup by last segment for fast matching
        last_seg_to_path: Dict[str, str] = {}
        for p in known_paths:
            seg = p.split("/")[-1] if p else ""
            if seg and seg not in last_seg_to_path:
                last_seg_to_path[seg] = p

        result: Dict[str, Any] = {}
        for key, value in context.items():
            if isinstance(value, dict) and "path" in value and isinstance(value["path"], str):
                orig_path = value["path"]
                if orig_path in known_paths:
                    # Already correct — keep as-is
                    result[key] = value
                else:
                    # Try to fix by matching last segment
                    last_seg = orig_path.split("/")[-1] if orig_path else ""
                    fixed_path = last_seg_to_path.get(last_seg, orig_path)
                    if fixed_path != orig_path:
                        result[key] = {**value, "path": fixed_path}
                    else:
                        # No match found — keep original, hope frontend resolves
                        result[key] = value
            else:
                result[key] = value
        return result

    @staticmethod
    def _collect_datamodel_paths(
        dm_entry: Dict[str, Any], prefix: str, out: List[str]
    ) -> None:
        """Recursively extract JSON Pointer paths from a dataModel entry.

        Handles both flat ``{key, valueString}`` entries and nested
        ``{key, valueMap: [{key, valueString}]}`` (recursive maps).

        Produces absolute paths like ``/booking/partySize`` so the
        frontend converter can resolve them from the live DataModel.
        """
        key = dm_entry.get("key")
        full_path = f"{prefix}/{key}" if key else prefix
        if key and full_path not in out:
            out.append(full_path)

        value_map = dm_entry.get("valueMap")
        if isinstance(value_map, list):
            for child in value_map:
                if isinstance(child, dict):
                    AgUiEventEncoder._collect_datamodel_paths(child, full_path, out)

        # Also traverse valueList if present
        value_list = dm_entry.get("valueList")
        if isinstance(value_list, list):
            for i, child in enumerate(value_list):
                if isinstance(child, dict):
                    AgUiEventEncoder._collect_datamodel_paths(child, f"{full_path}/{i}", out)

    def flush_final_answer_buffer(
        self, subagent_run_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Force-emit any text still lingering in ``_final_answer_buffer``.

        Called **once** in ``run.py``'s ``finally`` block before draining open
        messages and emitting ``RUN_FINISHED``.  If the buffer ends with an
        incomplete ``<a2ui-json>`` tag (model got cut off mid-tag), we still
        emit the accumulated text up to that point as plain text, then drop
        the unclosed tag — better to lose one malformed operation than to
        corrupt the AG-UI state machine by hanging RUN_FINISHED.
        """
        events: List[Dict[str, Any]] = []
        buf = self._final_answer_buffer
        if not buf:
            return events

        close_idx = buf.find(self._A2UI_CLOSE)
        if close_idx == -1:
            # No close tag at all — emit everything as plain text
            events.extend(self._encode_text_delta(buf, subagent_run_id))
        else:
            # Close tag exists somewhere; _encode_a2ui_tagged_text will find
            # complete pairs and emit them properly.  Just re-enter the
            # normal flow by re-feeding "" (buffer is already accumulated).
            events.extend(self._encode_a2ui_tagged_text("", subagent_run_id))

        # Emit whatever is still left (trailing unclosed tag — plain text it)
        if self._final_answer_buffer:
            leftover = self._final_answer_buffer
            self._final_answer_buffer = ""
            events.extend(self._encode_text_delta(leftover, subagent_run_id))
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
            "name": str(agent_name),
            "timestamp": _ts_ms(),
        }

    def _encode_subagent_end(
        self, subagent_run_id: Optional[str]
    ) -> Dict[str, Any]:
        return {
            "type": AGUI_SUBAGENT_FINISHED,
            "subagentRunId": subagent_run_id or _gen_id("subrun"),
            "outcome": {"type": "success"},
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
            "stepName": self._current_step_msg_id,
            "timestamp": _ts_ms(),
        }
        if subagent_run_id:
            event["subagentRunId"] = subagent_run_id
        return event

    def _encode_activity_snapshot(
        self, content: Any, subagent_run_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """A2UI / CARD chunk → AG-UI ACTIVITY_SNAPSHOT.

        Accepts three shapes and dispatches accordingly:

        1. Already a full AG-UI ACTIVITY_SNAPSHOT dict (``type`` + ``activityType`` +
           ``content.a2ui_operations`` emitted by the A2UI layer).  Forward as-is.
        2. A raw Nexus A2UI surface payload dict (no wrapping).  Wrap into a
           minimal ACTIVITY_SNAPSHOT so useAgUiRuntime picks it up.
        3. Any other shape — treat as opaque Nexus card content and emit as
           RAW so the frontend adapter can decide what to do with it.
        """
        if isinstance(content, str):
            # Fallback: if the string contains <a2ui-json> tags, extract
            # the inner JSON and use _encode_a2ui_json_content (which has
            # the proven raw_decode + Nexus→AG-UI conversion pipeline).
            if self._A2UI_OPEN in content:
                open_idx = content.find(self._A2UI_OPEN)
                close_idx = content.find(self._A2UI_CLOSE, open_idx + len(self._A2UI_OPEN))
                if close_idx > open_idx:
                    inner = content[open_idx + len(self._A2UI_OPEN):close_idx]
                    logger.debug(
                        "[AgUiEncoder] _encode_activity_snapshot: detected <a2ui-json> "
                        "tags in string, forwarding to _encode_a2ui_json_content, "
                        "inner=%d chars",
                        len(inner),
                    )
                    return self._encode_a2ui_json_content(inner, subagent_run_id)

            try:
                content = json.loads(content)
                logger.debug(
                    "[AgUiEncoder] _encode_activity_snapshot: JSON parsed, type=%s",
                    type(content).__name__,
                )
            except (json.JSONDecodeError, TypeError) as e:
                logger.debug(
                    "[AgUiEncoder] _encode_activity_snapshot: JSON parse FAILED → RAW, error=%s",
                    e,
                )
                # Plain string — emit as RAW
                return [self._raw_event("card", content, subagent_run_id)]

        if not isinstance(content, dict):
            return [self._raw_event("card", str(content), subagent_run_id)]

        # 1. Already AG-UI-shaped: {"type": "ACTIVITY_SNAPSHOT", ...}
        if content.get("type") == AGUI_ACTIVITY_SNAPSHOT:
            logger.debug(
                "[AgUiEncoder] _encode_activity_snapshot: case 1 (ACTIVITY_SNAPSHOT), "
                "activityType=%s",
                content.get("activityType"),
            )
            event = dict(content)
            if "messageId" not in event:
                event["messageId"] = _gen_id("a2ui")
            if "timestamp" not in event:
                event["timestamp"] = _ts_ms()
            if "replace" not in event:
                event["replace"] = True
            if subagent_run_id and "subagentRunId" not in event:
                event["subagentRunId"] = subagent_run_id

            # Nexus→AG-UI op conversion + flatten: SDK may send ops with
            # Nexus-format keys (beginRendering, surfaceUpdate) and nested
            # component trees.  Run them through _convert_nexus_a2ui_op to
            # ensure the frontend reducer gets proper AG-UI flat format.
            ops = event.get("content", {}).get("a2ui_operations")
            if isinstance(ops, list) and ops:
                has_nexus_keys = any(
                    any(k in op for k in self._NEXUS_TO_AGUI_OP if k not in ("createSurface", "updateComponents", "updateDataModel", "deleteSurface"))
                    for op in ops if isinstance(op, dict)
                )
                has_nested_component = False
                for op in ops:
                    if not isinstance(op, dict):
                        continue
                    payload = next((op[k] for k in op if k != "version"), None)
                    if isinstance(payload, dict):
                        components = payload.get("components")
                        if isinstance(components, list):
                            for comp in components:
                                if isinstance(comp, dict) and isinstance(comp.get("component"), dict):
                                    has_nested_component = True
                                    break

                # Always run P2 — SDK sends AG-UI flat ops (has_nexus_keys=False,
                # has_nested_component=False) but Button actions still need
                # context auto-completion.  Only run Nexus conversion if needed.
                if has_nexus_keys or has_nested_component:
                    logger.debug(
                        "[AgUiEncoder] _encode_activity_snapshot: converting Nexus-format ops "
                        "(has_nexus_keys=%s, has_nested_component=%s)",
                        has_nexus_keys, has_nested_component,
                    )
                    ops = [
                        self._convert_nexus_a2ui_op(op) for op in ops
                    ]

                # P2: Auto-complete Button action context from dataModel
                event["content"]["a2ui_operations"] = self._ensure_button_action_context(ops)

            return [event]

        # 2. Raw A2UI surface payload — wrap into ACTIVITY_SNAPSHOT
        #    Heuristic: has "a2ui_operations" or looks like a surface payload
        has_ops = "a2ui_operations" in content
        has_surface = any(
            k in content
            for k in ("surfaceId", "createSurface", "updateComponents", "updateDataModel")
        )
        if has_ops or has_surface:
            wrapped = {
                "type": AGUI_ACTIVITY_SNAPSHOT,
                "messageId": content.get("messageId") or _gen_id("a2ui"),
                "activityType": "a2ui-surface",
                "replace": True,
                "content": (
                    {"a2ui_operations": content["a2ui_operations"]}
                    if has_ops
                    else {"a2ui_operations": [content]}
                ),
                "timestamp": _ts_ms(),
            }
            if subagent_run_id:
                wrapped["subagentRunId"] = subagent_run_id
            return [wrapped]

        # 3. Nexus custom card — emit as RAW so frontend adapter handles it
        return [self._raw_event("card", content, subagent_run_id)]

    def _state_delta_event(
        self, state_key: str, content: Any, subagent_run_id: Optional[str]
    ) -> Dict[str, Any]:
        """AG-UI STATE_DELTA requires ``delta`` to be an array of patches.
        We wrap our Nexus {key: value} object as a single-element array
        so the schema validates cleanly."""
        return {
            "type": AGUI_STATE_DELTA,
            "delta": [{state_key: content}],
            "timestamp": _ts_ms(),
            **({"subagentRunId": subagent_run_id} if subagent_run_id else {}),
        }

    def _raw_event(
        self, source: str, content: Any, subagent_run_id: Optional[str]
    ) -> Dict[str, Any]:
        """Emit a ``RAW`` AG-UI event — the standard way to carry opaque
        domain-specific payloads that the runtime does not interpret natively.

        ``RAW`` carries ``event`` (the opaque payload) and optional ``source``
        (a string tag so middleware / frontend code can route it).  This
        replaces the previous ``CUSTOM`` emission which used wrong field
        names (``source``/``event`` instead of the official ``name``/``value``).
        """
        event: Dict[str, Any] = {
            "type": AGUI_RAW,
            "event": content,
            "source": source,
            "timestamp": _ts_ms(),
        }
        if subagent_run_id:
            event["subagentRunId"] = subagent_run_id
        return event

    # Legacy fallback — only used for truly unknown A2UI payloads
    def _custom_event(
        self, source: str, content: Any, subagent_run_id: Optional[str]
    ) -> Dict[str, Any]:
        """Legacy ``CUSTOM`` event emitter kept for backward compatibility.

        Prefer :meth:`_raw_event` for new code — it produces a well-formed
        AG-UI ``RAW`` event that the runtime can pass through to subscribers.
        """
        return {
            "type": AGUI_CUSTOM,
            "name": source,
            "value": content,
            "timestamp": _ts_ms(),
            **({"subagentRunId": subagent_run_id} if subagent_run_id else {}),
        }
