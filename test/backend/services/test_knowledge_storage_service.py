"""Unit tests for knowledge-base source-object accounting helpers."""

from unittest.mock import patch

import pytest

import backend.services.knowledge_storage_service as storage_service

KnowledgeStorageContext = storage_service.KnowledgeStorageContext
commit_uploaded_object = storage_service.commit_uploaded_object
compensate_uploaded_objects = storage_service.compensate_uploaded_objects
get_committed_bytes_by_kb = storage_service.get_committed_bytes_by_kb
get_committed_source_bytes_by_paths = storage_service.get_committed_source_bytes_by_paths
get_tenant_committed_source_bytes = storage_service.get_tenant_committed_source_bytes
release_storage_charge = storage_service.release_storage_charge
resolve_storage_context = storage_service.resolve_storage_context
resolve_storage_reference = storage_service.resolve_storage_reference
resolve_storage_object_knowledge = storage_service.resolve_storage_object_knowledge
resolve_storage_object_access = storage_service.resolve_storage_object_access


@pytest.fixture(autouse=True)
def default_bucket(monkeypatch):
    monkeypatch.setattr(storage_service, "MINIO_DEFAULT_BUCKET", "test-bucket")


@pytest.fixture(autouse=True)
def default_bucket(monkeypatch):
    monkeypatch.setattr(storage_service, "MINIO_DEFAULT_BUCKET", "test-bucket")


@pytest.fixture
def storage_context():
    return KnowledgeStorageContext(
        tenant_id="tenant-a",
        knowledge_id=7,
        index_name="kb-a",
        bucket_name="test-bucket",
    )


def test_resolve_storage_context_requires_tenant_owned_kb():
    with patch.object(
        storage_service,
        "get_knowledge_record",
        return_value={
            "tenant_id": "tenant-a",
            "knowledge_id": 7,
            "index_name": "kb-a",
        },
    ) as get_record:
        result = resolve_storage_context("kb-a", "tenant-a")

    assert result == KnowledgeStorageContext(
        tenant_id="tenant-a",
        knowledge_id=7,
        index_name="kb-a",
        bucket_name=storage_service.MINIO_DEFAULT_BUCKET,
    )
    get_record.assert_called_once_with({
        "index_name": "kb-a",
        "tenant_id": "tenant-a",
    })


@pytest.mark.parametrize(
    ("index_name", "tenant_id", "record"),
    [
        (None, "tenant-a", None),
        ("kb-a", None, None),
        ("kb-a", "tenant-a", {}),
        ("kb-a", "tenant-a", {"tenant_id": "tenant-b", "knowledge_id": 7}),
        ("kb-a", "tenant-a", {"tenant_id": "tenant-a", "knowledge_id": None}),
    ],
)
def test_resolve_storage_context_excludes_non_kb_and_cross_tenant(
    index_name,
    tenant_id,
    record,
):
    with patch.object(
        storage_service,
        "get_knowledge_record",
        return_value=record,
    ) as get_record:
        assert resolve_storage_context(index_name, tenant_id) is None

    if not index_name or not tenant_id:
        get_record.assert_not_called()


def test_resolve_storage_context_requires_configured_bucket(monkeypatch):
    monkeypatch.setattr(storage_service, "MINIO_DEFAULT_BUCKET", None)
    with patch.object(
        storage_service,
        "get_knowledge_record",
        return_value={"tenant_id": "tenant-a", "knowledge_id": 7},
    ):
        with pytest.raises(RuntimeError, match="default bucket"):
            resolve_storage_context("kb-a", "tenant-a")


def test_storage_usage_wrappers_normalize_values():
    with patch.object(
        storage_service,
        "aggregate_committed_bytes_by_kb",
        return_value={"7": 300, 8: None},
    ) as aggregate, patch.object(
        storage_service,
        "get_tenant_committed_bytes",
        return_value=500,
    ) as tenant_total:
        assert get_committed_bytes_by_kb("tenant-a", [7, 8]) == {7: 300, 8: 0}
        assert get_tenant_committed_source_bytes("tenant-a") == 500

    aggregate.assert_called_once_with(tenant_id="tenant-a", knowledge_ids=[7, 8])
    tenant_total.assert_called_once_with(tenant_id="tenant-a")


def test_get_committed_source_bytes_by_paths_batches_by_bucket():
    with patch.object(
        storage_service,
        "get_committed_source_bytes_by_object_names",
        side_effect=[
            {"knowledge_base/a.pdf": 300},
            {"knowledge_base/b.pdf": 450},
        ],
    ) as get_committed:
        result = get_committed_source_bytes_by_paths(
            tenant_id="tenant-a",
            knowledge_id=7,
            paths=[
                "knowledge_base/a.pdf",
                "s3://other-bucket/knowledge_base/b.pdf",
                "https://example.com/not-a-storage-object",
            ],
        )

    assert result == {
        "knowledge_base/a.pdf": 300,
        "s3://other-bucket/knowledge_base/b.pdf": 450,
    }
    assert get_committed.call_count == 2


@pytest.mark.parametrize(
    ("path_or_url", "expected"),
    [
        ("knowledge_base/a.pdf", (storage_service.MINIO_DEFAULT_BUCKET, "knowledge_base/a.pdf")),
        (
            "attachments/asset_owner/user-a/a.pdf",
            (storage_service.MINIO_DEFAULT_BUCKET, "attachments/asset_owner/user-a/a.pdf"),
        ),
        ("s3://other-bucket/knowledge_base/a.pdf", ("other-bucket", "knowledge_base/a.pdf")),
        ("/other-bucket/knowledge_base/a.pdf", ("other-bucket", "knowledge_base/a.pdf")),
        ("https://example.com/a.pdf", None),
        ("", None),
    ],
)
def test_resolve_storage_reference_normalizes_kb_source_paths(path_or_url, expected):
    result = resolve_storage_reference(path_or_url)

    if expected is None:
        assert result is None
    else:
        assert (result.bucket_name, result.object_name) == expected


def test_resolve_storage_object_knowledge_requires_consistent_active_ledger():
    ledger = {
        "tenant_id": "tenant-a",
        "knowledge_id": 7,
        "index_name": "kb-a",
        "bucket_name": "test-bucket",
        "object_name": "knowledge_base/a.pdf",
    }
    knowledge = {
        "tenant_id": "tenant-a",
        "knowledge_id": 7,
        "index_name": "kb-a",
        "ingroup_permission": "PRIVATE",
    }
    with patch.object(storage_service, "get_storage_object_by_identity", return_value=ledger), \
            patch.object(storage_service, "get_knowledge_record", return_value=knowledge):
        result = resolve_storage_object_knowledge(
            "knowledge_base/a.pdf",
            tenant_id="tenant-a",
        )

    assert result["ledger"] == ledger
    assert result["knowledge"] == knowledge


@pytest.mark.parametrize(
    "ledger",
    [
        None,
        {"tenant_id": "tenant-a", "knowledge_id": 7},
        {
            "tenant_id": "tenant-b",
            "knowledge_id": 7,
            "index_name": "kb-a",
        },
    ],
)
def test_resolve_storage_object_knowledge_rejects_invalid_ledger(ledger):
    with patch.object(
        storage_service,
        "get_storage_object_by_identity",
        return_value=ledger,
    ), patch.object(
        storage_service,
        "get_knowledge_record",
        return_value={
            "tenant_id": "tenant-a",
            "knowledge_id": 7,
            "index_name": "kb-a",
        },
    ) as get_record:
        result = resolve_storage_object_knowledge(
            "knowledge_base/a.pdf",
            tenant_id="tenant-a",
        )

    assert result is None
    if ledger is None or ledger.get("tenant_id") != "tenant-a":
        get_record.assert_not_called()


@pytest.mark.parametrize(
    "knowledge",
    [
        None,
        {"tenant_id": "tenant-a", "knowledge_id": 8, "index_name": "kb-a"},
        {"tenant_id": "tenant-a", "knowledge_id": 7, "index_name": "kb-b"},
        {"tenant_id": "tenant-b", "knowledge_id": 7, "index_name": "kb-a"},
    ],
)
def test_resolve_storage_object_knowledge_rejects_mismatched_knowledge(knowledge):
    ledger = {
        "tenant_id": "tenant-a",
        "knowledge_id": 7,
        "index_name": "kb-a",
    }
    with patch.object(
        storage_service, "get_storage_object_by_identity", return_value=ledger
    ), patch.object(
        storage_service, "get_knowledge_record", return_value=knowledge
    ):
        assert (
            resolve_storage_object_knowledge(
                "knowledge_base/a.pdf", tenant_id="tenant-a"
            )
            is None
        )


@pytest.mark.parametrize(
    ("permission", "expected"),
    [("EDIT", True), ("DELETE", True), ("READ", False)],
)
def test_resolve_storage_object_access_uses_kb_dac(permission, expected):
    ownership = {
        "knowledge": {
            "tenant_id": "tenant-a",
            "knowledge_id": 7,
            "index_name": "kb-a",
        },
        "ledger": {"tenant_id": "tenant-a"},
    }
    with patch.object(storage_service, "resolve_storage_object_knowledge", return_value=ownership), \
            patch(
                "management.services.knowledge_base.service.ElasticSearchService"
                ".resolve_knowledge_base_permission",
                return_value="EDIT",
            ) as resolve_permission:
        result = resolve_storage_object_access(
            "knowledge_base/a.pdf",
            user_id="user-a",
            tenant_id="tenant-a",
            required_permission=permission,
        )

    assert result is expected
    if permission != "READ":
        resolve_permission.assert_called_once_with(
            index_name="kb-a",
            user_id="user-a",
            tenant_id="tenant-a",
        )


def test_resolve_storage_object_access_denies_unresolved_object():
    with patch.object(storage_service, "resolve_storage_object_knowledge", return_value=None):
        assert not resolve_storage_object_access(
            "knowledge_base/legacy.pdf",
            user_id="user-a",
            tenant_id="tenant-a",
            required_permission="DELETE",
        )


@pytest.mark.parametrize(
    ("user_id", "tenant_id", "required_permission"),
    [
        (None, "tenant-a", "DELETE"),
        ("user-a", None, "DELETE"),
        ("user-a", "tenant-a", "READ"),
        ("user-a", "tenant-a", ""),
    ],
)
def test_resolve_storage_object_access_rejects_invalid_request(
    user_id, tenant_id, required_permission
):
    with patch.object(
        storage_service, "resolve_storage_object_knowledge"
    ) as resolve_ownership:
        assert not resolve_storage_object_access(
            "knowledge_base/a.pdf",
            user_id=user_id,
            tenant_id=tenant_id,
            required_permission=required_permission,
        )

    resolve_ownership.assert_not_called()


def test_resolve_storage_object_access_fails_closed_when_resolution_raises():
    with patch.object(
        storage_service,
        "resolve_storage_object_knowledge",
        side_effect=RuntimeError("ledger unavailable"),
    ):
        assert not resolve_storage_object_access(
            "knowledge_base/a.pdf",
            user_id="user-a",
            tenant_id="tenant-a",
            required_permission="DELETE",
        )


@pytest.mark.parametrize(
    "permission_error",
    [PermissionError("denied"), ValueError("invalid KB"), RuntimeError("DAC down")],
)
def test_resolve_storage_object_access_fails_closed_when_dac_raises(permission_error):
    ownership = {
        "knowledge": {"index_name": "kb-a"},
        "ledger": {"tenant_id": "tenant-a"},
    }
    with patch.object(
        storage_service, "resolve_storage_object_knowledge", return_value=ownership
    ), patch(
        "management.services.knowledge_base.service.ElasticSearchService"
        ".resolve_knowledge_base_permission",
        side_effect=permission_error,
    ):
        assert not resolve_storage_object_access(
            "knowledge_base/a.pdf",
            user_id="user-a",
            tenant_id="tenant-a",
            required_permission="DELETE",
        )


def test_resolve_storage_object_access_allows_creator_and_editor_only():
    ownership = {
        "knowledge": {"index_name": "kb-a"},
        "ledger": {"tenant_id": "tenant-a"},
    }
    with patch.object(
        storage_service, "resolve_storage_object_knowledge", return_value=ownership
    ), patch(
        "management.services.knowledge_base.service.ElasticSearchService"
        ".resolve_knowledge_base_permission",
        side_effect=["READ_ONLY", "CREATOR"],
    ):
        assert not resolve_storage_object_access(
            "knowledge_base/a.pdf", "user-a", "tenant-a", "DELETE"
        )
        assert resolve_storage_object_access(
            "knowledge_base/a.pdf", "user-a", "tenant-a", "DELETE"
        )


def test_get_committed_source_bytes_by_paths_skips_unsupported_paths():
    with patch.object(
        storage_service, "get_committed_source_bytes_by_object_names"
    ) as get_committed:
        assert get_committed_source_bytes_by_paths(
            "tenant-a", 7, ["https://example.com/file.txt", ""]
        ) == {}

    get_committed.assert_not_called()


def test_release_storage_charge_invalidates_only_after_ledger_release():
    with patch.object(
        storage_service,
        "mark_storage_object_deleted",
        side_effect=[True, False],
    ) as mark, patch.object(
        storage_service,
        "invalidate_storage_usage_cache",
    ) as invalidate:
        assert release_storage_charge(
            tenant_id="tenant-a", bucket_name="test-bucket", object_name="one.pdf"
        )
        assert not release_storage_charge(
            tenant_id="tenant-a", bucket_name="test-bucket", object_name="two.pdf"
        )

    assert mark.call_count == 2
    invalidate.assert_called_once_with("tenant-a")


def test_commit_uploaded_object_uses_authoritative_size(storage_context):
    with patch.object(
        storage_service,
        "get_file_size_from_minio_strict",
        return_value=321,
    ) as get_size, patch.object(
        storage_service,
        "commit_storage_object",
        return_value={
            "object_name": "knowledge_base/object-a",
            "status": "COMMITTED",
            "delete_flag": "N",
        },
    ) as commit:
        result = commit_uploaded_object(
            context=storage_context,
            object_name="knowledge_base/object-a",
            created_by="user-a",
        )

    assert result == {
        "object_name": "knowledge_base/object-a",
        "status": "COMMITTED",
        "delete_flag": "N",
    }
    get_size.assert_called_once_with(
        object_name="knowledge_base/object-a",
        bucket="test-bucket",
    )
    commit.assert_called_once_with(
        tenant_id="tenant-a",
        knowledge_id=7,
        index_name="kb-a",
        bucket_name="test-bucket",
        object_name="knowledge_base/object-a",
        raw_bytes=321,
        created_by="user-a",
        updated_by="user-a",
    )


@pytest.mark.parametrize("raw_size", [-1, True, "321"])
def test_commit_uploaded_object_rejects_invalid_authoritative_size(
    storage_context,
    raw_size,
):
    with patch.object(
        storage_service,
        "get_file_size_from_minio_strict",
        return_value=raw_size,
    ), patch.object(
        storage_service,
        "commit_storage_object",
    ) as commit:
        with pytest.raises(ValueError, match="Invalid authoritative"):
            commit_uploaded_object(storage_context, "object-a")
    commit.assert_not_called()


def test_commit_uploaded_object_rejects_confirmed_missing_object(storage_context):
    with patch.object(
        storage_service,
        "get_file_size_from_minio_strict",
        return_value=None,
    ), patch.object(storage_service, "commit_storage_object") as commit:
        with pytest.raises(FileNotFoundError, match="does not exist"):
            commit_uploaded_object(storage_context, "missing-object")
    commit.assert_not_called()


@pytest.mark.parametrize(
    "ledger_result",
    [
        {},
        {"status": "DELETED", "delete_flag": "Y"},
        {"status": "COMMITTED", "delete_flag": "Y"},
    ],
)
def test_commit_uploaded_object_rejects_non_active_ledger_result(
    storage_context,
    ledger_result,
):
    with patch.object(
        storage_service,
        "get_file_size_from_minio_strict",
        return_value=0,
    ), patch.object(
        storage_service,
        "commit_storage_object",
        return_value=ledger_result,
    ):
        with pytest.raises(RuntimeError, match="Failed to commit"):
            commit_uploaded_object(storage_context, "empty-object")


def test_compensation_releases_only_successfully_deleted_objects(storage_context):
    with patch.object(
        storage_service,
        "delete_file",
        side_effect=[
            {"success": True},
            {"success": False, "error": "still present"},
        ],
    ) as delete, patch.object(
        storage_service,
        "mark_storage_object_deleted",
        return_value=True,
    ) as mark_deleted, patch.object(
        storage_service,
        "commit_uploaded_object",
        return_value={"status": "COMMITTED", "delete_flag": "N"},
    ) as retry_commit:
        compensate_uploaded_objects(
            context=storage_context,
            object_names=["new-a", "new-b"],
            updated_by="user-a",
        )

    assert delete.call_count == 2
    mark_deleted.assert_called_once_with(
        tenant_id="tenant-a",
        bucket_name="test-bucket",
        object_name="new-a",
        updated_by="user-a",
    )
    retry_commit.assert_called_once_with(
        context=storage_context,
        object_name="new-b",
        created_by="user-a",
    )


def test_compensation_tolerates_missing_row_and_cleanup_exception(storage_context):
    with patch.object(
        storage_service,
        "delete_file",
        side_effect=[{"success": True}, RuntimeError("storage unavailable")],
    ), patch.object(
        storage_service,
        "mark_storage_object_deleted",
        return_value=False,
    ) as mark_deleted:
        compensate_uploaded_objects(
            context=storage_context,
            object_names=["uncommitted", "failed-delete"],
        )

    mark_deleted.assert_called_once()


def test_compensation_logs_when_retry_charge_also_fails(storage_context):
    with patch.object(
        storage_service,
        "delete_file",
        return_value={"success": False, "error": "still present"},
    ), patch.object(
        storage_service,
        "commit_uploaded_object",
        side_effect=RuntimeError("ledger unavailable"),
    ) as retry_commit:
        compensate_uploaded_objects(
            context=storage_context,
            object_names=["failed-delete"],
            updated_by="user-a",
        )

    retry_commit.assert_called_once_with(
        context=storage_context,
        object_name="failed-delete",
        created_by="user-a",
    )
