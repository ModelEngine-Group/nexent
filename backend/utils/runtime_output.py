"""Validate the explicit root result without inferring success from stream EOF."""

from nexent.core.agent_runtime_support.output import RunResult


def is_runtime_event(event):
    return (event.get("schema_version") == 1 and event.get("runtime_mode") == "native_agent"
            and event.get("agent_core") == "jiuwen")


class RuntimeOutputState:
    def __init__(self, required=False):
        self.required = required
        self.result = None
        self.invalid = False

    def observe(self, event):
        if not is_runtime_event(event) or event.get("invocation_id"):
            return
        self.required = True
        if self.result is not None:
            self.invalid = True
        if event.get("type") == "run_terminal":
            try:
                self.result = RunResult.model_validate({key: event[key] for key in (
                    "turn_id", "status", "end_reason", "final_content", "final_block_ids", "error",
                ) if key in event})
            except ValueError:
                self.invalid = True

    @property
    def status(self):
        return self.result.status if self.result is not None and not self.invalid else "failed"

    @property
    def final_content(self):
        return self.result.final_content if self.status == "completed" else ""
