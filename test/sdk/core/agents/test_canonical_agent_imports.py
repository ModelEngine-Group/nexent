# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Canonical Agent import contracts after the explicit compatibility removal."""

import ast
import importlib
import json
import pickle
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[4]
REMOVED = [
    "core_adapters", "agent_model", "clarification", "run_agent", "nexent_agent",
    "core_agent", "output_protocol", "plan_repo", "verification", "tool_fastpath",
    "managed_mcp", "subagent_wrapper", "a2a_agent_proxy", "tool_parameters",
    "tool_user_context", "sandbox_workspace", "context_input", "summary_cache",
    "context.runtime", "sandbox_tls", "sandbox_tls_bootstrap", "summary_config", "agent_context",
]
CANONICAL = [
    "contracts.config", "contracts.run", "contracts.adapter", "contracts.resources",
    "contracts.output", "contracts.context", "contracts.clarification", "factory",
    "orchestration.entry", "orchestration.children", "resources.provider", "resources.mcp",
    "resources.subagents", "resources.a2a", "output.answer", "cores.smolagents.adapter",
    "cores.smolagents.agent", "cores.smolagents.core_agent", "cores.smolagents.context",
    "cores.jiuwen.adapter", "cores.jiuwen.model", "cores.jiuwen.protocol", "cores.jiuwen.events",
    "sandbox.config", "sandbox.execution", "sandbox.tls", "sandbox.tls_bootstrap",
]


def test_project_imports_do_not_depend_on_removed_agent_paths():
    removed = ["nexent.core.agents." + name for name in REMOVED]
    removed += ["nexent.core.context_runtime", "nexent.core.agent_runtime_support"]
    failures = []
    for folder in [ROOT / "sdk/nexent", ROOT / "sdk/benchmark", ROOT / "backend"]:
        for path in folder.rglob("*.py"):
            if ".venv" in path.parts or "__pycache__" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
                if isinstance(node, ast.ImportFrom):
                    modules = [(node.module or "")] + [(node.module or "") + "." + item.name for item in node.names]
                elif isinstance(node, ast.Import):
                    modules = [item.name for item in node.names]
                else:
                    continue
                if any(module == old or module.startswith(old + ".") for module in modules for old in removed):
                    failures.append((str(path), node.lineno, modules))
    assert failures == []


def isolated(code):
    result = subprocess.run([sys.executable, "-I", "-c",
        "import sys;sys.path.insert(0," + repr(str(ROOT / "sdk")) + ");\n" + code],
        capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize("relative", CANONICAL)
def test_canonical_module_is_loaded_from_its_own_file(relative):
    module = importlib.import_module("nexent.core.agents." + relative)
    expected = ROOT / "sdk/nexent/core/agents" / (relative.replace(".", "/") + ".py")
    assert Path(module.__file__).resolve() == expected.resolve()
    assert module.__name__ == "nexent.core.agents." + relative


def test_removed_modules_and_historical_pickle_names_are_unavailable():
    names = ["nexent.core.agents." + name for name in REMOVED]
    names += ["nexent.core.context_runtime", "nexent.core.agent_runtime_support"]
    isolated(f'''
import importlib, importlib.util, pickle
for name in {names!r}:
    try:
        spec = importlib.util.find_spec(name)
    except ModuleNotFoundError:
        spec = None
    assert spec is None, name
    try:
        importlib.import_module(name)
    except ModuleNotFoundError as error:
        assert name == error.name or name.startswith(error.name + '.'), (name, error.name)
    else:
        raise AssertionError(name)
for module, symbol in [('nexent.core.agents.agent_model','AgentConfig'),
                       ('nexent.core.agent_runtime_support.output','RunResult'),
                       ('nexent.core.agents.sandbox','SandboxConfig')]:
    try:
        pickle.loads(f'c{{module}}\\n{{symbol}}\\n.'.encode())
    except (ImportError, AttributeError):
        pass
    else:
        raise AssertionError((module, symbol))
''')


def test_canonical_contract_serialization_validation_and_answer_errors():
    from nexent.core.agents.contracts.config import AgentConfig
    from nexent.core.agents.contracts.output import RunResult
    from nexent.core.agents.output.answer import AnswerBoundaryError, normalize_public_answer

    result = RunResult(turn_id="turn", status="completed", end_reason="answer", final_content="Done")
    assert RunResult.model_validate_json(result.model_dump_json()) == result
    assert pickle.loads(pickle.dumps(result)) == result
    assert AgentConfig.__module__ == "nexent.core.agents.contracts.config"
    with pytest.raises(ValidationError):
        RunResult(turn_id="turn", status="failed", end_reason="error", final_content="False success")
    with pytest.raises(AnswerBoundaryError, match="JIUWEN_FINAL_OUTPUT_INVALID"):
        normalize_public_answer("<completed_action_history>private")


def test_factory_extension_registration_dispatch_and_rejection(monkeypatch):
    from nexent.core.agents.contracts.adapter import AgentCoreAdapter, UnsupportedAgentCoreConfig
    from nexent.core.agents.factory import AgentCoreFactory

    monkeypatch.setattr(AgentCoreFactory, "_adapters", {})
    class Extension(AgentCoreAdapter):
        core_name = "fixture"
        @classmethod
        def capabilities(cls):
            return frozenset()
        def validate(self):
            pass
        def run(self):
            return "extension result"
    AgentCoreFactory.register("fixture", Extension)
    info = SimpleNamespace(agent_config=SimpleNamespace(agent_core="fixture"))
    assert AgentCoreFactory.create(info).run() == "extension result"
    with pytest.raises(ValueError, match="already registered"):
        AgentCoreFactory.register("fixture", Extension)
    with pytest.raises(UnsupportedAgentCoreConfig, match="Unknown agent core"):
        AgentCoreFactory.create(SimpleNamespace(agent_config=SimpleNamespace(agent_core="missing")))


@pytest.mark.parametrize("name,adapter,error", [("Invalid-name", object, ValueError), ("fixture", object, TypeError)])
def test_factory_rejects_invalid_registration(name, adapter, error):
    from nexent.core.agents.factory import AgentCoreFactory
    with pytest.raises(error):
        AgentCoreFactory.register(name, adapter)


def test_optional_jiuwen_dependency_does_not_affect_default_core_or_fall_back():
    output = isolated('''
import importlib.abc,json
class BlockJiuwen(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'openjiuwen' or fullname.startswith('openjiuwen.'):
            raise ModuleNotFoundError('optional Jiuwen unavailable', name=fullname)
sys.meta_path.insert(0, BlockJiuwen())
from nexent.core.agents.factory import AgentCoreFactory
from types import SimpleNamespace
assert not any(name.startswith('openjiuwen') for name in sys.modules)
info = SimpleNamespace(agent_config=SimpleNamespace(agent_core='smolagents'))
assert AgentCoreFactory.create(info, smolagents_executor=lambda value:'ok').run() == 'ok'
info.agent_config.agent_core='jiuwen'
try:
    AgentCoreFactory.create(info).prepare()
except ModuleNotFoundError as error:
    assert error.name.startswith('openjiuwen')
else:
    raise AssertionError('Jiuwen must not silently fall back')
print(json.dumps({'status':'PASS'}))
''')
    assert json.loads(output.splitlines()[-1])["status"] == "PASS"
