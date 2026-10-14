from contextlib import nullcontext

from database.db_models import ResourceTagAssignment
from database.tag_management_db import (
    TagManagementDB,
    _is_document_assignment_in_knowledge_base,
)
from services.tag_resource_adapters import _encode_document_resource_id


class _Query:
    def __init__(self, updated_count):
        self.updated_count = updated_count
        self.filters = []
        self.values = None

    def filter(self, *conditions):
        self.filters.extend(conditions)
        return self

    def update(self, values, synchronize_session):
        self.values = values
        assert synchronize_session is False
        return self.updated_count


class _Session:
    def __init__(self, query):
        self.query_result = query
        self.flushed = False

    def query(self, model):
        assert model is ResourceTagAssignment
        return self.query_result

    def flush(self):
        self.flushed = True


def test_cleanup_soft_deletes_only_the_requested_tenant_resource(monkeypatch):
    query = _Query(updated_count=2)
    session = _Session(query)
    monkeypatch.setattr(
        "database.tag_management_db.get_db_session", lambda: nullcontext(session)
    )

    updated_count = TagManagementDB.soft_delete_resource_assignments(
        "tenant-a", "agent", "17", "user-a"
    )

    assert updated_count == 2
    assert session.flushed is True
    assert query.values[ResourceTagAssignment.delete_flag] == "Y"
    assert query.values[ResourceTagAssignment.updated_by] == "user-a"
    assert query.filters[0].right.value == "tenant-a"


def test_cleanup_reports_zero_when_the_tenant_has_no_matching_assignments(monkeypatch):
    query = _Query(updated_count=0)
    session = _Session(query)
    monkeypatch.setattr(
        "database.tag_management_db.get_db_session", lambda: nullcontext(session)
    )

    assert TagManagementDB.soft_delete_resource_assignments(
        "tenant-b", "mcp_service", "17", "user-b"
    ) == 0
    assert query.filters[0].right.value == "tenant-b"


def test_document_cleanup_match_requires_the_full_canonical_provider_identity():
    resource_id = _encode_document_resource_id("aidp", "kb-1", "file-7")

    assert _is_document_assignment_in_knowledge_base(resource_id, "aidp", "kb-1") is True
    assert _is_document_assignment_in_knowledge_base(resource_id, "local", "kb-1") is False
    assert _is_document_assignment_in_knowledge_base(resource_id, "aidp", "kb-2") is False
    assert _is_document_assignment_in_knowledge_base("not-an-identity", "aidp", "kb-1") is False
