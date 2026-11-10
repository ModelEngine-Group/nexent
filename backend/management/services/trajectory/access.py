# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Separate the administrator actor from the conversation capture owner."""

from dataclasses import dataclass

from .primitives import QueryError


@dataclass(frozen=True)
class Actor:
    user_id: str
    tenant_id: str
    role: str

    @property
    def binding(self):
        return [self.user_id, self.tenant_id, self.role]


def authorize(catalog, actor, tenant_id=None):
    if actor.role not in {"ADMIN", "SU"}:
        raise QueryError("administrator_required", 403)
    if not catalog.actor_active(actor):
        raise QueryError("administrator_required", 403)
    tenants = catalog.tenants(actor)
    if tenant_id is not None:
        if tenant_id not in tenants:
            raise QueryError("trajectory_not_found", 404)
        return [tenant_id]
    return tenants
