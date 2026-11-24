# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Apply the same edit scope as the associated business experiment."""

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from management.db.evaluation import experiments, public_benchmarks
from management.services.evaluation.evolution_access import require_business_agent_edit


def _authorize(tenant, user, experiment):
    scope = experiments.scope(tenant, experiment)
    if scope is None:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
    require_business_agent_edit(scope["agent_id"], tenant, user)


def record_report(tenant, user, experiment, request):
    _authorize(tenant, user, experiment)
    return public_benchmarks.add_report(tenant, user, experiment, request.model_dump(mode="json"))


def read_reports(tenant, user, experiment, before, limit):
    _authorize(tenant, user, experiment)
    return public_benchmarks.list_reports(tenant, experiment, before, limit)
