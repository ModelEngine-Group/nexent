"""Unit tests for sdk.nexent.core.tools.plan_tools.

Exercises the two plan management tools (CreatePlanTool, UpdatePlanStepTool)
against the same v1.4 planing feature that the backend drives. Tests use an
inline shim of smolagents/observer so this file does not depend on the
``sdk`` package being pip-installed.
"""

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]


def _pkg(name, path):
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]
    sys.modules.setdefault(name, mod)
    return mod


sdk_pkg = _pkg("sdk", REPO_ROOT / "sdk")
nexent_pkg = _pkg("sdk.nexent", REPO_ROOT / "sdk" / "nexent")
core_pkg = _pkg("sdk.nexent.core", REPO_ROOT / "sdk" / "nexent" / "core")
tools_pkg = _pkg("sdk.nexent.core.tools", REPO_ROOT / "sdk" / "nexent" / "core" / "tools")
utils_pkg = _pkg("sdk.nexent.core.utils", REPO_ROOT / "sdk" / "nexent" / "core" / "utils")
agents_pkg = _pkg("sdk.nexent.core.agents", REPO_ROOT / "sdk" / "nexent" / "core" / "agents")

sdk_pkg.nexent = nexent_pkg
nexent_pkg.core = core_pkg
core_pkg.tools = tools_pkg
core_pkg.utils = utils_pkg
core_pkg.agents = agents_pkg


# ---------------------------------------------------------------------------
# observer shim
# ---------------------------------------------------------------------------

class MessageObserver:
    def add_message(self, *args, **kwargs):
        pass


class _ProcessType:
    PLAN = "plan"
    PLAN_STEP_UPDATE = "plan_step_update"


observer_mod = types.ModuleType("sdk.nexent.core.utils.observer")
observer_mod.MessageObserver = MessageObserver
observer_mod.ProcessType = _ProcessType
sys.modules["sdk.nexent.core.utils.observer"] = observer_mod
utils_pkg.observer = observer_mod


# ---------------------------------------------------------------------------
# tools_common_message shim
# ---------------------------------------------------------------------------

class _EnumValue:
    def __init__(self, value):
        self.value = value


class _ToolCategory:
    PLANNING = _EnumValue("planning")


class _ToolSign:
    PLAN_OPERATION = _EnumValue("plan_operation")


tools_common_mod = types.ModuleType("sdk.nexent.core.utils.tools_common_message")
tools_common_mod.ToolCategory = _ToolCategory
tools_common_mod.ToolSign = _ToolSign
sys.modules["sdk.nexent.core.utils.tools_common_message"] = tools_common_mod
utils_pkg.tools_common_message = tools_common_mod


# ---------------------------------------------------------------------------
# smolagents shim (Field-aware mock Tool, mirrors test_knowledge_base_search_tool.py)
# ---------------------------------------------------------------------------

class Tool:
    """Mock Tool that flattens pydantic Field definitions."""

    def __init__(self, *args, **kwargs):
        from pydantic.fields import FieldInfo

        for key, value in kwargs.items():
            setattr(self, key, value)

        for cls in type(self).__mro__:
            if cls is Tool:
                continue
            if hasattr(cls, "__annotations__"):
                for name, hint in cls.__annotations__.items():
                    if name in self.__dict__:
                        continue
                    if hasattr(cls, name):
                        value = getattr(cls, name)
                        if isinstance(value, FieldInfo):
                            if value.default_factory is not None:
                                value = value.default_factory()
                            else:
                                value = value.default
                        setattr(self, name, value)

    def __setattr__(self, name, value):
        from pydantic.fields import FieldInfo

        if isinstance(value, FieldInfo):
            for cls in type(self).__mro__:
                if cls is Tool:
                    continue
                if hasattr(cls, name):
                    class_attr = getattr(cls, name)
                    if class_attr is value:
                        if value.default_factory is not None:
                            value = value.default_factory()
                        else:
                            value = value.default
                        break
        self.__dict__[name] = value


smolagents_mod = types.ModuleType("smolagents")
smolagents_tools_mod = types.ModuleType("smolagents.tools")
smolagents_tools_mod.Tool = Tool
smolagents_mod.tools = smolagents_tools_mod
sys.modules["smolagents"] = smolagents_mod
sys.modules["smolagents.tools"] = smolagents_tools_mod


# ---------------------------------------------------------------------------
# agent_model shim
# ---------------------------------------------------------------------------
# plan_tools.forward imports ``from ..agents.agent_model import AgentPlan,
# PlanStep`` locally. We install a stub module that supplies two simple
# Pydantic-free containers holding the same fields the tool touches.

class _PlanStep:
    def __init__(self, *, id, title, description, status):
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
    def __init__(self, *, plan_id, title, steps, current_step_index):
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
                {
                    "id": s.id,
                    "title": s.title,
                    "description": s.description,
                    "status": s.status,
                }
                for s in self.steps
            ],
        }


agent_model_mod = types.ModuleType("sdk.nexent.core.agents.agent_model")
agent_model_mod.PlanStep = _PlanStep
agent_model_mod.AgentPlan = _AgentPlan
sys.modules["sdk.nexent.core.agents.agent_model"] = agent_model_mod
agents_pkg.agent_model = agent_model_mod


# ---------------------------------------------------------------------------
# Load the plan_tools module under test
# ---------------------------------------------------------------------------

MODULE_PATH = REPO_ROOT / "sdk" / "nexent" / "core" / "tools" / "plan_tools.py"
MODULE_NAME = "sdk.nexent.core.tools.plan_tools"
spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
plan_tools_module = importlib.util.module_from_spec(spec)
sys.modules[MODULE_NAME] = plan_tools_module
assert spec and spec.loader
spec.loader.exec_module(plan_tools_module)
tools_pkg.plan_tools = plan_tools_module

CreatePlanTool = plan_tools_module.CreatePlanTool
UpdatePlanStepTool = plan_tools_module.UpdatePlanStepTool
PlanStatus = plan_tools_module.PlanStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def make_create_tool():
    """Factory returning a CreatePlanTool with pluggable collaborators."""

    def _make(observer=None, plan_repo=None, on_plan_created=None,
              get_conversation_id=None, get_user_id=None):
        return CreatePlanTool(
            observer=observer,
            plan_repo=plan_repo,
            on_plan_created=on_plan_created,
            get_conversation_id=get_conversation_id,
            get_user_id=get_user_id,
        )

    return _make


@pytest.fixture
def make_update_tool():
    """Factory returning an UpdatePlanStepTool with pluggable collaborators."""

    def _make(observer=None, plan_repo=None, on_step_updated=None,
              get_conversation_id=None, get_user_id=None):
        return UpdatePlanStepTool(
            observer=observer,
            plan_repo=plan_repo,
            on_step_updated=on_step_updated,
            get_conversation_id=get_conversation_id,
            get_user_id=get_user_id,
        )

    return _make


@pytest.fixture
def minimal_steps():
    return [
        {"id": "step-1", "title": "First", "description": "do first thing"},
        {"id": "step-2", "title": "Second", "description": "do second thing"},
        {"id": "step-3", "title": "Third", "description": "do third thing"},
    ]


@pytest.fixture
def built_plan(minimal_steps):
    """Plan that has already been through CreatePlanTool.forward."""
    return _AgentPlan(
        plan_id="plan-abc",
        title="Test plan",
        steps=[
            _PlanStep(id=s["id"], title=s["title"], description=s["description"], status="in_progress" if i == 0 else "pending")
            for i, s in enumerate(minimal_steps)
        ],
        current_step_index=0,
    )


# ---------------------------------------------------------------------------
# CreatePlanTool
# ---------------------------------------------------------------------------

class TestCreatePlanTool:
    """CreatePlanTool.forward validation, persistence and event emission."""

    def test_happy_path_returns_plan_id_and_count(self, make_create_tool, minimal_steps):
        tool = make_create_tool()
        result = tool.forward(plan_id="plan-1", title="T", steps=minimal_steps)
        assert result == {"plan_id": "plan-1", "step_count": 3}

    def test_first_step_marked_in_progress(self, make_create_tool, minimal_steps):
        captured = {}

        def on_created(plan):
            captured["plan"] = plan

        tool = CreatePlanTool(on_plan_created=on_created)
        tool.forward(plan_id="p", title="t", steps=minimal_steps)
        assert captured["plan"].steps[0].status == "in_progress"
        assert all(s.status == "pending" for s in captured["plan"].steps[1:])

    def test_too_few_steps_raises(self, make_create_tool):
        tool = make_create_tool()
        with pytest.raises(ValueError, match="at least 3 steps"):
            tool.forward(
                plan_id="p",
                title="t",
                steps=[
                    {"id": "step-1", "title": "a", "description": "b"},
                    {"id": "step-2", "title": "a", "description": "b"},
                ],
            )

    def test_more_than_8_steps_warns_not_raises(self, make_create_tool, caplog):
        tool = make_create_tool()
        steps = [{"id": f"step-{i}", "title": f"T{i}", "description": f"D{i}"} for i in range(1, 10)]
        with caplog.at_level("WARNING", logger="plan_tools"):
            result = tool.forward(plan_id="p", title="t", steps=steps)
        assert result["step_count"] == 9
        assert any("recommended max is 8" in rec.message for rec in caplog.records)

    def test_non_list_steps_raises(self, make_create_tool):
        tool = make_create_tool()
        with pytest.raises(ValueError, match="at least 3 steps"):
            tool.forward(plan_id="p", title="t", steps="not-a-list")

    def test_step_must_be_dict(self, make_create_tool):
        tool = make_create_tool()
        steps = [
            {"id": "step-1", "title": "a", "description": "b"},
            "not-a-dict",
            {"id": "step-3", "title": "c", "description": "d"},
        ]
        with pytest.raises(ValueError, match="each step must be a dict"):
            tool.forward(plan_id="p", title="t", steps=steps)

    def test_empty_step_id_rejected(self, make_create_tool):
        tool = make_create_tool()
        steps = [
            {"id": "  ", "title": "a", "description": "b"},
            {"id": "step-2", "title": "a", "description": "b"},
            {"id": "step-3", "title": "a", "description": "b"},
        ]
        with pytest.raises(ValueError, match="step.id is required"):
            tool.forward(plan_id="p", title="t", steps=steps)

    def test_duplicate_step_id_rejected(self, make_create_tool):
        tool = make_create_tool()
        steps = [
            {"id": "step-1", "title": "a", "description": "b"},
            {"id": "step-1", "title": "c", "description": "d"},
            {"id": "step-3", "title": "e", "description": "f"},
        ]
        with pytest.raises(ValueError, match="duplicate step id"):
            tool.forward(plan_id="p", title="t", steps=steps)

    def test_missing_title_defaults_to_id(self, make_create_tool):
        captured = {}

        def on_created(plan):
            captured["plan"] = plan

        tool = CreatePlanTool(on_plan_created=on_created)
        steps = [
            {"id": "step-1", "title": "", "description": "b"},
            {"id": "step-2", "title": " ", "description": "d"},
            {"id": "step-3", "title": "real", "description": "f"},
        ]
        tool.forward(plan_id="p", title="t", steps=steps)
        # Empty / whitespace-only titles fall back to id
        assert captured["plan"].steps[0].title == "step-1"
        assert captured["plan"].steps[1].title == "step-2"
        assert captured["plan"].steps[2].title == "real"

    def test_blank_plan_id_replaced_with_uuid(self, make_create_tool, minimal_steps):
        tool = make_create_tool()
        result = tool.forward(plan_id="   ", title="t", steps=minimal_steps)
        assert result["plan_id"]
        assert result["plan_id"] != "   "

    def test_persist_calls_plan_repo(self, make_create_tool, minimal_steps):
        repo = MagicMock()
        tool = make_create_tool(plan_repo=repo, get_conversation_id=lambda: 42, get_user_id=lambda: "u-1")
        tool.forward(plan_id="plan-x", title="t", steps=minimal_steps)
        repo.save.assert_called_once()
        args, kwargs = repo.save.call_args
        assert kwargs["conversation_id"] == 42
        assert kwargs["user_id"] == "u-1"
        # plan_dict is the first positional argument
        assert args[0]["plan_id"] == "plan-x"

    def test_plan_repo_save_failure_is_swallowed(self, make_create_tool, minimal_steps, caplog):
        repo = MagicMock()
        repo.save.side_effect = RuntimeError("redis down")
        tool = make_create_tool(plan_repo=repo)
        with caplog.at_level("WARNING", logger="plan_tools"):
            result = tool.forward(plan_id="plan-x", title="t", steps=minimal_steps)
        assert result["plan_id"] == "plan-x"

    def test_no_observer_or_repo_is_supported(self, make_create_tool, minimal_steps):
        # When both observer and plan_repo are None, the tool still succeeds.
        tool = make_create_tool()
        assert tool.forward(plan_id="p", title="t", steps=minimal_steps)["step_count"] == 3

    def test_emits_plan_event_with_serialized_steps(self, make_create_tool, minimal_steps):
        observer = MagicMock()
        tool = make_create_tool(observer=observer)
        tool.forward(plan_id="plan-e", title="Title", steps=minimal_steps)
        observer.add_message.assert_called_once()
        _, process_type, payload = observer.add_message.call_args.args
        assert process_type == _ProcessType.PLAN
        body = json.loads(payload)
        assert body["plan_id"] == "plan-e"
        assert body["title"] == "Title"
        assert [s["id"] for s in body["steps"]] == ["step-1", "step-2", "step-3"]

    def test_observer_failure_is_swallowed(self, make_create_tool, minimal_steps):
        observer = MagicMock()
        observer.add_message.side_effect = RuntimeError("sse broken")
        tool = make_create_tool(observer=observer)
        # Should not raise
        tool.forward(plan_id="p", title="t", steps=minimal_steps)

    def test_callback_failure_is_swallowed(self, make_create_tool, minimal_steps):
        def cb(_plan):
            raise RuntimeError("listener died")

        tool = make_create_tool(on_plan_created=cb)
        # Should not raise
        tool.forward(plan_id="p", title="t", steps=minimal_steps)

    def test_callback_receives_plan_object(self, make_create_tool, minimal_steps):
        captured = {}

        def cb(plan):
            captured["plan_id"] = plan.plan_id
            captured["step_count"] = len(plan.steps)
            captured["first_status"] = plan.steps[0].status

        tool = make_create_tool(on_plan_created=cb)
        tool.forward(plan_id="plan-cb", title="t", steps=minimal_steps)
        assert captured == {"plan_id": "plan-cb", "step_count": 3, "first_status": "in_progress"}

    def test_default_callbacks_use_zero_and_anonymous(self, make_create_tool, minimal_steps):
        """When get_* are None, save is still attempted with sentinel values."""
        repo = MagicMock()
        tool = make_create_tool(plan_repo=repo)
        tool.forward(plan_id="p", title="t", steps=minimal_steps)
        kwargs = repo.save.call_args.kwargs
        assert kwargs["conversation_id"] == 0
        assert kwargs["user_id"] == "anonymous"


# ---------------------------------------------------------------------------
# UpdatePlanStepTool
# ---------------------------------------------------------------------------

class TestUpdatePlanStepTool:
    """UpdatePlanStepTool.forward resolves the active plan via the bound callback's owner."""

    @pytest.fixture
    def host(self, built_plan):
        """A minimal 'host' class that owns current_plan and a bound step_updated method.

        ``UpdatePlanStepTool`` resolves the active plan via
        ``getattr(self._on_step_updated, "__self__", None).current_plan`` -- it
        expects a bound method, not a plain function, so we attach one with
        ``types.MethodType``.
        """

        class Host:
            current_plan = built_plan
            current_step_index = 0

            def step_updated(self, plan, step_id, status):
                self.current_plan = plan
                steps = plan.steps
                idx = self.current_step_index
                while idx < len(steps) and steps[idx].status in ("completed", "skipped"):
                    idx += 1
                self.current_step_index = idx

        return Host()

    def _make_tool(self, host, *, observer=None, plan_repo=None,
                   get_conversation_id=None, get_user_id=None):
        return UpdatePlanStepTool(
            observer=observer,
            plan_repo=plan_repo,
            on_step_updated=host.step_updated,
            get_conversation_id=get_conversation_id,
            get_user_id=get_user_id,
        )

    def test_complete_step_updates_status(self, host):
        tool = self._make_tool(host)
        result = tool.forward(step_id="step-1", status="completed")
        assert result["step_id"] == "step-1"
        assert result["status"] == "completed"
        assert result["previous_status"] == "in_progress"
        assert host.current_plan.steps[0].status == "completed"

    def test_complete_first_advances_index(self, host):
        tool = self._make_tool(host)
        tool.forward(step_id="step-1", status="completed")
        # Callback advances the index to the next non-terminal step
        assert host.current_step_index == 1

    def test_invalid_status_rejected(self, host):
        tool = self._make_tool(host)
        with pytest.raises(ValueError, match="status must be one of"):
            tool.forward(step_id="step-1", status="bogus")

    def test_no_active_plan_raises(self):
        class NoPlan:
            current_plan = None

            def step_updated(self, plan, step_id, status):
                pass

        host = NoPlan()
        tool = self._make_tool(host)
        with pytest.raises(RuntimeError, match="no active plan"):
            tool.forward(step_id="step-1", status="completed")

    def test_unknown_step_id_rejected(self, host):
        tool = self._make_tool(host)
        with pytest.raises(ValueError, match="unknown step_id"):
            tool.forward(step_id="step-99", status="completed")

    def test_persist_on_update(self, host):
        repo = MagicMock()
        tool = self._make_tool(host, plan_repo=repo, get_conversation_id=lambda: 7,
                                get_user_id=lambda: "alice")
        tool.forward(step_id="step-1", status="completed")
        repo.save.assert_called_once()
        args, kwargs = repo.save.call_args
        # plan_dict is passed positionally
        assert args[0]["steps"][0]["status"] == "completed"
        assert kwargs["conversation_id"] == 7
        assert kwargs["user_id"] == "alice"

    def test_repo_save_failure_swallowed(self, host, caplog):
        repo = MagicMock()
        repo.save.side_effect = RuntimeError("boom")
        tool = self._make_tool(host, plan_repo=repo)
        with caplog.at_level("WARNING", logger="plan_tools"):
            tool.forward(step_id="step-1", status="completed")
        assert host.current_plan.steps[0].status == "completed"

    def test_emits_plan_step_update_event(self, host):
        observer = MagicMock()
        tool = self._make_tool(host, observer=observer)
        tool.forward(step_id="step-1", status="completed")
        observer.add_message.assert_called_once()
        _, process_type, payload = observer.add_message.call_args.args
        assert process_type == _ProcessType.PLAN_STEP_UPDATE
        body = json.loads(payload)
        assert body == {"step_id": "step-1", "status": "completed"}

    def test_observer_failure_swallowed(self, host):
        observer = MagicMock()
        observer.add_message.side_effect = RuntimeError("sse broken")
        tool = self._make_tool(host, observer=observer)
        tool.forward(step_id="step-1", status="completed")

    def test_callback_failure_swallowed(self, host, caplog):
        def bad_cb(plan, step_id, status):
            raise RuntimeError("listener died")

        host.step_updated = types.MethodType(
            lambda self, plan, step_id, status: bad_cb(plan, step_id, status),
            host,
        )
        tool = self._make_tool(host)
        with caplog.at_level("WARNING", logger="plan_tools"):
            tool.forward(step_id="step-1", status="completed")
        # Status still updated even though callback raised
        assert host.current_plan.steps[0].status == "completed"

    def test_skip_status(self, host):
        tool = self._make_tool(host)
        result = tool.forward(step_id="step-2", status="skipped")
        assert result["status"] == "skipped"
        # Tool itself only marks the targeted step; the in_progress flip of the
        # next pending step is CoreAgent's job (covered in test_core_agent_planning).
        assert host.current_plan.steps[1].status == "skipped"

    def test_callback_owner_without_current_plan(self, built_plan):
        """If the bound callback's owner has no current_plan, tool should raise."""

        class NoPlan:
            current_plan = None

            def cb(plan, step_id, status):
                pass

        # Attach a method whose owner has no current_plan
        host = NoPlan()
        host.cb = types.MethodType(
            lambda self, plan, step_id, status: None, host
        )
        tool = UpdatePlanStepTool(on_step_updated=host.cb)
        with pytest.raises(RuntimeError, match="no active plan"):
            tool.forward(step_id="step-1", status="completed")


class TestPlanStatusEnum:
    def test_values(self):
        assert PlanStatus.PENDING.value == "pending"
        assert PlanStatus.IN_PROGRESS.value == "in_progress"
        assert PlanStatus.COMPLETED.value == "completed"
        assert PlanStatus.SKIPPED.value == "skipped"
