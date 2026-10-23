import sys
from unittest.mock import MagicMock

from test.backend.services import test_conversation_management_service as legacy


service = __import__(
    "backend.services.conversation_management_service",
    fromlist=["update_conversation_workbench_config_service"],
)


class _ValidatedConfig:
    @classmethod
    def model_validate(cls, config):
        return cls(config)

    def __init__(self, config):
        self.config = config

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
