"""AC-043/044/045 tests for shared long-term memory versions."""

from unittest.mock import patch

import pytest

from services.memory_long_term_service import (
    LongTermMemoryConflict, LongTermMemoryError, LongTermMemoryService, subject_id_for,
)


def test_ac043_manual_version_metadata_and_parent_delegated():
    service = LongTermMemoryService()
    with patch("services.memory_long_term_service.try_scope_lock") as lock, patch(
        "services.memory_long_term_service.memory_long_term_db.create_and_activate"
    ) as create:
        lock.return_value.__enter__.return_value = True
        create.return_value = {"version_id": 2, "source": "manual", "parent_version_id": 1}
        result = service.create_manual("t", "u", "user", "# User Memory", 1)
    assert result["parent_version_id"] == 1
    assert create.call_args.kwargs["source"] == "manual"
    assert create.call_args.kwargs["expected_active_version_id"] == 1


def test_ac044_empty_manual_version_is_allowed():
    service = LongTermMemoryService()
    with patch("services.memory_long_term_service.try_scope_lock") as lock, patch(
        "services.memory_long_term_service.memory_long_term_db.create_and_activate",
        return_value={"content": ""},
    ):
        lock.return_value.__enter__.return_value = True
        assert service.create_manual("t", "u", "user", "", None)["content"] == ""


def test_ac045_stale_and_busy_are_conflicts():
    service = LongTermMemoryService()
    with patch("services.memory_long_term_service.try_scope_lock") as lock:
        lock.return_value.__enter__.return_value = False
        with pytest.raises(LongTermMemoryConflict): service.create_manual("t", "u", "user", "x", None)
    with patch("services.memory_long_term_service.try_scope_lock") as lock, patch(
        "services.memory_long_term_service.memory_long_term_db.create_and_activate", return_value=None
    ):
        lock.return_value.__enter__.return_value = True
        with pytest.raises(LongTermMemoryConflict): service.create_manual("t", "u", "user", "x", 1)


def test_ac043_scope_and_limit_validation():
    assert subject_id_for("tenant", "t", "u") == "t"
    assert subject_id_for("user", "t", "u") == "u"
    with pytest.raises(LongTermMemoryError): subject_id_for("agent", "t", "u")
    with pytest.raises(LongTermMemoryError): LongTermMemoryService().create_manual("t", "u", "user", "x" * 10001, None)
