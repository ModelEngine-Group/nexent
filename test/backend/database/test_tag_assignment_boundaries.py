from types import SimpleNamespace

import pytest
from consts.exceptions import TagManagementConflictError
from database.tag_management_db import TagManagementDB


def _value_rows(value_ids: list[int]):
    definition = SimpleNamespace(
        definition_id=7,
        definition_key="category",
        definition_name="Category",
        selection_mode="multi_select",
    )
    return [
        (
            SimpleNamespace(
                value_id=value_id,
                display_value=str(value_id),
                status="active",
            ),
            definition,
        )
        for value_id in value_ids
    ]


@pytest.mark.parametrize("value_count", [99, 100])
def test_replacement_validation_accepts_distinct_values_at_or_below_capacity(value_count):
    value_ids = list(range(1, value_count + 1))

    TagManagementDB._validate_replacement_values(value_ids, _value_rows(value_ids))


def test_replacement_validation_rejects_101_distinct_values():
    value_ids = list(range(1, 102))

    with pytest.raises(TagManagementConflictError) as error:
        TagManagementDB._validate_replacement_values(value_ids, _value_rows(value_ids))

    assert error.value.details == {
        "limit": 100,
        "current_count": 101,
        "scope": "assignment",
    }


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def with_for_update(self):
        return self

    def all(self):
        return self.rows


class _Session:
    def __init__(self, existing_assignments):
        self.existing_assignments = existing_assignments
        self.deleted = []
        self.added = []
        self.flushed = False

    def query(self, *args, **kwargs):
        return _Query(self.existing_assignments)

    def delete(self, assignment):
        self.deleted.append(assignment)

    def add_all(self, assignments):
        self.added.extend(assignments)

    def flush(self):
        self.flushed = True


class _SessionContext:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc_value, traceback):
        return False


def test_over_capacity_replacement_rejects_before_deleting_prior_rows(monkeypatch):
    prior_rows = [SimpleNamespace(value_id=9001), SimpleNamespace(value_id=9002)]
    session = _Session(prior_rows)
    monkeypatch.setattr(
        "database.tag_management_db.get_db_session", lambda: _SessionContext(session)
    )
    monkeypatch.setattr(
        TagManagementDB,
        "_get_active_resource_binding",
        staticmethod(lambda *args, **kwargs: SimpleNamespace(bucket_id=3)),
    )
    monkeypatch.setattr(
        TagManagementDB,
        "_load_assignable_values",
        staticmethod(lambda *args, **kwargs: _value_rows(list(range(1, 102)))),
    )

    with pytest.raises(TagManagementConflictError):
        TagManagementDB.replace_resource_assignments(
            "tenant-a", "skill", "resource-1", "default_resource", list(range(1, 102)), "actor-1"
        )

    assert session.deleted == []
    assert session.added == []
    assert session.flushed is False


def test_replacement_preserves_unchanged_assignments_and_only_adds_new_values(monkeypatch):
    prior_rows = [
        SimpleNamespace(value_id=1),
        SimpleNamespace(value_id=2),
    ]
    session = _Session(prior_rows)
    monkeypatch.setattr(
        "database.tag_management_db.get_db_session", lambda: _SessionContext(session)
    )
    monkeypatch.setattr(
        TagManagementDB,
        "_get_active_resource_binding",
        staticmethod(lambda *args, **kwargs: SimpleNamespace(bucket_id=3)),
    )
    monkeypatch.setattr(
        TagManagementDB,
        "_load_assignable_values",
        staticmethod(lambda *args, **kwargs: _value_rows([2, 3])),
    )

    TagManagementDB.replace_resource_assignments(
        "tenant-a", "skill", "resource-1", "default_resource", [2, 3], "actor-1"
    )

    assert session.deleted == [prior_rows[0]]
    assert [assignment.value_id for assignment in session.added] == [3]
    assert session.flushed is True
