# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Regression tests for local knowledge status resolution.

Covers the id-space aliasing fixed after the UI-8 visual-acceptance finding:
conversation knowledge scopes persist numeric knowledge ids, agent tool params
persist index names, and both identify the same knowledge base. A valid
knowledge base selected in a conversation must therefore resolve as available
instead of being reported as deleted, while a genuinely deleted knowledge base
must stay reported as not found.

The review follow-up adds the write-path boundary: only the read-only status
query accepts the numeric alias, while ``resolve_local_reference_access``
(which feeds the tool-save merge and binding validation) must stay strict by
index name so a numeric knowledge id can never be persisted into
``index_names``.
"""

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import backend.database.knowledge_reference_db as reference_db  # noqa: E402
import backend.services.knowledge_reference_service as service  # noqa: E402
import management.services.knowledge_base.permission as kb_permission  # noqa: E402


INDEX_A = "213-a99a7c1e4da34a2aa98d41e8abd7802c"
KNOWLEDGE_ID_A = "213"
RECORD_A = {
    "knowledge_id": 213,
    "index_name": INDEX_A,
    "knowledge_name": "kb-a",
    "tenant_id": "t1",
}


@contextmanager
def _fake_session():
    yield object()


def _local_ref(resource_id: str):
    return ("local", resource_id)


@pytest.fixture(autouse=True)
def _patched_dependencies(monkeypatch):
    monkeypatch.setattr(service, "get_db_session", _fake_session)
    monkeypatch.setattr(
        service,
        "query_local_knowledge_records",
        lambda session, names: {name: RECORD_A for name in names if name == INDEX_A},
    )
    monkeypatch.setattr(
        service,
        "query_local_knowledge_records_by_ids",
        lambda session, ids: {
            str(value): RECORD_A for value in ids if str(value) == KNOWLEDGE_ID_A
        },
    )
    permission_calls: list = []

    def _record_permission(index_name, user_id, tenant_id=None):
        permission_calls.append(index_name)
        return "EDIT"

    monkeypatch.setattr(
        kb_permission,
        "resolve_knowledge_base_permission",
        _record_permission,
    )
    yield
    permission_calls.clear()


def _status(resource_id: str, **kwargs):
    statuses = service.resolve_item_statuses(
        [_local_ref(resource_id)], user_id="u1", tenant_id="t1", **kwargs
    )
    assert len(statuses) == 1
    return statuses[0]


def test_numeric_knowledge_id_resolves_to_the_same_record():
    """A valid knowledge base selected in a conversation is available (UI-8)."""
    payload = _status(KNOWLEDGE_ID_A)
    assert payload["status"] == service.STATUS_AVAILABLE
    assert payload["reason_code"] is None
    # The requested identity is preserved so the client can match the response.
    assert payload["resource_id"] == KNOWLEDGE_ID_A


def test_index_name_keeps_resolving_as_before():
    payload = _status(INDEX_A)
    assert payload["status"] == service.STATUS_AVAILABLE
    assert payload["resource_id"] == INDEX_A


def test_deleted_knowledge_base_stays_not_found():
    """The real deletion case must keep reporting not_found (SC-12)."""
    payload = _status("999999")
    assert payload["status"] == service.STATUS_NOT_FOUND
    assert payload["reason_code"] == service.REASON_KNOWLEDGE_NOT_FOUND
    assert payload["resource_id"] == "999999"


def test_alias_resolved_record_without_permission_is_inaccessible(monkeypatch):
    monkeypatch.setattr(
        kb_permission,
        "resolve_knowledge_base_permission",
        lambda index_name, user_id, tenant_id=None: None,
    )
    payload = _status(KNOWLEDGE_ID_A)
    assert payload["status"] == service.STATUS_INACCESSIBLE
    assert payload["reason_code"] == service.REASON_PERMISSION_DENIED


def test_permission_check_receives_canonical_index_name(monkeypatch):
    """Querying by the numeric id must check permission on the real index."""
    calls: list = []

    def _recording(index_name, user_id, tenant_id=None):
        calls.append(index_name)
        return "EDIT"

    monkeypatch.setattr(
        kb_permission, "resolve_knowledge_base_permission", _recording
    )
    service.resolve_item_statuses(
        [_local_ref(KNOWLEDGE_ID_A)], user_id="u1", tenant_id="t1"
    )
    assert calls == [INDEX_A]


def test_write_path_resolver_rejects_numeric_alias():
    """The tool-save resolver must stay strict: a knowledge id is not an index name.

    Submitting index_names=["213"] must not pass binding validation, otherwise
    the invalid identifier is persisted and neither the runtime, the reference
    scan nor the deletion lock can match it.
    """
    access = service.resolve_local_reference_access(
        [KNOWLEDGE_ID_A], user_id="u1", tenant_id="t1"
    )
    assert access[KNOWLEDGE_ID_A]["status"] == service.STATUS_NOT_FOUND
    assert access[KNOWLEDGE_ID_A]["reason_code"] == service.REASON_KNOWLEDGE_NOT_FOUND


def test_write_path_resolver_accepts_canonical_index_name():
    access = service.resolve_local_reference_access(
        [INDEX_A], user_id="u1", tenant_id="t1"
    )
    assert access[INDEX_A]["status"] == service.STATUS_AVAILABLE


def test_mixed_batch_with_invalid_numeric_ids_does_not_fail():
    """Invalid numeric candidates degrade to per-item not_found, not a 500."""
    long_digits = "9" * 4301
    statuses = service.resolve_item_statuses(
        [
            _local_ref(KNOWLEDGE_ID_A),
            _local_ref("²"),
            _local_ref(long_digits),
            _local_ref("999999"),
        ],
        user_id="u1",
        tenant_id="t1",
    )
    by_id = {item["resource_id"]: item for item in statuses}
    assert by_id[KNOWLEDGE_ID_A]["status"] == service.STATUS_AVAILABLE
    for bad in ("²", long_digits, "999999"):
        assert by_id[bad]["status"] == service.STATUS_NOT_FOUND
        assert by_id[bad]["reason_code"] == service.REASON_KNOWLEDGE_NOT_FOUND


def test_safe_knowledge_id_filters_invalid_candidates():
    """Unicode digits and out-of-range values never reach the id query."""
    assert reference_db._safe_knowledge_id("213") == 213
    assert reference_db._safe_knowledge_id("007") == 7
    assert reference_db._safe_knowledge_id("²") is None
    assert reference_db._safe_knowledge_id("9" * 4301) is None
    assert reference_db._safe_knowledge_id("9" * 30) is None
    assert reference_db._safe_knowledge_id("abc") is None
    assert reference_db._safe_knowledge_id("") is None
    assert reference_db._safe_knowledge_id("-1") is None
    assert reference_db._safe_knowledge_id("0") is None


def test_missing_index_is_checked_against_the_canonical_index_name():
    """The physical-index check must use the resolved index name, not the alias."""

    class _FakeVdbCore:
        @staticmethod
        def get_user_indices(pattern: str):
            return ["some-other-index"]

    payload = _status(KNOWLEDGE_ID_A, vdb_core=_FakeVdbCore())
    assert payload["status"] == service.STATUS_NOT_FOUND
    assert payload["reason_code"] == service.REASON_KNOWLEDGE_INDEX_NOT_FOUND
    assert payload["resource_id"] == KNOWLEDGE_ID_A


def test_missing_index_does_not_fire_when_the_index_exists():
    class _FakeVdbCore:
        @staticmethod
        def get_user_indices(pattern: str):
            return [INDEX_A]

    payload = _status(KNOWLEDGE_ID_A, vdb_core=_FakeVdbCore())
    assert payload["status"] == service.STATUS_AVAILABLE
