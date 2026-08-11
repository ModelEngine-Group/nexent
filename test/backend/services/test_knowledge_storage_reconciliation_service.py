"""Tests for conservative KB source-object backfill and reconciliation."""

import sys
import types
from unittest.mock import MagicMock

import pytest

client_module = types.ModuleType("database.client")
client_module.as_dict = MagicMock(name="as_dict")
client_module.get_db_session = MagicMock(name="get_db_session")
client_module.minio_client = MagicMock(name="minio_client")
previous_client_module = sys.modules.get("database.client")
sys.modules["database.client"] = client_module

from services.knowledge_storage_reconciliation_service import (
    KnowledgeStorageReconciliationService,
    StorageObjectReference,
    invalidate_storage_usage_cache,
    release_storage_charge,
    resolve_storage_reference,
)
from database.knowledge_storage_object_db import StorageObjectConflictError

if previous_client_module is None:
    sys.modules.pop("database.client", None)
else:
    sys.modules["database.client"] = previous_client_module


@pytest.fixture
def vdb_core():
    return MagicMock()


@pytest.fixture
def service(vdb_core):
    return KnowledgeStorageReconciliationService(
        tenant_id="tenant-1",
        vdb_core=vdb_core,
        default_bucket="kb-bucket",
        updated_by="operator-1",
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("knowledge_base/doc.pdf", StorageObjectReference("kb-bucket", "knowledge_base/doc.pdf")),
        (
            "attachments/asset_owner/user-1/doc.pdf",
            StorageObjectReference("kb-bucket", "attachments/asset_owner/user-1/doc.pdf"),
        ),
        ("s3://other-bucket/folder/doc.pdf", StorageObjectReference("other-bucket", "folder/doc.pdf")),
        ("/other-bucket/folder/doc.pdf", StorageObjectReference("other-bucket", "folder/doc.pdf")),
        ("https://storage.example/doc.pdf", None),
        ("attachments/doc.pdf", None),
        ("", None),
        ("s3://bucket", None),
        ("/bucket", None),
    ],
)
def test_resolve_storage_reference(value, expected):
    assert resolve_storage_reference(value, "kb-bucket") == expected


def test_service_requires_tenant_and_bucket(vdb_core):
    with pytest.raises(ValueError, match="tenant_id"):
        KnowledgeStorageReconciliationService("", vdb_core)
    with pytest.raises(ValueError, match="bucket"):
        KnowledgeStorageReconciliationService("tenant-1", vdb_core, default_bucket=None)


def test_backfill_dry_run_reports_candidate_missing_conflict_and_unresolved(
    service, vdb_core, mocker
):
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.get_knowledge_info_by_tenant_id",
        return_value=[
            {"tenant_id": "tenant-1", "knowledge_id": 1, "index_name": "kb-1"},
            {"tenant_id": "tenant-1", "knowledge_id": 2, "index_name": "kb-2"},
        ],
    )
    vdb_core.get_documents_detail_strict.side_effect = [
        [
            {"path_or_url": "knowledge_base/good.pdf"},
            {"path_or_url": "knowledge_base/good.pdf"},
            {"path_or_url": "knowledge_base/missing.pdf"},
            {"path_or_url": "s3://kb-bucket/shared.pdf"},
            {"path_or_url": "https://external.example/doc.pdf"},
        ],
        [{"path_or_url": "/kb-bucket/shared.pdf"}],
    ]
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.get_file_size_from_minio_strict",
        side_effect=lambda object_name, bucket=None: (
            None if object_name == "knowledge_base/missing.pdf" else 123
        ),
    )
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.get_storage_object",
        return_value=None,
    )
    commit = mocker.patch(
        "services.knowledge_storage_reconciliation_service.commit_storage_object"
    )

    report = service.backfill()

    assert report["mode"] == "dry_run"
    assert report["summary"] == {
        "knowledge_bases_scanned": 2,
        "references_scanned": 5,
        "candidates": 1,
        "already_recorded": 0,
        "applied": 0,
        "missing": 1,
        "conflicting": 1,
        "unresolved": 1,
        "size_drift": 0,
        "errors": 0,
    }
    assert report["candidates"][0]["raw_bytes"] == 123
    commit.assert_not_called()


def test_backfill_apply_is_idempotent_and_invalidates_once(service, vdb_core, mocker):
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.get_knowledge_info_by_tenant_id",
        return_value=[{"tenant_id": "tenant-1", "knowledge_id": 1, "index_name": "kb-1"}],
    )
    vdb_core.get_documents_detail_strict.return_value = [
        {"path_or_url": "knowledge_base/new.pdf"},
        {"path_or_url": "knowledge_base/existing.pdf"},
    ]
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.get_file_size_from_minio_strict",
        return_value=50,
    )
    ledger = {
        ("kb-bucket", "knowledge_base/existing.pdf"): {
            "tenant_id": "tenant-1",
            "knowledge_id": 1,
            "index_name": "kb-1",
            "bucket_name": "kb-bucket",
            "object_name": "knowledge_base/existing.pdf",
            "raw_bytes": 50,
            "status": "COMMITTED",
            "delete_flag": "N",
        }
    }
    get_object = mocker.patch(
        "services.knowledge_storage_reconciliation_service.get_storage_object",
        side_effect=lambda _tenant, bucket, object_name, include_deleted=False: ledger.get((bucket, object_name)),
    )

    def commit_object(**kwargs):
        row = {**kwargs, "status": "COMMITTED", "delete_flag": "N"}
        ledger[(kwargs["bucket_name"], kwargs["object_name"])] = row
        return row

    commit = mocker.patch(
        "services.knowledge_storage_reconciliation_service.commit_storage_object",
        side_effect=commit_object,
    )
    invalidate = mocker.patch(
        "services.knowledge_storage_reconciliation_service.invalidate_storage_usage_cache"
    )

    first = service.backfill(apply=True)
    second = service.backfill(apply=True)

    assert first["summary"]["applied"] == 1
    assert first["summary"]["already_recorded"] == 1
    assert second["summary"]["applied"] == 0
    assert second["summary"]["already_recorded"] == 2
    assert commit.call_count == 1
    assert get_object.call_count == 4
    invalidate.assert_called_once_with("tenant-1")


def test_backfill_reports_deleted_owner_conflict_and_collection_errors(
    service, vdb_core, mocker
):
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.get_knowledge_info_by_tenant_id",
        return_value=[
            {"tenant_id": "tenant-1", "knowledge_id": None, "index_name": "broken"},
            {"tenant_id": "tenant-1", "knowledge_id": 1, "index_name": "es-error"},
            {"tenant_id": "tenant-1", "knowledge_id": 2, "index_name": "kb-2"},
        ],
    )
    vdb_core.get_documents_detail_strict.side_effect = [
        RuntimeError("ES unavailable"),
        [{"path_or_url": "knowledge_base/deleted.pdf"}],
    ]
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.get_file_size_from_minio_strict",
        return_value=10,
    )
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.get_storage_object",
        return_value={
            "tenant_id": "tenant-1",
            "knowledge_id": 2,
            "index_name": "kb-2",
            "raw_bytes": 10,
            "status": "DELETED",
            "delete_flag": "Y",
        },
    )

    report = service.backfill(apply=True)

    assert report["summary"]["errors"] == 2
    assert report["summary"]["conflicting"] == 1
    assert report["summary"]["applied"] == 0
    assert "terminal deleted" in report["conflicting"][0]["reason"]


def test_backfill_reports_metadata_and_commit_failures(service, vdb_core, mocker):
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.get_knowledge_info_by_tenant_id",
        return_value=[{"tenant_id": "tenant-1", "knowledge_id": 1, "index_name": "kb-1"}],
    )
    vdb_core.get_documents_detail_strict.return_value = [
        {"path_or_url": "knowledge_base/meta-error.pdf"},
        {"path_or_url": "knowledge_base/commit-error.pdf"},
    ]
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.get_file_size_from_minio_strict",
        side_effect=[RuntimeError("stat failed"), 20],
    )
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.get_storage_object",
        return_value=None,
    )
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.commit_storage_object",
        side_effect=RuntimeError("insert failed"),
    )

    report = service.backfill(apply=True)

    assert report["summary"]["candidates"] == 1
    assert report["summary"]["errors"] == 2
    assert report["summary"]["applied"] == 0


def test_backfill_classifies_cross_tenant_identity_conflict(
    service, vdb_core, mocker
):
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.get_knowledge_info_by_tenant_id",
        return_value=[{"tenant_id": "tenant-1", "knowledge_id": 1, "index_name": "kb-1"}],
    )
    vdb_core.get_documents_detail_strict.return_value = [
        {"path_or_url": "knowledge_base/conflict.pdf"}
    ]
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.get_file_size_from_minio_strict",
        return_value=20,
    )
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.get_storage_object",
        return_value=None,
    )
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.commit_storage_object",
        side_effect=StorageObjectConflictError("already owned by tenant-2"),
    )

    report = service.backfill(apply=True)

    assert report["summary"]["conflicting"] == 1
    assert report["summary"]["errors"] == 0
    assert "another owner" in report["conflicting"][0]["reason"]


def test_backfill_repairs_existing_size_drift_without_recommitting(service, vdb_core, mocker):
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.get_knowledge_info_by_tenant_id",
        return_value=[{"tenant_id": "tenant-1", "knowledge_id": 1, "index_name": "kb-1"}],
    )
    vdb_core.get_documents_detail_strict.return_value = [
        {"path_or_url": "knowledge_base/drift.pdf"}
    ]
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.get_file_size_from_minio_strict",
        return_value=25,
    )
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.get_storage_object",
        return_value={
            "tenant_id": "tenant-1",
            "knowledge_id": 1,
            "index_name": "kb-1",
            "raw_bytes": 20,
            "status": "COMMITTED",
            "delete_flag": "N",
        },
    )
    update = mocker.patch(
        "services.knowledge_storage_reconciliation_service.update_storage_object_raw_bytes",
        return_value=True,
    )
    commit = mocker.patch(
        "services.knowledge_storage_reconciliation_service.commit_storage_object"
    )

    report = service.backfill(apply=True)

    assert report["summary"]["size_drift"] == 1
    assert report["summary"]["applied"] == 1
    update.assert_called_once()
    commit.assert_not_called()


def test_reconcile_dry_run_reports_healthy_missing_and_size_drift(service, mocker):
    rows = [
        _ledger_row("healthy.pdf", 10),
        _ledger_row("missing.pdf", 20),
        _ledger_row("drift.pdf", 30),
    ]
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.list_committed_storage_objects",
        return_value=rows,
    )
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.get_file_size_from_minio_strict",
        side_effect=lambda object_name, bucket=None: {
            "healthy.pdf": 10,
            "missing.pdf": None,
            "drift.pdf": 35,
        }[object_name],
    )
    mark_deleted = mocker.patch(
        "services.knowledge_storage_reconciliation_service.mark_storage_object_deleted"
    )
    update_size = mocker.patch(
        "services.knowledge_storage_reconciliation_service.update_storage_object_raw_bytes"
    )

    report = service.reconcile()

    assert report["summary"]["already_recorded"] == 1
    assert report["summary"]["missing"] == 1
    assert report["summary"]["size_drift"] == 1
    assert report["summary"]["applied"] == 0
    mark_deleted.assert_not_called()
    update_size.assert_not_called()


def test_reconcile_apply_repairs_safely_and_is_idempotent(service, mocker):
    state = {
        "rows": [_ledger_row("missing.pdf", 20), _ledger_row("drift.pdf", 30)],
        "sizes": {"drift.pdf": 35},
    }
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.list_committed_storage_objects",
        side_effect=lambda _tenant: list(state["rows"]),
    )
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.get_file_size_from_minio_strict",
        side_effect=lambda object_name, bucket=None: state["sizes"].get(object_name),
    )

    def mark_missing(**_kwargs):
        state["rows"] = [row for row in state["rows"] if row["object_name"] != "missing.pdf"]
        return True

    def update_drift(**kwargs):
        for row in state["rows"]:
            if row["object_name"] == kwargs["object_name"]:
                row["raw_bytes"] = kwargs["raw_bytes"]
        return True

    release = mocker.patch(
        "services.knowledge_storage_reconciliation_service.mark_storage_object_deleted",
        side_effect=mark_missing,
    )
    update = mocker.patch(
        "services.knowledge_storage_reconciliation_service.update_storage_object_raw_bytes",
        side_effect=update_drift,
    )
    invalidate = mocker.patch(
        "services.knowledge_storage_reconciliation_service.invalidate_storage_usage_cache"
    )

    first = service.reconcile(apply=True)
    second = service.reconcile(apply=True)

    assert first["summary"]["applied"] == 2
    assert second["summary"]["applied"] == 0
    assert second["summary"]["already_recorded"] == 1
    release.assert_called_once()
    update.assert_called_once()
    invalidate.assert_called_once_with("tenant-1")


def test_reconcile_reports_metadata_and_repair_failures(service, mocker):
    rows = [
        _ledger_row("metadata-error.pdf", 10),
        _ledger_row("missing.pdf", 20),
        _ledger_row("drift.pdf", 30),
    ]
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.list_committed_storage_objects",
        return_value=rows,
    )

    def read_size(object_name, bucket=None):
        if object_name == "metadata-error.pdf":
            raise RuntimeError("MinIO unavailable")
        if object_name == "missing.pdf":
            return None
        return 31

    mocker.patch(
        "services.knowledge_storage_reconciliation_service.get_file_size_from_minio_strict",
        side_effect=read_size,
    )
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.mark_storage_object_deleted",
        side_effect=RuntimeError("delete state failed"),
    )
    mocker.patch(
        "services.knowledge_storage_reconciliation_service.update_storage_object_raw_bytes",
        return_value=False,
    )

    report = service.reconcile(apply=True)

    assert report["summary"]["errors"] == 3
    assert report["summary"]["applied"] == 0


def test_release_storage_charge_invalidates_only_when_row_is_released(mocker):
    mark = mocker.patch(
        "services.knowledge_storage_reconciliation_service.mark_storage_object_deleted",
        side_effect=[True, False],
    )
    invalidate = mocker.patch(
        "services.knowledge_storage_reconciliation_service.invalidate_storage_usage_cache"
    )

    assert release_storage_charge(
        tenant_id="tenant-1", bucket_name="bucket", object_name="one.pdf"
    )
    assert not release_storage_charge(
        tenant_id="tenant-1", bucket_name="bucket", object_name="two.pdf"
    )
    assert mark.call_count == 2
    invalidate.assert_called_once_with("tenant-1")


def test_invalidate_storage_usage_cache_logs_import_or_runtime_failure(mocker, monkeypatch):
    invalidate = MagicMock(side_effect=RuntimeError("cache unavailable"))
    quota_module = types.ModuleType("services.quota_service")
    quota_module.QuotaService = type(
        "QuotaService",
        (),
        {"invalidate_usage_cache": staticmethod(invalidate)},
    )
    monkeypatch.setitem(sys.modules, "services.quota_service", quota_module)
    logger = mocker.patch("services.knowledge_storage_reconciliation_service.logger")

    invalidate_storage_usage_cache("tenant-1")

    invalidate.assert_called_once_with("tenant-1")
    logger.exception.assert_called_once()


def _ledger_row(object_name: str, raw_bytes: int):
    return {
        "tenant_id": "tenant-1",
        "knowledge_id": 1,
        "index_name": "kb-1",
        "bucket_name": "kb-bucket",
        "object_name": object_name,
        "raw_bytes": raw_bytes,
        "status": "COMMITTED",
        "delete_flag": "N",
    }
