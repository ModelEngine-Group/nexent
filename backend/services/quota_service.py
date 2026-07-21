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

from consts.const import ASSET_OWNER_TENANT_ID
from consts.exceptions import PlatformQuotaConflictError, QuotaExceededError
from database.knowledge_db import (
    get_knowledge_info_by_tenant_id,
    update_knowledge_record,
)
from database.tenant_config_db import (
    delete_config_by_tenant_config_id,
    get_single_config_info,
    insert_config,
    update_config_by_tenant_config_id,
)

logger = logging.getLogger(__name__)

# Tenant config keys
KEY_TENANT_HARD_LIMIT_BYTES = "KB_QUOTA_TENANT_HARD_LIMIT_BYTES"
KEY_WARNING_ENABLED = "KB_QUOTA_WARNING_ENABLED"
KEY_WARNING_THRESHOLD_PCT = "KB_QUOTA_WARNING_THRESHOLD_PCT"
KEY_CRITICAL_THRESHOLD_PCT = "KB_QUOTA_CRITICAL_THRESHOLD_PCT"
KEY_HARD_LIMIT_EDITABLE = "KB_QUOTA_HARD_LIMIT_EDITABLE"
KEY_PLATFORM_CAPACITY_BYTES = "PLATFORM_KB_STORAGE_CAPACITY_BYTES"

# Constants
GB = 1024 * 1024 * 1024
CACHE_TTL_SECONDS = 60
DEFAULT_WARNING_THRESHOLD = 80
DEFAULT_CRITICAL_THRESHOLD = 95

# In-memory cache for usage data
_usage_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

# Config helpers use independent database sessions, so serialize allocation
# validation and writes within a config-service process.
_platform_allocation_lock = threading.RLock()


def _bytes_to_readable(size_bytes: Optional[int]) -> Optional[str]:
    """Convert bytes to human-readable string (e.g. '10 GB')."""
    if size_bytes is None:
        return None
    if size_bytes >= GB:
        return f"{size_bytes / GB:.1f} GB"
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


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
        Uses the existing ES index stats (store_size) from the vectordatabase service.
        """
        from services.vectordatabase_service import get_vector_db_core

        kb_list = get_knowledge_info_by_tenant_id(self.tenant_id)
        warning_config = self.get_warning_config()
        tenant_warning_threshold = warning_config["warning_threshold_pct"]
        tenant_critical_threshold = warning_config["critical_threshold_pct"]
        hard_limit_info = self.get_hard_limit()

        # Quota enforcement must always use every KB in the tenant, regardless
        # of the requesting user's KB visibility.
        try:
            vdb_core = get_vector_db_core()
            index_names = [
                kb.get("index_name")
                for kb in kb_list
                if kb.get("index_name")
                and kb.get("knowledge_sources") != "datamate"
            ]
            indices_detail = (
                vdb_core.get_indices_detail(index_names) if index_names else {}
            )
        except Exception:
            logger.warning("Failed to query ES indices for usage data", exc_info=True)
            indices_detail = {}

        # Build lookup: index_name -> {store_size_bytes, file_count}
        stats_lookup = {}
        for name, stats in indices_detail.items():
            stats = stats if isinstance(stats, dict) else {}
            base_info = stats.get("base_info", {}) if isinstance(stats, dict) else {}
            store_size_raw = base_info.get("store_size", "0")
            # Parse store_size string like "1.5 GB" or "500 MB" into bytes
            store_bytes = self._parse_store_size(store_size_raw)
            doc_count = base_info.get("doc_count", 0) or 0
            stats_lookup[name] = {"bytes": store_bytes, "file_count": doc_count}

        breakdown = []
        total_bytes = 0
        total_files = 0

        for kb in kb_list:
            index_name = kb.get("index_name", "")
            kb_id = kb.get("knowledge_id")
            kb_name = kb.get("knowledge_name", index_name)
            soft_quota_bytes = kb.get("quota_limit_bytes")

            kb_stats = stats_lookup.get(index_name, {})
            kb_actual_bytes = kb_stats.get("bytes", 0)
            kb_file_count = kb_stats.get("file_count", 0)

            total_bytes += kb_actual_bytes
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
            if tenant_id != asset_owner_tenant_id
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
