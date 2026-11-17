# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Admission resource ownership includes failed construction and failed cleanup."""

import pytest
from nexent.storage.errors import OutcomeUnknown

from infrastructure import knowledge_cleanse as composition
from test.backend.services.test_cleanse_jobs import context


@pytest.mark.parametrize("failure", [None, "body", "bind", "close"])
def test_composition_closes_every_constructed_resource(mocker, failure):
    engine = mocker.patch.object(composition, "record_engine").return_value
    bind_jobs = mocker.patch.object(composition, "bind_cleanse_jobs")
    bind_resources = mocker.patch.object(composition, "bind_cleanse_resources")
    if failure == "bind":
        bind_resources.side_effect = ValueError("controlled binding failure")
    if failure == "close":
        bind_resources.return_value.close.side_effect = RuntimeError("private detail")
    ctx = context()

    def exercise():
        with composition.knowledge_cleanse_ports(
            "tenant-a", "user-a", context=ctx
        ) as ports:
            assert ports == (bind_jobs.return_value, bind_resources.return_value)
            if failure == "body":
                raise ValueError("controlled body failure")

    if failure:
        with pytest.raises(OutcomeUnknown if failure == "close" else ValueError):
            exercise()
    else:
        exercise()
    engine.dispose.assert_called_once()
    bind_jobs.return_value.close.assert_called_once()
    if failure != "bind":
        bind_resources.return_value.close.assert_called_once()
    engine_scope = bind_jobs.call_args.args[0]
    resource_scope = bind_resources.call_args.args[0]
    assert engine_scope.service_role == resource_scope.service_role == "management"
    assert engine_scope.tenant_id == resource_scope.tenant_id == "tenant-a"
    assert engine_scope.actor_id == resource_scope.actor_id == "user-a"
    assert not engine_scope.system and not resource_scope.system
    assert engine_scope.namespaces == {composition.DATASET}
    assert resource_scope.namespaces == set(composition.TABLES)
    composition.record_engine.assert_called_once_with(ctx)


@pytest.mark.parametrize("include_files", [False, True])
@pytest.mark.parametrize("fail", [False, True])
def test_read_resource_scope_includes_files_only_when_explicit_and_always_closes(mocker, include_files, fail):
    engine = mocker.patch.object(composition, "record_engine").return_value
    bind = mocker.patch.object(composition, "bind_cleanse_resources")
    ctx = context()

    def exercise():
        with composition.knowledge_resource_ports("tenant-a", "user-a", context=ctx, include_files=include_files):
            if fail:
                raise ValueError("controlled query failure")

    if fail:
        with pytest.raises(ValueError):
            exercise()
    else:
        exercise()
    scope = bind.call_args.args[0]
    assert ("cleanse_files" in scope.namespaces) is include_files
    assert "knowledge_file_history" not in scope.namespaces
    assert scope.tenant_id == "tenant-a" and scope.actor_id == "user-a" and not scope.system
    bind.return_value.close.assert_called_once()
    engine.dispose.assert_called_once()
