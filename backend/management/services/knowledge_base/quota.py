# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from management.services.configuration.tenant.quotas import TenantQuotaPolicy
from management.services.configuration.user.quotas import PersonalQuotaPolicy
from management.services.knowledge_base.quota_common import (
    _UNSET,
    ASSET_OWNER_TENANT_ID,
    CACHE_TTL_SECONDS,
    DEFAULT_TENANT_ID,
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
    Dict,
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
    time,
    update_config_by_tenant_config_id,
    update_knowledge_record,
)
from management.services.knowledge_base.usage import KnowledgeUsageAccounting
from management.services.knowledge_base.quota_common import invalidate_usage_cache


class QuotaService(
    PersonalQuotaPolicy,
    TenantQuotaPolicy,
    KnowledgeUsageAccounting,
):
    def __init__(self, tenant_id: str, user_id: Optional[str] = None):
        self.tenant_id = tenant_id
        self.user_id = user_id or "system"

    @staticmethod
    def invalidate_usage_cache(tenant_id: Optional[str] = None) -> None:
        """Invalidate cached tenant usage used by tenant and platform quota views."""
        invalidate_usage_cache(tenant_id)

    def get_kb_soft_quota(self, knowledge_id: int) -> Optional[int]:
        """Get per-KB soft quota in bytes. Returns None if not set."""
        from infrastructure.rdb.client import get_db_session
        from management.db.models import KnowledgeRecord

        with get_db_session() as session:
            record = (
                session.query(KnowledgeRecord)
                .filter(
                    KnowledgeRecord.knowledge_id == knowledge_id,
                    KnowledgeRecord.delete_flag != "Y",
                )
                .first()
            )
            if record:
                return record.quota_limit_bytes
            return None

    def set_kb_soft_quota(self, index_name: str, limit_bytes: Optional[int]) -> bool:
        """
        Set per-KB soft quota via index_name. None = unlimited.
        Updates the knowledge_record_t row.
        """
        return update_knowledge_record(
            {
                "index_name": index_name,
                "quota_limit_bytes": limit_bytes,
                "user_id": self.user_id,
            }
        )

    def get_all_kb_quotas(self) -> List[Dict[str, Any]]:
        """Get all KB quota records for the tenant."""
        kb_list = get_knowledge_info_by_tenant_id(self.tenant_id)
        result = []
        for kb in kb_list:
            result.append(
                {
                    "knowledge_id": kb.get("knowledge_id"),
                    "index_name": kb.get("index_name"),
                    "knowledge_name": kb.get("knowledge_name"),
                    "quota_limit_bytes": kb.get("quota_limit_bytes"),
                }
            )
        return result


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
        from management.services.knowledge_base.quota_rules import check_user_capacity

        check_user_capacity(user_usage_bytes, upload_bytes, effective_quota, quota_source, user_id)

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
        from management.services.knowledge_base.quota_rules import check_kb_capacity

        check_kb_capacity(kb_usage_bytes, upload_bytes, kb_quota, index_name)

    def check_personal_kb_quota(
        self,
        user_id: str,
        upload_bytes: int,
        kb_record: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Enforce tenant, user, and PRIVATE-KB quotas before indexing.

        Raises AppException with a personal quota ErrorCode when a finite source
        quota would be exceeded. Shared-KB quota checks remain in the existing
        advisory path; this method is only used for PRIVATE KBs.
        """
        usage_data = self._get_personal_usage_data(strict=True, include_es=False)
        total_tenant_bytes = usage_data["total_bytes"]

        hard_limit_bytes = self.get_hard_limit().get("hard_limit_bytes")
        from management.services.knowledge_base.quota_rules import check_tenant_capacity

        check_tenant_capacity(total_tenant_bytes, upload_bytes, hard_limit_bytes)

        self._check_personal_user_quota_from_usage(usage_data, user_id, upload_bytes)
        self._check_personal_kb_quota_from_usage(
            usage_data,
            upload_bytes,
            kb_record,
        )
