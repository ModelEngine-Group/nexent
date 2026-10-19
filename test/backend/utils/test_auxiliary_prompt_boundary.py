# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""UT-BE-FPS-016: auxiliary model entry points delegate prompt assembly to SDK."""

import ast
from pathlib import Path

from test.common.source_files import iter_project_python_files


ROOT = Path(__file__).resolve().parents[3]
PRODUCTION_PATHS = (
    "backend/management/services/agent/prompt_generation.py",
    "backend/management/services/agent/naming.py",
    "backend/management/services/agent/prompt.py",
    "backend/agents/nl2agent_agent.py",
    "backend/management/services/agent/prompt_templates.py",
    "backend/management/services/conversation/service.py",
    "backend/management/services/automation/intent.py",
    "backend/management/services/automation/prompt.py",
    "backend/management/services/evaluation/runs.py",
    "backend/management/services/evaluation/sets.py",
    "backend/management/services/evaluation/evaluators.py",
    'backend/management/services/knowledge_base/summary.py',
    "backend/management/services/memory/extraction.py",
    "backend/management/services/memory/dreaming/summarizer.py",
    "backend/management/services/agent/profile.py",
)


def test_auxiliary_entries_do_not_load_yaml_or_render_jinja_in_backend():
    for relative_path in PRODUCTION_PATHS:
        tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8-sig"))
        imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert not any(node.module == "jinja2" for node in imports), relative_path
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        assert not any(
            isinstance(node.func, ast.Name) and node.func.id == "load_prompt"
            for node in calls
        ), relative_path


def test_auxiliary_entries_use_sdk_composers():
    for relative_path in PRODUCTION_PATHS:
        source = (ROOT / relative_path).read_text(encoding="utf-8-sig")
        assert "nexent.core.agents.prompt" in source, relative_path


def test_ut_be_fps_018_backend_imports_only_current_assembly_modules():
    """Backend callers use the new assembly package without old-path shims."""
    old_modules = (
        "nexent.core.prompts.auxiliary",
        "nexent.core.prompts.meta",
        "nexent.core.prompts.evaluation",
        "nexent.core.prompts.user_context",
    )
    for path in iter_project_python_files(ROOT / "backend"):
        source = path.read_text(encoding="utf-8-sig")
        assert not any(module in source for module in old_modules), path
    direct_callers = {
        "backend/management/services/evaluation/sets.py": "nexent.core.agents.prompt.evaluation",
        'backend/management/services/knowledge_base/summary.py': "nexent.core.agents.prompt.document",
        "backend/management/services/memory/extraction.py": "nexent.core.agents.prompt.memory",
        "backend/agents/create_agent_info.py": "nexent.core.agents.prompt.user_context",
    }
    for path, module in direct_callers.items():
        assert module in (ROOT / path).read_text(encoding="utf-8-sig")
