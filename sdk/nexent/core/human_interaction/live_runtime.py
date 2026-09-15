"""In-process human interaction without replacing the Agent's native executor.

Python objects, sandbox kernels and attachment workspaces stay in their original
runtime. Only interaction decisions are durable; a lost native continuation must
never be reconstructed by replaying potentially effectful code.
"""

import json
from threading import Lock

from pydantic import ValidationError
from smolagents.memory import TaskStep

from .clarification import CLARIFICATION_POLICY, ClarificationForm
from .contracts import RecoveryRequired, RunTerminated, StepSteered
from .runtime import AskUserTool, HumanInteractionRuntime


class LiveAskUserTool(AskUserTool):
    _nexent_execute_on_host = True
    emit_tool_event = False

    def __init__(self, runtime):
        self.runtime = runtime
        super().__init__()

    def forward(self, questions: list) -> str:
        try:
            return self.runtime.ask(questions)
        except RunTerminated as exc:
            # Remote tool bridges transport ordinary exceptions, not control signals.
            self.runtime.agent.stop_event.set()
            raise RuntimeError("The user interaction has ended") from exc


class LiveHumanInteractionRuntime(HumanInteractionRuntime):
    preserves_executor = True
    instructions = CLARIFICATION_POLICY

    def __init__(self, port):
        super().__init__(port)
        self._ask_index = 0
        self._ask_lock = Lock()
        self.steering_interrupt = False

    def attach(self, agent):
        self.agent = agent
        # Preserve existing custom tools while allocating an unambiguous interaction name.
        name = "ask_user"
        while name in agent.tools:
            name = "nexent_" + name
        self.instructions = CLARIFICATION_POLICY.replace("ask_user", name)
        self.port.bind_executor({"codec": "native-live-v1"})
        agent.human_interaction = self
        tool = LiveAskUserTool(self)
        tool.name = name
        tool.description = self.instructions
        agent.tools[name] = tool

    def restore(self):
        if self.port.checkpoint:
            raise RecoveryRequired("A native execution cannot be automatically replayed after worker loss")
        return False

    def capture(self):
        # Do not serialize images, credentials, Python objects or sandbox state.
        return {"codec": "native-live-v1", "steering_ids": list(self.steering_ids)}

    def safe_boundary(self):
        self._inject_clarification_context()
        feedback = self.port.boundary(self.capture())
        if not feedback:
            return False
        self.steering_ids.extend(feedback.get("request_ids", [feedback["request_id"]]))
        interrupted = self.pending_step is not None
        if interrupted:
            # Retain actual observations from the completed native code block.
            self.agent.memory.steps.append(self.pending_step)
            self.agent.step_number += 1
            self.pending_step = None
        self.agent.memory.steps.append(TaskStep(task=(
            "User steering for this same run (does not grant tool authorization):\n" + feedback["text"]
            + "\nContinue with this intent. Keep completed results; do not repeat completed external actions."
        )))
        self.port.save_checkpoint(self.capture())
        return interrupted

    def start_step(self, step):
        self.pending_step = step
        self._inject_clarification_context()
        if self.safe_boundary():
            raise StepSteered()
        self.port.save_checkpoint(self.capture())

    def completed_step(self, final_verification_round, final_answer=None):
        self.pending_step = None
        self.final_verification_round = final_verification_round
        self.port.save_checkpoint(self.capture())

    def complete_run(self, output):
        self.port.save_checkpoint(self.capture())

    def ask(self, questions):
        try:
            form = ClarificationForm.model_validate({"questions": questions})
        except ValidationError:
            # Malformed model output is repairable tool feedback, not a chat failure.
            return json.dumps({"status": "invalid_clarification", "instruction": (
                "No card was created. If essential input is still missing, retry with 1-5 concise questions. "
                "Each has a unique id, type (text/single_choice/multiple_choice), title and required. "
                "Choice options [{id,label}] and allow_other belong directly on the question. "
                "Do not include executable fields or explain the protocol error to the user."
            )})
        interaction = {"kind": "CLARIFICATION", "schema_version": 2, **form.model_dump(mode="json")}
        # Parallel tool helpers must not produce competing cards or duplicate slots.
        with self._ask_lock:
            slot = f"ask:{self._ask_index}"
            self._ask_index += 1
            result = self.port.dispatch(slot, "ask_user", {"questions": questions}, interaction=interaction)
            if result["status"] == "steered":
                # Stop the old code suffix through both local and remote executors.
                # CoreAgent recognizes this flag after the executor transports the exception.
                self.steering_interrupt = True
                raise RuntimeError("User guidance received; interrupt the current code block")
            answer = result["result"]
            self._record_clarification("\n".join(item.title for item in form.questions), answer)
            return answer
