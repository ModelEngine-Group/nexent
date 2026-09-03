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

from consts.const import ASSET_OWNER_TENANT_ID, DEFAULT_TENANT_ID
from consts.error_code import ErrorCode
from consts.exceptions import (
    AppException,
    PlatformQuotaConflictError,
    QuotaExceededError,
)
from database.knowledge_db import (
    get_knowledge_info_by_tenant_id,
    get_private_knowledge_info_by_creator,
    get_private_knowledge_info_by_tenant_id,
    update_knowledge_record,
)
from database.tenant_config_db import (
    delete_config_by_tenant_config_id,
    get_configs_by_tenant_id_and_keys,
    get_single_config_info,
    insert_config,
    update_config_by_tenant_config_id,
)
from database.user_tenant_db import get_user_email_map
from services.knowledge_storage_service import (
    get_committed_bytes_by_kb,
    get_committed_source_bytes_by_paths,
    get_tenant_committed_source_bytes,
)
from utils.bytes_utils import bytes_to_readable

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
    return gb * GB


def _mb_to_bytes(mb: int) -> int:
    """Convert integer MB to bytes."""
    return mb * MB


class QuotaService:
    """Service for managing storage quotas at tenant and KB level."""

    def __init__(self, tenant_id: str, user_id: Optional[str] = None):
        self.tenant_id = tenant_id
        self.user_id = user_id or "system"

    @staticmethod
    def invalidate_usage_cache(tenant_id: Optional[str] = None) -> None:
        """Invalidate cached tenant usage used by tenant and platform quota views."""
        if tenant_id is None:
            _usage_cache.clear()
            return
        _usage_cache.pop(tenant_id, None)

    # ── Tenant Config Helpers ──────────────────────────────────────────

    def _get_tenant_config(self, key: str) -> Optional[str]:
        """Read a single tenant config value."""
        record = get_single_config_info(self.tenant_id, key)
        return record.get("config_value") if record else None

    def _set_tenant_config(self, key: str, value: Any, value_type: str = "single") -> bool:
        """Upsert a tenant config key. Updates existing row or inserts new."""
        existing = get_single_config_info(self.tenant_id, key)
        if existing and existing.get("tenant_config_id"):
            return update_config_by_tenant_config_id(
                existing["tenant_config_id"], str(value)
            )
        else:
            return insert_config({
                "tenant_id": self.tenant_id,
                "user_id": self.user_id,
                "config_key": key,
                "config_value": str(value),
                "value_type": value_type,
            })

    def _delete_tenant_config(self, key: str) -> bool:
        """Soft-delete a tenant config key."""
        existing = get_single_config_info(self.tenant_id, key)
        tenant_config_id = existing.get("tenant_config_id") if existing else None
        if tenant_config_id is None:
            return True
        return delete_config_by_tenant_config_id(tenant_config_id)

    # ── Tenant-Level Hard Limit (task 2.2) ─────────────────────────────

    def get_hard_limit(self) -> Dict[str, Any]:
        """
        Get the tenant hard storage limit.
        Returns dict with _bytes and _readable fields, or defaults for unlimited.
        """
        raw = self._get_tenant_config(KEY_TENANT_HARD_LIMIT_BYTES)
        editable_raw = self._get_tenant_config(KEY_HARD_LIMIT_EDITABLE)
        editable = editable_raw != "false" if editable_raw else True

        if raw is not None:
            try:
                limit_bytes = int(raw)
                return {
                    "hard_limit_bytes": limit_bytes,
                    "hard_limit_readable": _bytes_to_readable(limit_bytes),
                    "hard_limit_editable": editable,
                }
            except (ValueError, TypeError):
                pass

        return {
            "hard_limit_bytes": None,
            "hard_limit_readable": None,
            "hard_limit_editable": editable,
        }

    def set_hard_limit(
        self,
        limit_gb: Optional[int] = None,
        limit_mb: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Set the tenant hard storage limit. None = unlimited.
        Accepts either limit_gb (GB) or limit_mb (MB) for testing with small quotas.
        Also sets hard_limit_editable = true (admins can manage their own limit).
        """
        if limit_gb is None and limit_mb is None:
            self._delete_tenant_config(KEY_TENANT_HARD_LIMIT_BYTES)
            self._set_tenant_config(KEY_HARD_LIMIT_EDITABLE, "true")
            return {"hard_limit_bytes": None, "hard_limit_readable": None}

        limit_bytes = self._quota_input_to_bytes(limit_gb, limit_mb)
        with _platform_allocation_lock:
            self._validate_tenant_hard_limit(limit_bytes)
            self._set_tenant_config(KEY_TENANT_HARD_LIMIT_BYTES, str(limit_bytes))
            self._set_tenant_config(KEY_HARD_LIMIT_EDITABLE, "true")
        return {
            "hard_limit_bytes": limit_bytes,
            "hard_limit_readable": _bytes_to_readable(limit_bytes),
        }

    def delete_hard_limit(self) -> bool:
        """Remove the tenant hard storage limit."""
        self._delete_tenant_config(KEY_TENANT_HARD_LIMIT_BYTES)
        self._delete_tenant_config(KEY_HARD_LIMIT_EDITABLE)
        return True

    # ── Warning Configuration (task 2.2) ───────────────────────────────

    def get_warning_config(self) -> Dict[str, Any]:
        """Get warning configuration: enabled, warning_pct, critical_pct."""
        enabled_raw = self._get_tenant_config(KEY_WARNING_ENABLED)
        warning_raw = self._get_tenant_config(KEY_WARNING_THRESHOLD_PCT)
        critical_raw = self._get_tenant_config(KEY_CRITICAL_THRESHOLD_PCT)

        enabled = enabled_raw.lower() == "true" if enabled_raw else True  # default on
        try:
            warning_pct = int(warning_raw) if warning_raw else DEFAULT_WARNING_THRESHOLD
        except (ValueError, TypeError):
            warning_pct = DEFAULT_WARNING_THRESHOLD
        try:
            critical_pct = int(critical_raw) if critical_raw else DEFAULT_CRITICAL_THRESHOLD
        except (ValueError, TypeError):
            critical_pct = DEFAULT_CRITICAL_THRESHOLD

        return {
            "warning_enabled": enabled,
            "warning_threshold_pct": warning_pct,
            "critical_threshold_pct": critical_pct,
        }

    def set_warning_config(
        self,
        enabled: Optional[bool] = None,
        warning_pct: Optional[int] = None,
        critical_pct: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Set warning thresholds. Validates 1-100 range."""
        if warning_pct is not None:
            if not 1 <= warning_pct <= 100:
                raise ValueError(f"warning_pct must be 1-100, got {warning_pct}")
            self._set_tenant_config(KEY_WARNING_THRESHOLD_PCT, str(warning_pct))

        if critical_pct is not None:
            if not 1 <= critical_pct <= 100:
                raise ValueError(f"critical_pct must be 1-100, got {critical_pct}")
            self._set_tenant_config(KEY_CRITICAL_THRESHOLD_PCT, str(critical_pct))

        if enabled is not None:
            self._set_tenant_config(KEY_WARNING_ENABLED, str(enabled).lower())

        return self.get_warning_config()

    # ── Per-KB Soft Quota (task 2.3) ───────────────────────────────────

    def get_kb_soft_quota(self, knowledge_id: int) -> Optional[int]:
        """Get per-KB soft quota in bytes. Returns None if not set."""
        from database.client import get_db_session
        from database.db_models import KnowledgeRecord

        with get_db_session() as session:
            record = session.query(KnowledgeRecord).filter(
                KnowledgeRecord.knowledge_id == knowledge_id,
                KnowledgeRecord.delete_flag != "Y",
            ).first()
            if record:
                return record.quota_limit_bytes
            return None

    def set_kb_soft_quota(self, index_name: str, limit_bytes: Optional[int]) -> bool:
        """
        Set per-KB soft quota via index_name. None = unlimited.
        Updates the knowledge_record_t row.
        """
        return update_knowledge_record({
            "index_name": index_name,
            "quota_limit_bytes": limit_bytes,
            "user_id": self.user_id,
        })

    def get_all_kb_quotas(self) -> List[Dict[str, Any]]:
        """Get all KB quota records for the tenant."""
        kb_list = get_knowledge_info_by_tenant_id(self.tenant_id)
        result = []
        for kb in kb_list:
            result.append({
                "knowledge_id": kb.get("knowledge_id"),
                "index_name": kb.get("index_name"),
                "knowledge_name": kb.get("knowledge_name"),
                "quota_limit_bytes": kb.get("quota_limit_bytes"),
            })
        return result

    # ── Quota Summary (task 2.4) ───────────────────────────────────────

    # Personal KB capacity methods (tasks 4.1-4.2)

    @staticmethod
    def _parse_quota_value(raw: Any) -> Optional[int]:
        """Parse a quota config value; invalid values are treated as zero."""
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    def get_personal_user_quota(self, user_id: str) -> Optional[int]:
        """Return a user's individual personal KB quota in bytes, or None."""
        return self._parse_quota_value(
            self._get_tenant_config(_personal_quota_key(user_id))
        )

    def set_personal_user_quota(
        self,
        user_id: str,
        quota_limit_bytes: Optional[int] = None,
        unlimited: bool = False,
    ) -> Dict[str, Any]:
        """Set or clear a user's individual personal KB quota."""
        if unlimited or quota_limit_bytes is None:
            self._delete_tenant_config(_personal_quota_key(user_id))
            return {
                "user_id": user_id,
                "quota_limit_bytes": None,
                "quota_limit_readable": None,
            }

        quota_limit_bytes = int(quota_limit_bytes)
        usage_data = self._get_personal_usage_data(user_id=user_id)
        user_usage = self._aggregate_personal_storage_by_user(
            usage_data, user_ids={user_id}
        ).get(user_id, {"total_bytes": 0})
        user_usage_bytes = user_usage["total_bytes"]
        if quota_limit_bytes < user_usage_bytes:
            raise AppException(
                ErrorCode.TENANT_PERSONAL_KB_QUOTA_BELOW_USAGE,
                message=(
                    f"Personal KB quota {_bytes_to_readable(quota_limit_bytes)} is below "
                    f"current usage {_bytes_to_readable(user_usage_bytes)}"
                ),
                details={
                    "quota_limit_bytes": quota_limit_bytes,
                    "usage_bytes": user_usage_bytes,
                },
            )

        self._set_tenant_config(_personal_quota_key(user_id), str(quota_limit_bytes))
        return {
            "user_id": user_id,
            "quota_limit_bytes": quota_limit_bytes,
            "quota_limit_readable": _bytes_to_readable(quota_limit_bytes),
        }

    def get_personal_default_quota(self) -> Optional[int]:
        """Return the tenant default personal KB quota in bytes, or None."""
        return self._parse_quota_value(
            self._get_tenant_config(KEY_PERSONAL_KB_QUOTA_DEFAULT)
        )

    def set_personal_default_quota(
        self,
        quota_limit_bytes: Optional[int] = None,
        unlimited: bool = False,
    ) -> Dict[str, Any]:
        """Set or clear the tenant default personal KB quota."""
        if unlimited or quota_limit_bytes is None:
            self._delete_tenant_config(KEY_PERSONAL_KB_QUOTA_DEFAULT)
            return {"quota_limit_bytes": None, "quota_limit_readable": None}

        quota_limit_bytes = int(quota_limit_bytes)
        self._set_tenant_config(KEY_PERSONAL_KB_QUOTA_DEFAULT, str(quota_limit_bytes))
        return {
            "quota_limit_bytes": quota_limit_bytes,
            "quota_limit_readable": _bytes_to_readable(quota_limit_bytes),
        }

    def _get_personal_effective_quota(
        self, user_id: str, default_quota: Any = _UNSET
    ) -> Tuple[Optional[int], str]:
        """Return effective personal KB quota and its source for a user."""
        individual = self.get_personal_user_quota(user_id)
        if individual is not None:
            return individual, "individual"
        default = (
            self.get_personal_default_quota()
            if default_quota is _UNSET
            else default_quota
        )
        if default is not None:
            return default, "default"
        return None, "unlimited"

    def _get_personal_effective_quota_map(
        self,
        user_ids: set[str],
        default_quota: Any = _UNSET,
    ) -> Tuple[Dict[str, Tuple[Optional[int], str]], Optional[int]]:
        """Resolve effective personal quotas for users with one config query."""
        normalized_user_ids = sorted(user_id for user_id in user_ids if user_id)
        config_keys = [_personal_quota_key(user_id) for user_id in normalized_user_ids]
        if default_quota is _UNSET:
            config_keys.append(KEY_PERSONAL_KB_QUOTA_DEFAULT)

        configs = get_configs_by_tenant_id_and_keys(self.tenant_id, config_keys)
        resolved_default = (
            self._parse_quota_value(configs.get(KEY_PERSONAL_KB_QUOTA_DEFAULT))
            if default_quota is _UNSET
            else default_quota
        )
        resolved: Dict[str, Tuple[Optional[int], str]] = {}
        for user_id in normalized_user_ids:
            individual_quota = self._parse_quota_value(
                configs.get(_personal_quota_key(user_id))
            )
            if individual_quota is not None:
                resolved[user_id] = (individual_quota, "individual")
            elif resolved_default is not None:
                resolved[user_id] = (resolved_default, "default")
            else:
                resolved[user_id] = (None, "unlimited")
        return resolved, resolved_default

    def get_personal_self_capacity(self, user_id: str) -> Dict[str, Any]:
        """Return the current user's PRIVATE KB usage and effective quota."""
        usage_data = self._get_personal_usage_data(strict=True, user_id=user_id)
        user_usage = self._aggregate_personal_storage_by_user(
            usage_data, user_ids={user_id}
        ).get(user_id, {"total_bytes": 0, "kb_count": 0})
        quota_bytes, quota_source = self._get_personal_effective_quota(user_id)
        used_bytes = user_usage["total_bytes"]
        usage_rate = None
        if quota_bytes is not None:
            usage_rate = (
                100.0
                if quota_bytes <= 0 and used_bytes > 0
                else round(used_bytes / quota_bytes * 100, 2)
                if quota_bytes > 0
                else 0.0
            )
        return {
            "used_bytes": used_bytes,
            "used_readable": _bytes_to_readable(used_bytes),
            "quota_bytes": quota_bytes,
            "quota_readable": _bytes_to_readable(quota_bytes),
            "quota_source": quota_source,
            "usage_rate": usage_rate,
            "is_over_quota": quota_bytes is not None and used_bytes > quota_bytes,
            "kb_count": user_usage["kb_count"],
        }

    @staticmethod
    def _is_valid_store_size(value: Any) -> bool:
        """Return whether an ES store_size value has a supported format."""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value >= 0
        if not isinstance(value, str) or not value.strip():
            return False
        parts = value.strip().split()
        if len(parts) != 2 or parts[1].upper() not in {"GB", "MB", "KB", "B"}:
            return False
        try:
            return float(parts[0]) >= 0
        except (TypeError, ValueError):
            return False

    def _get_kb_storage_stats(
        self,
        kb_list: List[Dict[str, Any]],
        strict: bool = False,
        exclude_datamate: bool = False,
    ) -> Dict[str, Any]:
        """Collect one consistent ES-plus-source storage view for KB records."""
        index_names = [
            kb.get("index_name")
            for kb in kb_list
            if kb.get("index_name")
            and not (exclude_datamate and kb.get("knowledge_sources") == "datamate")
        ]
        indices_detail: Dict[str, Any] = {}

        if index_names:
            try:
                from management.services.knowledge_base.service import get_vector_db_core

                vdb_core = get_vector_db_core()
                raw_indices_detail = vdb_core.get_indices_detail(index_names) or {}
                indices_detail = (
                    raw_indices_detail if isinstance(raw_indices_detail, dict) else {}
                )
                if strict:
                    missing_indices = set(index_names) - set(indices_detail)
                    if missing_indices:
                        raise AppException(
                            ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE,
                            "ES index stats missing for: "
                            + ", ".join(sorted(missing_indices)),
                        )
            except AppException:
                raise
            except Exception as exc:
                if strict:
                    raise AppException(
                        ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE,
                        f"Failed to query ES index stats: {exc}",
                    ) from exc
                logger.warning(
                    "Failed to query ES index stats for personal KB capacity",
                    exc_info=True,
                )

        knowledge_ids = [
            kb.get("knowledge_id")
            for kb in kb_list
            if kb.get("knowledge_id") is not None
        ]
        try:
            source_bytes_by_kb = (
                get_committed_bytes_by_kb(self.tenant_id, knowledge_ids)
                if knowledge_ids
                else {}
            )
        except Exception as exc:
            if strict:
                raise AppException(
                    ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE,
                    f"Failed to query source storage stats: {exc}",
                ) from exc
            logger.warning(
                "Failed to query source storage stats for personal KB capacity",
                exc_info=True,
            )
            source_bytes_by_kb = {}

        stats: Dict[str, int] = {}
        details: Dict[str, Dict[str, Any]] = {}
        for kb in kb_list:
            index_name = kb.get("index_name", "")
            if not index_name:
                continue

            raw_detail = indices_detail.get(index_name)
            es_bytes = 0
            store_size = None
            doc_count = 0
            chunk_count = 0
            is_datamate = kb.get("knowledge_sources") == "datamate"
            if not (exclude_datamate and is_datamate):
                detail = raw_detail if isinstance(raw_detail, dict) else {}
                if strict and not isinstance(raw_detail, dict):
                    raise AppException(
                        ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE,
                        f"ES index stats unavailable for {index_name}",
                    )
                if strict and "error" in detail:
                    raise AppException(
                        ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE,
                        f"ES index stats unavailable for {index_name}",
                    )
                base_info = (
                    detail.get("base_info")
                    if isinstance(detail.get("base_info"), dict)
                    else {}
                )
                store_size = base_info.get("store_size")
                if strict and not self._is_valid_store_size(store_size):
                    raise AppException(
                        ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE,
                        f"ES index store_size unavailable for {index_name}",
                    )
                es_bytes = self._parse_store_size(store_size)
                doc_count = base_info.get("doc_count", 0) or 0
                chunk_count = base_info.get("chunk_count", 0) or 0

            try:
                knowledge_id = int(kb.get("knowledge_id"))
            except (TypeError, ValueError):
                knowledge_id = None
            source_bytes = (
                source_bytes_by_kb.get(knowledge_id, 0)
                if knowledge_id is not None
                else 0
            )
            total_bytes = es_bytes + source_bytes
            stats[index_name] = total_bytes
            details[index_name] = {
                "store_size": store_size,
                "store_size_bytes": es_bytes,
                "source_size": _bytes_to_readable(source_bytes),
                "source_size_bytes": source_bytes,
                "total_size": _bytes_to_readable(total_bytes),
                "total_size_bytes": total_bytes,
                "doc_count": doc_count,
                "chunk_count": chunk_count,
            }

        return {
            "stats": stats,
            "details": details,
            "total_es_bytes": sum(item["store_size_bytes"] for item in details.values()),
            "total_source_bytes": sum(item["source_size_bytes"] for item in details.values()),
            "total_bytes": sum(stats.values()),
        }

    def _get_personal_usage_data(
        self,
        strict: bool = False,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Aggregate PRIVATE KB storage using the unified capacity definition.

        Non-strict mode degrades storage-stat failures to zero usage so admin
        capacity views stay available. Upload quota checks always use strict
        mode and fail closed when usage cannot be verified.
        """
        kb_list = (
            get_private_knowledge_info_by_creator(self.tenant_id, user_id)
            if user_id is not None
            else get_private_knowledge_info_by_tenant_id(self.tenant_id)
        )
        storage_stats = self._get_kb_storage_stats(kb_list, strict=strict)
        return {
            "kbs": kb_list,
            "stats": storage_stats["stats"],
            "details": storage_stats["details"],
            "total_bytes": storage_stats["total_bytes"],
        }

    def _aggregate_personal_storage_by_user(
        self,
        usage_data: Dict[str, Any],
        user_ids: Optional[set[str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Aggregate unified personal storage by KB creator."""
        grouped: Dict[str, Dict[str, Any]] = {}
        for kb in usage_data["kbs"]:
            user_id = kb.get("created_by")
            if not user_id or (user_ids is not None and user_id not in user_ids):
                continue
            item = grouped.setdefault(
                user_id,
                {"kbs": [], "kb_count": 0, "total_bytes": 0},
            )
            item["kbs"].append(kb)
            item["kb_count"] += 1
            item["total_bytes"] += usage_data["stats"].get(
                kb.get("index_name", ""), 0
            )

        for user_id in user_ids or set():
            grouped.setdefault(
                user_id,
                {"kbs": [], "kb_count": 0, "total_bytes": 0},
            )

        return grouped

    def _aggregate_personal_usage_by_user(
        self,
        usage_data: Dict[str, Any],
        user_ids: Optional[set[str]] = None,
        default_quota: Any = _UNSET,
        effective_quota_by_user: Optional[
            Dict[str, Tuple[Optional[int], str]]
        ] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Aggregate personal storage and attach effective quotas by creator."""
        grouped = self._aggregate_personal_storage_by_user(usage_data, user_ids)
        if effective_quota_by_user is None:
            effective_quota_by_user, _ = self._get_personal_effective_quota_map(
                set(grouped), default_quota=default_quota
            )
        for user_id, item in grouped.items():
            quota_bytes, quota_source = effective_quota_by_user.get(
                user_id, (None, "unlimited")
            )
            item["effective_quota_bytes"] = quota_bytes
            item["quota_source"] = quota_source
        return grouped

    def list_personal_capacity_users(
        self,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "total_bytes",
        sort_order: str = "desc",
        keyword: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List personal KB storage aggregated by creator with pagination."""
        usage_data = self._get_personal_usage_data()
        user_usage = self._aggregate_personal_usage_by_user(usage_data)
        user_ids = sorted(user_usage)
        email_map = get_user_email_map(user_ids)

        items = []
        for user_id in user_ids:
            user_data = user_usage[user_id]
            quota_limit_bytes = user_data["effective_quota_bytes"]
            quota_source = user_data["quota_source"]
            total_bytes = user_data["total_bytes"]
            items.append({
                "user_id": user_id,
                "user_name": email_map.get(user_id) or user_id,
                "email": email_map.get(user_id),
                "kb_count": user_data["kb_count"],
                "total_bytes": total_bytes,
                "total_readable": _bytes_to_readable(total_bytes),
                "quota_limit_bytes": quota_limit_bytes,
                "quota_limit_readable": _bytes_to_readable(quota_limit_bytes),
                "effective_quota_bytes": quota_limit_bytes,
                "effective_quota_readable": _bytes_to_readable(quota_limit_bytes),
                "quota_source": quota_source,
                "usage_rate": (
                    round(total_bytes / quota_limit_bytes * 100, 2)
                    if quota_limit_bytes and quota_limit_bytes > 0
                    else None
                ),
            })

        if keyword:
            lowered_keyword = keyword.strip().lower()
            if lowered_keyword:
                items = [
                    item
                    for item in items
                    if lowered_keyword
                    in str(item["user_name"]).lower()
                    or lowered_keyword in (item.get("email") or "").lower()
                ]

        sort_keys = {
            "user_name": lambda item: str(item["user_name"]).lower(),
            "kb_count": lambda item: item["kb_count"],
            "total_bytes": lambda item: item["total_bytes"],
            "quota_limit_bytes": lambda item: (
                item["quota_limit_bytes"]
                if item["quota_limit_bytes"] is not None
                else -1
            ),
            "usage_rate": lambda item: (
                item["usage_rate"]
                if item["usage_rate"] is not None
                else -1
            ),
        }
        key_func = sort_keys.get(sort_by, sort_keys["total_bytes"])
        items.sort(key=key_func, reverse=sort_order.lower() != "asc")

        total = len(items)
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        start = (page - 1) * page_size
        paged = items[start : start + page_size] if page_size > 0 else items
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "items": paged,
        }

    def get_personal_kb_details(
        self,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """List a user's personal KB records with unified storage details."""
        usage_data = self._get_personal_usage_data(user_id=user_id)
        kb_list = usage_data["kbs"]
        kb_list.sort(
            key=lambda kb: str(
                kb.get("last_doc_update_time") or kb.get("update_time") or ""
            ),
            reverse=True,
        )

        total = len(kb_list)
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        start = (page - 1) * page_size
        paged = kb_list[start : start + page_size] if page_size > 0 else kb_list

        kbs = []
        for kb in paged:
            index_name = kb.get("index_name", "")
            detail = usage_data["details"].get(index_name, {})
            quota_limit_bytes = kb.get("quota_limit_bytes")
            kbs.append({
                "kb_id": kb.get("knowledge_id"),
                "knowledge_id": kb.get("knowledge_id"),
                "index_name": index_name,
                "name": kb.get("knowledge_name") or index_name,
                "source": kb.get("knowledge_sources"),
                "doc_count": detail.get("doc_count", 0),
                "chunk_count": detail.get("chunk_count", 0),
                "store_size": detail.get("store_size"),
                "store_size_bytes": detail.get("store_size_bytes", 0),
                "source_size": detail.get("source_size"),
                "source_size_bytes": detail.get("source_size_bytes", 0),
                "total_size": detail.get("total_size"),
                "total_size_bytes": detail.get("total_size_bytes", 0),
                "quota_limit_bytes": quota_limit_bytes,
                "quota_limit_readable": _bytes_to_readable(quota_limit_bytes),
                "updated_at": (
                    kb.get("last_doc_update_time") or kb.get("update_time")
                ),
            })

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "kbs": kbs,
        }

    def get_personal_capacity_summary(self) -> Dict[str, Any]:
        """Return aggregate personal KB capacity stats for the tenant."""
        usage_data = self._get_personal_usage_data()
        kb_list = usage_data["kbs"]
        user_ids = {
            kb.get("created_by")
            for kb in kb_list
            if kb.get("created_by")
        }
        effective_quota_by_user, default_quota = (
            self._get_personal_effective_quota_map(user_ids)
        )
        user_usage = self._aggregate_personal_usage_by_user(
            usage_data,
            effective_quota_by_user=effective_quota_by_user,
        )
        allocated_quota_bytes = 0
        for user_data in user_usage.values():
            quota_limit_bytes = user_data["effective_quota_bytes"]
            if quota_limit_bytes is not None:
                allocated_quota_bytes += quota_limit_bytes

        return {
            "user_count": len(user_usage),
            "kb_count": len(kb_list),
            "total_bytes": usage_data["total_bytes"],
            "total_readable": _bytes_to_readable(usage_data["total_bytes"]),
            "allocated_quota_bytes": allocated_quota_bytes,
            "allocated_quota_readable": _bytes_to_readable(
                allocated_quota_bytes
            ),
            "default_quota_bytes": default_quota,
            "default_quota_readable": _bytes_to_readable(default_quota),
        }

    def get_pending_personal_upload_bytes(
        self,
        data: List[Dict[str, Any]],
        kb_record: Optional[Dict[str, Any]],
    ) -> int:
        """Calculate unique source bytes not yet committed to the storage ledger."""
        if not kb_record:
            return 0

        source_sizes: Dict[str, int] = {}
        for item in data or []:
            if not isinstance(item, dict):
                continue
            source = str(
                item.get("path_or_url") or item.get("filename") or ""
            ).strip()
            if not source:
                continue
            try:
                file_size = int(item.get("file_size"))
            except (TypeError, ValueError):
                continue
            if file_size > 0:
                source_sizes[source] = max(source_sizes.get(source, 0), file_size)

        if not source_sizes:
            return 0

        try:
            knowledge_id = int(kb_record.get("knowledge_id"))
        except (TypeError, ValueError):
            return sum(source_sizes.values())

        committed_sizes = get_committed_source_bytes_by_paths(
            tenant_id=self.tenant_id,
            knowledge_id=knowledge_id,
            paths=source_sizes,
        )
        return sum(
            file_size
            for source, file_size in source_sizes.items()
            if source not in committed_sizes
        )

    def _check_personal_user_quota_from_usage(
        self,
        usage_data: Dict[str, Any],
        user_id: str,
        upload_bytes: int,
    ) -> None:
        """Check only the effective user-level personal KB quota."""
        user_usage = self._aggregate_personal_storage_by_user(
            usage_data, user_ids={user_id}
        ).get(user_id, {"total_bytes": 0})
        user_usage_bytes = user_usage["total_bytes"]
        effective_quota, quota_source = self._get_personal_effective_quota(user_id)
        if effective_quota is None:
            return
        if effective_quota <= 0:
            if upload_bytes > 0:
                raise AppException(
                    ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED,
                    f"Personal KB quota is disabled (0 bytes) for user {user_id}",
                )
            return
        if user_usage_bytes + upload_bytes > effective_quota:
            raise AppException(
                ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED,
                f"Personal KB quota exceeded: "
                f"{_bytes_to_readable(user_usage_bytes + upload_bytes)} exceeds "
                f"{quota_source} quota of {_bytes_to_readable(effective_quota)}",
            )

    def _check_personal_kb_quota_from_usage(
        self,
        usage_data: Dict[str, Any],
        upload_bytes: int,
        kb_record: Optional[Dict[str, Any]],
    ) -> None:
        """Enforce a PRIVATE KB's own quota during indexing."""
        if not kb_record:
            return

        kb_quota = self._parse_quota_value(kb_record.get("quota_limit_bytes"))
        if kb_quota is None:
            return

        index_name = kb_record.get("index_name", "")
        kb_usage_bytes = usage_data["stats"].get(index_name, 0)
        projected_bytes = kb_usage_bytes + upload_bytes
        if kb_quota <= 0:
            if upload_bytes > 0:
                raise AppException(
                    ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED,
                    f"KB quota is disabled (0 bytes) for {index_name}",
                )
            return
        if projected_bytes > kb_quota:
            raise AppException(
                ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED,
                f"KB quota exceeded for {index_name}: "
                f"{_bytes_to_readable(projected_bytes)} exceeds "
                f"{_bytes_to_readable(kb_quota)}",
            )

    def check_personal_user_quota(
        self,
        user_id: str,
        upload_bytes: int,
    ) -> None:
        """Enforce only the user-level quota before a PRIVATE KB upload."""
        usage_data = self._get_personal_usage_data(strict=True, user_id=user_id)
        self._check_personal_user_quota_from_usage(usage_data, user_id, upload_bytes)

    def check_personal_kb_quota(
        self,
        user_id: str,
        upload_bytes: int,
        kb_record: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Enforce tenant, user, and PRIVATE-KB quotas before indexing.

        Raises AppException with a personal quota ErrorCode when a finite quota
        would be exceeded or ES usage cannot be verified. Shared-KB quota checks
        remain in the existing advisory path; this method is only used for
        PRIVATE KBs.
        """
        usage_data = self._get_personal_usage_data(strict=True)
        total_tenant_bytes = usage_data["total_bytes"]

        hard_limit_bytes = self.get_hard_limit().get("hard_limit_bytes")
        if hard_limit_bytes is not None:
            projected_bytes = total_tenant_bytes + upload_bytes
            if projected_bytes > hard_limit_bytes:
                raise AppException(
                    ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED,
                    f"Tenant personal KB storage full: "
                    f"{_bytes_to_readable(projected_bytes)} exceeds hard limit of "
                    f"{_bytes_to_readable(hard_limit_bytes)}",
                )

        self._check_personal_user_quota_from_usage(usage_data, user_id, upload_bytes)
        self._check_personal_kb_quota_from_usage(
            usage_data,
            upload_bytes,
            kb_record,
        )

    def get_quota_summary(self) -> Dict[str, Any]:
        """Return quota allocation summary with oversubscription ratio."""
        hard_limit = self.get_hard_limit()
        kb_quotas = self.get_all_kb_quotas()

        soft_allocated = sum(
            q["quota_limit_bytes"] for q in kb_quotas if q["quota_limit_bytes"] is not None
        )
        kbs_with_quota = sum(1 for q in kb_quotas if q["quota_limit_bytes"] is not None)
        kb_count = len(kb_quotas)

        oversubscription_ratio = None
        if hard_limit.get("hard_limit_bytes") and hard_limit["hard_limit_bytes"] > 0:
            oversubscription_ratio = round(
                soft_allocated / hard_limit["hard_limit_bytes"], 4
            )

        return {
            "soft_allocated_total_bytes": soft_allocated,
            "soft_allocated_readable": _bytes_to_readable(soft_allocated),
            "hard_limit_bytes": hard_limit.get("hard_limit_bytes"),
            "hard_limit_readable": hard_limit.get("hard_limit_readable"),
            "total_bytes": None,  # filled in when usage is available
            "total_readable": None,
            "oversubscription_ratio": oversubscription_ratio,
            "kb_count": kb_count,
            "kbs_with_quota": kbs_with_quota,
        }

    # ── Warning Level Computation (task 3.3) ───────────────────────────

    @staticmethod
    def _compute_kb_warning_level(
        usage_pct: Optional[float],
        warning_threshold: int = DEFAULT_WARNING_THRESHOLD,
        critical_threshold: int = DEFAULT_CRITICAL_THRESHOLD,
    ) -> str:
        """Compute KB-level warning: normal, warning, critical, exceeded.
        Uses tenant-configured thresholds for consistency."""
        if usage_pct is None:
            return "normal"
        if usage_pct >= 100:
            return "exceeded"
        if usage_pct >= critical_threshold:
            return "critical"
        if usage_pct >= warning_threshold:
            return "warning"
        return "normal"

    @staticmethod
    def _compute_tenant_warning_level(
        usage_pct: Optional[float],
        critical_threshold: int = DEFAULT_CRITICAL_THRESHOLD,
        warning_threshold: int = DEFAULT_WARNING_THRESHOLD,
    ) -> str:
        """Compute tenant-level warning: normal, warning, critical, blocked."""
        if usage_pct is None:
            return "normal"
        if usage_pct >= 100:
            return "blocked"
        if usage_pct >= critical_threshold:
            return "critical"
        if usage_pct >= warning_threshold:
            return "warning"
        return "normal"

    # ── Usage Tracking (tasks 3.1–3.4) ─────────────────────────────────

    def get_usage(
        self,
        force_refresh: bool = False,
        detail: bool = False,
    ) -> Dict[str, Any]:
        """
        Aggregate storage usage across all tenant KBs from MinIO/ES.
        Results are cached with 60s TTL. force_refresh bypasses cache.
        """
        cache_key = self.tenant_id

        # Check cache
        now = time.time()
        if not force_refresh and cache_key in _usage_cache:
            cached_time, cached_data = _usage_cache[cache_key]
            if now - cached_time < CACHE_TTL_SECONDS:
                if not detail:
                    # Return without breakdown for non-detail requests
                    result = dict(cached_data)
                    result.pop("breakdown", None)
                    return result
                return dict(cached_data)

        # Compute usage by querying file sizes from MinIO/ES
        usage_data = self._compute_usage()
        _usage_cache[cache_key] = (now, dict(usage_data))

        if not detail:
            result = dict(usage_data)
            result.pop("breakdown", None)
            return result
        return dict(usage_data)

    def _compute_usage(self) -> Dict[str, Any]:
        """
        Compute actual storage usage by summing file sizes across all tenant KBs.
        Uses the unified ES index stats plus committed source-storage ledger bytes.
        """
        kb_list = get_knowledge_info_by_tenant_id(self.tenant_id)
        warning_config = self.get_warning_config()
        tenant_warning_threshold = warning_config["warning_threshold_pct"]
        tenant_critical_threshold = warning_config["critical_threshold_pct"]
        hard_limit_info = self.get_hard_limit()

        # Quota enforcement must always use every KB in the tenant, regardless
        # of the requesting user's KB visibility.
        storage_stats = self._get_kb_storage_stats(
            kb_list,
            exclude_datamate=True,
        )
        stats_lookup = {
            name: {
                "bytes": detail["store_size_bytes"],
                "source_bytes": detail["source_size_bytes"],
                "total_bytes": detail["total_size_bytes"],
                "file_count": detail["doc_count"],
            }
            for name, detail in storage_stats["details"].items()
        }
        tenant_minio_bytes = get_tenant_committed_source_bytes(self.tenant_id)

        breakdown = []
        total_es_bytes = storage_stats["total_es_bytes"]
        total_files = 0

        for kb in kb_list:
            index_name = kb.get("index_name", "")
            kb_id = kb.get("knowledge_id")
            kb_name = kb.get("knowledge_name", index_name)
            soft_quota_bytes = kb.get("quota_limit_bytes")

            kb_stats = stats_lookup.get(index_name, {})
            kb_actual_bytes = kb_stats.get("total_bytes", 0)
            kb_file_count = kb_stats.get("file_count", 0)

            total_files += kb_file_count

            # Compute KB-level warning
            kb_usage_pct = None
            if soft_quota_bytes and soft_quota_bytes > 0:
                kb_usage_pct = round(kb_actual_bytes / soft_quota_bytes * 100, 2)
            kb_warning_level = self._compute_kb_warning_level(
                kb_usage_pct,
                warning_threshold=tenant_warning_threshold,
                critical_threshold=tenant_critical_threshold,
            )

            breakdown.append({
                "knowledge_id": kb_id,
                "knowledge_name": kb_name,
                "index_name": index_name,
                "soft_quota_bytes": soft_quota_bytes,
                "soft_quota_readable": _bytes_to_readable(soft_quota_bytes),
                "actual_bytes": kb_actual_bytes,
                "actual_readable": _bytes_to_readable(kb_actual_bytes),
                "usage_pct": kb_usage_pct,
                "file_count": kb_file_count,
                "kb_warning_level": kb_warning_level,
            })

        # Tenant totals include all active tenant ledger rows, including rows whose
        # KB is no longer returned in the active KB list. This avoids silently
        # dropping retained source objects from the tenant hard-limit calculation.
        total_bytes = total_es_bytes + tenant_minio_bytes

        # Compute tenant-level warning
        hard_limit_bytes = hard_limit_info.get("hard_limit_bytes")
        tenant_usage_pct = None
        if hard_limit_bytes and hard_limit_bytes > 0:
            tenant_usage_pct = round(total_bytes / hard_limit_bytes * 100, 2)
        tenant_warning_level = self._compute_tenant_warning_level(
            tenant_usage_pct,
            warning_config["critical_threshold_pct"],
            warning_config["warning_threshold_pct"],
        )

        available_bytes = None
        if hard_limit_bytes:
            available_bytes = max(0, hard_limit_bytes - total_bytes)

        result = {
            "total_bytes": total_bytes,
            "total_readable": _bytes_to_readable(total_bytes),
            "kb_count": len(kb_list),
            "file_count": total_files,
            "hard_limit_bytes": hard_limit_bytes,
            "hard_limit_readable": hard_limit_info.get("hard_limit_readable"),
            "available_bytes": available_bytes,
            "available_readable": _bytes_to_readable(available_bytes),
            "usage_pct": tenant_usage_pct,
            "tenant_warning_level": tenant_warning_level,
            "warning_enabled": warning_config["warning_enabled"],
            "warning_threshold_pct": warning_config["warning_threshold_pct"],
            "critical_threshold_pct": warning_config["critical_threshold_pct"],
            "breakdown": breakdown,
        }

        # Add summary when detail is provided
        summary = self.get_quota_summary()
        result["soft_allocated_total_bytes"] = summary["soft_allocated_total_bytes"]
        result["soft_allocated_readable"] = summary["soft_allocated_readable"]
        result["oversubscription_ratio"] = summary["oversubscription_ratio"]
        result["kbs_with_quota"] = summary["kbs_with_quota"]

        return result

    @staticmethod
    def _parse_store_size(size_str: Any) -> int:
        """Parse store_size string like '1.5 GB' or '500 MB' into bytes."""
        if size_str is None:
            return 0
        if isinstance(size_str, (int, float)):
            return int(size_str)
        if not isinstance(size_str, str) or not size_str.strip():
            return 0
        try:
            parts = size_str.strip().split()
            if len(parts) != 2:
                return 0
            value = float(parts[0])
            unit = parts[1].upper()
            if unit == "GB":
                return int(value * GB)
            elif unit == "MB":
                return int(value * 1024 * 1024)
            elif unit == "KB":
                return int(value * 1024)
            elif unit == "B":
                return int(value)
            return 0
        except (ValueError, IndexError):
            return 0

    # ── Quota Enforcement (tasks 4.1) ──────────────────────────────────

    def check_hard_limit(
        self,
        file_size_bytes: int,
        index_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Check if adding file_size_bytes would exceed the tenant hard limit.
        Returns quota_status dict if OK, raises QuotaExceededError if exceeded.
        """
        hard_limit_info = self.get_hard_limit()
        hard_limit_bytes = hard_limit_info.get("hard_limit_bytes")

        # No hard limit set = unlimited, always OK
        if hard_limit_bytes is None:
            return self._build_quota_status(index_name)

        usage = self.get_usage(force_refresh=True)
        current_bytes = usage.get("total_bytes", 0)
        projected_bytes = current_bytes + file_size_bytes

        if projected_bytes > hard_limit_bytes:
            raise QuotaExceededError(
                f"Tenant storage full: {_bytes_to_readable(projected_bytes)} exceeds "
                f"hard limit of {_bytes_to_readable(hard_limit_bytes)}",
                usage_bytes=current_bytes,
                hard_limit_bytes=hard_limit_bytes,
                exceeded_by_bytes=projected_bytes - hard_limit_bytes,
            )

        return self._build_quota_status(index_name)

    def check_hard_limit_post_write(
        self,
        file_size_bytes: int,
        index_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Post-write belt-and-suspenders check.
        Returns quota_status if OK, raises QuotaExceededError if exceeded.
        Called after MinIO write to handle race conditions.
        """
        hard_limit_info = self.get_hard_limit()
        hard_limit_bytes = hard_limit_info.get("hard_limit_bytes")

        if hard_limit_bytes is None:
            return self._build_quota_status(index_name)

        # Force refresh to get accurate post-write state
        usage = self.get_usage(force_refresh=True)
        if usage.get("total_bytes", 0) > hard_limit_bytes:
            raise QuotaExceededError(
                f"Tenant storage limit exceeded after write",
                usage_bytes=usage["total_bytes"],
                hard_limit_bytes=hard_limit_bytes,
                exceeded_by_bytes=usage["total_bytes"] - hard_limit_bytes,
            )

        return self._build_quota_status(index_name)

    def _build_quota_status(self, index_name: Optional[str] = None) -> Dict[str, Any]:
        """Build dual-level quota status for upload responses."""
        usage = self.get_usage(force_refresh=True, detail=True)
        hard_limit_info = self.get_hard_limit()

        # Tenant-level status
        hard_limit_bytes = hard_limit_info.get("hard_limit_bytes")
        tenant_usage_pct = usage.get("usage_pct")
        tenant_warning_level = usage.get("tenant_warning_level", "normal")
        kb_usage_pct = None
        kb_warning_level = "normal"
        if index_name:
            kb_status = next(
                (
                    item
                    for item in usage.get("breakdown", [])
                    if item.get("index_name") == index_name
                ),
                None,
            )
            if kb_status:
                kb_usage_pct = kb_status.get("usage_pct")
                kb_warning_level = kb_status.get("kb_warning_level", "normal")

        return {
            "quota_status": {
                "warning_enabled": usage.get("warning_enabled", True),
                "tenant_level": {
                    "usage_pct": tenant_usage_pct,
                    "warning_level": tenant_warning_level,
                    "hard_limit_bytes": hard_limit_bytes,
                    "hard_limit_readable": hard_limit_info.get("hard_limit_readable"),
                    "total_bytes": usage.get("total_bytes"),
                    "total_readable": usage.get("total_readable"),
                },
                "kb_level": {
                    "usage_pct": kb_usage_pct,
                    "warning_level": kb_warning_level,
                },
            }
        }

    # ── Platform-Level Methods (tasks 9.1–9.3) ─────────────────────────

    @staticmethod
    def _quota_input_to_bytes(limit_gb: Optional[int], limit_mb: Optional[int]) -> int:
        """Convert an API quota value to bytes."""
        if limit_mb is not None:
            return _mb_to_bytes(int(limit_mb))
        return _gb_to_bytes(int(limit_gb))

    @staticmethod
    def _get_allocation_state(asset_owner_tenant_id: str) -> Dict[str, Any]:
        """Return finite tenant allocations and unmanaged tenant count."""
        from database.tenant_config_db import get_all_tenant_ids, get_single_config_info

        tenant_ids = [
            tenant_id
            for tenant_id in get_all_tenant_ids()
            if _is_displayable_tenant_id(tenant_id, asset_owner_tenant_id)
        ]
        hard_limits: Dict[str, Optional[int]] = {}
        total_allocated_bytes = 0
        unmanaged_tenant_count = 0
        for tenant_id in tenant_ids:
            record = get_single_config_info(tenant_id, KEY_TENANT_HARD_LIMIT_BYTES)
            try:
                hard_limit_bytes = int(record["config_value"]) if record and record.get("config_value") else None
            except (TypeError, ValueError):
                hard_limit_bytes = None
            hard_limits[tenant_id] = hard_limit_bytes
            if hard_limit_bytes is None:
                unmanaged_tenant_count += 1
            else:
                total_allocated_bytes += hard_limit_bytes
        return {
            "tenant_ids": tenant_ids,
            "hard_limits": hard_limits,
            "total_allocated_bytes": total_allocated_bytes,
            "unmanaged_tenant_count": unmanaged_tenant_count,
        }

    def _validate_tenant_hard_limit(
        self,
        limit_bytes: int,
        asset_owner_tenant_id: str = ASSET_OWNER_TENANT_ID,
    ) -> None:
        """Validate a finite tenant quota against usage and platform allocation."""
        usage = self.get_usage(force_refresh=True)
        actual_bytes = usage.get("total_bytes", 0)
        if limit_bytes < actual_bytes:
            raise PlatformQuotaConflictError(
                "Tenant hard quota cannot be lower than current usage",
                "TenantQuotaBelowUsage",
                {
                    "tenant_id": self.tenant_id,
                    "requested_limit_bytes": limit_bytes,
                    "requested_limit_readable": _bytes_to_readable(limit_bytes),
                    "actual_usage_bytes": actual_bytes,
                    "actual_usage_readable": _bytes_to_readable(actual_bytes),
                },
            )

        capacity_bytes = QuotaService.get_platform_capacity(asset_owner_tenant_id).get("capacity_bytes")
        if capacity_bytes is None:
            return

        allocation_state = QuotaService._get_allocation_state(asset_owner_tenant_id)
        current_limit_bytes = allocation_state["hard_limits"].get(self.tenant_id) or 0
        proposed_total_bytes = allocation_state["total_allocated_bytes"] - current_limit_bytes + limit_bytes
        if proposed_total_bytes > capacity_bytes:
            raise PlatformQuotaConflictError(
                "Tenant hard quota exceeds remaining platform capacity",
                "PlatformCapacityExceeded",
                {
                    "tenant_id": self.tenant_id,
                    "requested_limit_bytes": limit_bytes,
                    "requested_limit_readable": _bytes_to_readable(limit_bytes),
                    "platform_capacity_bytes": capacity_bytes,
                    "platform_capacity_readable": _bytes_to_readable(capacity_bytes),
                    "total_allocated_bytes": allocation_state["total_allocated_bytes"],
                    "total_allocated_readable": _bytes_to_readable(allocation_state["total_allocated_bytes"]),
                    "remaining_allocatable_bytes": max(capacity_bytes - allocation_state["total_allocated_bytes"], 0),
                    "remaining_allocatable_readable": _bytes_to_readable(
                        max(capacity_bytes - allocation_state["total_allocated_bytes"], 0)
                    ),
                },
            )

    @staticmethod
    def get_platform_capacity(asset_owner_tenant_id: str = ASSET_OWNER_TENANT_ID) -> Dict[str, Any]:
        """Get platform-level declared storage capacity."""
        from database.tenant_config_db import get_single_config_info
        record = get_single_config_info(asset_owner_tenant_id, KEY_PLATFORM_CAPACITY_BYTES)
        raw = record.get("config_value") if record else None

        if raw is not None:
            try:
                capacity_bytes = int(raw)
                return {
                    "capacity_bytes": capacity_bytes,
                    "capacity_readable": _bytes_to_readable(capacity_bytes),
                }
            except (ValueError, TypeError):
                pass

        return {"capacity_bytes": None, "capacity_readable": None}

    @staticmethod
    def set_platform_capacity(
        capacity_gb: Optional[int],
        asset_owner_tenant_id: str = ASSET_OWNER_TENANT_ID,
        user_id: str = "system",
    ) -> Dict[str, Any]:
        """Set platform-level declared storage capacity. None = no tracking."""
        service = QuotaService(asset_owner_tenant_id, user_id)
        if capacity_gb is None:
            service._delete_tenant_config(KEY_PLATFORM_CAPACITY_BYTES)
            return {"capacity_bytes": None, "capacity_readable": None}

        capacity_bytes = _gb_to_bytes(int(capacity_gb))
        with _platform_allocation_lock:
            allocation_state = QuotaService._get_allocation_state(asset_owner_tenant_id)
            allocated_bytes = allocation_state["total_allocated_bytes"]
            if capacity_bytes < allocated_bytes:
                raise PlatformQuotaConflictError(
                    "Platform capacity cannot be lower than existing tenant allocations",
                    "PlatformCapacityBelowAllocation",
                    {
                        "requested_capacity_bytes": capacity_bytes,
                        "requested_capacity_readable": _bytes_to_readable(capacity_bytes),
                        "total_allocated_bytes": allocated_bytes,
                        "total_allocated_readable": _bytes_to_readable(allocated_bytes),
                    },
                )
            service._set_tenant_config(KEY_PLATFORM_CAPACITY_BYTES, str(capacity_bytes))
        return {
            "capacity_bytes": capacity_bytes,
            "capacity_readable": _bytes_to_readable(capacity_bytes),
        }

    @staticmethod
    def get_platform_overview(
        asset_owner_tenant_id: str = ASSET_OWNER_TENANT_ID,
    ) -> Dict[str, Any]:
        """
        Aggregate all tenants' hard limits and actual usage.
        Returns per-tenant breakdown + platform totals.
        """
        capacity_info = QuotaService.get_platform_capacity(asset_owner_tenant_id)

        allocation_state = QuotaService._get_allocation_state(asset_owner_tenant_id)
        tenant_ids = allocation_state["tenant_ids"]

        tenants = []
        total_allocated_bytes = 0
        total_actual_bytes = 0

        for tid in tenant_ids:
            # Get hard limit for this tenant
            hard_limit_bytes = allocation_state["hard_limits"].get(tid)
            if hard_limit_bytes is not None:
                total_allocated_bytes += hard_limit_bytes

            # Get actual usage for this tenant
            service = QuotaService(tid)
            try:
                usage = service.get_usage(force_refresh=True)
                actual_bytes = usage.get("total_bytes", 0)
                warning_enabled = usage.get("warning_enabled", True)
                warning_level = (
                    usage.get("tenant_warning_level", "normal")
                    if warning_enabled
                    else "normal"
                )
            except Exception:
                logger.warning("Failed to get usage for tenant %s", tid, exc_info=True)
                actual_bytes = 0
                warning_enabled = False
                warning_level = "normal"

            total_actual_bytes += actual_bytes

            usage_pct = None
            if hard_limit_bytes and hard_limit_bytes > 0:
                usage_pct = round(actual_bytes / hard_limit_bytes * 100, 2)

            # Try to get tenant name from config
            from database.tenant_config_db import get_single_config_info as gsci
            from consts.const import TENANT_NAME
            name_record = gsci(tid, TENANT_NAME)
            tenant_name = name_record.get("config_value") if name_record else tid

            tenants.append({
                "tenant_id": tid,
                "tenant_name": tenant_name or tid,
                "hard_limit_bytes": hard_limit_bytes,
                "hard_limit_readable": _bytes_to_readable(hard_limit_bytes),
                "actual_bytes": actual_bytes,
                "actual_readable": _bytes_to_readable(actual_bytes),
                "usage_pct": usage_pct,
                "warning_level": warning_level,
                "warning_enabled": warning_enabled,
            })

        platform_capacity = capacity_info.get("capacity_bytes")
        oversubscription_ratio = None
        remaining_allocatable_bytes = None
        allocation_percentage = None
        if platform_capacity is not None:
            remaining_allocatable_bytes = max(platform_capacity - total_allocated_bytes, 0)
            if platform_capacity > 0:
                oversubscription_ratio = round(total_allocated_bytes / platform_capacity, 4)
                allocation_percentage = round(total_allocated_bytes / platform_capacity * 100, 2)
            elif total_allocated_bytes == 0:
                allocation_percentage = 0

        return {
            "platform_capacity_bytes": platform_capacity,
            "platform_capacity_readable": capacity_info.get("capacity_readable"),
            "tenants": tenants,
            "total_allocated_bytes": total_allocated_bytes,
            "total_allocated_readable": _bytes_to_readable(total_allocated_bytes),
            "total_actual_bytes": total_actual_bytes,
            "total_actual_readable": _bytes_to_readable(total_actual_bytes),
            "tenant_count": len(tenants),
            "oversubscription_ratio": oversubscription_ratio,
            "remaining_allocatable_bytes": remaining_allocatable_bytes,
            "remaining_allocatable_readable": _bytes_to_readable(remaining_allocatable_bytes),
            "allocation_percentage": allocation_percentage,
            "unmanaged_tenant_count": allocation_state["unmanaged_tenant_count"],
            "capacity_management_enforced": (
                platform_capacity is not None and allocation_state["unmanaged_tenant_count"] == 0
            ),
        }

    @staticmethod
    def set_tenant_hard_limit(
        tenant_id: str,
        limit_gb: Optional[int] = None,
        limit_mb: Optional[int] = None,
        su_user_id: str = "system",
    ) -> Dict[str, Any]:
        """
        SU sets a hard quota on a target tenant. Accepts limit_gb or limit_mb.
        Sets hard_limit_editable = false so the tenant admin cannot modify it.
        """
        service = QuotaService(tenant_id, su_user_id)
        if limit_gb is None and limit_mb is None:
            service._delete_tenant_config(KEY_TENANT_HARD_LIMIT_BYTES)
            service._delete_tenant_config(KEY_HARD_LIMIT_EDITABLE)
            return {"hard_limit_bytes": None, "hard_limit_readable": None}

        limit_bytes = QuotaService._quota_input_to_bytes(limit_gb, limit_mb)
        with _platform_allocation_lock:
            service._validate_tenant_hard_limit(limit_bytes)
            service._set_tenant_config(KEY_TENANT_HARD_LIMIT_BYTES, str(limit_bytes))
            # Mark as SU-managed (not editable by tenant admin)
            service._set_tenant_config(KEY_HARD_LIMIT_EDITABLE, "false")
        return {
            "hard_limit_bytes": limit_bytes,
            "hard_limit_readable": _bytes_to_readable(limit_bytes),
        }

    @staticmethod
    def delete_tenant_hard_limit(
        tenant_id: str,
        su_user_id: str = "system",
    ) -> bool:
        """SU removes a tenant's hard quota."""
        service = QuotaService(tenant_id, su_user_id)
        service._delete_tenant_config(KEY_TENANT_HARD_LIMIT_BYTES)
        service._delete_tenant_config(KEY_HARD_LIMIT_EDITABLE)
        return True
