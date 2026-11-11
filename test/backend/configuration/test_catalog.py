# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit contracts for the frozen system configuration catalog."""

from dataclasses import FrozenInstanceError

import pytest

EXPECTED_DEFAULTS = {
    "MAX_TENANT_COUNT": 100,
    "MAX_USERS_PER_TENANT": 10000,
    "MAX_GROUPS_PER_TENANT": 1000,
    "MAX_SUPER_ADMIN_COUNT": 1,
    "MAX_ADMINS_PER_TENANT": 1000,
    "MAX_KNOWLEDGE_BASES_PER_TENANT": 10000,
    "MAX_KNOWLEDGE_BASES_PER_USER": 10,
    "MAX_PRIVILEGED_KNOWLEDGE_BASES_PER_USER": 1000,
    "MAX_KNOWLEDGE_FILE_SIZE_MB": 100,
    "MAX_CONVERSATION_TURNS": 100,
    "MAX_CONVERSATIONS_PER_USER": 1000,
    "MAX_MCP_SERVICES_PER_TENANT": 1000,
    "MCP_REQUEST_TIMEOUT_SECONDS": 10,
    "MAX_EVALUATION_SET_FILE_SIZE_MB": 20,
    "RUNTIME_MCP_TOOL_TIMEOUT_SECONDS": 60,
    "RUNTIME_PARALLEL_EXECUTOR_TIMEOUT_SECONDS": 120,
    "LLM_INCLUDE_LOGPROBS": False,
    "MAX_SKILLS_PER_TENANT": 1000,
    "MAX_SKILL_UPLOAD_SIZE_MB": 10,
}


def _catalog():
    from configuration.catalog import DEFAULT_CATALOG

    return DEFAULT_CATALOG


def _validation_error():
    from configuration.catalog import ConfigurationValidationError

    return ConfigurationValidationError


def test_catalog_contains_exact_frozen_defaults():
    catalog = _catalog()

    assert set(catalog.defaults) == set(EXPECTED_DEFAULTS)
    assert len(catalog.definitions) == 19
    assert catalog.defaults == EXPECTED_DEFAULTS
    assert all(item.recommendation_rule is None for item in catalog.definitions)


def test_snapshot_is_named_typed_and_immutable():
    snapshot = _catalog().build_snapshot(EXPECTED_DEFAULTS)

    assert snapshot.get("MAX_TENANT_COUNT") == 100
    assert snapshot.get("LLM_INCLUDE_LOGPROBS") is False
    assert snapshot.to_dict() == EXPECTED_DEFAULTS
    with pytest.raises(FrozenInstanceError):
        snapshot.values = {}
    with pytest.raises(TypeError):
        snapshot.values["MAX_TENANT_COUNT"] = 5


@pytest.mark.parametrize("value", [True, 0, -1, 1.5, "2", None, [], {}])
def test_positive_integers_reject_invalid_values(value):
    with pytest.raises(_validation_error()):
        _catalog().build_snapshot({**EXPECTED_DEFAULTS, "MAX_TENANT_COUNT": value})


@pytest.mark.parametrize("value", [True, 0, -1, float("nan"), float("inf"), "2", None])
def test_positive_numbers_reject_invalid_values(value):
    with pytest.raises(_validation_error()):
        _catalog().build_snapshot(
            {**EXPECTED_DEFAULTS, "MCP_REQUEST_TIMEOUT_SECONDS": value}
        )


@pytest.mark.parametrize("value", [0.5, 1, 2.5])
def test_positive_numbers_accept_finite_values(value):
    snapshot = _catalog().build_snapshot(
        {**EXPECTED_DEFAULTS, "MCP_REQUEST_TIMEOUT_SECONDS": value}
    )

    assert snapshot.get("MCP_REQUEST_TIMEOUT_SECONDS") == value


@pytest.mark.parametrize("value", [0, 1, "true", None])
def test_boolean_rejects_non_boolean_values(value):
    with pytest.raises(_validation_error()):
        _catalog().build_snapshot({**EXPECTED_DEFAULTS, "LLM_INCLUDE_LOGPROBS": value})


def test_missing_keys_do_not_fall_back_to_environment(monkeypatch):
    monkeypatch.setenv("MAX_TENANT_COUNT", "999")
    values = dict(EXPECTED_DEFAULTS)
    del values["MAX_TENANT_COUNT"]

    with pytest.raises(_validation_error(), match="MAX_TENANT_COUNT"):
        _catalog().build_snapshot(values)


def test_unknown_and_unmanaged_keys_are_rejected():
    with pytest.raises(_validation_error(), match="UNKNOWN"):
        _catalog().validate_changes(EXPECTED_DEFAULTS, {"UNKNOWN": 1})
    with pytest.raises(_validation_error(), match="MAX_AGENTS_PER_TENANT"):
        _catalog().validate_changes(EXPECTED_DEFAULTS, {"MAX_AGENTS_PER_TENANT": 1})


def test_changes_are_validated_against_the_merged_snapshot():
    snapshot = _catalog().validate_changes(
        EXPECTED_DEFAULTS,
        {"MAX_TENANT_COUNT": 5, "LLM_INCLUDE_LOGPROBS": True},
    )

    assert snapshot.get("MAX_TENANT_COUNT") == 5
    assert snapshot.get("LLM_INCLUDE_LOGPROBS") is True
    assert snapshot.get("MAX_USERS_PER_TENANT") == 10000
