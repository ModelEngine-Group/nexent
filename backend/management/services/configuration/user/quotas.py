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


class PersonalQuotaPolicy:
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
        usage_data = self._get_personal_usage_data(user_id=user_id, include_es=False)
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
