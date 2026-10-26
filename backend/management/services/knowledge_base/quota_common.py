# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""
Quota service for KB storage capacity management.

Provides three-tier quota management:
- Platform tier: SU declares capacity and allocates per-tenant hard quotas
- Tenant tier: Hard limit enforcement at upload time
- KB tier: Per-KB soft quotas (advisory, warnings only)
"""

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from contracts.constants.constants import ASSET_OWNER_TENANT_ID, DEFAULT_TENANT_ID
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException, PlatformQuotaConflictError, QuotaExceededError
from management.db.knowledge_base.repository import get_knowledge_info_by_tenant_id, get_private_knowledge_info_by_creator, get_private_knowledge_info_by_tenant_id, update_knowledge_record
from management.db.configuration.tenant import delete_config_by_tenant_config_id, get_configs_by_tenant_id_and_keys, get_single_config_info, insert_config, update_config_by_tenant_config_id
from management.db.identity.user_tenant import get_user_email_map
from infrastructure.formatting import bytes_to_readable
from management.services.knowledge_base.storage import (
    get_committed_bytes_by_kb,
    get_committed_source_bytes_by_paths,
    get_tenant_committed_source_bytes,
)

logger = logging.getLogger(__name__)

# Keep the existing service-level name for compatibility with callers and tests.
_bytes_to_readable = bytes_to_readable

# Tenant config keys
KEY_TENANT_HARD_LIMIT_BYTES = "KB_QUOTA_TENANT_HARD_LIMIT_BYTES"
KEY_WARNING_ENABLED = "KB_QUOTA_WARNING_ENABLED"
KEY_WARNING_THRESHOLD_PCT = "KB_QUOTA_WARNING_THRESHOLD_PCT"
KEY_CRITICAL_THRESHOLD_PCT = "KB_QUOTA_CRITICAL_THRESHOLD_PCT"
KEY_HARD_LIMIT_EDITABLE = "KB_QUOTA_HARD_LIMIT_EDITABLE"
KEY_PLATFORM_CAPACITY_BYTES = "PLATFORM_KB_STORAGE_CAPACITY_BYTES"
KEY_PERSONAL_KB_QUOTA_DEFAULT = "PERSONAL_KB_QUOTA_DEFAULT"


def _personal_quota_key(user_id: str) -> str:
    """Return the tenant config key for a user's personal KB quota."""
    return f"PERSONAL_KB_QUOTA_{user_id}"


def _is_displayable_tenant_id(
    tenant_id: Optional[str],
    asset_owner_tenant_id: str = ASSET_OWNER_TENANT_ID,
) -> bool:
    """Return whether a tenant id should appear in platform quota views."""
    normalized_tenant_id = (tenant_id or "").strip()
    return normalized_tenant_id not in {"", DEFAULT_TENANT_ID, asset_owner_tenant_id}


# Constants
GB = 1024 * 1024 * 1024
CACHE_TTL_SECONDS = 60
DEFAULT_WARNING_THRESHOLD = 80
DEFAULT_CRITICAL_THRESHOLD = 95

# In-memory cache for usage data
_usage_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_UNSET = object()

# Config helpers use independent database sessions, so serialize allocation
# validation and writes within a config-service process.
_platform_allocation_lock = threading.RLock()


MB = 1024 * 1024


def _gb_to_bytes(gb: int) -> int:
    """Convert integer GB to bytes."""
    if gb < 0:
        raise ValueError(f"GB value must be non-negative, got {gb}")
    return gb * GB


def _mb_to_bytes(mb: int) -> int:
    """Convert integer MB to bytes."""
    if mb < 0:
        raise ValueError(f"MB value must be non-negative, got {mb}")
    return mb * MB
