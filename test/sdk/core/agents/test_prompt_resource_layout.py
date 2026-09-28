"""D1 checks for the language-and-purpose prompt resource layout."""

import hashlib
import json
from pathlib import Path

import pytest

from test.common.prompt_resource_layout import ADDITIONAL_SHA256, destination_for_old_name


ROOT = Path(__file__).parents[4]
PROMPTS = ROOT / "sdk/nexent/core/prompts"
MIGRATED_SHA256 = json.loads(
    (ROOT / "test/assets/sdk_prompt_migration_hashes.json").read_text(encoding="utf-8")
)
ALL_SHA256 = {
    name: digest
    for name, digest in (MIGRATED_SHA256 | ADDITIONAL_SHA256).items()
    if not name.startswith("skill_creation_simple_")
}
POLICY_FILES = {
    Path("zh/agent/human_interaction.yaml"),
    Path("en/agent/human_interaction.yaml"),
    Path("en/agent/context_summary.yaml"),
    Path("en/agent/answer_verifier.yaml"),
    Path("zh/agent/context_summary.yaml"),
    Path("zh/agent/answer_verifier.yaml"),
    Path("zh/memory/dreaming_user.yaml"),
    Path("zh/memory/fa_extraction.yaml"),
    *(Path(f"{language}/agent/{name}.yaml")
      for language in ("zh", "en")
      for name in ("context_sections", "memory_tool_policy", "automation_tool_policy", "knowledge_scope")),
}


def test_ut_sdk_fps_004_all_resources_have_reviewed_layout_and_original_bytes():
    """UT-SDK-FPS-004: retained relocated files keep their original bytes."""
    assert len(ALL_SHA256) == 46
    expected = {destination_for_old_name(Path(name).name) for name in ALL_SHA256} | POLICY_FILES
    actual = {path.relative_to(PROMPTS) for path in PROMPTS.rglob("*.yaml")}
    assert len(actual) == 62
    assert actual == expected
    assert not list(PROMPTS.glob("*.yaml"))

    for old_name, digest in ALL_SHA256.items():
        destination = destination_for_old_name(Path(old_name).name)
        assert hashlib.sha256((PROMPTS / destination).read_bytes()).hexdigest() == digest
        if destination.parts[0] in {"zh", "en"}:
            assert not destination.stem.endswith(("_zh", "_en"))


@pytest.mark.parametrize(
    "template_type,language,old_name",
    [
        ("analyze_image", "zh", "analyze_image_zh.yaml"),
        ("analyze_audio", "en", "analyze_audio_en.yaml"),
        ("analyze_video", "zh", "analyze_video_zh.yaml"),
        ("analyze_file", "en", "analyze_file_en.yaml"),
    ],
)
def test_ut_sdk_fps_005_multimodal_loader_uses_new_resources(
    template_type, language, old_name,
):
    """UT-SDK-FPS-005: existing tool API still returns the same mapping."""
    import yaml

    from nexent.core.prompts import load_prompt

    expected = yaml.safe_load((PROMPTS / destination_for_old_name(old_name)).read_text(encoding="utf-8"))
    assert load_prompt(language, f"tool/{template_type}") == expected


def test_ut_sdk_fps_005_fixed_policy_loader_uses_localized_resources():
    """UT-SDK-FPS-005: split policy text retains its runtime contract."""
    import yaml

    from nexent.core.prompts import load_prompt

    for language in ("zh", "en"):
        source = yaml.safe_load((PROMPTS / language / "agent/human_interaction.yaml").read_text(encoding="utf-8"))
        assert load_prompt(language, "agent/human_interaction") == source
    verifier = yaml.safe_load((PROMPTS / "en/agent/answer_verifier.yaml").read_text(encoding="utf-8"))
    assert load_prompt("en", "agent/answer_verifier") == verifier


def test_ut_sdk_fps_005_invalid_resource_path_does_not_read_another_resource():
    """UT-SDK-FPS-005: path traversal is rejected before resource access."""
    from nexent.core.prompts import load_prompt

    with pytest.raises(ValueError, match="safe relative YAML path"):
        load_prompt("zh", "../agent/human_interaction")
