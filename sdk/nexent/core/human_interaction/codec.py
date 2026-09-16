"""Explicit, versioned JSON codecs. Never deserialize executable object graphs."""

import json
from dataclasses import asdict

from smolagents.memory import ActionStep, TaskStep, ToolCall
from smolagents.monitoring import Timing, TokenUsage
from smolagents.utils import AgentExecutionError


MAX_CHECKPOINT_BYTES = 2 * 1024 * 1024


def json_copy(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_CHECKPOINT_BYTES:
        raise ValueError("HITL JSON payload exceeds the checkpoint limit")
    return json.loads(encoded)


def encode_step(step):
    if isinstance(step, TaskStep):
        if step.task_images:
            raise ValueError("Image objects require an artifact codec before durable execution")
        return {"kind": "task", "task": step.task}
    if not isinstance(step, ActionStep) or step.observations_images:
        raise ValueError("Unsupported durable memory step")
    return json_copy({
        "kind": "action", "step_number": step.step_number,
        "timing": {"start_time": step.timing.start_time, "end_time": step.timing.end_time},
        "model_output": step.model_output, "code_action": step.code_action,
        "observations": step.observations, "action_output": step.action_output,
        "token_usage": {"input_tokens": step.token_usage.input_tokens,
                        "output_tokens": step.token_usage.output_tokens} if step.token_usage else None,
        "tool_calls": [asdict(call) for call in step.tool_calls or []],
        "error": str(step.error) if step.error else None, "is_final_answer": step.is_final_answer,
    })


def decode_step(data, logger):
    if data["kind"] == "task":
        return TaskStep(task=data["task"])
    if data["kind"] != "action":
        raise ValueError("Unsupported checkpoint step codec")
    values = {key: value for key, value in data.items() if key != "kind"}
    values["timing"] = Timing(**values["timing"])
    values["token_usage"] = TokenUsage(**values["token_usage"]) if values["token_usage"] else None
    values["tool_calls"] = [ToolCall(**call) for call in values["tool_calls"]]
    values["error"] = AgentExecutionError(values["error"], logger) if values["error"] else None
    return ActionStep(**values)
