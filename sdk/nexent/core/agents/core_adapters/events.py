"""Convert native Jiuwen stream output into Nexent observer messages."""

import json

from ...utils.observer import ProcessType


class JiuwenEventAdapter:
    def __init__(self, observer, agent_name):
        self.observer = observer
        self.agent_name = agent_name
        self.final_answer = None

    def emit(self, chunk):
        kind = getattr(chunk, "type", None)
        payload = getattr(chunk, "payload", None)
        if isinstance(chunk, dict):
            kind, payload = chunk.get("type", kind), chunk.get("payload", payload)
        if kind == "answer":
            if self.final_answer is not None:
                raise RuntimeError("Jiuwen emitted multiple terminal answers")
            if not isinstance(payload, dict) or payload.get("result_type") == "error":
                raise RuntimeError("Jiuwen agent execution failed")
            output = payload.get("output")
            if not isinstance(output, str) or not output.strip():
                raise RuntimeError("Jiuwen returned no final answer")
            self.final_answer = output
        elif kind == "llm_output" and isinstance(payload, dict):
            content = payload.get("content")
            if isinstance(content, str) and content:
                self.observer.add_message(self.agent_name, ProcessType.MODEL_OUTPUT_THINKING, content)
            reasoning = payload.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning:
                self.observer.add_message(self.agent_name, ProcessType.MODEL_OUTPUT_DEEP_THINKING, reasoning)
        elif kind == "context.usage" and isinstance(payload, dict):
            self.observer.add_message(self.agent_name, ProcessType.TOKEN_COUNT, json.dumps(payload))

    def finish(self):
        if self.final_answer is None:
            raise RuntimeError("Jiuwen stream ended without a terminal answer")
        self.observer.add_message(self.agent_name, ProcessType.FINAL_ANSWER, self.final_answer)
