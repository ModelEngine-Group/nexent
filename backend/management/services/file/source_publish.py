# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Publish once to the preallocated key and durably pin its confirmed identity."""

import hashlib
import io
import re
from datetime import datetime, timezone

from contracts.agentos_knowledge import ObjectReference
from nexent.storage.errors import (
    Conflict,
    InvalidInput,
    OutcomeUnknown,
    ScopeDenied,
    StorageError,
)
from nexent.storage.models import FieldPatch, ObjectRef, Revision

DATASET = "knowledge_source_bindings"


def validate_scope(records, objects):
    if (
        records.scope.tenant_id != objects.scope.tenant_id
        or records.scope.actor_id != objects.scope.actor_id
        or records.scope.service_role != "management"
        or objects.scope.service_role != "management"
        or records.scope.system
        or objects.scope.system
    ):
        raise ScopeDenied()


def binding_values(source):
    return {
        "source_space": source.space,
        "source_key": source.key,
        "source_revision": source.version,
        "source_sha256": source.sha256,
    }


def confirmed_reference(metadata, target, digest, size):
    if (
        metadata.ref.space != target.space
        or metadata.ref.key != target.key
        or metadata.ref.version is None
        or metadata.sha256 != digest
        or metadata.size != size
        or target.version is not None
        and metadata.ref.version != target.version
    ):
        raise OutcomeUnknown()
    return ObjectReference(
        space=target.space,
        key=target.key,
        version=metadata.ref.version.value,
        sha256=digest,
    )


class SourcePublisher:
    def __init__(self, records, objects):
        validate_scope(records, objects)
        self.records = records
        self.objects = objects

    def publish(self, file_id, content, *, content_type, expected_version, context):
        if (
            not isinstance(file_id, str)
            or not re.fullmatch(r"[0-9a-f]{32}", file_id)
            or not isinstance(content, bytes)
            or not content_type
            or type(expected_version) is not int
            or expected_version < 0
        ):
            raise InvalidInput()
        context.remaining()
        row = self.records.get(DATASET, file_id, context=context)
        if (
            not row
            or row["created_by"] != self.records.scope.actor_id
            or row["status"] not in {"UPLOADING", "UPLOADED"}
            or not row["object_name"]
        ):
            raise ScopeDenied()
        digest = hashlib.sha256(content).hexdigest()
        target = ObjectRef("files", row["object_name"])
        if row["source_revision"] is not None:
            source = ObjectReference(
                space=row["source_space"],
                key=row["source_key"],
                version=row["source_revision"],
                sha256=row["source_sha256"],
            )
            if (
                source.space != target.space
                or source.key != target.key
                or source.sha256 != digest
            ):
                raise Conflict()
            metadata = self.objects.stat(
                ObjectRef(source.space, source.key, Revision(source.version)),
                context=context,
            )
            if (
                metadata.ref.version != Revision(source.version)
                or metadata.sha256 != digest
                or metadata.size != len(content)
            ):
                raise Conflict()
            return source
        if row["status"] != "UPLOADING":
            raise Conflict()
        if row["stage"] == "SOURCE_UPLOAD":
            if row["source_upload_sha256"] != digest or row["file_size"] != len(
                content
            ):
                raise OutcomeUnknown(operation_id=context.operation_id)
            try:
                metadata = self.objects.stat(target, context=context)
            except StorageError:
                raise OutcomeUnknown(operation_id=context.operation_id) from None
            binding_version = row["version"]
        else:
            if row["stage"] != "UPLOAD" or row["version"] != expected_version:
                raise Conflict()
            intent = self.records.patch(
                DATASET,
                file_id,
                FieldPatch(
                    set_values={
                        "stage": "SOURCE_UPLOAD",
                        "source_upload_sha256": digest,
                        "file_size": len(content),
                        "source_upload_started_at": datetime.now(
                            timezone.utc
                        ).isoformat(),
                    }
                ),
                expected=Revision(str(expected_version)),
                context=context,
            )
            if not intent.matched:
                raise Conflict()
            binding_version = expected_version + 1
            metadata = self.objects.put(
                target,
                io.BytesIO(content),
                size=len(content),
                content_type=content_type,
                context=context,
            )
        try:
            source = confirmed_reference(metadata, target, digest, len(content))
            receipt = self.records.patch(
                DATASET,
                file_id,
                FieldPatch(set_values=binding_values(source)),
                expected=Revision(str(binding_version)),
                context=context,
            )
            if not receipt.matched:
                current = self.records.get(DATASET, file_id, context=context)
                if (
                    not current
                    or current["status"] not in {"UPLOADING", "UPLOADED"}
                    or current["source_generation"] != row["source_generation"]
                    or current["created_by"] != row["created_by"]
                    or any(
                        current[name] != value
                        for name, value in binding_values(source).items()
                    )
                ):
                    raise OutcomeUnknown()
            return source
        except (StorageError, ValueError):
            # The object can already exist; retain the UPLOADING intent for reconciliation.
            raise OutcomeUnknown(operation_id=context.operation_id) from None
