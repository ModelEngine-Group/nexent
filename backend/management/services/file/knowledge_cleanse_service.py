# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""KB-only admission; durable jobs are dispatched separately after record commit."""

from contextlib import contextmanager

from contracts.knowledge_cleanse import KnowledgeCleanseLookup, KnowledgeCleanseRequest
from management.services.file.cleanse_authorization import KnowledgeCleanseAuthorization
from management.services.file.cleanse_jobs import CleanseJobs
from nexent.storage.errors import InvalidInput, ScopeDenied

from infrastructure.knowledge_cleanse import knowledge_cleanse_ports


class KnowledgeCleanseService:
    def __init__(self, *, parser_version):
        if not isinstance(parser_version, str) or not 0 < len(parser_version) <= 128:
            raise InvalidInput()
        self.parser_version = parser_version

    @contextmanager
    def _jobs(self, tenant_id, user_id, context):
        if any(
            not isinstance(value, str) or not value.strip() or len(value) > 100
            for value in (tenant_id, user_id)
        ):
            raise ScopeDenied()
        context.remaining()
        with knowledge_cleanse_ports(tenant_id, user_id, context=context) as (
            jobs,
            resources,
        ):
            authorization = KnowledgeCleanseAuthorization(resources, user_id=user_id)
            yield CleanseJobs(
                jobs,
                authorize=authorization.authorize,
                parser_version=self.parser_version,
            )

    def submit(self, request, *, tenant_id, user_id, context):
        if not isinstance(request, KnowledgeCleanseRequest):
            raise ScopeDenied()
        with self._jobs(tenant_id, user_id, context) as jobs:
            return jobs.submit(request, context=context)

    def inspect(self, lookup, *, tenant_id, user_id, context):
        if not isinstance(lookup, KnowledgeCleanseLookup):
            raise ScopeDenied()
        with self._jobs(tenant_id, user_id, context) as jobs:
            return jobs.inspect(lookup, context=context)

    def cancel(self, lookup, *, tenant_id, user_id, context):
        if not isinstance(lookup, KnowledgeCleanseLookup):
            raise ScopeDenied()
        with self._jobs(tenant_id, user_id, context) as jobs:
            return jobs.cancel(lookup, context=context)
