import json
import zipfile
from pathlib import Path

import pytest

from services.official_agent_bundle_service import (
    load_official_bundles,
    parse_official_agent_profiles,
)


def _agent_payload(agent_id: int = 101) -> dict:
    return {
        "agent_id": agent_id,
        "agent_info": {
            str(agent_id): {
                "agent_id": agent_id,
                "name": "medical_assistant",
                "description": "Medical assistant",
                "max_steps": 15,
                "provide_run_summary": True,
                "enabled": True,
                "tools": [],
                "managed_agents": [],
            }
        },
        "mcp_info": [],
        "display_name": "Medical Assistant",
        "description": "Medical assistant",
        "tags": ["medical"],
    }


def _write_bundle(root: Path, profile: str, name: str, payload: dict) -> None:
    profile_dir = root / profile
    profile_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(profile_dir / f"{name}.zip", "w") as archive:
        archive.writestr("agent.json", json.dumps(payload))
        archive.writestr("skills/research.zip", b"skill")
        archive.writestr("kb/medical/overview.md", "seed")


def test_parse_profiles_supports_multiple_profiles_and_deduplicates():
    assert parse_official_agent_profiles(" medical,finance,medical ") == [
        "medical",
        "finance",
    ]


def test_load_official_bundles_only_reads_selected_profiles(tmp_path: Path):
    _write_bundle(tmp_path, "medical", "assistant", _agent_payload())
    _write_bundle(tmp_path, "finance", "finance_assistant", _agent_payload(202))
    _write_bundle(tmp_path, "general", "assistant", _agent_payload(303))

    bundles = load_official_bundles(tmp_path, ["medical", "finance"])

    assert [(bundle.profile, bundle.name) for bundle in bundles] == [
        ("finance", "finance_assistant"),
        ("medical", "assistant"),
    ]
    assert all(bundle.snapshot.agent_id in {101, 202} for bundle in bundles)


def test_load_official_bundles_rejects_duplicate_bundle_keys(tmp_path: Path):
    _write_bundle(tmp_path, "medical", "assistant", _agent_payload())
    _write_bundle(tmp_path, "finance", "assistant", _agent_payload(202))

    with pytest.raises(ValueError, match="duplicate official agent bundle"):
        load_official_bundles(tmp_path, ["medical", "finance"])


def test_load_official_bundles_rejects_zip_path_traversal(tmp_path: Path):
    profile_dir = tmp_path / "medical"
    profile_dir.mkdir()
    with zipfile.ZipFile(profile_dir / "unsafe.zip", "w") as archive:
        archive.writestr("../agent.json", json.dumps(_agent_payload()))

    assert load_official_bundles(tmp_path, ["medical"]) == []
