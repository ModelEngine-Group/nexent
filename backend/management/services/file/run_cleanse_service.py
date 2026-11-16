# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run-file cleansing admission; no parser, broker, model or Runtime table access."""

from contracts.agentos_knowledge import (
    FileCleanseLookup,
    FileCleanseReleased,
    FileCleanseRequest,
)
from contracts.constants import environment
from contracts.knowledge_cleanse import parse_cleanse_request
from management.services.file.cleanse_release import release_artifacts
from management.services.file.cleanse_service import CleanseService
from management.services.file.run_cleanse_authorization import RunCleanseAuthorization
from nexent.storage.errors import Conflict, ScopeDenied

from infrastructure.file_processing.artifacts import bind_run_cleanse_artifacts
from infrastructure.knowledge_cleanse import knowledge_cleanse_ports


class FileCleanseService(CleanseService):
    request_type = FileCleanseRequest
    lookup_type = FileCleanseLookup
    authorization_type = RunCleanseAuthorization

    def release(self, lookup, *, tenant_id, user_id, context):
        if not isinstance(lookup, FileCleanseLookup):
            raise ScopeDenied()
        with self._jobs(tenant_id, user_id, context) as jobs:
            row = jobs.record(lookup, context=context)
            if row["status"] == "released":
                return FileCleanseReleased(**lookup.model_dump())
            if row["status"] != "completed" or row["reconcile_required"]:
                raise Conflict()
            request = parse_cleanse_request(row)
            handle = jobs.begin_release(
                lookup, revision=row["revision"], context=context
            )
            objects = bind_run_cleanse_artifacts(
                tenant_id, user_id, lookup, request.source, context=context
            )
            try:
                release_artifacts(
                    objects,
                    handle,
                    lookup,
                    limit=environment.MAX_KNOWLEDGE_FILE_SIZE_BYTES,
                    context=context,
                )
            finally:
                objects.close()
            jobs.finish_release(handle, context=context)
            return FileCleanseReleased(**lookup.model_dump())

    def _ports(self, tenant_id, user_id, *, context):
        return knowledge_cleanse_ports(
            tenant_id,
            user_id,
            context=context,
            resource_namespaces={"cleanse_memberships", "cleanse_accounts"},
        )
