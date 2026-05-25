"""Golden test: assembled system prompt must equal old Jinja2-rendered prompt.

Refactor `refactor/context-management` (commit 790d3ea2) routes system-prompt
assembly through ContextManager.build_system_prompt() instead of feeding the
Jinja2-rendered string straight to CoreAgent. The design intent is that the
move is behavior-preserving: whatever the Jinja2 template produced before,
the component path must produce the same string after.

Two tests:

* ``test_system_prompt_component_roundtrip`` - the minimal "搬家无损" check.
  Wrap the Jinja2 output in one SystemPromptComponent, register, build,
  join, assert byte-identical. This is what the colleague's refactor MUST
  satisfy. If this fails the component plumbing itself is broken
  (deduplication / strategy filtering / role filtering).

* ``test_full_build_context_components_matches_jinja2`` - the diagnostic.
  Runs the *current* ``backend/utils/context_utils.build_context_components``
  on the same inputs and compares its assembled output to Jinja2. This is
  EXPECTED to fail today - the diff IS the work-list of "what the new
  components still need to cover to match the old prompt".

Run from refactor/context-management branch:

    pytest test/sdk/core/agents/test_prompt_equivalence.py -v -s
"""

from __future__ import annotations

import difflib
import os
import sys
from typing import Any, Dict, List

import pytest


# ---------------------------------------------------------------------------
# Path setup - test runs from any cwd, finds repo root via this file
# ---------------------------------------------------------------------------

_HERE = os.path.abspath(os.path.dirname(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
for _p in (
    _REPO_ROOT,
    os.path.join(_REPO_ROOT, "sdk"),
    os.path.join(_REPO_ROOT, "backend"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Branch gating - skip cleanly on branches without the refactor symbols
# ---------------------------------------------------------------------------

try:
    from jinja2 import StrictUndefined, Template
except ImportError as exc:
    pytest.skip(f"jinja2 unavailable: {exc}", allow_module_level=True)

try:
    from nexent.core.agents.agent_context import ContextManager
    from nexent.core.agents.summary_config import ContextManagerConfig
    from nexent.core.agents.agent_model import SystemPromptComponent
except ImportError as exc:
    pytest.skip(
        f"Refactor symbols not importable ({exc}); this test must run on "
        "refactor/context-management or a descendant.",
        allow_module_level=True,
    )

try:
    from utils.prompt_template_utils import get_agent_prompt_template
except ImportError as exc:
    pytest.skip(f"backend.utils.prompt_template_utils unavailable: {exc}",
                allow_module_level=True)

try:
    from utils.context_utils import build_context_components
except ImportError:
    build_context_components = None  # diagnostic test will skip itself


# ---------------------------------------------------------------------------
# Representative agent inputs - mirror the shape of render_kwargs built by
# backend/agents/create_agent_info.py:386 so the Jinja2 render call is exactly
# what production would have produced.
# ---------------------------------------------------------------------------

class _ToolStub:
    """ToolConfig-like duck type matching attrs read by Jinja2 + format helpers."""

    def __init__(self, name: str, description: str, inputs: str,
                 output_type: str, source: str = "local"):
        self.name = name
        self.description = description
        self.inputs = inputs
        self.output_type = output_type
        # Template branches on tool.source ('mcp' vs others).
        self.source = source


class _ManagedAgentStub:
    """managed_agents entry duck type."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description


@pytest.fixture
def render_kwargs() -> Dict[str, Any]:
    tools = [
        _ToolStub("wiki_search", "Search Wikipedia for a query",
                  "query: str", "str"),
        _ToolStub("calculator", "Evaluate a math expression",
                  "expr: str", "float"),
    ]
    managed_agents = [
        _ManagedAgentStub("researcher", "Sub-agent specialised in deep research"),
    ]
    return {
        "duty": "Help the user answer factual questions accurately.",
        "constraint": "Cite sources when possible. Do not fabricate.",
        "few_shots": "Q: capital of France?\nA: Paris.",
        "tools": {t.name: t for t in tools},
        "skills": [{"name": "summarize", "description": "Distill long text"}],
        "managed_agents": {m.name: m for m in managed_agents},
        "external_a2a_agents": {},
        "APP_NAME": "Nexent",
        "APP_DESCRIPTION": "Nexent is an open-source agent SDK",
        "memory_list": [
            {"memory": "User prefers concise answers.",
             "memory_level": "user", "score": 0.92},
            {"memory": "User's timezone is UTC+8.",
             "memory_level": "user", "score": 0.81},
        ],
        "knowledge_base_summary": "KB covers French history (1789-1815).",
        # Frozen so the diff between runs is reproducible.
        "time": "2026-05-25 09:00:00",
        "user_id": "user-001",
    }


# ---------------------------------------------------------------------------
# Helpers - the two rendering paths under comparison
# ---------------------------------------------------------------------------

def _render_jinja2(render_kwargs: Dict[str, Any],
                   is_manager: bool, language: str = "zh") -> str:
    """Reproduce the exact rendering done by create_agent_info.py:402."""
    template = get_agent_prompt_template(is_manager=is_manager, language=language)
    return Template(template["system_prompt"],
                    undefined=StrictUndefined).render(render_kwargs)


def _render_via_component(jinja2_prompt: str) -> str:
    """Wrap Jinja2 output in SystemPromptComponent, run full assembly, join.

    Reproduces what CoreAgent.initialize_system_prompt does post-refactor:
        components -> build_system_prompt() -> filter role=system -> join.

    Token budgets are set high enough that TokenBudgetStrategy cannot drop
    anything - we are testing plumbing fidelity, not budget pruning.
    """
    component = SystemPromptComponent(content=jinja2_prompt)
    cm_config = ContextManagerConfig(
        enabled=True,
        token_threshold=10**6,
        component_budgets={
            "system_prompt": 10**6,
            "tools": 10**6,
            "skills": 10**6,
            "memory": 10**6,
            "knowledge_base": 10**6,
            "managed_agents": 10**6,
            "external_a2a_agents": 10**6,
            "conversation_history": 10**6,
        },
    )
    cm = ContextManager(config=cm_config)
    cm.register_component(component)
    messages = cm.build_system_prompt()
    return "\n\n".join(
        msg.get("content", "")
        for msg in messages
        if msg.get("role") == "system"
    )


def _render_via_build_context_components(rk: Dict[str, Any],
                                          system_prompt: str) -> str:
    """Run the production-facing build_context_components path and join.

    Mirrors backend/agents/create_agent_info.py: render Jinja2 first, then
    pass the rendered string into build_context_components so it emits a
    single SystemPromptComponent. The whole point of the migration phase is
    that this round-trip stays byte-identical to the Jinja2 baseline.
    """
    components = build_context_components(
        system_prompt=system_prompt,
        tools=rk["tools"],
        skills=rk["skills"],
        managed_agents=rk["managed_agents"],
        external_a2a_agents=rk["external_a2a_agents"],
        memory_list=rk["memory_list"],
        memory_search_query=None,
        knowledge_base_summary=rk["knowledge_base_summary"],
        app_name=rk["APP_NAME"],
        app_description=rk["APP_DESCRIPTION"],
        user_id=rk["user_id"],
    )
    cm_config = ContextManagerConfig(
        enabled=True,
        token_threshold=10**6,
        component_budgets={k: 10**6 for k in (
            "system_prompt", "tools", "skills", "memory",
            "knowledge_base", "managed_agents", "external_a2a_agents",
            "conversation_history",
        )},
    )
    cm = ContextManager(config=cm_config)
    for c in components:
        cm.register_component(c)
    messages = cm.build_system_prompt()
    return "\n\n".join(
        msg.get("content", "")
        for msg in messages
        if msg.get("role") == "system"
    )


def _format_diff(expected: str, actual: str,
                 expected_name: str, actual_name: str,
                 max_lines: int = 200) -> str:
    diff_lines = list(difflib.unified_diff(
        expected.splitlines(),
        actual.splitlines(),
        fromfile=expected_name,
        tofile=actual_name,
        lineterm="",
        n=3,
    ))
    truncated = diff_lines[:max_lines]
    suffix = "" if len(diff_lines) <= max_lines \
        else f"\n... [diff truncated, {len(diff_lines) - max_lines} more lines]"
    return "\n".join(truncated) + suffix


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("is_manager", [True, False], ids=["manager", "managed"])
@pytest.mark.parametrize("language", ["zh", "en"])
def test_system_prompt_component_roundtrip(render_kwargs, is_manager, language):
    """Wrap Jinja2 output in SystemPromptComponent, ensure no loss through CM.

    A failure here means the ContextManager component machinery itself is
    not behavior-preserving (deduplication mangles content, role filter
    drops the message, strategy refuses to select it, ...).
    """
    rk = dict(render_kwargs)
    if not is_manager:
        # Managed (sub-) agents render with a different template and no
        # managed_agents entries of their own.
        rk["managed_agents"] = {}

    expected = _render_jinja2(rk, is_manager=is_manager, language=language)
    actual = _render_via_component(expected)

    if expected != actual:
        pytest.fail(
            "SystemPromptComponent round-trip FAILED "
            f"(is_manager={is_manager}, language={language}).\n"
            f"  jinja2  length: {len(expected)} chars\n"
            f"  via-CM  length: {len(actual)} chars\n"
            f"--- DIFF (expected jinja2 vs actual via-CM) ---\n"
            + _format_diff(expected, actual, "jinja2", "via_component")
        )


@pytest.mark.skipif(
    build_context_components is None,
    reason="backend.utils.context_utils not importable",
)
@pytest.mark.parametrize("is_manager", [True, False], ids=["manager", "managed"])
def test_full_build_context_components_matches_jinja2(render_kwargs, is_manager):
    """End-to-end equivalence via the production-facing API.

    Mirrors create_agent_info.py: render Jinja2, then hand the rendered
    string to build_context_components(system_prompt=...). The assembled
    output through ContextManager must equal the Jinja2 baseline. If this
    test fails it means the behaviour-preserving migration path itself is
    broken; pipe-wise component coverage is tracked separately.
    """
    rk = dict(render_kwargs)
    if not is_manager:
        rk["managed_agents"] = {}

    expected = _render_jinja2(rk, is_manager=is_manager, language="zh")
    actual = _render_via_build_context_components(rk, system_prompt=expected)

    if expected != actual:
        pytest.fail(
            "build_context_components output does NOT match Jinja2 baseline "
            f"(is_manager={is_manager}).\n"
            f"  jinja2     length: {len(expected)} chars\n"
            f"  components length: {len(actual)} chars\n"
            "The migration path (system_prompt=... -> single "
            "SystemPromptComponent) is regressing.\n"
            "--- DIFF (expected jinja2 vs actual components) ---\n"
            + _format_diff(expected, actual, "jinja2", "build_context_components")
        )


# ---------------------------------------------------------------------------
# Standalone runner - useful when pytest is heavyweight to invoke
#   python test/sdk/core/agents/test_prompt_equivalence.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    rk = {
        "duty": "Help the user answer factual questions accurately.",
        "constraint": "Cite sources when possible. Do not fabricate.",
        "few_shots": "Q: capital of France?\nA: Paris.",
        "tools": {
            "wiki_search": _ToolStub("wiki_search", "Search Wikipedia",
                                     "query: str", "str"),
            "calculator": _ToolStub("calculator", "Evaluate a math expression",
                                    "expr: str", "float"),
        },
        "skills": [{"name": "summarize", "description": "Distill long text"}],
        "managed_agents": {
            "researcher": _ManagedAgentStub("researcher", "Deep research sub-agent"),
        },
        "external_a2a_agents": {},
        "APP_NAME": "Nexent",
        "APP_DESCRIPTION": "Nexent is an open-source agent SDK",
        "memory_list": [
            {"memory": "User prefers concise answers.",
             "memory_level": "user", "score": 0.92},
        ],
        "knowledge_base_summary": "KB covers French history (1789-1815).",
        "time": "2026-05-25 09:00:00",
        "user_id": "user-001",
    }

    print("\n[1/2] SystemPromptComponent round-trip ...")
    expected = _render_jinja2(rk, is_manager=True, language="zh")
    actual = _render_via_component(expected)
    if expected == actual:
        print("    PASS - component machinery is loss-less.")
    else:
        print("    FAIL - diff:")
        print(_format_diff(expected, actual, "jinja2", "via_component"))

    if build_context_components is not None:
        print("\n[2/2] Full build_context_components vs Jinja2 ...")
        actual = _render_via_build_context_components(rk, system_prompt=expected)
        if expected == actual:
            print("    PASS - components now cover the full Jinja2 prompt.")
        else:
            print(f"    FAIL - "
                  f"jinja2={len(expected)}c, components={len(actual)}c")
            print(_format_diff(expected, actual, "jinja2",
                               "build_context_components",
                               max_lines=80))
    else:
        print("\n[2/2] SKIPPED - backend.utils.context_utils not importable.")
