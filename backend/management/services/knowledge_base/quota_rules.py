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
        source = str(item.get('path_or_url') or item.get('filename') or '').strip()
        if not source:
            continue
        try:
            size = int(item.get('file_size'))
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


def check_tenant_capacity(used, pending, limit):
    if limit is not None and used + pending > limit:
        raise AppException(ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED,
            f'Tenant personal KB storage full: {bytes_to_readable(used + pending)} exceeds hard limit of {bytes_to_readable(limit)}')


def check_user_capacity(used, pending, limit, source, user_id):
    if limit is None:
        return
    if limit <= 0:
        if pending > 0:
            raise AppException(ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED,
                f'Personal KB quota is disabled (0 bytes) for user {user_id}')
        return
    if used + pending > limit:
        raise AppException(ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED,
            f'Personal KB quota exceeded: {bytes_to_readable(used + pending)} exceeds {source} quota of {bytes_to_readable(limit)}')


def check_kb_capacity(used, pending, limit, index_name):
    if limit is None:
        return
    if limit <= 0:
        if pending > 0:
            raise AppException(ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED,
                f'KB quota is disabled (0 bytes) for {index_name}')
        return
    if used + pending > limit:
        raise AppException(ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED,
            f'KB quota exceeded for {index_name}: {bytes_to_readable(used + pending)} exceeds {bytes_to_readable(limit)}')
