"""D1 checks that Backend resolves SDK resources without type aliases."""

import ast
from pathlib import Path

ROOT = Path(__file__).parents[3]


def test_ut_be_fps_005_backend_has_no_generic_template_type_adapter():
    """UT-BE-FPS-005: Backend call sites name actual SDK resources."""
    source = (ROOT / "backend/utils/prompt_template_utils.py").read_text(encoding="utf-8")
    assert "def get_prompt_template(" not in source
    assert "load_prompt_template" not in source

    for file in (ROOT / "backend").rglob("*.py"):
        if file == ROOT / "backend/utils/prompt_template_utils.py":
            continue
        text = file.read_text(encoding="utf-8")
        assert "get_prompt_template(" not in text, file


def test_ut_be_fps_005_business_helpers_keep_field_merging():
    """UT-BE-FPS-005: template-field merging remains Backend business logic."""
    from utils.prompt_template_utils import merge_prompt_generate_templates

    assert merge_prompt_generate_templates(
        {"duty_system_prompt": "custom"}, {"duty_system_prompt": "default", "user_prompt": "user"},
    )["duty_system_prompt"] == "custom"


def test_ut_be_fps_006_production_prompt_loads_use_relative_paths():
    """UT-BE-FPS-006: each production call uses the two-argument API."""
    for root in (ROOT / "backend", ROOT / "sdk/nexent/core"):
        for file in root.rglob("*.py"):
            tree = ast.parse(file.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                if node.func.id == "load_prompt":
                    assert len(node.args) == 2, f"{file}:{node.lineno}"


def test_ut_be_fps_007_production_calls_use_new_prompt_layout():
    """UT-BE-FPS-007: production paths no longer name retired resource folders."""
    obsolete = (
        '"generation/', '"skill/', '"agent/managed"', '"agent/manager"',
        '"agent/nl2agent"', '"meta/nl2skills_',
    )
    for root in (ROOT / "backend", ROOT / "sdk/nexent/core"):
        for file in root.rglob("*.py"):
            source = file.read_text(encoding="utf-8-sig")
            if "load_prompt" not in source:
                continue
            for old_path in obsolete:
                assert old_path not in source, (file, old_path)
