# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bind Runtime job policy to a fresh signed Management resource grant."""

from contextlib import contextmanager

from contracts.agentos_knowledge import KnowledgeFileDelete, KnowledgeFileUpload
from nexent.storage.errors import ScopeDenied
from runtime.knowledge_base.jobs import KnowledgeJobs

from infrastructure.knowledge_runtime import knowledge_runtime_ports


@contextmanager
def knowledge_jobs(actor, grant, *, context):
    def authorized(reference, *, context):
        context.remaining()
        if any(
            getattr(reference, name) != getattr(grant, name)
            for name in ("knowledge_id", "file_id", "file_version")
        ):
            raise ScopeDenied()
        if isinstance(reference, KnowledgeFileUpload) and (
            grant.action not in {"upload", "execute"}
            or grant.source is None
            or reference.artifact != grant.artifact
            or reference.parser_version != grant.parser_version
        ):
            raise ScopeDenied()
        if isinstance(reference, KnowledgeFileDelete) and grant.action != "delete":
            raise ScopeDenied()

    with knowledge_runtime_ports(actor, context=context) as records:
        yield KnowledgeJobs(records, authorize=authorized)
