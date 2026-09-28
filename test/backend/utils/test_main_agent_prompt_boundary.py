"""Static boundary checks for the main-Agent production prompt path."""

from pathlib import Path


def test_ut_be_fps_015_main_agent_backend_does_not_load_prompt_fragments():
    """UT-BE-FPS-015: Backend passes facts and switches to SDK composition."""
    root = Path(__file__).parents[3]
    sources = {
        relative: (root / relative).read_text(encoding="utf-8")
        for relative in (
            "backend/agents/create_agent_info.py",
            "backend/services/knowledge_scope_service.py",
            "backend/utils/context_utils.py",
            "backend/utils/memory_tool_prompt.py",
            "backend/utils/automation_tool_prompt.py",
            "backend/management/services/agent/prompt_template_loader.py",
        )
    }
    assert all("load_prompt(" not in source for source in sources.values())
    create_source = sources["backend/agents/create_agent_info.py"]
    assert "enable_memory_tool_policy=enable_memory_tool_policy" in create_source
    assert "enable_automation_tool_policy=enable_automation_tool_policy" in create_source
    assert "knowledge_scope=(runtime_knowledge_context or {}).get(\"scope\")" in create_source
    assert "knowledge_base_summaries=knowledge_base_summaries" in create_source
