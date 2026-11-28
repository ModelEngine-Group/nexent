# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


"""Validation and request-boundary helpers for ontology routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Path
from pydantic import AfterValidator, StringConstraints

from contracts.constants.constants import CAN_EDIT_ALL_USER_ROLES
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.roles import has_any_role
from management.db.identity.user_tenant import get_user_role_by_tenant


def _utf8_max_bytes(limit: int):
    """Return a validator enforcing AIDP's UTF-8 byte ceiling."""

    def _validate(value: str) -> str:
        if len(value.encode("utf-8")) > limit:
            raise ValueError(f"String should have at most {limit} UTF-8 bytes")
        return value

    return _validate


# AIDP publishes these limits as UTF-8 bytes. Character caps are only the
# matching upper bounds for ASCII; the byte validator is the authoritative one.
DomainName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[^-]+$",
    ),
    AfterValidator(_utf8_max_bytes(64)),
]
DomainDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=512),
    AfterValidator(_utf8_max_bytes(512)),
]
MetadataFieldName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=63),
    AfterValidator(_utf8_max_bytes(64)),
]
EntityApiName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z](?:[A-Za-z0-9_]*[A-Za-z0-9])?$",
    ),
]
EntityName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    AfterValidator(_utf8_max_bytes(64)),
]
EntityDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=512),
    AfterValidator(_utf8_max_bytes(512)),
]
RuleName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
    AfterValidator(_utf8_max_bytes(128)),
]
RuleDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=512),
    AfterValidator(_utf8_max_bytes(512)),
]
NumericId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=20, pattern=r"^\d+$"),
]
MetadataKey = Annotated[
    str,
    StringConstraints(min_length=1, max_length=64),
    AfterValidator(_utf8_max_bytes(64)),
]
MetadataValue = (
    Annotated[
        str,
        StringConstraints(max_length=256),
        AfterValidator(_utf8_max_bytes(256)),
    ]
    | None
)


def _validate_metadata_json(
    value: dict[str, str | None],
) -> dict[str, str | None]:
    if not value:
        raise ValueError("metadata_json must not be empty")
    if len(value) > 20:
        raise ValueError("metadata_json must not exceed 20 fields")
    return value


MetadataJson = Annotated[
    dict[MetadataKey, MetadataValue],
    AfterValidator(_validate_metadata_json),
]


def _bad_request(
    message: str, errors: list[dict[str, Any]] | None = None
) -> AppException:
    return AppException(
        ErrorCode.COMMON_PARAMETER_INVALID,
        message,
        details={"errors": errors} if errors else None,
    )


def _forbidden(message: str) -> AppException:
    return AppException(ErrorCode.COMMON_FORBIDDEN, message)


def _require_ontology_manager(user_id: str, tenant_id: str) -> None:
    """Only existing management roles may change ontology definitions.

    Knowledge-base binding is gated separately by the target KB permission so
    a KB owner can bind without acquiring platform-wide ontology rights.
    """
    role = get_user_role_by_tenant(user_id, tenant_id)
    if not has_any_role(role, CAN_EDIT_ALL_USER_ROLES):
        raise _forbidden("the current user cannot manage ontologies")


def _domain_id_path() -> Any:
    return Path(..., min_length=1, max_length=20, pattern=r"^\d+$")
