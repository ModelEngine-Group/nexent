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
    List,
    Optional,
    PlatformQuotaConflictError,
    QuotaExceededError,
    Tuple,
    _gb_to_bytes,
    _is_displayable_tenant_id,
    _mb_to_bytes,
    _personal_quota_key,
    _usage_cache,
    bytes_to_readable,
    delete_config_by_tenant_config_id,
    get_committed_bytes_by_kb,
    get_committed_source_bytes_by_paths,
    get_knowledge_info_by_tenant_id,
    get_private_knowledge_info_by_creator,
    get_private_knowledge_info_by_tenant_id,
    get_single_config_info,
    get_tenant_committed_source_bytes,
    get_user_email_map,
    insert_config,
    logger,
    logging,
    time,
    update_config_by_tenant_config_id,
    update_knowledge_record,
)


class PersonalQuotaPolicy:
    @staticmethod
    def _parse_quota_value(raw: Any) -> Optional[int]:
        """Parse a quota config value; invalid values are treated as zero."""
        from management.services.knowledge_base.quota_rules import parse_personal_quota

        return parse_personal_quota(raw)

    def get_personal_user_quota(self, user_id: str) -> Optional[int]:
        """Return a user's individual personal KB quota in bytes, or None."""
        return self._parse_quota_value(
            self._get_tenant_config(_personal_quota_key(user_id))
        )


    def get_personal_default_quota(self) -> Optional[int]:
        """Return the tenant default personal KB quota in bytes, or None."""
        return self._parse_quota_value(
            self._get_tenant_config(KEY_PERSONAL_KB_QUOTA_DEFAULT)
        )


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
