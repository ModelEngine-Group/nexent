"""The request-time marker follows the page language and remains removable."""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import sys
import types

import pytest


@pytest.fixture
def time_context(monkeypatch):
    root = Path(__file__).resolve().parents[3]
    prompts_root = root / "sdk/nexent/core/prompts"
    prompt_spec = importlib.util.spec_from_file_location(
        "_time_context_prompt_package", prompts_root / "__init__.py",
        submodule_search_locations=[str(prompts_root)],
    )
    assert prompt_spec is not None and prompt_spec.loader is not None
    prompt_package = importlib.util.module_from_spec(prompt_spec)
    monkeypatch.setitem(sys.modules, prompt_spec.name, prompt_package)
    prompt_spec.loader.exec_module(prompt_package)

    user_spec = importlib.util.spec_from_file_location(
        "nexent.core.agents.prompt.user_context", root / "sdk/nexent/core/agents/prompt/user_context.py",
    )
    assert user_spec is not None and user_spec.loader is not None
    user_module = importlib.util.module_from_spec(user_spec)
    monkeypatch.setitem(sys.modules, user_spec.name, user_module)
    monkeypatch.setitem(sys.modules, "nexent", types.ModuleType("nexent"))
    monkeypatch.setitem(sys.modules, "nexent.core", types.ModuleType("nexent.core"))
    agents_package = types.ModuleType("nexent.core.agents")
    agents_package.__path__ = []
    monkeypatch.setitem(sys.modules, "nexent.core.agents", agents_package)
    assembly_package = types.ModuleType("nexent.core.agents.prompt")
    assembly_package.__path__ = []
    monkeypatch.setitem(sys.modules, "nexent.core.agents.prompt", assembly_package)
    monkeypatch.setitem(sys.modules, "nexent.core.prompts", prompt_package)
    user_spec.loader.exec_module(user_module)

    spec = importlib.util.spec_from_file_location("_time_context_test_module", root / "backend/utils/time_context_utils.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("language,marker", [("zh", "[当前时间:"), ("en", "[Current time:")])
def test_time_marker_uses_page_language_and_is_stripped(time_context, language, marker):
    query = time_context.prepend_current_time(
        "question", "Asia/Shanghai", now=datetime(2026, 9, 28, tzinfo=timezone.utc), language=language,
    )
    assert query.startswith("question\n\n" + marker)
    assert time_context.strip_current_time_prefix(query) == "question"
    assert time_context.prepend_current_time(query, "Asia/Shanghai", language=language) == query


@pytest.mark.parametrize("language,marker", [("en", "Current time"), ("zh", "当前时间")])
def test_time_context_keeps_workspace_last_and_strips_runtime_time(time_context, language, marker):
    request = "question\n\nRun workspace: /run/1"
    result = time_context.prepend_current_time(
        request, "Asia/Shanghai", now=datetime(2026, 10, 9, tzinfo=timezone.utc), language=language,
    )
    assert result == f"question\n\n[{marker}: 2026-10-09 08:00:00]\n\nRun workspace: /run/1"
    assert time_context.strip_current_time_prefix(result) == request
    assert time_context.prepend_current_time(result, "Asia/Shanghai", language=language) == result
