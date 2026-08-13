"""Regression tests for atomic long-term-memory activation ordering."""

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from database import memory_long_term_db


class _VersionRow:
    def __init__(self, version_id: int, active: bool, events: list[str]):
        self.version_id = version_id
        self._is_active = active
        self._events = events
        self.tenant_id = "tenant"
        self.scope = "user"
        self.subject_id = "user"
        self.version_no = version_id
        self.parent_version_id = None
        self.source = "manual"
        self.author_user_id = "user"
        self.editor_user_id = "user"
        self.authored_at = datetime.now(timezone.utc)
        self.dreaming_run_id = None
        self.character_count = 1
        self.generation_audit = {}
        self.evidence_ids = []
        self.fallback_details = {}
        self.omission_details = {}
        self.content = "x"
        self.raw_dreaming_input = None
        self.delete_flag = "N"

    @property
    def is_active(self):
        return self._is_active

    @is_active.setter
    def is_active(self, value):
        self._is_active = value
        self._events.append("activate" if value else "deactivate")


def test_historical_activation_flushes_deactivation_before_activation():
    events: list[str] = []
    current = _VersionRow(5, True, events)
    target = _VersionRow(1, False, events)
    session = MagicMock()
    session.query.return_value.filter.return_value.with_for_update.return_value.all.return_value = [
        target,
        current,
    ]
    session.flush.side_effect = lambda: events.append("flush")

    @contextmanager
    def session_scope():
        yield session

    with patch.object(memory_long_term_db, "get_db_session", session_scope):
        status, value = memory_long_term_db.activate(
            "tenant", "user", "user", 1, "user", 5
        )

    assert status == "ok"
    assert value["version_id"] == 1
    assert events[:3] == ["deactivate", "flush", "activate"]
    session.commit.assert_called_once_with()
