# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Backend configuration adapter for the pure Gateway identity protocol."""

from gateway.security import identity as protocol
from gateway.security.identity import IDENTITY_HEADER, ISSUER, LOOKUP_PATH, TTL, IdentityError, bearer_token
from gateway.security.context import identity_context, trusted_identity


def signing_key():
    from contracts.constants import environment

    return protocol.derive_signing_key(environment.JWT_SECRET, environment.GATEWAY_SIGNING_SECRET)


def enabled():
    from contracts.constants import environment

    return getattr(environment, "GATEWAY_AUTH_ENABLED", False)


def sign_identity(identity, audience, method, path, query, *, key=None):
    return protocol.sign_identity(identity, audience, method, path, query, key=signing_key() if key is None else key)


def verify_identity(token, audience, method, path, query, *, key=None):
    return protocol.verify_identity(token, audience, method, path, query, key=signing_key() if key is None else key)


def sign_lookup(body, *, key=None):
    return protocol.sign_lookup(body, key=signing_key() if key is None else key)


def verify_lookup(token, body, *, key=None):
    return protocol.verify_lookup(token, body, key=signing_key() if key is None else key)
