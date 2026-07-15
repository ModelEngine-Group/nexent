"""Unit tests for the v1.4 planing methods on CoreAgent.

Scope is narrow: only the plan-related instance methods
(``_on_plan_created``, ``_on_step_updated``, ``_advance_current_index``,
``_implicit_advance_step``, ``_cleanup_plan``, ``_get_conversation_id``,
``_get_user_id``) and the ``enable_planning`` / ``redis_client`` init
branches. We construct a CoreAgent by faking the smolagents CodeAgent parent
so the heavy smolagents machinery never runs.
"""

import importlib.util
import json
import sys
import types
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]


# ---------------------------------------------------------------------------
# Module shim construction
# ---------------------------------------------------------------------------

def _mock_module(name):
    m = ModuleType(name)
    m.__path__ = []
    sys.modules[name] = m
    return m


# -- rich ------------------------------------------------------------
mock_rich = _mock_module("rich")
mock_rich_text = _mock_module("rich.text")
mock_rich_console = _mock_module("rich.console")
mock_rich.Group = MagicMock(side_effect=lambda *args: args)
mock_rich_text.Text = MagicMock()
mock_rich_console.Group = MagicMock(side_effect=lambda *args: args)
mock_rich.console = mock_rich_console
mock_rich.text = mock_rich_text

# -- jinja2 ----------------------------------------------------------
mock_jinja2 = _mock_module("jinja2")
mock_jinja2.Template = MagicMock()
mock_jinja2.StrictUndefined = MagicMock()

# -- nexent monitor (also referenced directly in core_agent) -------------
mock_smolagents = _mock_module("smolagents")

mock_agents = _mock_module("smolagents.agents")
mock_agents.CodeAgent = type("CodeAgent", (), {})
mock_agents.AgentError = type("AgentError", (Exception,), {})
mock_agents.ActionOutput = type("ActionOutput", (), {})
mock_agents.RunResult = type("RunResult", (), {})
mock_agents.handle_agent_output_types = lambda x: x
mock_smolagents.agents = mock_agents
sys.modules["smolagents.agents"] = mock_agents

mock_lpe = _mock_module("smolagents.local_python_executor")
mock_lpe.fix_final_answer_code = lambda x: x
sys.modules["smolagents.local_python_executor"] = mock_lpe

mock_memory = _mock_module("smolagents.memory")
for _n in ("ActionStep", "TaskStep", "SystemPromptStep", "PlanningStep",
           "FinalAnswerStep", "ToolCall", "AgentMemory", "MemoryStep"):
    setattr(mock_memory, _n, type(_n, (), {}))
sys.modules["smolagents.memory"] = mock_memory

mock_models = _mock_module("smolagents.models")
mock_models.ChatMessage = type("ChatMessage", (), {})
mock_models.MessageRole = type("MessageRole", (), {})
mock_models.CODEAGENT_RESPONSE_FORMAT = type("CODEAGENT_RESPONSE_FORMAT", (), {})
sys.modules["smolagents.models"] = mock_models

mock_mon = _mock_module("smolagents.monitoring")
mock_mon.LogLevel = type("LogLevel", (), {
    "WARN": "WARN", "INFO": "INFO", "DEBUG": "DEBUG", "ERROR": "ERROR"
})
mock_mon.Timing = type("Timing", (), {})
mock_mon.YELLOW_HEX = "#fff"
mock_mon.TokenUsage = type("TokenUsage", (), {})
sys.modules["smolagents.monitoring"] = mock_mon

mock_utils = _mock_module("smolagents.utils")
for _n in ("AgentExecutionError", "AgentGenerationError", "AgentParsingError",
           "AgentMaxStepsError", "truncate_content", "extract_code_from_text"):
    setattr(mock_utils, _n, type(_n, (Exception,) if "Error" in _n else (), {}))
sys.modules["smolagents.utils"] = mock_utils

mock_tools = _mock_module("smolagents.tools")
mock_tools.Tool = type("Tool", (), {})
sys.modules["smolagents.tools"] = mock_tools

mock_smolagents.ActionStep = mock_memory.ActionStep
mock_smolagents.TaskStep = mock_memory.TaskStep
mock_smolagents.Timing = mock_mon.Timing
mock_smolagents.AgentText = type("AgentText", (), {})
mock_smolagents.handle_agent_output_types = mock_agents.handle_agent_output_types
mock_smolagents.CodeAgent = mock_agents.CodeAgent

# -- sdk.nexent sub-tree ---------------------------------------------
def _sdk_pkg(name):
    parts = name.split(".")
    result = None
    for i, part in enumerate(parts):
        full = ".".join(parts[: i + 1])
        parent_full = ".".join(parts[:i]) if i > 0 else None
        if full in sys.modules:
            result = sys.modules[full]
        else:
            m = _mock_module(full)
            if parent_full and parent_full in sys.modules:
                setattr(sys.modules[parent_full], part, m)
            result = m
    return result


agent_model_mod = _sdk_pkg("sdk.nexent.core.agents.agent_model")


class _AgentVerificationConfig:
    def __init__(
        self,
        enabled=False,
        max_final_rounds=1,
        final_verification_enabled=False,
        step_verification_enabled=True,
        llm_verification_enabled=True,
        pass_score=0.8,
    ):
        self.enabled = enabled
        self.max_final_rounds = max_final_rounds
        self.final_verification_enabled = final_verification_enabled
        self.step_verification_enabled = step_verification_enabled
        self.llm_verification_enabled = llm_verification_enabled
        self.pass_score = pass_score


agent_model_mod.AgentVerificationConfig = _AgentVerificationConfig

# Also add what test_core_agent.py shim needs (it's imported before our stub runs)
agent_model_mod.PROTOCOL_JSONRPC = "JSONRPC"
agent_model_mod.PROTOCOL_HTTP_JSON = "HTTP+JSON"
agent_model_mod.PROTOCOL_GRPC = "GRPC"

# plan_repo stub
plan_repo_mod = _sdk_pkg("sdk.nexent.core.agents.plan_repo")


class _PlanRepo:
    def __init__(self, redis_client=None, ttl_seconds=86400):
        self._redis = redis_client
        self._ttl = ttl_seconds
        self.saved = []

    def save(self, plan_dict, conversation_id=None, user_id=None, status="active"):
        self.saved.append({
            "plan_dict": plan_dict,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "status": status,
        })


plan_repo_mod.PlanRepo = _PlanRepo

# observer stub
observer_mod = _sdk_pkg("sdk.nexent.core.utils.observer")


class _ProcessType:
    STEP_COUNT = "STEP_COUNT"
    PARSE = "PARSE"
    EXECUTION_LOGS = "EXECUTION_LOGS"
    AGENT_NEW_RUN = "AGENT_NEW_RUN"
    AGENT_FINISH = "AGENT_FINISH"
    FINAL_ANSWER = "FINAL_ANSWER"
    ERROR = "ERROR"
    TOOL = "TOOL"
    CARD = "CARD"
    MEMORY_SEARCH = "MEMORY_SEARCH"
    MAX_STEPS_REACHED = "MAX_STEPS_REACHED"
    PLAN = "PLAN"
    PLAN_STEP_UPDATE = "PLAN_STEP_UPDATE"


class MessageObserver:
    def __init__(self):
        self.add_message = MagicMock()
        self.lang = "en"


observer_mod.MessageObserver = MessageObserver
observer_mod.ProcessType = _ProcessType

# context_runtime contracts stub
contracts_mod = _sdk_pkg("sdk.nexent.core.context_runtime.contracts")
contracts_mod.UnconfiguredContextRuntime = type("UnconfiguredContextRuntime", (), {})
contracts_mod.ContextRuntime = type("ContextRuntime", (), {})

# token_estimation stub
token_mod = _sdk_pkg("sdk.nexent.core.utils.token_estimation")
token_mod.msg_token_count = lambda *a, **k: 0

# verification stub
verification_mod = _sdk_pkg("sdk.nexent.core.agents.verification")


class _AutoResult:
    """Result object that auto-returns another _AutoResult for any missing attr or call."""

    def __init__(self):
        self.passed = True
        self.severity = ""
        self.phase = ""
        self.event = ""
        self.score = 1.0
        self.failed_criteria = []
        self.repair_instruction = ""
        self.user_visible_note = ""

    def __getattr__(self, name):
        return _AutoResult()

    def __call__(self, *args, **kwargs):
        return _AutoResult()


class _VerificationController:
    """Stub that accepts any keyword args and provides a mock for every attribute."""

    def __init__(self, config=None, observer=None, agent_name="", model=None, logger=None):
        self.config = config
        self.observer = observer
        self.agent_name = agent_name
        self.model = model
        self.logger = logger
        object.__setattr__(self, "_mocks", {})

    def __getattr__(self, name):
        result = _AutoResult()
        object.__getattribute__(self, "_mocks")[name] = result
        return result


class _VerificationResult:
    passed = True
    phase = ""
    severity = ""
    event = ""
    score = 1.0


verification_mod.VerificationController = _VerificationController
verification_mod.VerificationResult = _VerificationResult

# monitor stub
monitor_mod = _sdk_pkg("sdk.nexent.monitor")
monitor_mod.get_monitoring_manager = MagicMock(return_value=MagicMock())


# ---- Load core_agent under controlled sys.modules -----------------
CORE_AGENT_PATH = REPO_ROOT / "sdk" / "nexent" / "core" / "agents" / "core_agent.py"
CORE_AGENT_NAME = "sdk.nexent.core.agents.core_agent"
spec = importlib.util.spec_from_file_location(CORE_AGENT_NAME, CORE_AGENT_PATH)
core_agent_module = importlib.util.module_from_spec(spec)
sys.modules[CORE_AGENT_NAME] = core_agent_module
agents_mod = sys.modules["sdk.nexent.core.agents"]
agents_mod.core_agent = core_agent_module
assert spec and spec.loader
spec.loader.exec_module(core_agent_module)

CoreAgent = core_agent_module.CoreAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _PlanStep:
    def __init__(self, *, id, title="", description="", status="pending"):
        self.id = id
        self.title = title
        self.description = description
        self.status = status

    def model_dump(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
        }


class _AgentPlan:
    def __init__(self, *, plan_id, title, steps, current_step_index=0):
        self.plan_id = plan_id
        self.title = title
        self.steps = list(steps)
        self.current_step_index = current_step_index

    def model_dump(self):
        return {
            "plan_id": self.plan_id,
            "title": self.title,
            "current_step_index": self.current_step_index,
            "steps": [
                s.model_dump() if hasattr(s, "model_dump") else s.__dict__
                for s in self.steps
            ],
        }


def _make_core_agent(*, enable_planning=False, redis_client=None,
                     context_manager=None):
    """Construct a minimal CoreAgent-like object with just the plan methods.

    We bypass ``CoreAgent.__init__`` entirely (it calls the smolagents parent
    which we have stubbed out). Instead we use ``__new__`` to get an empty
    instance and manually set the attributes that the plan methods need.
    """
    agent = CoreAgent.__new__(CoreAgent)
    agent.enable_planning = enable_planning
    agent.plan_repo = _PlanRepo(redis_client=redis_client) if enable_planning else None
    agent.current_plan = None
    agent.current_step_index = 0
    agent.lang = "en"
    agent.observer = MessageObserver()
    agent.context_manager = context_manager
    agent.tools = {}
    agent.managed_agents = {}
    agent.prompt_templates = {}
    agent.code_block_tags = ["", ""]
    agent.logger = MagicMock()
    return agent


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEnablePlanningInit:
    """CoreAgent branches on enable_planning: PlanRepo instantiated only when True."""

    def test_plan_repo_built_when_enabled(self):
        agent = _make_core_agent(enable_planning=True)
        assert isinstance(agent.plan_repo, _PlanRepo)

    def test_plan_repo_none_when_disabled(self):
        agent = _make_core_agent(enable_planning=False)
        assert agent.plan_repo is None

    def test_initial_state(self):
        agent = _make_core_agent(enable_planning=True)
        assert agent.current_plan is None
        assert agent.current_step_index == 0


class TestGetConversationAndUserId:
    """Helpers read from context_manager; default to 0 / 'anonymous'."""

    def test_no_context_manager_returns_sentinels(self):
        agent = _make_core_agent(enable_planning=True)
        assert agent._get_conversation_id() == 0
        assert agent._get_user_id() == "anonymous"

    def test_reads_from_context_manager(self):
        ctx = MagicMock()
        ctx.conversation_id = 42
        ctx.user_id = "alice"
        agent = _make_core_agent(enable_planning=True, context_manager=ctx)
        assert agent._get_conversation_id() == 42
        assert agent._get_user_id() == "alice"

    def test_user_id_is_stringified(self):
        ctx = MagicMock()
        ctx.conversation_id = 1
        ctx.user_id = 7  # int should be stringified
        agent = _make_core_agent(enable_planning=True, context_manager=ctx)
        assert agent._get_user_id() == "7"


class TestOnPlanCreated:
    def test_stores_plan_and_resets_index(self):
        agent = _make_core_agent(enable_planning=True)
        plan = _AgentPlan(
            plan_id="p", title="t",
            steps=[_PlanStep(id="step-1"), _PlanStep(id="step-2")],
        )
        agent._on_plan_created(plan)
        assert agent.current_plan is plan
        assert agent.current_step_index == 0

    def test_works_without_repo(self):
        agent = _make_core_agent(enable_planning=False)
        plan = _AgentPlan(plan_id="p", title="t", steps=[_PlanStep(id="s")])
        agent._on_plan_created(plan)
        assert agent.current_plan is plan


class TestAdvanceCurrentIndex:
    def _make_plan(self, statuses):
        return _AgentPlan(
            plan_id="p", title="t",
            steps=[_PlanStep(id=f"step-{i+1}", status=s)
                   for i, s in enumerate(statuses)],
        )

    def test_no_plan_is_noop(self):
        agent = _make_core_agent(enable_planning=True)
        agent._advance_current_index()
        assert agent.current_step_index == 0

    def test_advances_past_completed_step(self):
        agent = _make_core_agent(enable_planning=True)
        plan = self._make_plan(["completed", "pending", "pending"])
        agent.current_plan = plan
        agent.current_step_index = 0
        agent._advance_current_index()
        assert agent.current_step_index == 1
        assert plan.steps[1].status == "in_progress"

    def test_advances_past_skipped_steps(self):
        agent = _make_core_agent(enable_planning=True)
        plan = self._make_plan(["skipped", "skipped", "pending"])
        agent.current_plan = plan
        agent.current_step_index = 0
        agent._advance_current_index()
        assert agent.current_step_index == 2
        assert plan.steps[2].status == "in_progress"

    def test_does_not_touch_already_in_progress(self):
        agent = _make_core_agent(enable_planning=True)
        plan = self._make_plan(["in_progress", "pending"])
        agent.current_plan = plan
        agent.current_step_index = 0
        agent._advance_current_index()
        assert agent.current_step_index == 0
        assert plan.steps[0].status == "in_progress"

    def test_past_end_of_plan(self):
        agent = _make_core_agent(enable_planning=True)
        plan = self._make_plan(["completed", "completed"])
        agent.current_plan = plan
        agent.current_step_index = 0
        agent._advance_current_index()
        assert agent.current_step_index == 2


class TestImplicitAdvanceStep:
    """Fallback when LLM skipped update_plan_step before final_answer."""

    def _make_plan(self, statuses):
        return _AgentPlan(
            plan_id="p", title="t",
            steps=[_PlanStep(id=f"step-{i+1}", status=s)
                   for i, s in enumerate(statuses)],
        )

    def test_completes_when_all_others_terminal(self):
        agent = _make_core_agent(enable_planning=True)
        plan = self._make_plan(["in_progress", "completed", "skipped"])
        agent.current_plan = plan
        agent.current_step_index = 0
        agent._implicit_advance_step()
        # Status flipped to completed
        assert plan.steps[0].status == "completed"
        # Index advanced past the end (no next pending step, so no in_progress flip)
        assert agent.current_step_index == 3
        # plan_repo.save called (without exception, using defaults for conv/user id)
        assert len(agent.plan_repo.saved) == 1

    def test_no_op_when_later_steps_pending(self):
        agent = _make_core_agent(enable_planning=True)
        plan = self._make_plan(["in_progress", "pending", "pending"])
        agent.current_plan = plan
        agent.current_step_index = 0
        agent._implicit_advance_step()
        assert plan.steps[0].status == "in_progress"

    def test_no_op_when_current_not_in_progress(self):
        agent = _make_core_agent(enable_planning=True)
        plan = self._make_plan(["pending", "pending"])
        agent.current_plan = plan
        agent.current_step_index = 0
        agent._implicit_advance_step()
        assert plan.steps[0].status == "pending"

    def test_no_op_when_planning_disabled(self):
        agent = _make_core_agent(enable_planning=False)
        agent._implicit_advance_step()  # no crash
        assert agent.current_plan is None

    def test_no_op_when_index_past_end(self):
        agent = _make_core_agent(enable_planning=True)
        plan = self._make_plan(["completed"])
        agent.current_plan = plan
        agent.current_step_index = 5
        agent._implicit_advance_step()
        assert plan.steps[0].status == "completed"

    def test_repo_save_failure_is_swallowed(self, caplog):
        agent = _make_core_agent(enable_planning=True)
        plan = self._make_plan(["in_progress", "completed", "completed"])
        agent.current_plan = plan
        agent.current_step_index = 0
        agent.plan_repo.save = MagicMock(side_effect=RuntimeError("redis down"))
        agent._implicit_advance_step()  # no crash
        assert plan.steps[0].status == "completed"


class TestOnStepUpdatedCallback:
    def test_callback_advances_index_past_completed_step(self):
        """_on_step_updated only advances the pointer; step status must already be
        updated by UpdatePlanStepTool.forward before this callback fires."""
        agent = _make_core_agent(enable_planning=True)
        plan = _AgentPlan(
            plan_id="p", title="t",
            steps=[
                _PlanStep(id="step-1", status="completed"),  # already flipped by tool
                _PlanStep(id="step-2", status="pending"),
            ],
        )
        agent.current_plan = plan
        agent.current_step_index = 0
        agent._on_step_updated(plan, "step-1", "completed")
        assert agent.current_plan is plan
        assert agent.current_step_index == 1
        assert plan.steps[1].status == "in_progress"


class TestCleanupPlan:
    def test_persists_final_plan(self):
        agent = _make_core_agent(enable_planning=True)
        plan = _AgentPlan(
            plan_id="p", title="t",
            steps=[
                _PlanStep(id="step-1", status="completed"),
                _PlanStep(id="step-2", status="in_progress"),
            ],
        )
        agent.current_plan = plan
        agent._cleanup_plan()
        assert len(agent.plan_repo.saved) == 1
        saved = agent.plan_repo.saved[0]
        assert saved["plan_dict"]["plan_id"] == "p"

    def test_noop_when_planning_disabled(self):
        agent = _make_core_agent(enable_planning=False)
        agent._cleanup_plan()

    def test_noop_when_no_plan(self):
        agent = _make_core_agent(enable_planning=True)
        agent._cleanup_plan()
        assert agent.plan_repo.saved == []

    def test_save_failure_is_swallowed(self, caplog):
        agent = _make_core_agent(enable_planning=True)
        plan = _AgentPlan(plan_id="p", title="t", steps=[_PlanStep(id="step-1")])
        agent.current_plan = plan
        agent.plan_repo.save = MagicMock(side_effect=RuntimeError("boom"))
        agent._cleanup_plan()  # no crash
