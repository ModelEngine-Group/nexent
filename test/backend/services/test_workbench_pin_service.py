"""Isolated identity, validation and persistence error tests."""

import pytest

from consts.exceptions import ConversationNotFoundError, UnauthorizedError, ValidationError
from services import workbench_pin_service as service


@pytest.mark.parametrize("user,tenant", [(None, "t"), ("u", None), ("", "t"), ("u", "")])
def test_missing_identity_rejected_without_db(mocker, user, tenant):
    db = mocker.patch.object(service, "list_workbench_pins")
    with pytest.raises(UnauthorizedError):
        service.get_workbench_pins(user, tenant)
    db.assert_not_called()


def test_reads_canonical_scoped_pins(mocker):
    items = [{"conversation_id": 2}, {"conversation_id": 1}]
    db = mocker.patch.object(service, "list_workbench_pins", return_value=items)
    assert service.get_workbench_pins("u", "t") == {"items": items}
    db.assert_called_once_with("u", "t")


@pytest.mark.parametrize("conversation_id,pinned", [(0, True), (-1, True), (2147483648, True), (True, True), (1, "true"), (1, 1)])
def test_invalid_input_rejected_before_write(mocker, conversation_id, pinned):
    db = mocker.patch.object(service, "set_workbench_pin")
    with pytest.raises(ValidationError):
        service.update_workbench_pin(conversation_id, pinned, "u", "t")
    db.assert_not_called()


@pytest.mark.parametrize("pinned", [True, False])
def test_write_passes_scoped_intent_and_canonical_order(mocker, pinned):
    db = mocker.patch.object(service, "set_workbench_pin", return_value=[{"conversation_id": 1}])
    assert service.update_workbench_pin(1, pinned, "u", "t") == {"items": [{"conversation_id": 1}]}
    db.assert_called_once_with(1, pinned, "u", "t")


@pytest.mark.parametrize("error", [ConversationNotFoundError("missing"), RuntimeError("db unavailable")])
def test_persistence_failure_propagates(mocker, error):
    mocker.patch.object(service, "set_workbench_pin", side_effect=error)
    with pytest.raises(type(error)):
        service.update_workbench_pin(1, True, "u", "t")


def test_identity_length_matches_schema(mocker):
    db = mocker.patch.object(service, "list_workbench_pins", return_value=[])
    assert service.get_workbench_pins("u" * 100, "t" * 100) == {"items": []}
    with pytest.raises(ValidationError):
        service.get_workbench_pins("u" * 101, "t")
    assert db.call_count == 1
