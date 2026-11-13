# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Batch path checks, directory fallback and request-local file freshness."""

import asyncio
import os
import threading
from unittest.mock import Mock

import pytest

from contracts.errors.exceptions import ForbiddenError, SkillException
from management.services.skill import files, service
from management.services.skill.local_config import SkillConfigPaths
from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "CONTAINER_SKILLS_PATH", str(tmp_path))
    from management.services.skill import local_config
    monkeypatch.setattr(local_config, "CONTAINER_SKILLS_PATH", str(tmp_path))
    folder = tmp_path / "sample/config"
    folder.mkdir(parents=True)
    return SkillConfigPaths(str(tmp_path)), folder


def test_two_files_share_one_directory_scan(context, mocker):
    paths, folder = context
    (folder / "config.yaml").write_text("value: 1")
    (folder / "schema.yaml").mkdir()
    scan = mocker.patch.object(os, "scandir", wraps=os.scandir)
    stat = mocker.patch.object(os.path, "isfile", wraps=os.path.isfile)
    assert paths.files_for("sample") == [(str(folder / "config.yaml"), True), (str(folder / "schema.yaml"), False)]
    assert scan.call_count == 1
    assert stat.call_count == 2


def test_listing_a_name_does_not_bypass_stat_access_policy(context, mocker):
    paths, folder = context
    (folder / "config.yaml").write_text("value: 1")
    stat = mocker.patch.object(os.path, "isfile", return_value=False)
    assert [exists for _, exists in paths.files_for("sample")] == [False, False]
    stat.assert_called_once_with(str(folder / "config.yaml"))


def test_missing_parent_does_not_add_leaf_stats(context, mocker):
    paths, folder = context
    folder.rmdir()
    stat = mocker.patch.object(os.path, "isfile", wraps=os.path.isfile)
    assert [exists for _, exists in paths.files_for("sample")] == [False, False]
    stat.assert_not_called()


@pytest.mark.parametrize("error", [PermissionError("not enumerable"), OSError("temporary filesystem error")])
def test_enumeration_failure_falls_back_to_existing_stat_policy(context, mocker, error):
    paths, folder = context
    (folder / "config.yaml").write_text("value: 1")
    mocker.patch.object(os, "scandir", side_effect=error)
    stat = mocker.patch.object(os.path, "isfile", wraps=os.path.isfile)
    assert [exists for _, exists in paths.files_for("sample")] == [True, False]
    assert stat.call_count == 2


def test_existence_is_not_cached_even_within_context(context):
    paths, folder = context
    assert [exists for _, exists in paths.files_for("sample")] == [False, False]
    (folder / "config.yaml").write_text("value: 1")
    assert [exists for _, exists in paths.files_for("sample")] == [True, False]
    (folder / "config.yaml").unlink()
    assert [exists for _, exists in paths.files_for("sample")] == [False, False]


@pytest.mark.parametrize("name", ["../escape", "a/b", "a\\b"])
def test_backend_invalid_name_mapping(context, name):
    paths, _ = context
    with pytest.raises(SkillException):
        paths.files_for(name)


def test_list_resolves_local_directory_once_and_observes_changes(tmp_path, monkeypatch, mocker):
    from management.services.skill import local_config
    monkeypatch.setattr(local_config, "CONTAINER_SKILLS_PATH", str(tmp_path))
    reader = service.SkillService(skill_manager=Mock(), tenant_id="tenant")
    root = mocker.patch.object(reader, "_resolve_local_skills_dir_for_overlay", return_value=str(tmp_path))
    rows = [{"skill_id": number, "name": f"skill-{number}", "config_values": {"db": True}} for number in range(3)]
    mocker.patch.object(service.skill_db, "list_skills", side_effect=lambda *args, **kwargs: [dict(row) for row in rows])
    assert all("config_values" not in row for row in reader.list_skills())
    root.assert_called_once()
    folder = tmp_path / "skill-1/config"
    folder.mkdir(parents=True)
    config = folder / "config.yaml"
    config.write_text("value: 1")
    assert reader.list_skills()[1]["config_values"] == {"value": 1}
    config.write_text("value: 2")
    assert reader.list_skills()[1]["config_values"] == {"value": 2}
    config.unlink()
    assert "config_values" not in reader.list_skills()[1]
    assert root.call_count == 4


def test_optimized_list_keeps_schema_and_current_db_failure_fallback(tmp_path, monkeypatch, mocker):
    from management.services.skill import local_config
    monkeypatch.setattr(local_config, "CONTAINER_SKILLS_PATH", str(tmp_path))
    reader = service.SkillService(skill_manager=Mock(), tenant_id="tenant")
    mocker.patch.object(reader, "_resolve_local_skills_dir_for_overlay", return_value=str(tmp_path))
    row = {"skill_id": 1, "name": "sample", "config_values": {"db": 1}, "config_schemas": [{"name": "db"}]}
    mocker.patch.object(service.skill_db, "list_skills", side_effect=lambda *args, **kwargs: [dict(row)])
    folder = tmp_path / "sample/config"
    folder.mkdir(parents=True)
    config, schema = folder / "config.yaml", folder / "schema.yaml"
    config.write_text("value: 1")
    schema.write_text("value:\n  type: number\n")
    first = reader.list_skills()[0]
    assert first["config_values"] == {"value": 1}
    assert first["config_schemas"][0]["name"] == "value"
    config.write_text("broken: [unterminated")
    assert reader.list_skills()[0]["config_values"] == {"db": 1}
    row["config_values"] = {"db": 2}
    assert reader.list_skills()[0]["config_values"] == {"db": 2}
    config.write_text("value: 2")
    schema.unlink()
    current = reader.list_skills()[0]
    assert current["config_values"] == {"value": 2}
    assert "config_schemas" not in current


def test_empty_list_and_missing_root_do_not_touch_paths(tmp_path, mocker):
    reader = service.SkillService(skill_manager=Mock(), tenant_id="tenant")
    rows = mocker.patch.object(service.skill_db, "list_skills", return_value=[])
    root = mocker.patch.object(reader, "_resolve_local_skills_dir_for_overlay", return_value=None)
    assert reader.list_skills() == []
    root.assert_not_called()
    row = {"skill_id": 1, "name": "sample", "config_values": {"db": True}}
    rows.return_value = [row]
    assert reader.list_skills() == [row]
    root.assert_called_once()


def test_fresh_context_does_not_reuse_other_tenants_root(tmp_path, monkeypatch):
    from management.services.skill import local_config
    monkeypatch.setattr(local_config, "CONTAINER_SKILLS_PATH", str(tmp_path))
    for tenant, value in [("a", 1), ("b", 2)]:
        folder = tmp_path / tenant / "sample/config"
        folder.mkdir(parents=True)
        (folder / "config.yaml").write_text(f"value: {value}")
    first, second = SkillConfigPaths(str(tmp_path / "a")), SkillConfigPaths(str(tmp_path / "b"))
    assert first.files_for("sample")[0][0] != second.files_for("sample")[0][0]
    assert first._resolver is not second._resolver


def test_backend_root_error_mapping(tmp_path, monkeypatch):
    from management.services.skill import local_config
    monkeypatch.setattr(local_config, "CONTAINER_SKILLS_PATH", str(tmp_path / "allowed"))
    with pytest.raises(SkillException, match="Unsafe local skills directory"):
        SkillConfigPaths(str(tmp_path / "outside")).files_for("sample")


def test_backend_escaping_symlink_mapping(context, tmp_path):
    paths, folder = context
    outside = tmp_path.parent / f"{tmp_path.name}-external.yaml"
    outside.write_text("outside: true")
    try:
        try:
            (folder / "config.yaml").symlink_to(outside)
        except OSError as exc:
            pytest.skip(f"Host cannot create symlinks: {exc}")
        with pytest.raises(ForbiddenError, match="Unsafe local skill path"):
            paths.files_for("sample")
    finally:
        outside.unlink()


def test_simultaneous_lists_keep_tenant_roots_isolated(tmp_path, monkeypatch, mocker):
    from management.services.skill import local_config
    monkeypatch.setattr(local_config, "CONTAINER_SKILLS_PATH", str(tmp_path))
    barrier = threading.Barrier(2)
    readers = []
    for tenant, value in [("a", 1), ("b", 2)]:
        folder = tmp_path / tenant / "sample/config"
        folder.mkdir(parents=True)
        (folder / "config.yaml").write_text(f"value: {value}")
        reader = service.SkillService(skill_manager=Mock(), tenant_id=tenant)

        def resolve(root=str(tmp_path / tenant)):
            barrier.wait(timeout=3)
            return root

        mocker.patch.object(reader, "_resolve_local_skills_dir_for_overlay", side_effect=resolve)
        readers.append(reader)
    mocker.patch.object(service.skill_db, "list_skills", side_effect=lambda *args, **kwargs: [
        {"skill_id": 1, "name": "sample", "config_values": {"db": True}}])
    async def run():
        manager = ThreadManager(service_name="path-isolation-test", lane_policies={
            "control-io": LanePolicy(name="control-io", max_workers=2, max_queue_size=0),
        })
        manager.start()
        try:
            results = await asyncio.gather(*(manager.run(
                "control-io", ManagedTaskSpec(task_name="list", owner="test"), reader.list_skills
            ) for reader in readers))
            assert [rows[0]["config_values"] for rows in results] == [{"value": 1}, {"value": 2}]
        finally:
            result = await manager.shutdown(timeout=3)
            assert not result.stuck_execution_ids
            assert manager.snapshot().active_count == 0

    asyncio.run(run())
