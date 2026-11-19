# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from management.services.knowledge_base.quota_common import (
    _UNSET,
    ASSET_OWNER_TENANT_ID,
    CACHE_TTL_SECONDS,
    DEFAULT_TENANT_ID,
    GB,
    KEY_HARD_LIMIT_EDITABLE,
    KEY_PERSONAL_KB_QUOTA_DEFAULT,
    KEY_PLATFORM_CAPACITY_BYTES,
    KEY_TENANT_HARD_LIMIT_BYTES,
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
    _gb_to_bytes,
    _is_displayable_tenant_id,
    _mb_to_bytes,
    _personal_quota_key,
    _usage_cache,
    bytes_to_readable,
    get_committed_bytes_by_kb,
    get_committed_source_bytes_by_paths,
    get_configs_by_tenant_id_and_keys,
    get_knowledge_info_by_tenant_id,
    get_private_knowledge_info_by_creator,
    get_private_knowledge_info_by_tenant_id,
    get_single_config_info,
    get_tenant_committed_source_bytes,
    get_user_email_map,
    logger,
    logging,
    time,
    update_knowledge_record,
)


class TenantQuotaPolicy:
    def _get_tenant_config(self, key: str) -> Optional[str]:
        """Read a single tenant config value."""
        record = get_single_config_info(self.tenant_id, key)
        return record.get("config_value") if record else None



    def get_hard_limit(self) -> Dict[str, Any]:
        """
        Get the tenant hard storage limit.
        Returns dict with _bytes and _readable fields, or defaults for unlimited.
        """
        from management.services.knowledge_base.quota_rules import hard_limit_values
        return hard_limit_values(self._get_tenant_config(KEY_TENANT_HARD_LIMIT_BYTES),
                                 self._get_tenant_config(KEY_HARD_LIMIT_EDITABLE))
