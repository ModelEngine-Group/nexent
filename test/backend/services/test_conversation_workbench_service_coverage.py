# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import sys
from unittest.mock import MagicMock
from types import ModuleType

import pytest

from test.backend.services import test_conversation_management_service as legacy


service = __import__(
    "management.services.conversation.service",
    fromlist=["update_conversation_workbench_config_service"],
)


@pytest.fixture(autouse=True)
def retrieval_validation(monkeypatch):
    module = ModuleType("services.knowledge_scope_service")
    module.validate_conversation_retrieval_config = MagicMock()
    monkeypatch.setitem(sys.modules, "services.knowledge_scope_service", module)
    return module.validate_conversation_retrieval_config


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
        tenant_id="tenant-a",
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
        tenant_id="tenant-a",
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
def test_invalid_retrieval_policy_is_rejected_before_either_write(monkeypatch, retrieval_validation, joint):
    monkeypatch.setattr(sys.modules["consts.model"], "WorkbenchSessionConfig", _ValidatedConfig, raising=False)
    replace_config = MagicMock()
    replace_joint = MagicMock()
    monkeypatch.setattr(service, "replace_conversation_workbench_config", replace_config)
    monkeypatch.setattr(service, "replace_conversation_workbench_and_metadata", replace_joint)
    retrieval_validation.side_effect = ValueError("top_k: expected integer 1-100")
    kwargs = {"conversation_id": 42, "config": {"mode": "generic_chat", "knowledge_scope": {"retrieval_config": {"top_k": 0}}}, "user_id": "user", "tenant_id": "tenant"}
    with pytest.raises(ValueError, match="top_k"):
        if joint:
            service.update_conversation_workbench_and_metadata_service(**kwargs, expected_config_version=1, metadata={}, expected_metadata_version=1)
        else:
            service.update_conversation_workbench_config_service(**kwargs, expected_version=1)
    replace_config.assert_not_called()
    replace_joint.assert_not_called()
    retrieval_validation.assert_called_once_with(kwargs["config"]["knowledge_scope"], "tenant")
