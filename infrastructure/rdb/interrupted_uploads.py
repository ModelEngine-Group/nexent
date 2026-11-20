# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read and compare-and-set interrupted uploads within their owner scope."""

from contracts.knowledge import INTERRUPTED_UPLOADS
from nexent.storage.errors import InvalidInput
from nexent.storage.models import StorageScope
from sqlalchemy import or_, select

from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

_ACTOR = "upload-recovery"


class _RecoveryAudit(RecordAudit):
    def values(self, actor, *, create=False):
        values = super().values(actor, create=create)
        # Recovery changes state and timestamp while retaining the original last editor.
        del values[self.updated_by]
        return values


def bind_interrupted_uploads(owner, engine, *, record=None, expected_status="UPLOADING"):
    if not isinstance(owner, str) or not 0 < len(owner) <= 32 or expected_status not in {"UPLOADING", "FAILED"}:
        raise InvalidInput()
    table = KnowledgeFileLifecycle.__table__
    names = (
        "file_id", "tenant_id", "created_by", "updated_by", "create_time", "update_time", "delete_flag",
        "object_name", "bucket_name", "version", "status", "stage", "source_upload_sha256", "source_revision",
        "error_code", "error_message", "error_stage", "failed_at",
    )
    selection = select(*(table.c[name] for name in names)).where(
        table.c.upload_owner_service == owner, table.c.status == expected_status,
    )
    if record is not None:
        selection = selection.where(
            table.c.file_id == record["file_id"],
            or_(table.c.stage.is_(None), table.c.stage != "SOURCE_UPLOAD"),
            or_(table.c.source_upload_sha256.is_(None), table.c.source_upload_sha256 == ""),
            or_(table.c.source_revision.is_(None), table.c.source_revision == ""),
        )
    project = selection.subquery(INTERRUPTED_UPLOADS)
    manager = frozenset({"management"})
    definition = DatasetDefinition(
        INTERRUPTED_UPLOADS, "file_id",
        tuple(FieldDefinition(name, "integer" if name == "version" else "string", table.c[name].nullable)
              for name in names),
        manager, manager if record is not None else frozenset(),
        tenant_field="tenant_id", active_field="delete_flag", allow_system=record is None,
    )
    scope = StorageScope("management", record["tenant_id"] if record is not None else None,
                         _ACTOR, {INTERRUPTED_UPLOADS}, system=record is None)
    return SQLRecordStore(
        scope, DatasetCatalog((definition,)), {INTERRUPTED_UPLOADS: project}, engine,
        revision_fields={INTERRUPTED_UPLOADS: "version"},
        audit_mappings={INTERRUPTED_UPLOADS: _RecoveryAudit(
            "create_time", "update_time", "created_by", "updated_by", extra_dates=frozenset({"failed_at"}),
        )},
        write_tables={INTERRUPTED_UPLOADS: table} if record is not None else {},
    )
