# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Project engine observations onto the established Nexent client protocol."""

import json


def _native(event):
    return (event.get("schema_version") == 1 and event.get("runtime_mode") == "native_agent"
            and isinstance(event.get("turn_id"), str))


def _converted(event, kind, **fields):
    # Internal envelope markers must not cause clients to adapt an event again.
    return {**{k: v for k, v in event.items() if k not in {
        "schema_version", "runtime_mode", "agent_core", "sequence", "final_content",
        "final_block_ids", "status", "end_reason", "error",
    }}, "type": kind, **fields}


class NexentOutputAdapter:
    """Keep validation and invocation state on the server, never in a UI consumer."""

    def __init__(self):
        self.runs = {}
        self.invocations = {}
        self.duplicates = set()
        self.closed = False
        self.root = None

    @staticmethod
    def _status(run):
        return "failed" if run.get("invalid") else (run.get("result") or {}).get("status", "failed")

    def _complete(self, run):
        if run.get("emitted"):
            return []
        run["emitted"] = True
        result = run.get("result") or {}
        source = result or run["source"]
        status = self._status(run)
        if status == "completed":
            if result.get("end_reason") == "awaiting_input":
                return []
            ids = result.get("final_block_ids", [])
            return [_converted(source, "final_answer", content=result.get("final_content", ""),
                answer_phase="complete", reclassify_step=True,
                step_id=(run["blocks"].get(ids[0]) or run["step"]) if ids else run["step"])]
        if status == "stopped":
            return []
        error = result.get("error") if isinstance(result.get("error"), dict) else {}
        return [_converted(source, "error", content=run.get("invalid") or error.get("safe_message")
                           or result.get("end_reason") or "NEXENT_TERMINAL_MISSING")]

    def push(self, event):
        if not _native(event):
            run = self.invocations.get(event.get("invocation_id") or "")
            kind, call = event.get("type"), event.get("tool_call_id")
            if run and kind in {"tool", "tool-call"} and call:
                key = json.dumps([run["source"]["turn_id"], event.get("invocation_id") or "", call],
                                 ensure_ascii=False, separators=(",", ":"))
                run["calls"][call] = key
                return [_converted(event, kind, tool_call_id=key)]
            if run and (kind == "final_answer" or kind == "token_count" and '"step_number"' not in event.get("content", "")):
                return []
            if kind == "execution_logs" and self._duplicate(event) in self.duplicates:
                return []
            if kind == "subagent_end":
                try:
                    payload = json.loads(event.get("content", ""))
                except (TypeError, ValueError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                child = self.invocations.get(payload.get("invocation_id") or event.get("invocation_id"))
                if child:
                    return [*self._complete(child), {**event, "content": json.dumps(
                        {**payload, "status": self._status(child)}, ensure_ascii=False)}]
            if run and call in run["calls"]:
                return [_converted(event, kind, tool_call_id=run["calls"][call])]
            return [event]
        identity = event["turn_id"]
        if identity not in self.runs:
            run = {"source": event, "sequence": 0, "blocks": {}, "calls": {}, "results": set(),
                   "step": event.get("step_id") or identity}
            self.runs[identity] = run
            self.invocations[event.get("invocation_id") or ""] = run
            if not event.get("invocation_id"):
                self.root = run
        run = self.runs[identity]
        if self.closed or run.get("result") or run.get("emitted"):
            run["invalid"] = "NEXENT_OUTPUT_AFTER_TERMINAL"
            return []
        sequence = event.get("sequence")
        if type(sequence) is not int or sequence <= run["sequence"]:
            run["invalid"] = "NEXENT_OUTPUT_ORDER_INVALID"
            return []
        run["sequence"] = sequence
        kind = event.get("type")
        if kind == "step_count":
            run["step"] = event.get("step_id") or f"{identity}:step:{event.get('content', '')}"
            return [_converted(event, kind, step_id=run["step"])]
        if kind in {"model_output", "model_output_deep_thinking"}:
            block = event.get("block_id") or event.get("step_id") or run["step"]
            first = block not in run["blocks"]
            step = run["blocks"].setdefault(block, event.get("step_id") or block)
            boundary = ([_converted(event, "step_count", content="", step_id=step)]
                        if first and run["step"] != step else [])
            run["step"] = step
            return [*boundary, _converted(event, "model_output_thinking" if kind == "model_output" else kind,
                                          step_id=step)]
        if kind == "tool":
            local = event.get("local_call_id") or event.get("tool_call_id")
            if not local or local in run["calls"]:
                run["invalid"] = "NEXENT_TOOL_ID_INVALID"
                return []
            key = json.dumps([identity, event.get("invocation_id") or "", local], ensure_ascii=False,
                             separators=(",", ":"))
            run["calls"][local] = key
            return [_converted(event, kind, tool_call_id=key)]
        if kind == "tool_result":
            key = run["calls"].get(event.get("local_call_id") or event.get("tool_call_id"))
            if not key or key in run["results"]:
                run["invalid"] = "NEXENT_TOOL_RESULT_UNPAIRED"
                return []
            run["results"].add(key)
            output = _converted(event, "execution_logs", content=str(event.get("result", event.get("content", ""))),
                                tool_call_id=key)
            self.duplicates.add(self._duplicate(output))
            return [output]
        if kind == "step_observation":
            usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
            capacity = event.get("context_capacity") if isinstance(event.get("context_capacity"), dict) else {}
            warning = ([_converted(event, "warning", content=event["step_error"].get("safe_message")
                        or event["step_error"].get("category") or "Model step failed")]
                       if isinstance(event.get("step_error"), dict) else [])
            return [*warning, _converted(event, "token_count", content=json.dumps({
                "step_number": event.get("step_number"), "duration": event.get("duration"),
                "step_input_tokens": usage.get("input_tokens"), "step_output_tokens": usage.get("output_tokens"),
                "total_output_tokens": usage.get("output_tokens"),
                **{key: capacity.get(key) for key in ("context_window_tokens", "token_threshold",
                    "effective_input_limit_tokens", "context_processing_mode")},
            }, ensure_ascii=False))]
        if kind == "run_terminal":
            from nexent.core.agents.contracts.output import RunResult

            try:
                result = RunResult.model_validate({key: event[key] for key in (
                    "turn_id", "status", "end_reason", "final_content", "final_block_ids", "error") if key in event})
                if result.status == "completed":
                    if result.end_reason == "awaiting_input":
                        if result.final_content or result.final_block_ids:
                            raise ValueError("Waiting for input cannot confirm an answer")
                    elif not result.final_content.strip():
                        raise ValueError("Completed answers must not be empty")
            except ValueError:
                run["invalid"] = "NEXENT_TERMINAL_INVALID"
            run["result"] = event
            return []
        return [_converted(event, kind)]

    @staticmethod
    def _duplicate(event):
        return event.get("invocation_id"), event.get("type"), event.get("content")

    def close(self, status=None):
        if self.closed:
            return []
        self.closed = True
        for run in self.runs.values():
            if not run.get("result"):
                run["invalid"] = "NEXENT_TERMINAL_MISSING"
            if run is self.root and status == "failed" and self._status(run) != "failed":
                run["invalid"] = "NEXENT_PERSISTED_RUN_FAILED"
            if run is self.root and status == "stopped":
                run.pop("invalid", None)
                run["result"] = {**run["source"], "status": "stopped"}
        return [event for run in self.runs.values() for event in self._complete(run)]

    @property
    def status(self):
        return self._status(self.root) if self.root is not None else None


def normalize_nexent_history(events, status=None):
    """Decode saved envelopes only; never interpret JSON inside ordinary model text."""
    adapter = NexentOutputAdapter()
    output = []
    for event in events:
        event = dict(event)
        try:
            nested = json.loads(event.get("content", ""))
        except (ValueError, TypeError):
            nested = None
        if isinstance(nested, dict) and _native(nested) and nested.get("type") == event.get("type"):
            event = {**event, **nested, "unit_index": event.get("unit_index", nested.get("unit_index"))}
        output.extend(adapter.push(event))
    if status not in {"streaming", "pending", "running"}:
        output.extend(adapter.close(status))
    providers = {e.get("tool_call_id"): e["provider_call_id"] for e in output
                 if e.get("type") == "execution_logs" and e.get("provider_call_id")}
    finals = {(e.get("invocation_id"), e.get("step_id")) for e in output
              if e.get("type") == "final_answer" and e.get("reclassify_step")}
    for event in output:
        if event.get("type") == "tool" and not event.get("provider_call_id"):
            event["provider_call_id"] = providers.get(event.get("tool_call_id"))
    return [e for e in output if not (e.get("type") == "model_output_thinking"
            and e.get("block_id") and (e.get("invocation_id"), e.get("step_id")) in finals)], (status if status in {"streaming", "pending", "running"} else adapter.status or status)


class NexentSSEAdapter:
    """Accept complete SSE frames from backend producers without delaying deltas."""

    def __init__(self):
        self.output = NexentOutputAdapter()

    def push(self, frame):
        result = []
        for block in frame.split("\n\n"):
            if not block.strip():
                continue
            if not block.startswith("data:"):
                result.append(block + "\n\n")
                continue
            try:
                event = json.loads(block[5:].strip())
            except (TypeError, ValueError):
                result.append(block + "\n\n")
                continue
            if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                result.append(block + "\n\n")
                continue
            if event["type"] == "done":
                result.extend(self.close())
            result.extend(self.serialize(item) for item in self.output.push(event))
        return result

    @staticmethod
    def serialize(event):
        return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    def close(self, status=None):
        return [self.serialize(event) for event in self.output.close(status)]


async def adapt_nexent_stream(source):
    adapter = NexentSSEAdapter()
    try:
        async for frame in source:
            for public in adapter.push(frame):
                yield public
        for public in adapter.close():
            yield public
    finally:
        await source.aclose()
