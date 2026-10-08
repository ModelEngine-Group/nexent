"""Verify relocated modules retain legacy imports and shared runtime identity."""

import subprocess
import sys

import pytest


MODULE_PAIRS = [
    ("nexent.core.agents.core_agent", "nexent.core.agents.execution.code.legacy_agent", "CoreAgent"),
    ("nexent.core.agents.managed_mcp", "nexent.core.agents.resources.managed_mcp", "ManagedMCPToolCollection"),
    ("nexent.core.agents.tool_user_context", "nexent.core.agents.resources.tool_user_context", "USER_CONTEXT_FIELDS"),
    ("nexent.core.gateway.modality.llm.llm_adapter", "nexent.core.gateway.llm.adapter", "LLMRequest"),
    ("nexent.core.gateway.modality.llm.openai", "nexent.core.gateway.llm.providers.openai", "OpenAILLMAdapter"),
]


@pytest.mark.parametrize("old,new,symbol", MODULE_PAIRS)
@pytest.mark.parametrize("legacy_first", [True, False])
def test_legacy_import_and_patch_share_one_implementation(old, new, symbol, legacy_first):
    """Import order cannot duplicate types, state or patch lookup sites."""
    code = f"""
import importlib
from unittest.mock import patch
first, second = { (old, new) if legacy_first else (new, old)!r}
importlib.import_module(first)
importlib.import_module(second)
legacy = importlib.import_module({old!r})
canonical = importlib.import_module({new!r})
assert legacy is canonical
assert getattr(legacy, {symbol!r}) is getattr(canonical, {symbol!r})
original = getattr(canonical, {symbol!r})
marker = object()
with patch({(old + '.' + symbol)!r}, marker):
    assert getattr(canonical, {symbol!r}) is marker
assert getattr(canonical, {symbol!r}) is original
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_relocated_packages_do_not_load_codeagent_or_context_manager():
    """Package discovery stays safe for future engine/resource factories."""
    code = """
import importlib
import sys
for name in ('nexent.core.agents.execution', 'nexent.core.agents.execution.code',
             'nexent.core.agents.resources'):
    importlib.import_module(name)
for name in ('nexent.core.agents.execution.code.legacy_agent',
             'nexent.core.agents.core_agent',
             'nexent.core.agents.context.manager'):
    assert name not in sys.modules, name
from nexent.core.agents import AgentConfig
assert 'nexent.core.agents.execution.code.legacy_agent' not in sys.modules
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_gateway_registration_uses_canonical_classes_without_duplicates():
    """Legacy and new paths share the same adapter registration and request type."""
    code = """
import importlib
import pickle
from nexent.core.gateway import get_registry, modality
from nexent.core.gateway.llm.adapter import LLMRequest
from nexent.core.gateway.llm.providers.openai import OpenAILLMAdapter, OpenAILongContextLLMAdapter
registry = get_registry()
before = registry.list_adapters()
importlib.import_module('nexent.core.gateway.modality.llm.openai')
assert registry.list_adapters() == before
assert registry.resolve('openai', 'llm') is OpenAILLMAdapter
assert registry.resolve('openai', 'llm_long_context') is OpenAILongContextLLMAdapter
assert modality.LLMRequest is LLMRequest
request = LLMRequest(messages=[{'role': 'user', 'content': 'hello'}], kwargs={'temperature': 0})
assert pickle.loads(pickle.dumps(request)) == request
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
