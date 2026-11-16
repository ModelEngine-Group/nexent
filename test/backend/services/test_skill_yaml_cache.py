# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Successful-parse caching, freshness and resource bounds with real local files."""

import asyncio
import json
import os
import threading
from unittest.mock import Mock

import pytest

from management.services.skill import yaml_cache
from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager


def test_hits_are_isolated_and_parsers_and_tenant_paths_are_distinct(tmp_path):
    cache = yaml_cache.SkillYamlCache()
    first, second = tmp_path / "a.yaml", tmp_path / "b.yaml"
    for path in [first, second]:
        path.write_text('{"nested": [1]}')
    parser = Mock(side_effect=json.loads)
    result = cache.load(str(first), parser)
    result["nested"].append(99)
    assert cache.load(str(first), parser) == {"nested": [1]}
    assert parser.call_count == 1
    assert cache.load(str(second), parser) == {"nested": [1]}
    other_parser = Mock(return_value=[{"schema": True}])
    assert cache.load(str(first), other_parser) == [{"schema": True}]
    assert parser.call_count == 2
    assert other_parser.call_count == 1


def test_updates_replacement_deletion_and_recreation(tmp_path):
    path = tmp_path / "config.yaml"
    cache = yaml_cache.SkillYamlCache()
    parser = Mock(side_effect=json.loads)
    path.write_text('{"value": 1}')
    assert cache.load(str(path), parser) == {"value": 1}
    path.write_text('{"value": 22}')
    assert cache.load(str(path), parser) == {"value": 22}
    before = path.stat()
    replacement = tmp_path / "replacement.yaml"
    replacement.write_text('{"value": 33}')
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    replacement.replace(path)
    assert cache.load(str(path), parser) == {"value": 33}
    path.unlink()
    with pytest.raises(FileNotFoundError):
        cache.load(str(path), parser)
    path.write_text('{"value": 44}')
    assert cache.load(str(path), parser) == {"value": 44}
    assert parser.call_count == 4


def test_parse_and_read_failures_never_serve_old_value_or_poison_cache(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text('{"value": 1}')
    cache = yaml_cache.SkillYamlCache()
    parser = Mock(side_effect=json.loads)
    assert cache.load(str(path), parser) == {"value": 1}
    path.write_text("invalid json")
    for _ in range(2):
        with pytest.raises(ValueError):
            cache.load(str(path), parser)
    assert parser.call_count == 3
    path.write_text('{"value": 2}')
    with monkeypatch.context() as patch:
        patch.setattr("builtins.open", Mock(side_effect=PermissionError("denied")))
        with pytest.raises(PermissionError):
            cache.load(str(path), parser)
    assert cache.load(str(path), parser) == {"value": 2}


def test_changed_during_parse_only_caches_the_bytes_that_were_read(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text('{"value": 1}')
    cache = yaml_cache.SkillYamlCache()

    def parse_and_edit(raw):
        path.write_text('{"value": 22}')
        return json.loads(raw)

    parser = Mock(side_effect=parse_and_edit)
    assert cache.load(str(path), parser) == {"value": 1}
    parser.side_effect = json.loads
    assert cache.load(str(path), parser) == {"value": 22}
    assert cache.load(str(path), parser) == {"value": 22}
    assert parser.call_count == 2


def test_same_size_edit_with_restored_timestamp_and_replacement_are_visible(tmp_path):
    path = tmp_path / "config.yaml"
    replacement = tmp_path / "new.yaml"
    path.write_text("old")
    replacement.write_text("new")
    cache = yaml_cache.SkillYamlCache()
    assert cache.load(str(path), bytes.decode) == "old"
    before = path.stat()
    path.write_text("alt")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert cache.load(str(path), bytes.decode) == "alt"
    replacement.replace(path)
    assert cache.load(str(path), bytes.decode) == "new"


def test_warm_cache_does_not_bypass_read_permissions(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("value")
    cache = yaml_cache.SkillYamlCache()
    assert cache.load(str(path), bytes.decode) == "value"
    monkeypatch.setattr("builtins.open", Mock(side_effect=PermissionError("denied")))
    with pytest.raises(PermissionError, match="denied"):
        cache.load(str(path), bytes.decode)


def test_hits_update_lru_recency(tmp_path):
    cache = yaml_cache.SkillYamlCache(max_entries=2)
    parser = Mock(side_effect=bytes.decode)
    paths = [tmp_path / f"{number}.yaml" for number in range(3)]
    for path in paths:
        path.write_text("value")
    for number in [0, 1, 0, 2, 0]:
        assert cache.load(str(paths[number]), parser) == "value"
    assert parser.call_count == 3
    assert cache.load(str(paths[1]), parser) == "value"
    assert parser.call_count == 4


@pytest.mark.parametrize("max_entries,max_bytes", [(2, 100), (100, 4), (0, 100), (100, 0)])
def test_lru_is_bounded_and_oversized_inputs_are_not_retained(tmp_path, max_entries, max_bytes):
    cache = yaml_cache.SkillYamlCache(max_entries=max_entries, max_bytes=max_bytes)
    parser = Mock(side_effect=bytes.decode)
    paths = [tmp_path / f"{number}.yaml" for number in range(4)]
    for path in paths:
        path.write_text("123")
        assert cache.load(str(path), parser) == "123"
    assert len(cache._entries) <= max_entries
    assert cache._bytes <= max_bytes
    before = parser.call_count
    assert cache.load(str(paths[0]), parser) == "123"
    assert parser.call_count == before + 1
    large = tmp_path / "large.yaml"
    large.write_text("z" * 101)
    for _ in range(2):
        assert cache.load(str(large), parser) == "z" * 101
    assert len(cache._stripes) == 32


@pytest.mark.asyncio
async def test_concurrent_cache_misses_parse_once_and_release_managed_workers(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text('{"value": []}')
    cache = yaml_cache.SkillYamlCache()
    started, release = threading.Event(), threading.Event()

    def parse(raw):
        started.set()
        assert release.wait(3)
        return json.loads(raw)

    parser = Mock(side_effect=parse)
    manager = ThreadManager(service_name="yaml-cache-test", lane_policies={
        "control-io": LanePolicy(name="control-io", max_workers=4, max_queue_size=8),
    })
    manager.start()

    async def load():
        return await manager.run("control-io", ManagedTaskSpec(task_name="yaml", owner="test"),
                                 cache.load, str(path), parser)

    tasks = [asyncio.create_task(load()) for _ in range(8)]
    try:
        async def wait_started():
            while not started.is_set():
                await asyncio.sleep(0.001)
        await asyncio.wait_for(wait_started(), 2)
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks), 4)
        assert parser.call_count == 1
        results[0]["value"].append(9)
        assert all(row == {"value": []} for row in results[1:])
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        result = await manager.shutdown(timeout=3)
        assert not result.stuck_execution_ids
        assert manager.snapshot().active_count == 0
