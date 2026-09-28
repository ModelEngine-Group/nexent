"""D1 contracts for split Agent policies and direct SDK resource loading."""

import hashlib
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[4]
PROMPTS = ROOT / "sdk/nexent/core/prompts"
POLICY_HASHES = {
    "zh/agent/human_interaction.yaml": "31bb381d4603d6d0ae5ab4492dc3d6d980d4ad9a3b64de84685b479927d71b2d",
    "en/agent/human_interaction.yaml": "af8fe686dd7e1549a1ba24c563800076bf291a38c36c653d9a8f86e6a5a50f79",
    "en/agent/context_summary.yaml": "dd689841e3e4f03809ea6d198121688dbbb8531234fc90e2dc0107ae0939543b",
    "en/agent/answer_verifier.yaml": "0232a3c067ebff27194ea6d9abe9f4bfb2005aea678e18281a91742077d0ac15",
}


def test_ut_sdk_fps_006_policies_match_approved_baselines():
    """UT-SDK-FPS-006: each Agent policy matches its approved current baseline."""
    for relative, expected_hash in POLICY_HASHES.items():
        parsed = yaml.safe_load((PROMPTS / relative).read_text(encoding="utf-8"))
        actual_hash = hashlib.sha256(
            json.dumps(parsed, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        assert actual_hash == expected_hash, relative
    assert not (PROMPTS / "shared/agent/runtime_policies.yaml").exists()


def test_ut_sdk_fps_007_loads_resources_by_actual_coordinates():
    """UT-SDK-FPS-007: no old template-type aliases are needed to load YAML."""
    from nexent.core.prompts import load_prompt

    for language, path in [
        ("zh", "agent/agent_manager"),
        ("en", "evaluation/generate_cases"),
        ("en", "tool/analyze_image"),
        ("en", "agent/context_summary"),
    ]:
        first = load_prompt(language, path)
        assert first == yaml.safe_load(
            (PROMPTS / language / f"{path}.yaml").read_text(encoding="utf-8")
        )
        first["test_mutation"] = True
        assert "test_mutation" not in load_prompt(language, path)


@pytest.mark.parametrize(
    "coordinates,error",
    [
        (("fr", "agent/agent_manager"), ValueError),
        (("zh", "../agent/manager"), ValueError),
        (("zh", "agent/../../secret"), ValueError),
        (("zh", "agent/missing"), FileNotFoundError),
    ],
)
def test_ut_sdk_fps_007_invalid_coordinates_fail_explicitly(coordinates, error):
    """UT-SDK-FPS-007: invalid paths never fall back to another resource."""
    from nexent.core.prompts import load_prompt

    with pytest.raises(error):
        load_prompt(*coordinates)


def test_ut_sdk_fps_007_catalog_and_old_policy_file_are_absent():
    """UT-SDK-FPS-007: the package does not retain the old mapping layer."""
    assert not (PROMPTS / "catalog.py").exists()
    assert not (PROMPTS / "shared/agent/runtime_policies.yaml").exists()
    assert not (ROOT / "sdk/nexent/core/utils/prompt_template_utils.py").exists()


def test_ut_sdk_fps_008_relative_path_accepts_optional_yaml_suffix():
    """UT-SDK-FPS-008: both path spellings load independent equivalent maps."""
    from nexent.core.prompts import load_prompt

    for language, path in [("zh", "meta/nl2agent"), ("en", "evaluation/judge")]:
        first = load_prompt(language, path)
        assert first == load_prompt(language, f"{path}.yaml")
        first["test_mutation"] = True
        assert "test_mutation" not in load_prompt(language, path)


@pytest.mark.parametrize(
    "path",
    ["", "/agent/manager", "../agent/manager", "agent//manager", "agent/../manager",
     "agent\\manager", "agent/manager.txt", "agent/.yaml"],
)
def test_ut_sdk_fps_008_rejects_unsafe_relative_paths(path):
    """UT-SDK-FPS-008: only files under the selected language are readable."""
    from nexent.core.prompts import load_prompt

    with pytest.raises(ValueError):
        load_prompt("zh", path)


def test_ut_sdk_fps_009_special_names_and_no_redundant_automation_path():
    """UT-SDK-FPS-009: specialized names survive the file layout update."""
    assert (PROMPTS / "zh/meta/nl2agent.yaml").is_file()
    for language in ("zh", "en"):
        assert (PROMPTS / language / "meta/nl2skill.yaml").is_file()
        assert not (PROMPTS / language / "meta/nl2skill_simple.yaml").exists()
        assert not (PROMPTS / language / "meta/nl2skill_complicated.yaml").exists()
        assert (PROMPTS / language / "automation/agent.yaml").is_file()
        assert not (PROMPTS / language / "automation/agent_automation.yaml").exists()
        assert (PROMPTS / language / "meta/generate_prompt.yaml").is_file()
        assert not (PROMPTS / language / "generation/prompt_generate.yaml").exists()
    assert (PROMPTS / "en/memory/dreaming_user.yaml").is_file()
    assert not (PROMPTS / "en/memory/dreaming_user_memory.yaml").exists()
    resources = list(PROMPTS.rglob("*.yaml"))
    assert len(resources) == 62
    for resource in resources:
        if resource.stem.startswith(("nl2agent", "nl2skill", "agent_manager", "agent_worker")):
            continue
        assert resource.parent.name not in resource.stem, resource


def test_ut_sdk_fps_010_meta_and_agent_paths_replace_old_layout():
    """UT-SDK-FPS-010: renamed resources are unique and the old folders vanish."""
    expected = {
        "meta/generate_greeting", "meta/generate_prompt", "meta/optimize_prompt",
        "meta/nl2agent", "meta/nl2skill",
        "agent/generate_chat_title", "agent/agent_worker", "agent/agent_manager",
    }
    from nexent.core.prompts import load_prompt

    for language in ("zh", "en"):
        assert not (PROMPTS / language / "generation").exists()
        assert not (PROMPTS / language / "skill").exists()
        for path in expected:
            assert load_prompt(language, path) == yaml.safe_load(
                (PROMPTS / language / f"{path}.yaml").read_text(encoding="utf-8")
            )


def test_ut_sdk_fps_011_languages_have_matching_paths_fields_and_jinja_variables():
    """UT-SDK-FPS-011: every English resource has a Chinese structural peer."""
    from nexent.core.prompts import load_prompt

    en_paths = {p.relative_to(PROMPTS / "en") for p in (PROMPTS / "en").rglob("*.yaml")}
    zh_paths = {p.relative_to(PROMPTS / "zh") for p in (PROMPTS / "zh").rglob("*.yaml")}
    assert len(en_paths) == len(zh_paths) == 31
    assert en_paths == zh_paths

    def flatten(value, prefix=""):
        if isinstance(value, dict):
            return {
                key: item for name, child in value.items()
                for key, item in flatten(child, f"{prefix}.{name}" if prefix else name).items()
            }
        return {prefix: value}

    for relative in en_paths:
        en = flatten(load_prompt("en", relative.as_posix()))
        zh = flatten(load_prompt("zh", relative.as_posix()))
        assert en.keys() == zh.keys(), relative
        for key in en:
            assert type(en[key]) is type(zh[key]), (relative, key)
            if isinstance(en[key], str):
                variable_pattern = r"\{\{\s*([A-Za-z_][A-Za-z_0-9]*)"
                assert set(re.findall(variable_pattern, en[key])) == set(
                    re.findall(variable_pattern, zh[key])
                ), (relative, key)


def test_ut_sdk_fps_011_new_chinese_resources_preserve_runtime_protocol():
    """UT-SDK-FPS-011: translated resources retain format slots and tags."""
    from nexent.core.prompts import load_prompt

    for path in (
        "agent/context_summary", "agent/answer_verifier",
        "memory/dreaming_user", "memory/fa_extraction",
    ):
        en = load_prompt("en", path)
        zh = load_prompt("zh", path)
        assert en.keys() == zh.keys()
        for key in ("system", "user"):
            if key not in en:
                continue
            format_pattern = r"\{([A-Za-z_][A-Za-z_0-9]*)\}"
            tag_pattern = r"</?[a-z][a-z-]*/?>"
            assert set(re.findall(format_pattern, en[key])) == set(
                re.findall(format_pattern, zh[key])
            ), (path, key)
            assert set(re.findall(tag_pattern, en[key])) == set(
                re.findall(tag_pattern, zh[key])
            ), (path, key)
    verifier = load_prompt("zh", "agent/answer_verifier")["system_prompt"]
    for key in ("passed", "score", "status", "failed_criteria", "checks",
                "revision_instruction", "user_visible_note"):
        assert key in verifier
    assert "# Compact Result of History" in load_prompt(
        "zh", "agent/context_summary"
    )["system_prompt"]


def test_ut_sdk_fps_012_tool_policy_registry_is_active_not_a_prompt_alias():
    """UT-SDK-FPS-012: runtime policy filtering stays independent of YAML paths."""
    from nexent.core.tools.prompt_registry import filter_effective_prompt_tools

    result = filter_effective_prompt_tools(
        {"visible": {"description": "shown"}, "hidden": {"description": "system"}},
        enabled={"visible"}, allowed={"visible"}, system_default_hidden={"hidden"},
        policy_version="p1", tool_schema_version="v1",
    )
    assert set(result.tools) == {"visible"}
    assert set(result.execution_tools) == {"visible", "hidden"}
    assert result.audit["policy_version"] == "p1"
    assert "prompt_registry" in (ROOT / "backend/agents/create_agent_info.py").read_text(encoding="utf-8")
    assert "prompt_registry" in (ROOT / "sdk/nexent/core/agents/nexent_agent.py").read_text(encoding="utf-8")
