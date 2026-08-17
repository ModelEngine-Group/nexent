from pathlib import Path
from unittest.mock import MagicMock

import pytest
from consts.exceptions import SkillException
from services import modelscope_skill_service as module
from services.modelscope_skill_service import (
    ModelScopeSkillService,
    _parse_source_timestamp,
    _validate_downloaded_directory,
)

SKILL_MD = """---
name: source-skill
description: Source description
allowed-tools:
  - tool-a
tags:
  - source
---

Use this Skill.
"""


class FakeSkillManager:
    def __init__(self, root: Path):
        self.root = root

    def resolve_tenant_dir(self, *, tenant_id: str) -> str:
        return str(self.root / tenant_id)

    def resolve_skill_dir(self, skill_name: str, *, tenant_id: str) -> str:
        return str(self.root / tenant_id / skill_name)


class FakeAdapter:
    def __init__(self, *, with_skill_md: bool = True):
        self.with_skill_md = with_skill_md
        self.download_calls: list[str] = []

    def get_skill(self, skill_id: str):
        return {
            "skill_id": "@owner/source-skill",
            "last_modified": "2026-08-07T06:37:46Z",
        }

    def download_skill(self, skill_id: str, local_dir: Path) -> Path:
        self.download_calls.append(skill_id)
        downloaded = local_dir / "snapshot"
        downloaded.mkdir()
        if self.with_skill_md:
            (downloaded / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
            (downloaded / "scripts").mkdir()
            (downloaded / "scripts" / "run.py").write_text(
                "print('not executed')", encoding="utf-8"
            )
            (downloaded / "assets").mkdir()
            (downloaded / "assets" / "note.txt").write_text(
                "kept", encoding="utf-8"
            )
        return downloaded


class ConfiguredAdapter(FakeAdapter):
    def download_skill(self, skill_id: str, local_dir: Path) -> Path:
        downloaded = super().download_skill(skill_id, local_dir)
        config_dir = downloaded / "config"
        config_dir.mkdir()
        (config_dir / "schema.yaml").write_text(
            "query:\n  type: string\n  required: true\n  description_en: Search text\n",
            encoding="utf-8",
        )
        (config_dir / "config.yaml").write_text(
            "query: default", encoding="utf-8"
        )
        return downloaded


@pytest.fixture(autouse=True)
def mock_tenant_groups(monkeypatch):
    monkeypatch.setattr(
        module,
        "query_groups_by_tenant",
        MagicMock(
            return_value={
                "groups": [{"group_id": 2}, {"group_id": 3}],
                "total": 2,
            }
        ),
    )


def _service(tmp_path: Path, adapter=None):
    return ModelScopeSkillService(
        adapter=adapter or FakeAdapter(),
        skill_manager=FakeSkillManager(tmp_path),
    )


def _install(service: ModelScopeSkillService, name: str = "local-skill"):
    return service.install_skill(
        skill_id="requested-id",
        name=name,
        description="Local description",
        tags=["local", "demo"],
        group_ids=[2, 3],
        ingroup_permission="EDIT",
        tenant_id="tenant-a",
        user_id="user-a",
    )


def test_install_skill_parses_db_data_and_moves_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(module.skill_db, "get_skill_by_name", MagicMock(return_value=None))
    monkeypatch.setattr(module.skill_db, "get_tool_ids_by_names", MagicMock(return_value=[7]))
    create = MagicMock(side_effect=lambda data, tenant_id: {**data, "skill_id": 9})
    monkeypatch.setattr(module.skill_db, "create_skill", create)

    result = _install(_service(tmp_path))

    destination = tmp_path / "tenant-a" / "local-skill"
    assert result["skill_id"] == 9
    assert destination.joinpath("assets", "note.txt").read_text() == "kept"
    saved_md = destination.joinpath("SKILL.md").read_text(encoding="utf-8")
    assert "name: local-skill" in saved_md
    assert "description: Local description" in saved_md
    data = create.call_args.args[0]
    assert data["unique_id"] == "@owner/source-skill"
    assert data["source"] == "modelscope"
    assert data["tool_ids"] == [7]
    assert data["version_update_time"].isoformat() == "2026-08-07T06:37:46+00:00"


def test_same_external_skill_can_be_installed_under_different_names(tmp_path, monkeypatch):
    monkeypatch.setattr(module.skill_db, "get_skill_by_name", MagicMock(return_value=None))
    monkeypatch.setattr(module.skill_db, "get_tool_ids_by_names", MagicMock(return_value=[]))
    create = MagicMock(side_effect=lambda data, tenant_id: dict(data))
    monkeypatch.setattr(module.skill_db, "create_skill", create)
    adapter = FakeAdapter()
    service = _service(tmp_path, adapter)

    _install(service, "copy-one")
    _install(service, "copy-two")

    assert [call.args[0]["unique_id"] for call in create.call_args_list] == [
        "@owner/source-skill",
        "@owner/source-skill",
    ]


def test_install_parses_schema_and_config_files(tmp_path, monkeypatch):
    monkeypatch.setattr(module.skill_db, "get_skill_by_name", MagicMock(return_value=None))
    monkeypatch.setattr(module.skill_db, "get_tool_ids_by_names", MagicMock(return_value=[]))
    create = MagicMock(side_effect=lambda data, tenant_id: dict(data))
    monkeypatch.setattr(module.skill_db, "create_skill", create)

    _install(_service(tmp_path, ConfiguredAdapter()))

    data = create.call_args.args[0]
    assert data["config_schemas"][0]["name"] == "query"
    assert data["config_values"] == {"query": "default"}


def test_install_rejects_existing_database_name(tmp_path, monkeypatch):
    monkeypatch.setattr(module.skill_db, "get_skill_by_name", MagicMock(return_value={"skill_id": 1}))

    with pytest.raises(SkillException, match="already exists"):
        _install(_service(tmp_path))


def test_install_rejects_existing_local_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(module.skill_db, "get_skill_by_name", MagicMock(return_value=None))
    (tmp_path / "tenant-a" / "local-skill").mkdir(parents=True)

    with pytest.raises(SkillException, match="already exists locally"):
        _install(_service(tmp_path))


def test_install_rejects_unsafe_name(tmp_path):
    with pytest.raises(SkillException, match="Invalid Skill name"):
        _install(_service(tmp_path), "../escape")


def test_install_rejects_missing_skill_md(tmp_path, monkeypatch):
    monkeypatch.setattr(module.skill_db, "get_skill_by_name", MagicMock(return_value=None))

    with pytest.raises(SkillException, match="root SKILL.md"):
        _install(_service(tmp_path, FakeAdapter(with_skill_md=False)))


def test_install_rejects_group_from_another_tenant(tmp_path, monkeypatch):
    monkeypatch.setattr(module.skill_db, "get_skill_by_name", MagicMock(return_value=None))
    module.query_groups_by_tenant.return_value = {
        "groups": [{"group_id": 2}],
        "total": 1,
    }

    with pytest.raises(SkillException, match="do not belong"):
        _install(_service(tmp_path))


def test_install_does_not_move_files_when_database_insert_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(module.skill_db, "get_skill_by_name", MagicMock(return_value=None))
    monkeypatch.setattr(module.skill_db, "get_tool_ids_by_names", MagicMock(return_value=[]))
    monkeypatch.setattr(module.skill_db, "create_skill", MagicMock(side_effect=RuntimeError("db down")))

    with pytest.raises(RuntimeError, match="db down"):
        _install(_service(tmp_path))
    assert not (tmp_path / "tenant-a" / "local-skill").exists()


def test_install_rolls_back_database_when_atomic_move_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(module.skill_db, "get_skill_by_name", MagicMock(return_value=None))
    monkeypatch.setattr(module.skill_db, "get_tool_ids_by_names", MagicMock(return_value=[]))
    monkeypatch.setattr(module.skill_db, "create_skill", MagicMock(return_value={"skill_id": 8}))
    delete = MagicMock(return_value=True)
    monkeypatch.setattr(module.skill_db, "delete_skill", delete)
    monkeypatch.setattr(module.os, "replace", MagicMock(side_effect=OSError("locked")))

    with pytest.raises(SkillException, match="local storage"):
        _install(_service(tmp_path))
    delete.assert_called_once_with("local-skill", "tenant-a", updated_by="user-a")


def test_validate_download_rejects_symlink(tmp_path):
    root = tmp_path / "skill"
    root.mkdir()
    (root / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    try:
        (root / "link").symlink_to(root / "SKILL.md")
    except OSError:
        pytest.skip("Symlinks are unavailable on this Windows environment")

    with pytest.raises(SkillException, match="symbolic links"):
        _validate_downloaded_directory(root)


def test_validate_download_enforces_file_count(tmp_path, monkeypatch):
    root = tmp_path / "skill"
    root.mkdir()
    (root / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (root / "extra.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(module, "MAX_SKILL_FILE_COUNT", 1)

    with pytest.raises(SkillException, match="too many files"):
        _validate_downloaded_directory(root)


def test_validate_download_enforces_total_size(tmp_path, monkeypatch):
    root = tmp_path / "skill"
    root.mkdir()
    (root / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    monkeypatch.setattr(module, "MAX_SKILL_TOTAL_BYTES", 1)

    with pytest.raises(SkillException, match="too large"):
        _validate_downloaded_directory(root)


def test_validate_download_rejects_missing_directory(tmp_path):
    with pytest.raises(SkillException, match="does not exist"):
        _validate_downloaded_directory(tmp_path / "missing")


def test_parse_source_timestamp_handles_empty_and_invalid_values():
    assert _parse_source_timestamp(None) is None
    with pytest.raises(module.ModelScopeSkillError, match="last_modified"):
        _parse_source_timestamp("not-a-timestamp")


def test_market_query_methods_delegate_to_adapter(tmp_path):
    adapter = MagicMock()
    adapter.list_skills.return_value = {"items": []}
    adapter.get_skill.return_value = {"skill_id": "@owner/demo"}
    service = _service(tmp_path, adapter)

    assert service.list_skills(search="demo", page_number=2, page_size=8) == {
        "items": []
    }
    assert service.get_skill("@owner/demo") == {"skill_id": "@owner/demo"}
    adapter.list_skills.assert_called_once_with(
        search="demo", page_number=2, page_size=8
    )
