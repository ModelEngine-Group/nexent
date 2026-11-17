# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authorize and serialize the publication and binding of unbound local uploads."""

import re

from contracts.knowledge_ingestion import LOCAL_SOURCE_DATASET as DATASET
from nexent.storage.errors import (
    Conflict,
    InvalidInput,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    Junction,
    PageRequest,
    RecordQuery,
    Revision,
    WriteOutcome,
)


class LocalSourceStaging:
    def __init__(self, records):
        self.records = records

    def _owned(self, stage_id, *, context):
        row = self.records.get(DATASET, stage_id, context=context)
        if row is None or row["created_by"] != self.records.scope.actor_id:
            raise NotFound()
        return row

    def reserve(self, stage_id, path, filename, size, sha256, *, context):
        if (
            not isinstance(stage_id, str)
            or not re.fullmatch(r"[0-9a-f]{32}", stage_id)
            or not isinstance(path, str)
            or not 0 < len(path) <= 2048
            or not isinstance(filename, str)
            or not 0 < len(filename) <= 1024
            or type(size) is not int
            or size < 0
            or not isinstance(sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", sha256)
        ):
            raise InvalidInput()
        return self.records.create(
            DATASET,
            {
                "stage_id": stage_id,
                "tenant_id": self.records.scope.tenant_id,
                "local_source_path": path,
                "original_filename": filename,
                "file_size": size,
                "source_sha256": sha256,
                "state": "UPLOADING",
                "knowledge_id": None,
                "bound_file_id": None,
            },
            context=context,
        )

    def find(self, path, *, context):
        if not isinstance(path, str) or not 0 < len(path) <= 2048:
            raise InvalidInput()
        page = self.records.query(
            DATASET,
            RecordQuery(
                where=Junction(
                    "and",
                    (
                        Comparison("local_source_path", "eq", path),
                        Comparison("created_by", "eq", self.records.scope.actor_id),
                    ),
                )
            ),
            PageRequest(limit=2),
            context=context,
        )
        if not page.items:
            raise NotFound()
        if len(page.items) != 1 or page.next_cursor:
            raise ScopeDenied()
        return page.items[0]

    def _change(self, snapshot, state, values, *, context):
        row = self._owned(snapshot["stage_id"], context=context)
        if row["version"] != snapshot["version"] or row["state"] != state:
            raise Conflict()
        receipt = self.records.patch(
            DATASET,
            row["stage_id"],
            FieldPatch(set_values=values),
            expected=Revision(str(row["version"])),
            context=context,
        )
        if receipt.outcome is WriteOutcome.UNKNOWN:
            raise OutcomeUnknown(operation_id=context.operation_id)
        if receipt.outcome is not WriteOutcome.CONFIRMED or not receipt.matched:
            raise Conflict()
        try:
            return self._owned(row["stage_id"], context=context)
        except Exception as error:
            raise OutcomeUnknown(operation_id=context.operation_id) from error

    def confirm(self, snapshot, *, context):
        return self._change(snapshot, "UPLOADING", {"state": "READY"}, context=context)

    def bind(self, snapshot, knowledge_id, file_id, authorization, *, context):
        self._owned(snapshot["stage_id"], context=context)
        if (
            type(knowledge_id) is not int
            or knowledge_id <= 0
            or not isinstance(file_id, str)
            or not re.fullmatch(r"[0-9a-f]{32}", file_id)
        ):
            raise InvalidInput()
        authorization.resolve_knowledge(knowledge_id, edit=True, context=context)
        return self._change(
            snapshot,
            "READY",
            {
                "state": "BINDING",
                "knowledge_id": knowledge_id,
                "bound_file_id": file_id,
            },
            context=context,
        )

    def complete(self, snapshot, *, context):
        return self._change(snapshot, "BINDING", {"state": "BOUND"}, context=context)
