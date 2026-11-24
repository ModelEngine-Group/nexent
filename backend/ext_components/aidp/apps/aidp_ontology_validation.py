# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


"""Validation and request-boundary helpers for ontology routes."""

from __future__ import annotations

from typing import Any

from fastapi import Path

from contracts.constants.constants import CAN_EDIT_ALL_USER_ROLES
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.roles import has_any_role
from management.db.identity.user_tenant import get_user_role_by_tenant


_DOMAIN_NAME_MAX_CHARS = 64


_DOMAIN_DESCRIPTION_MAX_CHARS = 512


_METADATA_FIELD_NAME_MAX_CHARS = 63


_METADATA_FIELD_NAME_MAX_BYTES = 64


_ENTITY_NAME_MAX_CHARS = 64


_ENTITY_DESCRIPTION_MAX_CHARS = 512


_DOMAIN_NAME_MAX_BYTES = 64

_DOMAIN_DESCRIPTION_MAX_BYTES = 512

_ENTITY_NAME_MAX_BYTES = 64

_ENTITY_DESCRIPTION_MAX_BYTES = 512

_RULE_NAME_MAX_BYTES = 128

_RULE_DESCRIPTION_MAX_BYTES = 512


def _utf8_size(value: str) -> int:
    return len(value.encode("utf-8"))


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
        raise _forbidden("当前用户没有本体库管理权限")


def _clean_required(value: Any, message: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _bad_request(message)
    return value.strip()


def _validate_domain_name(value: str) -> str:
    name = _clean_required(value, "本体库名称不能为空")
    if len(name) > _DOMAIN_NAME_MAX_CHARS:
        raise _bad_request(f"本体库名称不能超过 {_DOMAIN_NAME_MAX_CHARS} 个字符")
    if _utf8_size(name) > _DOMAIN_NAME_MAX_BYTES:
        raise _bad_request(f"本体库名称不能超过 {_DOMAIN_NAME_MAX_BYTES} 字节")
    # AIDP rejects hyphens with an opaque 500/code1001; fail fast with a
    # readable 400 before the request leaves Nexent.
    if "-" in name:
        raise _bad_request("本体库名称不能包含连字符 -")
    return name


def _validate_domain_description(value: str | None) -> str:
    description = (value or "").strip()
    if len(description) > _DOMAIN_DESCRIPTION_MAX_CHARS:
        raise _bad_request(f"本体库描述不能超过 {_DOMAIN_DESCRIPTION_MAX_CHARS} 个字符")
    if _utf8_size(description) > _DOMAIN_DESCRIPTION_MAX_BYTES:
        raise _bad_request(f"本体库描述不能超过 {_DOMAIN_DESCRIPTION_MAX_BYTES} 字节")
    return description


def _validate_field_name(value: str, *, message: str = "字段名不能为空") -> str:
    """Apply the conservative AIDP field-name limits.

    The documentation states an upper bound of 64 but also notes that the
    deployed check rejects ``len() >= 64``, so the usable limit is 63
    characters. A separate 64-byte key limit applies to non-ASCII names.
    """
    name = _clean_required(value, message)
    if len(name) > _METADATA_FIELD_NAME_MAX_CHARS:
        raise _bad_request(f"字段名不能超过 {_METADATA_FIELD_NAME_MAX_CHARS} 个字符")
    if _utf8_size(name) > _METADATA_FIELD_NAME_MAX_BYTES:
        raise _bad_request(f"字段名不能超过 {_METADATA_FIELD_NAME_MAX_BYTES} 字节")
    return name


def _validate_entity_name(value: str, *, message: str = "名称不能为空") -> str:
    """Validate one AIDP entity display name against the 64-byte limit."""
    name = (value or "").strip()
    if not name:
        raise ValueError(message)
    if _utf8_size(name) > _ENTITY_NAME_MAX_BYTES:
        raise ValueError(f"名称不能超过 {_ENTITY_NAME_MAX_BYTES} 字节")
    return name


def _validate_entity_description(value: str | None) -> str:
    description = (value or "").strip()
    if _utf8_size(description) > _ENTITY_DESCRIPTION_MAX_BYTES:
        raise ValueError(f"实体描述不能超过 {_ENTITY_DESCRIPTION_MAX_BYTES} 字节")
    return description


def _validate_rule_name(value: str) -> str:
    name = (value or "").strip()
    if not name:
        raise ValueError("规则名称不能为空")
    if _utf8_size(name) > _RULE_NAME_MAX_BYTES:
        raise ValueError(f"规则名称不能超过 {_RULE_NAME_MAX_BYTES} 字节")
    return name


def _validate_rule_description(value: str | None) -> str:
    description = (value or "").strip()
    if _utf8_size(description) > _RULE_DESCRIPTION_MAX_BYTES:
        raise ValueError(f"规则描述不能超过 {_RULE_DESCRIPTION_MAX_BYTES} 字节")
    return description


def _domain_id_path() -> Any:
    return Path(..., min_length=1, max_length=20, pattern=r"^\d+$")


def _numeric_domain_id(domain_id: str) -> int:
    try:
        value = int(domain_id)
    except (TypeError, ValueError):
        raise _bad_request("本体库 ID 必须是数字") from None
    if value < 0:
        raise _bad_request("本体库 ID 不合法")
    return value
