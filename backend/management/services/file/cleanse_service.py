# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared admission operations; concrete services supply their scope and authorization."""

from contextlib import contextmanager

from management.services.file.cleanse_jobs import CleanseJobs
from nexent.storage.errors import InvalidInput, ScopeDenied


class CleanseService:
    def __init__(self, *, parser_version):
        if not isinstance(parser_version, str) or not 0 < len(parser_version) <= 128:
            raise InvalidInput()
        self.parser_version = parser_version

    @contextmanager
    def _jobs(self, tenant_id, user_id, context):
        if any(not isinstance(value, str) or not value.strip() or len(value) > 100
               for value in (tenant_id, user_id)):
            raise ScopeDenied()
        context.remaining()
        with self._ports(tenant_id, user_id, context=context) as (jobs, resources):
            authorization = self.authorization_type(resources, user_id=user_id)
            yield CleanseJobs(jobs, authorize=authorization.authorize, parser_version=self.parser_version)

    def submit(self, request, *, tenant_id, user_id, context):
        if not isinstance(request, self.request_type):
            raise ScopeDenied()
        with self._jobs(tenant_id, user_id, context) as jobs:
            return jobs.submit(request, context=context)

    def inspect(self, lookup, *, tenant_id, user_id, context):
        if not isinstance(lookup, self.lookup_type):
            raise ScopeDenied()
        with self._jobs(tenant_id, user_id, context) as jobs:
            return jobs.inspect(lookup, context=context)

    def cancel(self, lookup, *, tenant_id, user_id, context):
        if not isinstance(lookup, self.lookup_type):
            raise ScopeDenied()
        with self._jobs(tenant_id, user_id, context) as jobs:
            return jobs.cancel(lookup, context=context)
