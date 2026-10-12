"""Backend compatibility checks for SDK-owned prompt templates."""

import json
from pathlib import Path

import pytest
import yaml
from nexent.core.prompts import load_prompt


ROOT = Path(__file__).parents[3]
# Baseline captures the committed SDK resources at merge 32fa76ef6.
BASELINE = json.loads(
    (ROOT / "test" / "assets" / "sdk_prompt_migration_hashes.json").read_text(
        encoding="utf-8"
    )
)

@pytest.mark.parametrize(
    "source_name",
    sorted(
        name for name in BASELINE
        if not name.startswith(("en/memory/", "zh/memory/"))
    ),
)
def test_ut_be_fps_001_loader_preserves_sdk_asset_mapping(source_name):
    """UT-BE-FPS-001: existing Backend callers receive the original mapping."""
    relative = Path(source_name)
    language = relative.parts[0]
    path = relative.relative_to(language).as_posix()
    expected = yaml.safe_load(
        (ROOT / "sdk" / "nexent" / "core" / "prompts" / relative).read_text(
            encoding="utf-8"
        )
    )
    assert load_prompt(language, path) == expected


def test_ut_be_fps_001_backend_prompt_files_are_migrated():
    """UT-BE-FPS-001: prompt YAML has one packaged owner."""
    assert not list((ROOT / "backend" / "prompts").rglob("*.yaml"))


def test_ut_be_fps_002_memory_services_load_sdk_prompt_resources():
    """UT-BE-FPS-002: direct memory consumers retain their original messages."""
    from services.fa_memory_extractor import FaMemoryExtractor
    from services.memory_dreaming_summarizer import _load_prompt

    extractor = FaMemoryExtractor(
        tenant_id="tenant", user_id="user", agent_id="1", conversation_id="conv",
    )
    assert extractor._load_prompt() == load_prompt("en", "memory/fa_extraction")
    messages = extractor._build_messages("final answer", "question")
    assert messages[0]["content"] == extractor._load_prompt()["system"]
    assert "final answer" in messages[1]["content"]
    assert _load_prompt() == load_prompt("en", "memory/dreaming_user")


def test_ut_be_fps_002_memory_resource_failure_is_not_silenced(mocker):
    """UT-BE-FPS-002: missing SDK resources fail before model invocation."""
    from services.fa_memory_extractor import FaMemoryExtractor
    from services.memory_dreaming_summarizer import _load_prompt

    extractor = FaMemoryExtractor(
        tenant_id="tenant", user_id="user", agent_id="1", conversation_id="conv",
    )
    mocker.patch(
        "nexent.core.agents.prompt.memory.load_prompt",
        side_effect=FileNotFoundError("missing"),
    )
    with pytest.raises(FileNotFoundError):
        extractor._build_messages("final answer")
    with pytest.raises(FileNotFoundError):
        _load_prompt()


def test_ut_be_fps_003_sdk_package_data_covers_yaml_resources():
    """UT-BE-FPS-003: moved assets are included in the SDK wheel layout."""
    import tomllib

    config = tomllib.loads((ROOT / "sdk" / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = config["tool"]["setuptools"]["package-data"]["nexent.core.prompts"]
    assert "zh/*/*.yaml" in patterns
    assert "en/*/*.yaml" in patterns
