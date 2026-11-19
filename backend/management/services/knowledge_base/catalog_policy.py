# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Share the existing local/provider KB quota and name creation policy."""

from contracts.constants.environment import (
    MAX_KNOWLEDGE_BASES_PER_TENANT,
    MAX_KNOWLEDGE_BASES_PER_USER,
    MAX_PRIVILEGED_KNOWLEDGE_BASES_PER_USER,
)
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException, DuplicateError
from contracts.roles import has_any_role, normalize_roles
from nexent.storage.models import Comparison, PageRequest, RecordQuery

from infrastructure.knowledge_catalog import ACTOR, CATALOG


def _limit(scope, limit, count, role=None):
    details = {
        "resource": "knowledge_bases",
        "scope": scope,
        "limit": limit,
        "current_count": count,
    }
    if role:
        details["role"] = role
    raise AppException(
        ErrorCode.KNOWLEDGE_RESOURCE_EXCEEDED,
        f"Knowledge base {scope} limit reached: maximum {limit} knowledge bases per {scope}",
        details=details,
    )


def enforce_catalog_creation(records, actor, name, context):
    count = records.count(CATALOG, RecordQuery(), context=context)
    if count >= MAX_KNOWLEDGE_BASES_PER_TENANT:
        _limit("tenant", MAX_KNOWLEDGE_BASES_PER_TENANT, count)
    identities = records.query(
        ACTOR, RecordQuery(), PageRequest(limit=2), context=context
    )
    try:
        role = normalize_roles(
            identities.items[0]["user_roles"] if len(identities.items) == 1 else "USER"
        )
    except ValueError:
        role = ("USER",)
    limit = (
        MAX_PRIVILEGED_KNOWLEDGE_BASES_PER_USER
        if has_any_role(role, {"DEV", "ADMIN", "SU", "ASSET_OWNER"})
        else MAX_KNOWLEDGE_BASES_PER_USER
    )
    count = records.count(
        CATALOG,
        RecordQuery(where=Comparison("created_by", "eq", actor.user_id)),
        context=context,
    )
    if count >= limit:
        _limit("user", limit, count, role)
    if records.count(
        CATALOG,
        RecordQuery(where=Comparison("knowledge_name", "eq", name)),
        context=context,
    ):
        raise DuplicateError(f"Knowledge base name '{name}' already exists")
