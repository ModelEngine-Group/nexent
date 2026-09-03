import pytest
from consts.model import TagAssignmentFilter
from database.tag_management_db import TagManagementDB
from services.tag_management_service import TagManagementService


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def distinct(self):
        return self

    def all(self):
        return self.rows


class _Session:
    def __init__(self, result_sets):
        self.result_sets = iter(result_sets)
        self.query_count = 0

    def query(self, *args, **kwargs):
        self.query_count += 1
        return _Query(next(self.result_sets))


class _SessionContext:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc_value, traceback):
        return False


def test_filter_uses_or_within_definition_and_and_across_definitions(monkeypatch):
    session = _Session(
        [
            [("resource-1",), ("resource-2",)],
            [("resource-2",), ("resource-3",)],
        ]
    )
    monkeypatch.setattr(
        "database.tag_management_db.get_db_session", lambda: _SessionContext(session)
    )

    result = TagManagementService.filter_authorized_resource_ids(
        "tenant-a",
        "skill",
        ["resource-1", "resource-2", "resource-2", "resource-3"],
        [
            TagAssignmentFilter(definition_id=10, value_ids=[100, 101]),
            TagAssignmentFilter(definition_id=20, value_ids=[200]),
        ],
    )

    assert result == ["resource-2"]
    assert session.query_count == 2


def test_filter_with_no_predicates_returns_unique_authorized_ids_without_querying(monkeypatch):
    def fail_if_opened():
        pytest.fail("an empty filter list must not query assignments")

    monkeypatch.setattr("database.tag_management_db.get_db_session", fail_if_opened)

    result = TagManagementService.filter_authorized_resource_ids(
        "tenant-a", "tool", ["resource-1", "resource-1", "resource-2"], []
    )

    assert result == ["resource-1", "resource-2"]


def test_filter_never_expands_beyond_authorized_candidates(monkeypatch):
    session = _Session([[('resource-1',), ('resource-3',)]])
    monkeypatch.setattr(
        "database.tag_management_db.get_db_session", lambda: _SessionContext(session)
    )

    result = TagManagementDB.filter_authorized_resource_ids(
        "tenant-a",
        "tool",
        ["resource-1", "resource-2"],
        [TagAssignmentFilter(definition_id=10, value_ids=[100])],
    )

    assert result == ["resource-1"]
