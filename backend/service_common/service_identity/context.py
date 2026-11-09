# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Downstream request-local principal; application middleware owns its lifetime."""

from contextvars import ContextVar

from service_common.security.identity import IdentityError

identity_context = ContextVar("gateway_identity", default=None)


def trusted_identity(kind=None):
    identity = identity_context.get()
    if identity is not None and kind is not None and identity.get("kind") != kind:
        raise IdentityError("Credential policy mismatch")
    return identity
