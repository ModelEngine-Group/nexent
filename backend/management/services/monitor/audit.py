# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Security audit logging: moved to the shared Web layer, re-exported here.

The implementation lives in ``backend/http/server/security_audit.py`` because
the ops ``/nb`` mirror records the same ``[SEC_AUDIT]`` events; this module
keeps the historical import path working for the existing management call
sites. See the shared module for the entry format and guarantees.
"""

from backend.http.server.security_audit import (  # noqa: F401 - re-exported
    AUDIT_DETAIL_LIST_LIMIT,
    AUDIT_LOG_PREFIX,
    AUDIT_RESULT_SUCCESS,
    USER_AGENT_MAX_LENGTH,
    format_audit_entry,
    record_security_event,
)

__all__ = [
    "AUDIT_DETAIL_LIST_LIMIT",
    "AUDIT_LOG_PREFIX",
    "AUDIT_RESULT_SUCCESS",
    "USER_AGENT_MAX_LENGTH",
    "format_audit_entry",
    "record_security_event",
]
