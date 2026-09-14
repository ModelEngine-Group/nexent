"""CoreAgent lifecycle adapter; persistence and human decisions remain host ports."""

import hashlib
import inspect
from copy import deepcopy

from smolagents import Tool
from smolagents.memory import TaskStep

from .clarification import CLARIFICATION_POLICY, ClarificationForm
from .codec import decode_step, encode_step, json_copy
from .contracts import InteractionPort, RecoveryRequired, StepSteered
from .executor import LinearToolExecutor


class AskUserTool(Tool):
    name = "ask_user"
    description = CLARIFICATION_POLICY
    inputs = {
        "questions": {
            "type": "array",
            "description": (
                "1-5 essential questions only, each with unique id, type (text/single_choice/"
                "multiple_choice), title, required (boolean), options ([{id,label}] for choices), "
                "allow_other (boolean for choices), placeholder (optional). Use 2-12 options for choices."
            ),
        },
    }
    output_type = "string"

    def forward(self, questions: list) -> str:
        raise RuntimeError("ask_user requires an application interaction port")


class DurablePlanRepo:
    def __init__(self, port):
        self.port = port

    def save(self, plan_dict, conversation_id=None, user_id=None, status="active"):
        try:
            self.port.save_plan(json_copy(plan_dict))
        except Exception as exc:
            raise RecoveryRequired("Durable plan persistence failed") from exc

    def load(self, conversation_id=None, user_id=None):
        return self.port.load_plan()


class HumanInteractionRuntime:
    preserves_executor = False
    instructions = CLARIFICATION_POLICY + (
        " Executable code must use only linear variable assignments, JSON values, registered tool calls, "
        "and print. Do not use imports, attributes, nested calls, loops, or callbacks. "
        "Use separate steps for complex work. Human approval never replaces resource permissions."
    )

    def __init__(self, port: InteractionPort):
        self.port = port
        self.agent = None
        self.pending_step = None
        self.initial_state = {}
        self.final_verification_round = 0
        self.restored = False
        self.legacy_replay_step = None
        self.suspended = False
        self.steering_ids = []
        self.clarifications = []
        self.clarification_context = []
        self.clarification_context_step = 0
        self.block_has_receipts = False
        self.completed_output = None

    def attach(self, agent):
        from smolagents.default_tools import FinalAnswerTool
        # Arbitrary managed callables and sandbox bridges need separate durable adapters.
        # Reject before the model or any user tool is dispatched.
        if agent.managed_agents:
            raise ValueError("HITL currently requires a root Agent without managed/A2A sub-agents")
        if "ask_user" in agent.tools:
            raise ValueError("The reserved ask_user tool name is already registered")
        if type(agent.tools.get("final_answer")) is not FinalAnswerTool:
            raise ValueError("HITL requires the trusted built-in final_answer tool")
        identities = {}
        for name, tool in agent.tools.items():
            try:
                source = inspect.getsource(type(tool))
            except (OSError, TypeError):
                source = type(tool).__module__ + "." + type(tool).__qualname__
            identities[name] = {"class": type(tool).__module__ + "." + type(tool).__qualname__,
                                "source": hashlib.sha256(source.encode()).hexdigest(),
                                "inputs": tool.inputs, "description": tool.description}
        self.port.bind_executor({"codec": "linear-json-v1", "tools": identities})
        self.agent = agent
        agent.human_interaction = self
        agent.tools["ask_user"] = AskUserTool()
        agent.python_executor = LinearToolExecutor(self)
        if agent.enable_planning:
            agent.plan_repo = DurablePlanRepo(self.port)
            for name in ("create_plan", "update_plan_step"):
                if name in agent.tools:
                    agent.tools[name].plan_repo = agent.plan_repo

    def restore(self):
        data = self.port.checkpoint
        if not data:
            return False
        if data.get("codec") != 1:
            raise RecoveryRequired("Unsupported HITL checkpoint version")
        agent = self.agent
        agent.task = data["task"]
        agent.memory.steps = [decode_step(item, agent.logger) for item in data["memory"]]
        agent._history_step_count = data["history_step_count"]
        agent.step_number = data["step_number"]
        agent.state = json_copy(data["state"])
        agent.python_executor.state = json_copy(data["state"])
        self.initial_state = json_copy(data["state"])
        self.pending_step = decode_step(data["pending_step"], agent.logger) if data["pending_step"] else None
        self.legacy_replay_step = (
            agent.step_number if self.pending_step is not None and data.get("clarification_schema_version", 1) == 1
            else None
        )
        self.final_verification_round = data["final_verification_round"]
        self.steering_ids = data.get("steering_ids", [])
        self.clarifications = data.get("clarifications", [])
        self.clarification_context_step = data.get("clarification_context_step", 0)
        self.clarification_context = data.get("clarification_context", [])
        if "clarification_context" not in data and self.clarifications:
            # Old checkpoints stored a step counter instead of delivered answers.
            # Derive delivery from actual memory, including an answer pending at suspension.
            context = self._clarification_task(self.clarifications)
            if any(isinstance(step, TaskStep) and step.task == context for step in agent.memory.steps):
                self.clarification_context = deepcopy(self.clarifications)
        self.completed_output = data.get("completed_output")
        self.restore_plan()
        self.restored = True
        return True

    def restore_plan(self):
        plan = self.port.load_plan()
        if plan is not None:
            from ..agents.agent_model import AgentPlan
            self.agent.current_plan = AgentPlan.model_validate(plan)
            self.agent.current_step_index = self.agent.current_plan.current_step_index

    def capture(self):
        agent = self.agent
        return json_copy({
            "codec": 1, "task": agent.task, "step_number": agent.step_number,
            "clarification_schema_version": 1 if self.legacy_replay_step == agent.step_number else 2,
            "history_step_count": agent._history_step_count,
            "memory": [encode_step(step) for step in agent.memory.steps],
            # Replay uses the state at the beginning of the current block.
            "state": self.initial_state,
            "pending_step": encode_step(self.pending_step) if self.pending_step else None,
            "final_verification_round": self.final_verification_round, "steering_ids": self.steering_ids,
            "clarifications": self.clarifications,
            "clarification_context": self.clarification_context,
            "clarification_context_step": self.clarification_context_step,
            "completed_output": self.completed_output,
        })

    def _record_clarification(self, question, answer):
        normalized = question.strip()
        current = {"question": normalized, "answer": answer}
        for index, item in enumerate(self.clarifications):
            if item["question"] == normalized:
                self.clarifications[index] = current
                return
        self.clarifications.append(current)

    @staticmethod
    def _clarification_task(answers):
        lines = ["Current-run human clarification (authoritative user input):"]
        for item in answers:
            lines.extend([f"Question: {item['question']}", f"Answer: {item['answer']}"])
        lines.append("Use these answers for the current task. Do not call ask_user again for the same information.")
        return "\n".join(lines)

    def _inject_clarification_context(self):
        # Answers remain in current-run memory. Re-appending them on every step
        # creates new user tasks and can supersede newer steering with old intent.
        changed = [item for item in self.clarifications if item not in self.clarification_context]
        if not changed:
            return
        self.agent.memory.steps.append(TaskStep(task=self._clarification_task(changed)))
        self.clarification_context = deepcopy(self.clarifications)
        self.clarification_context_step = self.agent.step_number

    def safe_boundary(self):
        self._inject_clarification_context()
        feedback = self.port.boundary(self.capture())
        if feedback:
            self.steering_ids.extend(feedback.get("request_ids", [feedback["request_id"]]))
            interrupted = self.pending_step is not None
            if interrupted:
                # Keep completed tool evidence, abandon only the unexecuted suffix.
                self.pending_step.observations = feedback.get("completed_actions", "")
                self.pending_step.code_action = None
                self.agent.memory.steps.append(self.pending_step)
                self.agent.step_number += 1
                self.pending_step = None
                self.initial_state = json_copy(self.agent.python_executor.state)
            self.agent.memory.steps.append(TaskStep(task=(
                "User steering for this same run (does not grant tool authorization):\n" + feedback["text"]
                + "\nRe-evaluate pending actions and revise the plan if needed. Do not repeat completed actions."
            )))
            self.port.save_checkpoint(self.capture())
            return interrupted
        return False

    def start_step(self, step):
        if step is not self.pending_step:
            self.legacy_replay_step = None
        self.block_has_receipts = False
        self.pending_step = step
        self.initial_state = json_copy(self.agent.python_executor.state)
        self._inject_clarification_context()
        if self.safe_boundary():
            raise StepSteered()
        self.port.save_checkpoint(self.capture())

    def generated(self, step):
        self.pending_step = step
        self.port.save_checkpoint(self.capture())
        if self.safe_boundary():
            raise StepSteered()

    def completed_step(self, final_verification_round, final_answer=None):
        self.legacy_replay_step = None
        self.pending_step = None
        self.final_verification_round = final_verification_round
        self.completed_output = final_answer
        self.initial_state = json_copy(self.agent.python_executor.state)
        self.port.save_checkpoint(self.capture())

    def complete_run(self, output):
        self.completed_output = output
        self.port.save_checkpoint(self.capture())

    def prepare_completion(self):
        close = getattr(self.port, "close_steering", None)
        if close is not None and not close(self.capture()):
            if self.pending_step is not None:
                self.pending_step.is_final_answer = False
            self.safe_boundary()
            return False
        return True

    def call(self, index, name, args, kwargs, tool):
        inputs = getattr(tool, "inputs", {})
        if (name == "ask_user" and "questions" not in kwargs
                and self.legacy_replay_step == self.agent.step_number
                and ("question" in kwargs or (args and isinstance(args[0], str)))):
            # Frozen legacy code can resume, but new model output only sees the structured schema.
            inputs = {"question": {"type": "string"},
                      "options": {"type": "array", "nullable": True},
                      "allow_other": {"type": "boolean", "nullable": True}}
        keys = list(inputs)
        if len(args) > len(keys) or any(key not in inputs for key in kwargs):
            raise ValueError("Tool arguments do not match its registered schema")
        arguments = dict(kwargs)
        for key, value in zip(keys, args):
            if key in arguments:
                raise ValueError("Duplicate tool argument")
            arguments[key] = value
        for key, spec in inputs.items():
            if key not in arguments and not spec.get("nullable"):
                raise ValueError(f"Missing required tool argument: {key}")
            if key not in arguments:
                continue
            value = arguments[key]
            if value is None and spec.get("nullable"):
                continue
            expected = {"string": (str,), "integer": (int,), "number": (int, float),
                        "boolean": (bool,), "object": (dict,), "array": (list,), "null": (type(None),)}
            kind = spec.get("type", "any")
            if kind != "any" and (kind not in expected or type(value) not in expected[kind]):
                raise ValueError(f"Tool argument {key} does not match its registered JSON type")
        engine = getattr(self.agent.verification_controller, "guardrail_engine", None)
        if engine:
            decision = engine.check_tool_args(args=(), kwargs=arguments)
            if decision.effective_action in {"block", "terminate"}:
                raise ValueError("Tool input was blocked by the content guardrail")
            if decision.effective_action == "mask" and decision.masked_kwargs is not None:
                arguments = decision.masked_kwargs
        arguments = json_copy(arguments)
        interaction = None
        if name == "ask_user":
            questions = arguments.get("questions")
            question = arguments.get("question")
            options = arguments.get("options") or []
            allow_other = arguments.get("allow_other") is not False
            if questions is not None:
                if question is not None or arguments.get("options"):
                    raise ValueError("Use questions only; do not mix structured and legacy clarification fields")
                form = ClarificationForm.model_validate({"questions": questions})
                interaction = {"kind": "CLARIFICATION", "schema_version": 2, **form.model_dump(mode="json")}
            elif not isinstance(question, str) or not question.strip() or len(question) > 4000:
                raise ValueError("ask_user requires a nonempty question of at most 4000 characters")
            if (not isinstance(options, list) or len(options) > 12
                    or any(not isinstance(item, str) or not item.strip() or len(item) > 300 for item in options)
                    or len(set(options)) != len(options)):
                raise ValueError("ask_user options must be distinct nonempty strings")
            interaction = interaction or {
                "kind": "CLARIFICATION",
                "question": question,
                "options": options,
                "allow_other": allow_other,
            }
        slot = f"{self.agent.step_number}:{index}"
        dispatch = self.port.dispatch(slot, name, arguments, interaction=interaction)
        if dispatch["status"] == "steered":
            self.safe_boundary()
            raise StepSteered()
        if dispatch["status"] == "replay":
            self.block_has_receipts = True
            self.restore_plan()
            result = json_copy(dispatch["result"])
            if name == "ask_user":
                title = arguments.get("question") or "\n".join(item["title"] for item in interaction["questions"])
                self._record_clarification(title, result)
            return result
        try:
            result = tool(**deepcopy(dispatch["arguments"]))
        except Exception as exc:
            self.port.receipt(slot, None, uncertain=True)
            raise RecoveryRequired("Tool outcome is uncertain; automatic retry is forbidden") from exc
        try:
            result = json_copy(result)
        except (TypeError, ValueError) as exc:
            self.port.receipt(slot, None, uncertain=True)
            raise RecoveryRequired("Executed tool result needs an unsupported artifact codec") from exc
        self.port.receipt(slot, result)
        self.block_has_receipts = True
        return result
