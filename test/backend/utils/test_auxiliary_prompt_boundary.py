"""UT-BE-FPS-016: auxiliary model entry points delegate prompt assembly to SDK."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PRODUCTION_PATHS = (
    "backend/services/prompt_service.py",
    "backend/management/services/agent/naming.py",
    "backend/utils/prompt_template_utils.py",
    "backend/agents/nl2agent_agent.py",
    "backend/services/prompt_template_service.py",
    "backend/services/conversation_management_service.py",
    "backend/services/agent_automation/intent_analyzer.py",
    "backend/services/agent_automation/prompt_generator.py",
    "backend/services/agent_evaluation_service.py",
    "backend/services/evaluation_set_service.py",
    "backend/services/evaluator_service.py",
    "backend/utils/document_vector_utils.py",
    "backend/services/fa_memory_extractor.py",
    "backend/services/memory_dreaming_summarizer.py",
    "backend/utils/agent_profile_utils.py",
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
        assert "nexent.core.agents.prompt." in source, relative_path


def test_ut_be_fps_018_backend_imports_only_current_assembly_modules():
    """Backend callers use the new assembly package without old-path shims."""
    old_modules = (
        "nexent.core.prompts.auxiliary",
        "nexent.core.prompts.meta",
        "nexent.core.prompts.evaluation",
        "nexent.core.prompts.user_context",
    )
    for path in (ROOT / "backend").rglob("*.py"):
        source = path.read_text(encoding="utf-8-sig")
        assert not any(module in source for module in old_modules), path
    direct_callers = {
        "backend/services/evaluation_set_service.py": "nexent.core.agents.prompt.evaluation",
        "backend/utils/document_vector_utils.py": "nexent.core.agents.prompt.document",
        "backend/services/fa_memory_extractor.py": "nexent.core.agents.prompt.memory",
        "backend/agents/create_agent_info.py": "nexent.core.agents.prompt.user_context",
    }
    for path, module in direct_callers.items():
        assert module in (ROOT / path).read_text(encoding="utf-8-sig")
