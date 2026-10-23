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


class TenantQuotaPolicy:
    def _get_tenant_config(self, key: str) -> Optional[str]:
        """Read a single tenant config value."""
        record = get_single_config_info(self.tenant_id, key)
        return record.get("config_value") if record else None

    def _set_tenant_config(
        self, key: str, value: Any, value_type: str = "single"
    ) -> bool:
        """Upsert a tenant config key. Updates existing row or inserts new."""
        existing = get_single_config_info(self.tenant_id, key)
        if existing and existing.get("tenant_config_id"):
            return update_config_by_tenant_config_id(
                existing["tenant_config_id"], str(value)
            )
        else:
            return insert_config(
                {
                    "tenant_id": self.tenant_id,
                    "user_id": self.user_id,
                    "config_key": key,
                    "config_value": str(value),
                    "value_type": value_type,
                }
            )

    def _delete_tenant_config(self, key: str) -> bool:
        """Soft-delete a tenant config key."""
        existing = get_single_config_info(self.tenant_id, key)
        tenant_config_id = existing.get("tenant_config_id") if existing else None
        if tenant_config_id is None:
            return True
        return delete_config_by_tenant_config_id(tenant_config_id)

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
            critical_pct = (
                int(critical_raw) if critical_raw else DEFAULT_CRITICAL_THRESHOLD
            )
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
        """Set warning thresholds. Validates 1-100 range and warning < critical."""
        if warning_pct is not None:
            if not 1 <= warning_pct <= 100:
                raise ValueError(f"warning_pct must be 1-100, got {warning_pct}")

        if critical_pct is not None:
            if not 1 <= critical_pct <= 100:
                raise ValueError(f"critical_pct must be 1-100, got {critical_pct}")

        # Reject inverted thresholds against the values effective after update.
        effective_warning = (
            warning_pct
            if warning_pct is not None
            else self.get_warning_config().get("warning_threshold_pct")
        )
        effective_critical = (
            critical_pct
            if critical_pct is not None
            else self.get_warning_config().get("critical_threshold_pct")
        )
        if (
            effective_warning is not None
            and effective_critical is not None
            and effective_warning >= effective_critical
        ):
            raise ValueError(
                f"warning_threshold_pct ({effective_warning}) must be lower than "
                f"critical_threshold_pct ({effective_critical})"
            )

        if warning_pct is not None:
            self._set_tenant_config(KEY_WARNING_THRESHOLD_PCT, str(warning_pct))
        if critical_pct is not None:
            self._set_tenant_config(KEY_CRITICAL_THRESHOLD_PCT, str(critical_pct))

        if enabled is not None:
            self._set_tenant_config(KEY_WARNING_ENABLED, str(enabled).lower())

        return self.get_warning_config()
