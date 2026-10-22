# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import sys
from unittest.mock import MagicMock

import pytest



service = __import__(
    "management.services.conversation.service",
    fromlist=["update_conversation_workbench_config_service"],
)


class _ValidatedConfig:
    @classmethod
    def model_validate(cls, config):
        return cls(config)

    def __init__(self, config):
        self.config = config
        self.knowledge_scope = config.get("knowledge_scope")

    def model_dump(self, *, mode):
        assert mode == "json"
        return {**self.config, "schema_version": 3}


def test_create_conversation_forwards_workbench_config(monkeypatch):
    create = MagicMock(return_value={"conversation_id": 42})
    monkeypatch.setattr(service, "create_conversation", create)
    config = {"mode": "generic_chat"}

    result = service.create_new_conversation(
        "New chat", "user-a", workbench_config=config
    )

    assert result == {"conversation_id": 42}
    assert create.call_args.kwargs["workbench_config"] is config


def test_update_workbench_config_validates_and_forwards(monkeypatch):
    monkeypatch.setattr(sys.modules["consts.model"], "WorkbenchSessionConfig", _ValidatedConfig, raising=False)
    replace = MagicMock(return_value={"workbench_config_version": 3})
    monkeypatch.setattr(service, "replace_conversation_workbench_config", replace)

    result = service.update_conversation_workbench_config_service(
        conversation_id=42,
        config={"mode": "generic_chat"},
        expected_version=2,
        user_id="user-a",
        only_if_changed=True,
    )

    assert result == {"workbench_config_version": 3}
    replace.assert_called_once_with(
        conversation_id=42,
        user_id="user-a",
        config={"mode": "generic_chat", "schema_version": 3},
        expected_version=2,
        only_if_changed=True,
    )


def test_update_workbench_and_metadata_validates_and_forwards(monkeypatch):
    monkeypatch.setattr(sys.modules["consts.model"], "WorkbenchSessionConfig", _ValidatedConfig, raising=False)
    replace = MagicMock(return_value={"runtime_metadata_version": 5})
    monkeypatch.setattr(service, "replace_conversation_workbench_and_metadata", replace)

    result = service.update_conversation_workbench_and_metadata_service(
        conversation_id=42,
        config={"mode": "generic_chat"},
        expected_config_version=2,
        metadata={"ticket": "NEX-1"},
        expected_metadata_version=4,
        user_id="user-a",
    )

    assert result == {"runtime_metadata_version": 5}
    replace.assert_called_once_with(
        conversation_id=42,
        user_id="user-a",
        config={"mode": "generic_chat", "schema_version": 3},
        expected_config_version=2,
        metadata={"ticket": "NEX-1"},
        expected_metadata_version=4,
    )


@pytest.mark.parametrize("joint", [False, True])
def test_internal_workbench_save_discards_retired_policy(monkeypatch, joint):
    replace_config, replace_joint = MagicMock(), MagicMock()
    monkeypatch.setattr(service, "replace_conversation_workbench_config", replace_config)
    monkeypatch.setattr(service, "replace_conversation_workbench_and_metadata", replace_joint)
    import nexent.core.ext_components.aidp.retrieval_config as policy
    check = MagicMock(side_effect=AssertionError("Prepared internal policy must not be checked again"))
    monkeypatch.setattr(policy, "validate_config", check)
    kwargs = {"conversation_id": 42, "config": {"mode": "generic_chat", "knowledge_scope": {"retrieval_config": {"top_k": 7}}}, "user_id": "user"}
    if joint:
        service.update_conversation_workbench_and_metadata_service(**kwargs, expected_config_version=1, metadata={}, expected_metadata_version=1)
        replace_joint.assert_called_once()
        persisted = replace_joint.call_args.kwargs["config"]
    else:
        service.update_conversation_workbench_config_service(**kwargs, expected_version=1)
        replace_config.assert_called_once()
        persisted = replace_config.call_args.kwargs["config"]
    assert "retrieval_config" not in persisted["knowledge_scope"]
    check.assert_not_called()
