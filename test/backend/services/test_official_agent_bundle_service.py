import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services import official_agent_bundle_service as bundle_service
from services.official_agent_bundle_service import (
    MAX_BUNDLE_BYTES,
    MAX_BUNDLE_FILE_BYTES,
    OfficialAgentBundle,
    _load_kb_documents,
    _load_skill_entries,
    _read_bundle_json,
    _safe_member_path,
    _seed_doc,
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


@pytest.mark.parametrize("value", [["../medical"], ["medical/extra"], ["medical\\extra"], ["."]])
def test_parse_profiles_rejects_paths(value):
    with pytest.raises(ValueError, match="invalid official agent profile"):
        parse_official_agent_profiles(value)


def test_seed_doc_includes_optional_content_and_file_path():
    assert _seed_doc("guide.pdf", content="ignored", file_path="/tmp/guide.pdf") == {
        "file_name": "guide.pdf",
        "content": "ignored",
        "file_path": "/tmp/guide.pdf",
    }


@pytest.mark.parametrize("member_name", ["", "bad\x00name", "../outside", "nested/../../outside"])
def test_safe_member_path_rejects_unsafe_members(tmp_path: Path, member_name: str):
    assert _safe_member_path(tmp_path, member_name) is None


def test_read_bundle_json_requires_agent_json_object(tmp_path: Path):
    with pytest.raises(ValueError, match="missing agent.json"):
        _read_bundle_json(tmp_path)

    (tmp_path / "agent.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="must contain an object"):
        _read_bundle_json(tmp_path)


def test_load_skill_entries_reads_declared_skill_zip(tmp_path: Path):
    skill_dir = Path("skills")
    (tmp_path / skill_dir).mkdir()
    (tmp_path / skill_dir / "alpha.zip").write_bytes(b"skill-content")
    snapshot = SimpleNamespace(
        agent_info={
            "1": SimpleNamespace(skill_names=["alpha", "missing", None]),
        }
    )

    entries = _load_skill_entries(tmp_path, snapshot)

    assert len(entries) == 1
    assert entries[0].skill_name == "alpha"
    assert entries[0].skill_zip_base64


def test_load_skill_entries_rejects_unsafe_declared_skill_name(tmp_path: Path):
    snapshot = SimpleNamespace(
        agent_info={"1": SimpleNamespace(skill_names=["../unsafe"])}
    )

    with pytest.raises(ValueError, match="unsafe official skill name"):
        _load_skill_entries(tmp_path, snapshot)


def test_load_kb_documents_reads_text_and_binary_files_and_skips_hidden_files(tmp_path: Path):
    kb_dir = tmp_path / "kb" / "medical"
    kb_dir.mkdir(parents=True)
    (kb_dir / "overview.md").write_text("overview", encoding="utf-8")
    (kb_dir / "notes.txt").write_text("notes", encoding="utf-8")
    (kb_dir / "manual.pdf").write_bytes(b"pdf")
    (kb_dir / ".hidden.md").write_text("hidden", encoding="utf-8")
    (tmp_path / "kb" / "empty").mkdir()

    result = _load_kb_documents(
        tmp_path,
        {
            "knowledge_bases": [
                {"logical_index_name": "medical"},
                {"logical_index_name": "empty"},
                "invalid",
            ]
        },
    )

    assert result == {
        "medical": [
            {"file_name": "manual.pdf", "file_path": str(kb_dir / "manual.pdf")},
            {"file_name": "notes.txt", "content": "notes"},
            {"file_name": "overview.md", "content": "overview"},
        ]
    }


def test_load_kb_documents_rejects_unsafe_logical_name(tmp_path: Path):
    with pytest.raises(ValueError, match="unsafe official knowledge base name"):
        _load_kb_documents(tmp_path, {"knowledge_bases": [{"logical_index_name": "../medical"}]})


def test_load_zip_bundle_rejects_bundle_size_limit(tmp_path: Path):
    path = tmp_path / "large.zip"
    path.write_bytes(b"zip")
    with patch.object(Path, "stat", return_value=SimpleNamespace(st_size=MAX_BUNDLE_BYTES + 1)):
        with pytest.raises(ValueError, match="exceeds size limit"):
            bundle_service._load_zip_bundle("medical", path)


def test_load_zip_bundle_rejects_oversized_member(tmp_path: Path):
    path = tmp_path / "oversized.zip"
    path.write_bytes(b"zip")
    member = SimpleNamespace(filename="agent.json", file_size=MAX_BUNDLE_FILE_BYTES + 1)
    fake_archive = MagicMock()
    fake_archive.__enter__.return_value = fake_archive
    fake_archive.infolist.return_value = [member]
    with patch.object(bundle_service.zipfile, "ZipFile", return_value=fake_archive):
        with pytest.raises(ValueError, match="oversized file"):
            bundle_service._load_zip_bundle("medical", path)


def test_load_zip_bundle_rejects_too_many_members(tmp_path: Path):
    path = tmp_path / "too-many-files.zip"
    path.write_bytes(b"zip")
    fake_archive = MagicMock()
    fake_archive.__enter__.return_value = fake_archive
    fake_archive.infolist.return_value = [
        SimpleNamespace(filename="agent.json", file_size=0)
    ] * (bundle_service.MAX_BUNDLE_FILES + 1)
    with patch.object(bundle_service.zipfile, "ZipFile", return_value=fake_archive):
        with pytest.raises(ValueError, match="too many files"):
            bundle_service._load_zip_bundle("medical", path)


def test_load_zip_bundle_attaches_skill_entries_to_snapshot(tmp_path: Path):
    payload = _agent_payload()
    profile_dir = tmp_path / "medical"
    profile_dir.mkdir()
    with zipfile.ZipFile(profile_dir / "assistant.zip", "w") as archive:
        archive.writestr("agent.json", json.dumps(payload))
        archive.writestr("skills/research.zip", b"skill")

    snapshot = SimpleNamespace(
        agent_info={"101": SimpleNamespace(skill_names=["research"])},
        model_copy=MagicMock(return_value="snapshot-with-skills"),
    )
    with patch.object(bundle_service, "_snapshot_from_json", return_value=snapshot):
        bundle = bundle_service._load_zip_bundle("medical", profile_dir / "assistant.zip")

    assert bundle is not None
    assert bundle.snapshot == "snapshot-with-skills"
    snapshot.model_copy.assert_called_once()


def test_load_official_bundles_skips_missing_profile(tmp_path: Path):
    assert load_official_bundles(tmp_path, ["medical"]) == []


def test_load_official_bundles_skips_bundle_when_loader_returns_none(tmp_path: Path):
    _write_bundle(tmp_path, "medical", "assistant", _agent_payload())
    with patch.object(bundle_service, "_load_zip_bundle", return_value=None):
        assert load_official_bundles(tmp_path, ["medical"]) == []


def test_load_official_bundles_loads_directory_bundle_and_dependencies(tmp_path: Path):
    bundle_dir = tmp_path / "medical" / "assistant"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "agent.json").write_text(json.dumps(_agent_payload()), encoding="utf-8")
    snapshot = SimpleNamespace(agent_info={})
    with patch.object(bundle_service, "_snapshot_from_json", return_value=snapshot):
        bundles = load_official_bundles(tmp_path, ["medical"])

    assert len(bundles) == 1
    assert isinstance(bundles[0], OfficialAgentBundle)
    assert bundles[0].profile == "medical"
    assert bundles[0].name == "assistant"
    assert bundles[0].bundle_path == bundle_dir


def test_load_official_bundles_attaches_directory_skill_entries(tmp_path: Path):
    bundle_dir = tmp_path / "medical" / "assistant"
    skills_dir = bundle_dir / "skills"
    skills_dir.mkdir(parents=True)
    (bundle_dir / "agent.json").write_text(json.dumps(_agent_payload()), encoding="utf-8")
    (skills_dir / "research.zip").write_bytes(b"skill")
    snapshot = SimpleNamespace(
        agent_info={"101": SimpleNamespace(skill_names=["research"])},
        model_copy=MagicMock(return_value="snapshot-with-skills"),
    )
    with patch.object(bundle_service, "_snapshot_from_json", return_value=snapshot):
        bundles = load_official_bundles(tmp_path, ["medical"])

    assert len(bundles) == 1
    assert bundles[0].snapshot == "snapshot-with-skills"
    snapshot.model_copy.assert_called_once()


def test_load_official_bundles_skips_invalid_directory_bundle(tmp_path: Path):
    bundle_dir = tmp_path / "medical" / "broken"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "agent.json").write_text("not-json", encoding="utf-8")

    assert load_official_bundles(tmp_path, ["medical"]) == []


def test_load_official_bundles_rejects_duplicate_directory_bundle_names(tmp_path: Path):
    for profile in ("medical", "finance"):
        bundle_dir = tmp_path / profile / "assistant"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "agent.json").write_text(json.dumps(_agent_payload()), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate official agent bundle"):
        load_official_bundles(tmp_path, ["medical", "finance"])


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
