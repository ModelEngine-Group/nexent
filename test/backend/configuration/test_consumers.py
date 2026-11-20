# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Focused proof that business operations use their current local snapshot."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from infrastructure.system_configuration.catalog import DEFAULT_CATALOG
from contracts.errors.exceptions import AppException, TenantResourceLimitError

from test.backend.configuration.test_catalog import EXPECTED_DEFAULTS


def _snapshot(**changes):
    return DEFAULT_CATALOG.build_snapshot({**EXPECTED_DEFAULTS, **changes})


async def test_knowledge_upload_uses_one_snapshot_for_bytes_and_error(mocker):
    from management.services.file import service

    mocker.patch.object(
        service,
        "get_config_snapshot",
        return_value=_snapshot(MAX_KNOWLEDGE_FILE_SIZE_MB=1),
    )
    mocker.patch.object(
        service, "_get_upload_size", AsyncMock(return_value=1024 * 1024 + 1)
    )
    upload = SimpleNamespace(filename="large.pdf")

    with pytest.raises(AppException) as error:
        await service._validate_knowledge_file_sizes([upload])

    assert error.value.details["limit_mb"] == 1
    assert error.value.details["limit_bytes"] == 1024 * 1024
    assert "1 MB" in str(error.value)
    service.get_config_snapshot.assert_called_once_with()


def test_evaluation_upload_uses_current_database_limit(mocker):
    from management.api.evaluation import evaluation_set

    mocker.patch.object(
        evaluation_set,
        "get_config_snapshot",
        return_value=_snapshot(MAX_EVALUATION_SET_FILE_SIZE_MB=1),
    )

    with pytest.raises(AppException) as error:
        evaluation_set._validate_evaluation_set_file_size(
            b"x" * (1024 * 1024 + 1), "cases.xlsx"
        )

    assert error.value.details["limit_mb"] == 1
    assert error.value.details["limit_bytes"] == 1024 * 1024


def test_conversation_creation_uses_refreshed_limit(mocker):
    from management.db.conversation import repository

    session = Mock()
    session.scalar.return_value = 1
    mocker.patch.object(
        repository,
        "get_config_snapshot",
        return_value=_snapshot(MAX_CONVERSATIONS_PER_USER=1),
    )

    with pytest.raises(AppException) as error:
        repository._enforce_user_conversation_limit(session, "user-1")

    assert error.value.details["limit"] == 1


def test_conversation_turn_limit_boundaries_and_bypasses(mocker):
    from contracts.constants.constants import MESSAGE_ROLE
    from contracts.conversation import MessageSource
    from management.db.conversation import repository

    session = Mock()
    session.scalar.return_value = 1
    getter = mocker.patch.object(
        repository,
        "get_config_snapshot",
        return_value=_snapshot(MAX_CONVERSATION_TURNS=1),
    )

    with pytest.raises(AppException) as error:
        repository._enforce_conversation_turn_limit(
            session, 42, MESSAGE_ROLE["USER"], "user-1"
        )

    assert error.value.details == {
        "resource": "conversation_turns",
        "scope": "conversation",
        "limit": 1,
        "current_count": 1,
    }
    getter.assert_called_once_with()

    session.scalar.return_value = 0
    repository._enforce_conversation_turn_limit(
        session, 42, MESSAGE_ROLE["USER"], "user-1"
    )

    getter.reset_mock()
    for role, user_id, source in (
        (MESSAGE_ROLE["ASSISTANT"], "user-1", MessageSource.CHAT),
        (MESSAGE_ROLE["USER"], "user-1", MessageSource.AUTOMATION),
        (MESSAGE_ROLE["USER"], None, MessageSource.CHAT),
    ):
        session.scalar.return_value = 1
        repository._enforce_conversation_turn_limit(
            session, 42, role, user_id, source
        )
    getter.assert_not_called()


def test_identity_limit_uses_snapshot_instead_of_import_time_constant(mocker):
    from management.db.identity import user_tenant

    query = Mock()
    query.filter.return_value = query
    query.count.return_value = 1
    session = Mock()
    session.query.return_value = query
    mocker.patch.object(
        user_tenant,
        "get_config_snapshot",
        return_value=_snapshot(MAX_USERS_PER_TENANT=1),
    )

    with pytest.raises(TenantResourceLimitError) as error:
        user_tenant._validate_user_tenant_limit(session, "tenant-1", "USER")

    assert error.value.limit == 1


async def test_new_model_bindings_capture_current_logprobs_flag(mocker):
    from management.services.model import run_bindings

    main_record = {
        "model_id": None,
        "profile_schema_version": None,
        "model_factory": "openai",
        "model_name": "model",
    }
    mocker.patch.object(run_bindings, "get_model_records", return_value=[])
    mocker.patch.object(
        run_bindings.tenant_config_manager,
        "get_model_config",
        return_value=main_record,
    )
    mocker.patch.object(run_bindings, "restore_model_snapshot", return_value=None)
    mocker.patch.object(run_bindings, "resolve_prompt_cache_profile", return_value=None)
    getter = mocker.patch.object(
        run_bindings,
        "get_config_snapshot",
        side_effect=[
            _snapshot(LLM_INCLUDE_LOGPROBS=True),
            _snapshot(LLM_INCLUDE_LOGPROBS=False),
        ],
    )

    enabled = await run_bindings.create_model_config_list("tenant-1")
    disabled = await run_bindings.create_model_config_list("tenant-1")

    assert [item.extra_body for item in enabled] == [{"logprobs": True}] * 2
    assert [item.extra_body for item in disabled] == [None, None]
    assert getter.call_count == 2


async def test_resolved_model_bindings_capture_current_logprobs_flag(mocker):
    from management.services.model import run_bindings
    from test.sdk.core.model_service.conftest import (
        openai_profile as resolved_profile_fixture,
    )

    snapshot = resolved_profile_fixture.__wrapped__()
    main_record = {
        "model_id": 1,
        "profile_schema_version": "v1",
        "display_name": "model",
        "api_key": "",
        "http_headers": {},
    }
    mocker.patch.object(run_bindings, "get_model_records", return_value=[main_record])
    mocker.patch.object(
        run_bindings.tenant_config_manager,
        "get_model_config",
        return_value=main_record,
    )
    mocker.patch.object(run_bindings, "restore_model_snapshot", return_value=snapshot)
    mocker.patch("infrastructure.agent_model_config.restore_model_snapshot", return_value=snapshot)
    mocker.patch(
        "infrastructure.model_adapter.project_saved_outlet",
        return_value={"reasoning_capability": None},
    )
    mocker.patch.object(
        run_bindings,
        "get_config_snapshot",
        side_effect=[
            _snapshot(LLM_INCLUDE_LOGPROBS=True),
            _snapshot(LLM_INCLUDE_LOGPROBS=False),
        ],
    )

    enabled = await run_bindings.create_model_config_list("tenant-1")
    disabled = await run_bindings.create_model_config_list("tenant-1")

    assert {item.cite_name: item.extra_body for item in enabled} == {
        "model": None,
        "main_model": {"logprobs": True},
        "sub_model": {"logprobs": True},
    }
    assert {item.cite_name: item.extra_body for item in disabled} == {
        "model": None,
        "main_model": None,
        "sub_model": None,
    }
