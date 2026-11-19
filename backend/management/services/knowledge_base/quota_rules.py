# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Pure existing source-byte quota rules, shared by SI and administrative callers."""

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from management.services.knowledge_base.quota_formatting import bytes_to_readable


def source_sizes(data):
    result = {}
    for item in data or []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("path_or_url") or item.get("filename") or "").strip()
        if not source:
            continue
        try:
            size = int(item.get("file_size"))
        except (TypeError, ValueError):
            continue
        if size > 0:
            result[source] = max(result.get(source, 0), size)
    return result


def parse_personal_quota(raw):
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def check_user_quota_allocation(limit, used):
    if limit < used:
        raise AppException(ErrorCode.TENANT_PERSONAL_KB_QUOTA_BELOW_USAGE,
            message=f'Personal KB quota {bytes_to_readable(limit)} is below current usage {bytes_to_readable(used)}',
            details={'quota_limit_bytes': limit, 'usage_bytes': used})


def check_tenant_capacity(used, pending, limit):
    if limit is not None and used + pending > limit:
        raise AppException(
            ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED,
            f"Tenant personal KB storage full: {bytes_to_readable(used + pending)} exceeds hard limit of {bytes_to_readable(limit)}",
        )


def check_user_capacity(used, pending, limit, source, user_id):
    if limit is None:
        return
    if limit <= 0:
        if pending > 0:
            raise AppException(
                ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED,
                f"Personal KB quota is disabled (0 bytes) for user {user_id}",
            )
        return
    if used + pending > limit:
        raise AppException(
            ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED,
            f"Personal KB quota exceeded: {bytes_to_readable(used + pending)} exceeds {source} quota of {bytes_to_readable(limit)}",
        )


def check_kb_capacity(used, pending, limit, index_name):
    if limit is None:
        return
    if limit <= 0:
        if pending > 0:
            raise AppException(
                ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED,
                f"KB quota is disabled (0 bytes) for {index_name}",
            )
        return
    if used + pending > limit:
        raise AppException(
            ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED,
            f"KB quota exceeded for {index_name}: {bytes_to_readable(used + pending)} exceeds {bytes_to_readable(limit)}",
        )


def hard_limit_values(raw, editable_raw):
    editable = editable_raw != "false" if editable_raw else True
    try:
        limit = int(raw) if raw is not None else None
    except (ValueError, TypeError):
        limit = None
    return {
        "hard_limit_bytes": limit,
        "hard_limit_readable": bytes_to_readable(limit),
        "hard_limit_editable": editable,
    }


def warning_values(
    enabled_raw, warning_raw, critical_raw, *, default_warning=80, default_critical=95
):
    enabled = enabled_raw.lower() == "true" if enabled_raw else True
    try:
        warning = int(warning_raw) if warning_raw else default_warning
    except (ValueError, TypeError):
        warning = default_warning
    try:
        critical = int(critical_raw) if critical_raw else default_critical
    except (ValueError, TypeError):
        critical = default_critical
    return {
        "warning_enabled": enabled,
        "warning_threshold_pct": warning,
        "critical_threshold_pct": critical,
    }


def allocation_summary(hard_limit, allocated, kb_count, kbs_with_quota):
    limit = hard_limit.get("hard_limit_bytes")
    ratio = round(allocated / limit, 4) if limit and limit > 0 else None
    return {
        "soft_allocated_total_bytes": allocated,
        "soft_allocated_readable": bytes_to_readable(allocated),
        "hard_limit_bytes": limit,
        "hard_limit_readable": hard_limit.get("hard_limit_readable"),
        "total_bytes": None,
        "total_readable": None,
        "oversubscription_ratio": ratio,
        "kb_count": kb_count,
        "kbs_with_quota": kbs_with_quota,
    }
