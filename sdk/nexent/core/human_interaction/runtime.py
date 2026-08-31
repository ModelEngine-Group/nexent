"""CoreAgent lifecycle adapter; persistence and human decisions remain host ports."""

from copy import deepcopy
import hashlib
import inspect

from smolagents import Tool
from smolagents.memory import TaskStep

from .codec import decode_step, encode_step, json_copy
from .contracts import InteractionPort, RecoveryRequired
from .executor import LinearToolExecutor


class AskUserTool(Tool):
    name = "ask_user"
    description = (
        "Pause the current run to ask the user for missing information or a choice. "
        "Use this proactively when the goal is ambiguous. The validated answer is returned when the run resumes. "
        "Never ask for passwords or credentials."
    )
    inputs = {
        "question": {"type": "string", "description": "A clear question for the user"},
        "options": {"type": "array", "description": "Optional list of distinct choice strings", "nullable": True},
    }
    output_type = "string"

    def forward(self, question: str, options: list | None = None) -> str:
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
    def __init__(self, port: InteractionPort):
        self.port = port
        self.agent = None
        self.pending_step = None
        self.initial_state = {}
        self.final_verification_round = 0
        self.restored = False
        self.suspended = False
        self.steering_ids = []
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
        self.final_verification_round = data["final_verification_round"]
        self.steering_ids = data.get("steering_ids", [])
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
            "history_step_count": agent._history_step_count,
            "memory": [encode_step(step) for step in agent.memory.steps],
            # Replay uses the state at the beginning of the current block.
            "state": self.initial_state,
            "pending_step": encode_step(self.pending_step) if self.pending_step else None,
            "final_verification_round": self.final_verification_round, "steering_ids": self.steering_ids,
            "completed_output": self.completed_output,
        })

    def safe_boundary(self):
        feedback = self.port.boundary(self.capture())
        if feedback:
            self.steering_ids.append(feedback["request_id"])
            self.agent.memory.steps.append(TaskStep(task=(
                "User steering for this same run (does not grant tool authorization):\n" + feedback["text"]
                + "\nRe-evaluate pending actions and revise the plan if needed. Do not repeat completed actions."
            )))
            if self.pending_step is not None:
                # Keep completed tool evidence, abandon only the unexecuted suffix.
                self.pending_step.observations = feedback.get("completed_actions", "")
                self.pending_step.code_action = None
                self.agent.memory.steps.append(self.pending_step)
                self.agent.step_number += 1
                self.pending_step = None
                self.initial_state = json_copy(self.agent.python_executor.state)
                self.port.save_checkpoint(self.capture())
                return True
            self.port.save_checkpoint(self.capture())
        return False

    def start_step(self, step):
        self.block_has_receipts = False
        self.pending_step = step
        self.initial_state = json_copy(self.agent.python_executor.state)
        self.safe_boundary()
        self.port.save_checkpoint(self.capture())

    def generated(self, step):
        self.pending_step = step
        self.port.save_checkpoint(self.capture())
        self.safe_boundary()

    def completed_step(self, final_verification_round, final_answer=None):
        self.pending_step = None
        self.final_verification_round = final_verification_round
        self.completed_output = final_answer
        self.initial_state = json_copy(self.agent.python_executor.state)
        self.port.save_checkpoint(self.capture())

    def complete_run(self, output):
        self.completed_output = output
        self.port.save_checkpoint(self.capture())

    def call(self, index, name, args, kwargs, tool):
        inputs = getattr(tool, "inputs", {})
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
            question = arguments.get("question")
            options = arguments.get("options") or []
            if not isinstance(question, str) or not question.strip() or len(question) > 4000:
                raise ValueError("ask_user requires a nonempty question of at most 4000 characters")
            if (not isinstance(options, list) or len(options) > 12
                    or any(not isinstance(item, str) or not item.strip() or len(item) > 300 for item in options)
                    or len(set(options)) != len(options)):
                raise ValueError("ask_user options must be distinct nonempty strings")
            interaction = {"kind": "CLARIFICATION", "question": question, "options": options}
        slot = f"{self.agent.step_number}:{index}"
        dispatch = self.port.dispatch(slot, name, arguments, interaction=interaction)
        if dispatch["status"] == "replay":
            self.block_has_receipts = True
            self.restore_plan()
            return json_copy(dispatch["result"])
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
