"""D1 checks for concise bilingual system-prompt prose."""

import ast
from pathlib import Path
import re

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[4]
PROMPTS = ROOT / "sdk/nexent/core/prompts"
TOOLS = ROOT / "sdk/nexent/core/tools"


def _prompt(language: str, name: str) -> dict:
    return yaml.safe_load((PROMPTS / language / name).read_text(encoding="utf-8"))


def _tool_text(filename: str, class_name: str, field: str) -> str:
    tree = ast.parse((TOOLS / filename).read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    value = next(
        node.value for node in cls.body
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == field for target in node.targets
        )
    )
    return ast.literal_eval(value)


@pytest.mark.parametrize("language,old_clause", [
    ("zh", "也不要用 final_answer 征求输入"),
    ("en", "or use final_answer to solicit input"),
])
def test_ut_sdk_fps_030_clarification_keeps_only_no_repeat_rule(language, old_clause):
    policy = _prompt(language, "agent/human_interaction.yaml")["clarification_policy"]
    assert old_clause not in policy
    assert ("不要重复这些问题" if language == "zh" else "Do not repeat the questions") in policy


@pytest.mark.parametrize("language", ["zh", "en"])
def test_ut_sdk_fps_031_one_complete_code_block_per_step(language):
    role = _prompt(language, "agent/agent_manager.yaml")["system_sections"]
    worker = _prompt(language, "agent/agent_worker.yaml")["system_sections"]
    meta = _prompt(language, "meta/generate_prompt.yaml")["FEW_SHOTS_SYSTEM_PROMPT"]
    for sections in (role, worker):
        text = sections["execution_flow"] + sections["code_norms"]
        assert "<code>" in text
        assert ("多个代码块将被视为同一个代码块" if language == "zh" else "multiple code blocks are treated as one code block") in text.lower()
        assert ("必须相邻" if language == "zh" else "consecutively with whitespace only") not in text
    assert ("多个代码块将被视为同一个代码块" if language == "zh" else "multiple code blocks are treated as one code block") in meta.lower()


@pytest.mark.parametrize("field", ["description", "description_zh"])
def test_ut_sdk_fps_032_parallel_example_is_code_not_escaped_prose(field):
    text = _tool_text("parallel_executor.py", "ParallelExecutorTool", field)
    assert "<code>\n" in text and "\n</code>" in text
    assert "\\\"" not in text
    assert "import" not in text.lower()
    sample = text.split("<code>\n", 1)[1].split("\n</code>", 1)[0]
    ast.parse(sample)
    assert sample.count("knowledge_base_search") == 2


@pytest.mark.parametrize("language", ["zh", "en"])
def test_ut_sdk_fps_033_fixed_tool_call_examples_are_structured(language):
    role = _prompt(language, "agent/agent_manager.yaml")["system_sections"]
    policy = _prompt(language, "agent/human_interaction.yaml")["clarification_policy"]
    examples = _prompt(language, "meta/generate_prompt.yaml")["FEW_SHOTS_SYSTEM_PROMPT"]
    assert re.search(r"<code>\s*tool_name\(", role["code_norms"])
    assert re.search(r"<code>\s*ask_user\(", policy)
    assert "<code>" in _prompt(language, "agent/context_sections.yaml")["worker_agents"]["guidance"]
    assert re.search(r"<code>\s*results = parallel_executor\(", examples)
    assert re.search(r"<code>\s*assistant_name\(", examples)


@pytest.mark.parametrize("language", ["zh", "en"])
def test_ut_sdk_fps_034_generated_system_sections_require_second_person(language):
    generated = _prompt(language, "meta/generate_prompt.yaml")
    optimized = _prompt(language, "meta/optimize_prompt.yaml")["OPTIMIZE_SYSTEM_PROMPT"]
    marker = "第二人称" if language == "zh" else "second person"
    for key in ("DUTY_SYSTEM_PROMPT", "CONSTRAINT_SYSTEM_PROMPT", "FEW_SHOTS_SYSTEM_PROMPT"):
        assert marker in generated[key]
    assert marker in optimized
    display = generated["AGENT_DESCRIPTION_SYSTEM_PROMPT"]
    assert ("第一人称" if language == "zh" else "first person") in display


@pytest.mark.parametrize("filename,class_name,forbidden", [
    ("create_file_tool.py", "CreateFileTool", "defaults to utf-8"),
    ("create_directory_tool.py", "CreateDirectoryTool", "Parent directories"),
    ("plan_tools.py", "CreatePlanTool", "stable id"),
    ("parallel_executor.py", "ParallelExecutorTool", "max_workers controls"),
])
def test_ut_sdk_fps_032_tool_description_omits_input_field_details(filename, class_name, forbidden):
    assert forbidden.lower() not in _tool_text(filename, class_name, "description").lower()


@pytest.mark.parametrize("filename,class_name,input_names", [
    ("create_file_tool.py", "CreateFileTool", {"file_path", "content", "encoding"}),
    ("read_file_tool.py", "ReadFileTool", {"file_path", "encoding"}),
    ("delete_file_tool.py", "DeleteFileTool", {"file_path"}),
    ("create_directory_tool.py", "CreateDirectoryTool", {"directory_path", "permissions"}),
    ("list_directory_tool.py", "ListDirectoryTool", {"directory_path", "max_depth", "show_hidden", "show_size"}),
    ("delete_directory_tool.py", "DeleteDirectoryTool", {"directory_path"}),
    ("move_item_tool.py", "MoveItemTool", {"source_path", "destination_path"}),
    ("upload_to_s3_tool.py", "UploadToS3Tool", {"file_path", "target_filename"}),
    ("download_from_s3_tool.py", "DownloadFromS3Tool", {"s3_path", "local_filename"}),
])
def test_ut_sdk_fps_032_batch_cleanup_keeps_input_contract(filename, class_name, input_names):
    assert set(_tool_text(filename, class_name, "inputs")) == input_names
    for field in ("description", "description_zh"):
        text = _tool_text(filename, class_name, field)
        assert text
        assert "e.g." not in text and "例如" not in text


@pytest.mark.parametrize("language", ["zh", "en"])
def test_ut_sdk_fps_032_builtin_tool_summaries_omit_parameter_rules(language):
    descriptions = _prompt(language, "agent/context_sections.yaml")["builtin_tools"]
    assert descriptions["create_plan"] and descriptions["run_skill_script"]
    for name in ("create_plan", "update_plan_step"):
        assert "status=" not in descriptions[name]
        assert "step-1" not in descriptions[name]
    assert "script_path" not in descriptions["run_skill_script"]
