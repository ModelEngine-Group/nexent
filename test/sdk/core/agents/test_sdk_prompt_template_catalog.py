"""D1 contracts for SDK ownership of former Backend prompt resources."""

import hashlib
import json
from pathlib import Path

import pytest
from jinja2 import UndefinedError


ROOT = Path(__file__).parents[4]
# Baseline captures reviewed SDK resources, including workspace guidance merged in 95c166472.
BASELINE = json.loads(
    (ROOT / "test" / "assets" / "sdk_prompt_migration_hashes.json").read_text(
        encoding="utf-8"
    )
)


def test_ut_sdk_fps_001_all_prompt_files_keep_their_original_bytes():
    """UT-SDK-FPS-001: Packaged prompt assets retain their reviewed LF-normalized content."""
    target = ROOT / "sdk" / "nexent" / "core" / "prompts"
    assert BASELINE
    for source_name, expected_hash in BASELINE.items():
        target_file = target / source_name
        assert target_file.is_file(), source_name
        assert hashlib.sha256(target_file.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == expected_hash


def test_ut_sdk_fps_001_dynamic_fields_render_with_supplied_parameters():
    """UT-SDK-FPS-001: SDK renders actual values and rejects missing ones."""
    from nexent.core.prompts import load_prompt, render_prompt_text

    duty = render_prompt_text(
        load_prompt("zh", "agent/agent_manager")["system_sections"]["duty"],
        {"duty": "负责核对账目"},
    )
    assert "负责核对账目" in duty
    assert "{{duty}}" not in duty

    document = render_prompt_text(
        load_prompt("zh", "document/summary")["user_prompt"],
        {"filename": "report.pdf", "content": "正文", "max_words": 100},
    )
    assert "report.pdf" in document
    assert "正文" in document
    assert "{{" not in document

    with pytest.raises(UndefinedError):
        render_prompt_text(
            load_prompt("zh", "agent/agent_manager")["system_sections"]["duty"], {},
        )


@pytest.mark.parametrize(
    "coordinates",
    [
        ("fr", "agent/agent_manager"),
        ("zh", "../agent/agent_manager"),
        ("zh", "memory/fa_extraction.txt"),
    ],
)
def test_ut_sdk_fps_001_rejects_unknown_resource_paths(coordinates):
    """UT-SDK-FPS-001: invalid template paths fail explicitly."""
    from nexent.core.prompts import load_prompt

    with pytest.raises(ValueError):
        load_prompt(*coordinates)


def test_ut_sdk_fps_001_loaded_templates_are_independent():
    """UT-SDK-FPS-001: one consumer cannot change the next caller's template."""
    from nexent.core.prompts import load_prompt

    first = load_prompt("zh", "agent/agent_manager")
    original = first["system_sections"]["header"]
    first["system_sections"]["header"] = "changed"
    assert load_prompt("zh", "agent/agent_manager")[
        "system_sections"
    ]["header"] == original
