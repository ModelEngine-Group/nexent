# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Compatibility re-export of the shared domain-error registry.

The registry is a contract, so its definition moved to
``contracts.errors.domain``: the shared Web layer translates domain failures
too and must not import business source. Callers may keep importing it from
here; new code should import ``contracts.errors.domain`` directly.
"""

from contracts.errors.domain import (  # noqa: F401 - re-exported for existing callers
    DOMAIN_ERROR_SPECS,
    MAX_MESSAGE_LENGTH,
    DomainErrorSpec,
    domain_error_body,
    domain_error_message,
    registered_domain_errors,
    resolve_domain_error,
)

__all__ = [
    "DOMAIN_ERROR_SPECS",
    "MAX_MESSAGE_LENGTH",
    "DomainErrorSpec",
    "domain_error_body",
    "domain_error_message",
    "registered_domain_errors",
    "resolve_domain_error",
]
