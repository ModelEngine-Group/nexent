# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from management.services.knowledge_base.quota_common import (
    _UNSET,
    ASSET_OWNER_TENANT_ID,
    CACHE_TTL_SECONDS,
    DEFAULT_CRITICAL_THRESHOLD,
    DEFAULT_TENANT_ID,
    DEFAULT_WARNING_THRESHOLD,
    GB,
    KEY_CRITICAL_THRESHOLD_PCT,
    KEY_HARD_LIMIT_EDITABLE,
    KEY_PERSONAL_KB_QUOTA_DEFAULT,
    KEY_PLATFORM_CAPACITY_BYTES,
    KEY_TENANT_HARD_LIMIT_BYTES,
    KEY_WARNING_ENABLED,
    KEY_WARNING_THRESHOLD_PCT,
    MB,
    Any,
    AppException,
    Dict,
    ErrorCode,
    List,
    Optional,
    PlatformQuotaConflictError,
    QuotaExceededError,
    Tuple,
    _bytes_to_readable,
    _gb_to_bytes,
    _is_displayable_tenant_id,
    _mb_to_bytes,
    _personal_quota_key,
    _platform_allocation_lock,
    _usage_cache,
    bytes_to_readable,
    delete_config_by_tenant_config_id,
    get_committed_bytes_by_kb,
    get_committed_source_bytes_by_paths,
    get_configs_by_tenant_id_and_keys,
    get_knowledge_info_by_tenant_id,
    get_private_knowledge_info_by_creator,
    get_private_knowledge_info_by_tenant_id,
    get_single_config_info,
    get_tenant_committed_source_bytes,
    get_user_email_map,
    insert_config,
    logger,
    logging,
    threading,
    time,
    update_config_by_tenant_config_id,
    update_knowledge_record,
)


class PlatformCapacityPolicy:
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
                    "es_physical_bytes": usage.get("es_physical_bytes"),
                    "es_physical_readable": usage.get("es_physical_readable"),
                },
                "kb_level": {
                    "usage_pct": kb_usage_pct,
                    "warning_level": kb_warning_level,
                },
            }
        }

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
                hard_limit_bytes = (
                    int(record["config_value"])
                    if record and record.get("config_value")
                    else None
                )
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
        from management.services.knowledge_base.quota import QuotaService

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

        capacity_bytes = QuotaService.get_platform_capacity(asset_owner_tenant_id).get(
            "capacity_bytes"
        )
        if capacity_bytes is None:
            return

        allocation_state = QuotaService._get_allocation_state(asset_owner_tenant_id)
        current_limit_bytes = allocation_state["hard_limits"].get(self.tenant_id) or 0
        proposed_total_bytes = (
            allocation_state["total_allocated_bytes"]
            - current_limit_bytes
            + limit_bytes
        )
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
                    "total_allocated_readable": _bytes_to_readable(
                        allocation_state["total_allocated_bytes"]
                    ),
                    "remaining_allocatable_bytes": max(
                        capacity_bytes - allocation_state["total_allocated_bytes"], 0
                    ),
                    "remaining_allocatable_readable": _bytes_to_readable(
                        max(
                            capacity_bytes - allocation_state["total_allocated_bytes"],
                            0,
                        )
                    ),
                },
            )

    @staticmethod
    def get_platform_capacity(
        asset_owner_tenant_id: str = ASSET_OWNER_TENANT_ID,
    ) -> Dict[str, Any]:
        """Get platform-level declared storage capacity."""
        from database.tenant_config_db import get_single_config_info

        record = get_single_config_info(
            asset_owner_tenant_id, KEY_PLATFORM_CAPACITY_BYTES
        )
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
        from management.services.knowledge_base.quota import QuotaService

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
                        "requested_capacity_readable": _bytes_to_readable(
                            capacity_bytes
                        ),
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
        from management.services.knowledge_base.quota import QuotaService

        capacity_info = QuotaService.get_platform_capacity(asset_owner_tenant_id)

        allocation_state = QuotaService._get_allocation_state(asset_owner_tenant_id)
        tenant_ids = allocation_state["tenant_ids"]

        tenants = []
        total_allocated_bytes = 0
        total_actual_bytes = 0
        total_es_physical_bytes = 0

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
                tenant_es_bytes = usage.get("es_physical_bytes", 0) or 0
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
                tenant_es_bytes = 0

            total_actual_bytes += actual_bytes
            total_es_physical_bytes += tenant_es_bytes

            usage_pct = None
            if hard_limit_bytes and hard_limit_bytes > 0:
                usage_pct = round(actual_bytes / hard_limit_bytes * 100, 2)

            # Try to get tenant name from config
            from consts.const import TENANT_NAME
            from database.tenant_config_db import get_single_config_info as gsci

            name_record = gsci(tid, TENANT_NAME)
            tenant_name = name_record.get("config_value") if name_record else tid

            tenants.append(
                {
                    "tenant_id": tid,
                    "tenant_name": tenant_name or tid,
                    "hard_limit_bytes": hard_limit_bytes,
                    "hard_limit_readable": _bytes_to_readable(hard_limit_bytes),
                    "actual_bytes": actual_bytes,
                    "actual_readable": _bytes_to_readable(actual_bytes),
                    "es_physical_bytes": tenant_es_bytes,
                    "es_physical_readable": _bytes_to_readable(tenant_es_bytes),
                    "usage_pct": usage_pct,
                    "warning_level": warning_level,
                    "warning_enabled": warning_enabled,
                }
            )

        platform_capacity = capacity_info.get("capacity_bytes")
        oversubscription_ratio = None
        remaining_allocatable_bytes = None
        allocation_percentage = None
        if platform_capacity is not None:
            remaining_allocatable_bytes = max(
                platform_capacity - total_allocated_bytes, 0
            )
            if platform_capacity > 0:
                oversubscription_ratio = round(
                    total_allocated_bytes / platform_capacity, 4
                )
                allocation_percentage = round(
                    total_allocated_bytes / platform_capacity * 100, 2
                )
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
            "total_es_physical_bytes": total_es_physical_bytes,
            "total_es_physical_readable": _bytes_to_readable(total_es_physical_bytes),
            "tenant_count": len(tenants),
            "oversubscription_ratio": oversubscription_ratio,
            "remaining_allocatable_bytes": remaining_allocatable_bytes,
            "remaining_allocatable_readable": _bytes_to_readable(
                remaining_allocatable_bytes
            ),
            "allocation_percentage": allocation_percentage,
            "unmanaged_tenant_count": allocation_state["unmanaged_tenant_count"],
            "capacity_management_enforced": (
                platform_capacity is not None
                and allocation_state["unmanaged_tenant_count"] == 0
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
        from management.services.knowledge_base.quota import QuotaService

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
        from management.services.knowledge_base.quota import QuotaService

        service = QuotaService(tenant_id, su_user_id)
        service._delete_tenant_config(KEY_TENANT_HARD_LIMIT_BYTES)
        service._delete_tenant_config(KEY_HARD_LIMIT_EDITABLE)
        return True
