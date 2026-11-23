"""D1 checks for the language-and-purpose prompt resource layout."""

import hashlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[4]
PROMPTS = ROOT / "sdk/nexent/core/prompts"
# Baseline captures reviewed SDK resources, including workspace guidance merged in 95c166472.
MIGRATED_SHA256 = json.loads(
    (ROOT / "test/assets/sdk_prompt_migration_hashes.json").read_text(encoding="utf-8")
)


def test_ut_sdk_fps_004_all_resources_have_reviewed_layout_and_original_bytes():
    """UT-SDK-FPS-004: Packaged resources keep their reviewed layout and LF-normalized content."""
    expected = {Path(name) for name in MIGRATED_SHA256}
    actual = {path.relative_to(PROMPTS) for path in PROMPTS.rglob("*.yaml")}
    assert actual == expected
    assert not list(PROMPTS.glob("*.yaml"))

    for relative, digest in MIGRATED_SHA256.items():
        destination = Path(relative)
        content = (PROMPTS / destination).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(content).hexdigest() == digest, relative
        if destination.parts[0] in {"zh", "en"}:
            assert not destination.stem.endswith(("_zh", "_en"))


@pytest.mark.parametrize(
    "template_type,language",
    [
        ("analyze_image", "zh"),
        ("analyze_audio", "en"),
        ("analyze_video", "zh"),
        ("analyze_file", "en"),
    ],
)
def test_ut_sdk_fps_005_multimodal_loader_uses_new_resources(
    template_type, language,
):
    """UT-SDK-FPS-005: existing tool API still returns the same mapping."""
    import yaml

    from nexent.core.prompts import load_prompt

    expected = yaml.safe_load((PROMPTS / language / "tool" / f"{template_type}.yaml").read_text(encoding="utf-8"))
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
