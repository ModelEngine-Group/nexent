"""Auxiliary model requests are assembled from SDK-owned resources."""

import importlib
import importlib.util
from pathlib import Path
import sys
import types

import pytest


PROMPTS_ROOT = Path(__file__).resolve().parents[4] / "sdk/nexent/core/prompts"
ASSEMBLY_ROOT = PROMPTS_ROOT.parent / "agents/prompt"
PREFIX = "_auxiliary_prompt_test_package"
for name in (PREFIX, f"{PREFIX}.core", f"{PREFIX}.core.agents"):
    module = types.ModuleType(name)
    module.__path__ = []
    sys.modules[name] = module
spec = importlib.util.spec_from_file_location(
    f"{PREFIX}.core.prompts", PROMPTS_ROOT / "__init__.py",
    submodule_search_locations=[str(PROMPTS_ROOT)],
)
assert spec is not None and spec.loader is not None
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
assembly = types.ModuleType(f"{PREFIX}.core.agents.prompt")
assembly.__path__ = [str(ASSEMBLY_ROOT)]
sys.modules[assembly.__name__] = assembly
auxiliary = importlib.import_module(f"{assembly.__name__}.auxiliary")
meta = importlib.import_module(f"{assembly.__name__}.meta")
evaluation = importlib.import_module(f"{assembly.__name__}.evaluation")
document = importlib.import_module(f"{assembly.__name__}.document")
memory = importlib.import_module(f"{assembly.__name__}.memory")

compose_auxiliary_prompt = auxiliary.compose_auxiliary_prompt
compose_analysis_report = evaluation.compose_analysis_report
compose_evaluation_case_context_blocks = evaluation.compose_evaluation_case_context_blocks
compose_evaluation_kb_context = evaluation.compose_evaluation_kb_context
compose_evaluation_set_cases = evaluation.compose_evaluation_set_cases
compose_evaluation_set_system = evaluation.compose_evaluation_set_system
evaluation_case_sources = evaluation.evaluation_case_sources
compose_document_cluster_summary = document.compose_document_cluster_summary
compose_evaluator_generation = evaluation.compose_evaluator_generation
compose_evaluator_run_prompt = evaluation.compose_evaluator_run_prompt
compose_memory_prompt = memory.compose_memory_prompt
format_dreaming_source = memory.format_dreaming_source
render_evaluation_section = evaluation.render_evaluation_section
compose_agent_generation_user = meta.compose_agent_generation_user
compose_agent_optimization = meta.compose_agent_optimization
compose_name_regeneration = meta.compose_name_regeneration
compose_nl2skill = meta.compose_nl2skill
default_section_title = meta.default_section_title
append_optimization_scope_instruction = meta.append_optimization_scope_instruction
format_agent_profile_context = evaluation.format_agent_profile_context


@pytest.mark.parametrize("language", ["zh", "en"])
def test_chat_title_is_rendered_in_sdk(language):
    prompt = compose_auxiliary_prompt(
        language, "chat_title", {"question": "How do I reset my password?"}
    )
    assert "How do I reset my password?" in prompt.user
    assert prompt.system
    assert "{{" not in prompt.user


def test_missing_variable_is_an_error():
    with pytest.raises(Exception):
        compose_auxiliary_prompt("en", "chat_title", {})


def test_automation_intent_renders_runtime_values():
    prompt = compose_auxiliary_prompt(
        "en", "automation_intent", {
            "message": "Remind me tomorrow",
            "current_datetime": "2026-09-24T12:00:00",
            "timezone": "Asia/Shanghai",
            "min_interval_seconds": 60,
        }
    )
    assert "Remind me tomorrow" in prompt.user
    assert "2026-09-24" in prompt.user


def test_custom_override_keeps_its_fields():
    prompt = compose_auxiliary_prompt(
        "en", "chat_title", {"question": "hello"},
        override={"SYSTEM_PROMPT": "Custom", "USER_PROMPT": "Title {{question}}"},
    )
    assert prompt.system == "Custom"
    assert prompt.user == "Title hello"


@pytest.mark.parametrize("language", ["zh", "en"])
def test_agent_generation_resources_and_knowledge_scope(language):
    result = compose_agent_generation_user(
        language, {"user_prompt": "{{tool_description}}\n{{assistant_description}}"},
        task_description="task",
        tools=[{"name": "search", "description": "find", "inputs": "query", "output_type": "str"}],
        worker_agents=[{"name": "worker", "description": "delegate"}],
        has_local_knowledge_tool=True,
        has_aidp_knowledge_tool=False,
        has_selected_resources=True,
    )
    assert "search" in result and "worker" in result
    assert "index_names" in result


def test_optimization_has_both_messages():
    prompt = compose_agent_optimization(
        "en", section_type="duty", section_title="Role",
        task_description="task", current_content="current", feedback="improve",
        tools=[], worker_agents=[], has_local_knowledge_tool=False,
        has_aidp_knowledge_tool=False,
    )
    assert prompt.system and "current" in prompt.user


def test_evaluator_request_selects_variant_without_rendering_literal_examples():
    plain = compose_evaluator_generation("en", "accuracy")
    scoped = compose_evaluator_generation("en", "accuracy", "Agent profile")
    assert "Generate an evaluator based" in plain.user
    assert "Agent profile" in scoped.user
    assert "{{actual}}" in scoped.system


def test_document_reduce_formats_entries():
    prompt = compose_document_cluster_summary("en", ["one", "two"], 50)
    assert "Document 1: one" in prompt.user
    assert "Document 2: two" in prompt.user


def test_memory_uses_original_format_placeholders():
    prompt = compose_memory_prompt(
        "memory_extraction", {"final_answer": "Done", "user_query": "Question"}
    )
    assert "Done" in prompt.user and "Question" in prompt.user
    assert "## Map Summary 2" in format_dreaming_source(
        "map_summary", {"index": 2, "content": "Content"}
    )


def test_evaluator_run_uses_selected_template_and_history():
    result = compose_evaluator_run_prompt(
        "Q={{query}}; A={{actual}}; R={{runtime_stats}}",
        query="Question", expected="Expected", actual="Actual",
        runtime_context="Step 1", conversation_history=[
            {"role": "user", "content": "Earlier"},
            {"role": "assistant", "content": "Reply"},
        ],
    )
    assert result.startswith("## Previous Conversation Turns\nUser: Earlier\nAgent: Reply\n\n")
    assert result.endswith("Q=Question; A=Actual; R=Step 1")


def test_evaluation_sections_have_matching_language_keys():
    assert render_evaluation_section("zh", "scene", {"description": "退货"}) == "## 场景描述\n退货"
    assert render_evaluation_section("en", "analysis_case", {"index": 1, "query": "Q"}) == "Case 1: Q=Q"


@pytest.mark.parametrize("language", ["zh", "en"])
def test_evaluation_case_evidence_is_ordered_and_truncated_in_sdk(language):
    blocks = compose_evaluation_case_context_blocks(
        language, agent_block="AGENT", description="Return order",
        kb_block="KNOWLEDGE", file_name="policy.txt",
        file_content="x" * 3001,
    )
    assert blocks[0] == "AGENT"
    assert "Return order" in blocks[1]
    assert blocks[2] == "KNOWLEDGE"
    assert "policy.txt" in blocks[3]
    assert "x" * 3000 in blocks[3]
    assert "x" * 3001 not in blocks[3]


def test_evaluation_kb_context_and_sources_include_only_available_evidence():
    assert "retrieved" in compose_evaluation_kb_context(
        "en", kb_context="retrieved", kb_names="ignored"
    )
    assert "catalog" in compose_evaluation_kb_context(
        "en", kb_context="", kb_names="catalog"
    )
    assert compose_evaluation_kb_context("en", kb_context="", kb_names="") == ""
    sources = evaluation_case_sources("en", has_kb=True, has_agent=False, has_file=True)
    assert "knowledge" in sources.lower()
    assert "reference document" in sources.lower()
    assert "agent" not in sources.lower()


def test_evaluation_set_system_matches_complete_sdk_request():
    prompt = compose_evaluation_set_cases(
        "zh", context_blocks=["EVIDENCE"], count=3,
        sources="场景描述", max_turns=5,
    )
    assert prompt.system == compose_evaluation_set_system("zh", max_turns=5)
    assert "5" in prompt.system
    assert "EVIDENCE" in prompt.user


def test_structured_profile_formats_only_available_resources():
    profile = {
        "name": "Example", "description": "", "duty_prompt": "Help",
        "constraint_prompt": "", "business_description": "",
        "tools": [{"name": "search", "source": "remote", "description": "Finds pages"}],
        "skills": [{"name": "research", "description": ""}],
        "sub_agents": [], "knowledge_bases": [],
    }
    result = format_agent_profile_context(profile)
    assert result.startswith("## Agent Configuration\n### Agent: Example")
    assert "Tools: search [REMOTE]: Finds pages" in result
    assert "Skills: research" in result
    assert "Sub-agents:" not in result


def test_optimization_titles_and_scope_instruction_are_sdk_owned():
    assert default_section_title("zh", "duty") == "智能体角色"
    assert default_section_title("en", "few_shots") == "Few Shots"
    assert default_section_title("unknown", "duty") == "智能体角色"
    result = append_optimization_scope_instruction("Improve this", "en")
    assert result.startswith("Improve this\n\n")
    assert "index_names" in result


def test_name_regeneration_honors_selected_user_template_and_default():
    custom = compose_name_regeneration(
        "en", {
            "agent_name_regenerate_system_prompt": "Choose {{ original_value }}",
            "agent_name_regenerate_user_prompt": "Task {{ task_description }}",
        }, field_key="name", task_description="search", original_value="finder",
        existing_values="old",
    )
    assert custom.system == "Choose finder"
    assert custom.user == "Task search"
    fallback = compose_name_regeneration(
        "en", {}, field_key="name", task_description="search",
        original_value="finder", existing_values="old",
    )
    assert "finder" in fallback.user and fallback.system


def test_nl2skill_keeps_raw_template_when_strict_render_fails(monkeypatch):
    original_loader = meta.load_prompt

    def load_with_unknown_field(language, path):
        if path == "meta/nl2skill":
            return {"system_prompt": "{{ missing }}", "user_prompt": "Request {{ user_request }}"}
        return original_loader(language, path)

    monkeypatch.setattr(meta, "load_prompt", load_with_unknown_field)
    rendered = compose_nl2skill(
        "en", existing_skill=None, user_request="Create", target_files=[]
    )
    assert rendered == {
        "system_prompt": "{{ missing }}", "user_prompt": "Request Create",
    }


def test_analysis_report_composes_stats_and_failures_in_sdk():
    prompt = compose_analysis_report(
        "en", total=3, passed=1, thresholds={"quality": 0.7},
        failure_examples=[{
            "query": "Question", "score": {"quality": 0.4},
            "reason": "Incomplete", "answer": "Response",
        }], max_examples=2,
    )
    assert prompt.system
    assert "Total cases: 3, Passed: 1, Failed: 2" in prompt.user
    assert "Case 1: Q=Question" in prompt.user
    assert "Reason: Incomplete" in prompt.user
