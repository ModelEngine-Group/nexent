from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from consts.exceptions import ModelScopeSkillError, SkillException
from nexent.skills.skill_loader import SkillLoader
from services import modelscope_skill_service as module
from services.modelscope_skill_service import (
    ModelScopeSkillService,
    _read_directory_skill_data,
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


class FakeAdapter:
    def __init__(self, *, with_skill_md: bool = True):
        self.with_skill_md = with_skill_md
        self.download_calls: list[str] = []

    def get_skill(self, skill_id: str):
        return {
            "skill_id": "@owner/source-skill",
            "description": "Source description",
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
def patch_container_skills_path(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "services.skill_service.CONTAINER_SKILLS_PATH",
        str(tmp_path),
    )


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


def _mock_create_skill(monkeypatch, create=None):
    monkeypatch.setattr(module.skill_db, "get_skill_by_name", MagicMock(return_value=None))
    if create is None:
        create = MagicMock(side_effect=lambda data, tenant_id: {**data, "skill_id": 9})
    monkeypatch.setattr(module.skill_db, "create_skill", create)
    return create


def _mock_update_skill(monkeypatch, update=None):
    if update is None:
        update = MagicMock(
            side_effect=lambda name, data, tenant_id, updated_by=None: {
                **data,
                "skill_id": 9,
                "name": name,
            }
        )
    monkeypatch.setattr(module.skill_db, "update_skill", update)
    return update


def test_install_skill_parses_db_data_and_moves_snapshot(tmp_path, monkeypatch):
    create = _mock_create_skill(monkeypatch)
    update = _mock_update_skill(monkeypatch)
    monkeypatch.setattr(module.skill_db, "get_tool_ids_by_names", MagicMock(return_value=[7]))

    result = _install(_service(tmp_path))

    destination = tmp_path / "tenant-a" / "local-skill"
    assert result["skill_id"] == 9
    assert destination.joinpath("assets", "note.txt").read_text() == "kept"
    saved_md = destination.joinpath("SKILL.md").read_text(encoding="utf-8")
    assert "name: local-skill" in saved_md
    assert "description: Local description" in saved_md
    created = create.call_args.args[0]
    assert created["unique_id"] == "@owner/source-skill"
    assert created["source"] == "modelscope"
    assert isinstance(created["version_update_time"], datetime)
    updated = update.call_args.args[1]
    assert updated["tool_ids"] == [7]


def test_same_external_skill_can_be_installed_under_different_names(tmp_path, monkeypatch):
    create = _mock_create_skill(
        monkeypatch,
        MagicMock(side_effect=lambda data, tenant_id: dict(data)),
    )
    _mock_update_skill(monkeypatch)
    monkeypatch.setattr(module.skill_db, "get_tool_ids_by_names", MagicMock(return_value=[]))
    adapter = FakeAdapter()
    service = _service(tmp_path, adapter)

    _install(service, "copy-one")
    _install(service, "copy-two")

    assert [call.args[0]["unique_id"] for call in create.call_args_list] == [
        "@owner/source-skill",
        "@owner/source-skill",
    ]


def test_install_parses_schema_and_config_files(tmp_path, monkeypatch):
    _mock_create_skill(monkeypatch)
    update = _mock_update_skill(monkeypatch)
    monkeypatch.setattr(module.skill_db, "get_tool_ids_by_names", MagicMock(return_value=[]))

    _install(_service(tmp_path, ConfiguredAdapter()))

    data = update.call_args.args[1]
    assert data["config_schemas"][0]["name"] == "query"
    assert data["config_values"] == {"query": "default"}


def test_read_directory_normalizes_allowed_tools_and_preserves_script_outputs(
    tmp_path, monkeypatch
):
    skill_dir = tmp_path / "snapshot"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: source-skill
description: Source description
allowed-tools: tool-a, tool-b
script_outputs:
  scripts/run.py:
    type: text
---

Use this Skill.
""",
        encoding="utf-8",
    )
    get_tool_ids = MagicMock(return_value=[7, 8])
    monkeypatch.setattr(module.skill_db, "get_tool_ids_by_names", get_tool_ids)

    result = _read_directory_skill_data(
        skill_dir,
        local_name="local-skill",
        description="Local description",
        tags=["local"],
        tenant_id="tenant-a",
    )

    get_tool_ids.assert_called_once_with(["tool-a", "tool-b"], "tenant-a")
    assert result["tool_ids"] == [7, 8]
    assert result["script_outputs"] == {"scripts/run.py": {"type": "text"}}

    rewritten = SkillLoader.load(str(skill_dir / "SKILL.md"))
    assert rewritten["allowed_tools"] == ["tool-a", "tool-b"]
    assert rewritten["script_outputs"] == {
        "scripts/run.py": {"type": "text"}
    }


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
    with pytest.raises(SkillException, match="Invalid skill name"):
        _install(_service(tmp_path), "../escape")


def test_install_rejects_missing_skill_md(tmp_path, monkeypatch):
    _mock_create_skill(monkeypatch)
    delete = MagicMock(return_value=True)
    monkeypatch.setattr(module.skill_db, "delete_skill", delete)

    with pytest.raises(SkillException, match="root SKILL.md"):
        _install(_service(tmp_path, FakeAdapter(with_skill_md=False)))
    delete.assert_called_once_with("local-skill", "tenant-a", updated_by="user-a")


def test_install_rejects_group_from_another_tenant(tmp_path, monkeypatch):
    monkeypatch.setattr(module.skill_db, "get_skill_by_name", MagicMock(return_value=None))
    module.query_groups_by_tenant.return_value = {
        "groups": [{"group_id": 2}],
        "total": 1,
    }

    with pytest.raises(SkillException, match="do not belong"):
        _install(_service(tmp_path))


def test_install_does_not_download_when_database_insert_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(module.skill_db, "get_skill_by_name", MagicMock(return_value=None))
    monkeypatch.setattr(module.skill_db, "create_skill", MagicMock(side_effect=RuntimeError("db down")))
    adapter = FakeAdapter()

    with pytest.raises(RuntimeError, match="db down"):
        _install(_service(tmp_path, adapter))
    assert adapter.download_calls == []
    assert not (tmp_path / "tenant-a" / "local-skill").exists()


def test_install_rolls_back_database_when_download_fails(tmp_path, monkeypatch):
    _mock_create_skill(monkeypatch)
    delete = MagicMock(return_value=True)
    monkeypatch.setattr(module.skill_db, "delete_skill", delete)
    adapter = FakeAdapter()
    adapter.download_skill = MagicMock(side_effect=ModelScopeSkillError("download failed"))

    with pytest.raises(ModelScopeSkillError, match="download failed"):
        _install(_service(tmp_path, adapter))
    delete.assert_called_once_with("local-skill", "tenant-a", updated_by="user-a")
    assert not (tmp_path / "tenant-a" / "local-skill").exists()


def test_install_rolls_back_database_when_atomic_move_fails(tmp_path, monkeypatch):
    _mock_create_skill(monkeypatch)
    _mock_update_skill(monkeypatch)
    monkeypatch.setattr(module.skill_db, "get_tool_ids_by_names", MagicMock(return_value=[]))
    delete = MagicMock(return_value=True)
    monkeypatch.setattr(module.skill_db, "delete_skill", delete)
    monkeypatch.setattr(module.shutil, "move", MagicMock(side_effect=OSError("locked")))

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


def test_get_market_skill_detail_returns_empty_when_not_installed(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        module.skill_db,
        "get_skill_by_unique_id_and_owner",
        MagicMock(return_value=None),
    )
    adapter = MagicMock()

    result = _service(tmp_path, adapter).get_market_skill_detail(
        skill_id="@owner/missing",
        source="modelscope",
        user_id="user-a",
        tenant_id="tenant-a",
    )

    assert result == {}
    adapter.get_skill.assert_not_called()


def test_get_market_skill_detail_returns_local_record_without_upstream(
    tmp_path, monkeypatch
):
    local_record = {
        "skill_id": 12,
        "name": "local-demo",
        "source": "modelscope",
        "unique_id": "@owner/demo",
        "version_update_time": "2026-08-01T00:00:00Z",
    }
    monkeypatch.setattr(
        module.skill_db,
        "get_skill_by_unique_id_and_owner",
        MagicMock(return_value=local_record),
    )
    adapter = MagicMock()

    result = _service(tmp_path, adapter).get_market_skill_detail(
        skill_id="@owner/demo",
        source="modelscope",
        user_id="user-a",
        tenant_id="tenant-a",
    )

    assert result == local_record
    assert "upstream_last_modified" not in result
    adapter.get_skill.assert_not_called()


def test_get_upstream_last_modified_returns_hub_timestamp(tmp_path):
    adapter = MagicMock()
    adapter.get_skill.return_value = {
        "skill_id": "@owner/demo",
        "last_modified": "2026-08-07T06:37:46Z",
    }

    result = _service(tmp_path, adapter).get_upstream_last_modified("@owner/demo")

    assert result == "2026-08-07T06:37:46Z"
    adapter.get_skill.assert_called_once_with("@owner/demo")


def test_get_upstream_last_modified_returns_none_for_empty_unique_id(tmp_path):
    adapter = MagicMock()

    result = _service(tmp_path, adapter).get_upstream_last_modified("  ")

    assert result is None
    adapter.get_skill.assert_not_called()


def test_get_market_skill_detail_skips_upstream_for_non_modelscope_source(
    tmp_path, monkeypatch
):
    local_record = {
        "skill_id": 12,
        "name": "local-demo",
        "source": "custom",
        "unique_id": "@owner/demo",
    }
    monkeypatch.setattr(
        module.skill_db,
        "get_skill_by_unique_id_and_owner",
        MagicMock(return_value=local_record),
    )
    adapter = MagicMock()

    result = _service(tmp_path, adapter).get_market_skill_detail(
        skill_id="@owner/demo",
        source="custom",
        user_id="user-a",
        tenant_id="tenant-a",
    )

    assert result == local_record
    assert "upstream_last_modified" not in result
    adapter.get_skill.assert_not_called()


def test_get_upstream_last_modified_returns_none_when_hub_missing(tmp_path):
    from consts.exceptions import ModelScopeSkillNotFoundError

    adapter = MagicMock()
    adapter.get_skill.side_effect = ModelScopeSkillNotFoundError("missing")

    result = _service(tmp_path, adapter).get_upstream_last_modified("@owner/demo")

    assert result is None


def test_update_skill_refreshes_downloaded_content_and_preserves_local_metadata(
    tmp_path, monkeypatch
):
    existing_skill = {
        "skill_id": 9,
        "name": "local-skill",
        "description": "Local description",
        "tags": ["local", "demo"],
        "source": "modelscope",
        "unique_id": "@owner/source-skill",
    }
    monkeypatch.setattr(
        module.skill_db, "get_skill_by_id", MagicMock(return_value=existing_skill)
    )
    update_by_id = MagicMock(
        side_effect=lambda skill_id, data, tenant_id, updated_by=None: {
            **existing_skill,
            **data,
            "skill_id": skill_id,
        }
    )
    monkeypatch.setattr(module.skill_db, "update_skill_by_id", update_by_id)
    monkeypatch.setattr(
        module.skill_db, "get_tool_ids_by_names", MagicMock(return_value=[7])
    )
    destination = tmp_path / "tenant-a" / "local-skill"
    destination.mkdir(parents=True)
    (destination / "SKILL.md").write_text("old", encoding="utf-8")

    result = _service(tmp_path).update_skill(
        skill_id=9,
        unique_id="@owner/source-skill",
        tenant_id="tenant-a",
        user_id="user-a",
    )

    assert result["skill_id"] == 9
    assert destination.joinpath("assets", "note.txt").read_text() == "kept"
    saved_md = destination.joinpath("SKILL.md").read_text(encoding="utf-8")
    assert "name: local-skill" in saved_md
    assert "description: Source description" in saved_md
    updated = update_by_id.call_args.args[1]
    assert updated["tool_ids"] == [7]
    assert updated["description"] == "Source description"
    assert isinstance(updated["version_update_time"], datetime)
    assert "name" not in updated
    assert "tags" not in updated


def test_update_skill_rejects_non_modelscope_skill(tmp_path, monkeypatch):
    monkeypatch.setattr(
        module.skill_db,
        "get_skill_by_id",
        MagicMock(
            return_value={
                "skill_id": 9,
                "name": "local-skill",
                "description": "Local description",
                "tags": ["local"],
                "source": "custom",
                "unique_id": "@owner/source-skill",
            }
        ),
    )

    with pytest.raises(SkillException, match="Only ModelScope skills can be updated"):
        _service(tmp_path).update_skill(
            skill_id=9,
            unique_id="@owner/source-skill",
            tenant_id="tenant-a",
            user_id="user-a",
        )
