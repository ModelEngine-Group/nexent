"""UT-SDK-FPS-037: prompt assembly code has one functional home."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
RESOURCE_PACKAGE = ROOT / "sdk/nexent/core/prompts"
ASSEMBLY_PACKAGE = ROOT / "sdk/nexent/core/agents/prompt"


def test_ut_sdk_fps_037_resource_package_has_no_assembly_modules():
    assert sorted(path.name for path in RESOURCE_PACKAGE.glob("*.py")) == ["__init__.py"]


def test_ut_sdk_fps_037_assembly_functions_are_grouped_by_purpose():
    expected = {
        "auxiliary.py": {"compose_auxiliary_prompt", "render_auxiliary_field"},
        "meta.py": {"compose_agent_generation_user", "compose_nl2skill"},
        "evaluation.py": {"compose_evaluation_set_cases", "format_agent_profile_context"},
        "document.py": {"compose_document_cluster_summary"},
        "memory.py": {"compose_memory_prompt"},
        "user_context.py": {"render_user_context", "has_current_time_marker"},
    }
    for filename, names in expected.items():
        source = (ASSEMBLY_PACKAGE / filename).read_text(encoding="utf-8")
        actual = {
            node.name for node in ast.parse(source).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert names <= actual
