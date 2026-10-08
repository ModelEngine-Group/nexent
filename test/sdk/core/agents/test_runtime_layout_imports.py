"""Verify the public entry point and canonical internal module ownership."""

import subprocess
import sys

import pytest


REMOVED_MODULES = [
    "nexent.core.agents.managed_mcp",
    "nexent.core.agents.tool_user_context",
    "nexent.core.gateway.modality.llm.llm_adapter",
    "nexent.core.gateway.modality.llm.openai",
]


def run_isolated(code):
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("public_first", [True, False])
def test_public_core_agent_exports_only_the_existing_class(public_first):
    """Public exports retain class identity without aliasing entire modules."""
    paths = ("nexent.core.agents.core_agent", "nexent.core.agents.execution.code.legacy_agent")
    run_isolated(f"""
import importlib
first, second = {paths if public_first else paths[::-1]!r}
importlib.import_module(first)
importlib.import_module(second)
public = importlib.import_module({paths[0]!r})
implementation = importlib.import_module({paths[1]!r})
from nexent.core.agents import CoreAgent
assert public is not implementation
assert public.CoreAgent is implementation.CoreAgent is CoreAgent
assert public.__all__ == ['CoreAgent']
assert not hasattr(public, 'convert_code_format')
assert not hasattr(public, 'AgentExecutionError')
""")


@pytest.mark.parametrize("name", REMOVED_MODULES)
def test_removed_internal_paths_are_not_importable(name):
    """Internal imports cannot silently fall back to compatibility modules."""
    run_isolated(f"""
import importlib
try:
    importlib.import_module({name!r})
except ModuleNotFoundError as exc:
    assert {name!r}.startswith(exc.name)
else:
    raise AssertionError('removed internal module still importable')
""")


def test_relocated_packages_do_not_load_codeagent_or_context_manager():
    run_isolated("""
import importlib
import sys
for name in ('nexent.core.agents.execution', 'nexent.core.agents.execution.code',
             'nexent.core.agents.resources'):
    importlib.import_module(name)
for name in ('nexent.core.agents.execution.code.legacy_agent',
             'nexent.core.agents.core_agent', 'nexent.core.agents.context.manager'):
    assert name not in sys.modules, name
from nexent.core.agents import AgentConfig
assert 'nexent.core.agents.execution.code.legacy_agent' not in sys.modules
""")


def test_gateway_registration_and_request_serialization_use_canonical_classes():
    run_isolated("""
import pickle
from nexent.core.gateway import get_registry, modality
from nexent.core.gateway.llm.adapter import LLMRequest
from nexent.core.gateway.llm.providers.openai import OpenAILLMAdapter, OpenAILongContextLLMAdapter
registry = get_registry()
assert registry.resolve('openai', 'llm') is OpenAILLMAdapter
assert registry.resolve('openai', 'llm_long_context') is OpenAILongContextLLMAdapter
assert modality.LLMRequest is LLMRequest
request = LLMRequest(messages=[{'role': 'user', 'content': 'hello'}], kwargs={'temperature': 0})
assert pickle.loads(pickle.dumps(request)) == request
""")
