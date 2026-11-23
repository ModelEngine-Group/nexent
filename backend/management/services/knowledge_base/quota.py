# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from management.services.configuration.platform.capacity import PlatformCapacityPolicy
from management.services.configuration.tenant.quotas import TenantQuotaPolicy
from management.services.configuration.user.quotas import PersonalQuotaPolicy
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
from management.services.knowledge_base.usage import KnowledgeUsageAccounting


class QuotaService(
    PlatformCapacityPolicy,
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
        if tenant_id is None:
            _usage_cache.clear()
            return
        _usage_cache.pop(tenant_id, None)

    def get_kb_soft_quota(self, knowledge_id: int) -> Optional[int]:
        """Get per-KB soft quota in bytes. Returns None if not set."""
        from database.client import get_db_session
        from database.db_models import KnowledgeRecord

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
            "es_physical_bytes": user_usage.get("es_physical_bytes"),
            "es_physical_readable": _bytes_to_readable(
                user_usage.get("es_physical_bytes")
            ),
            "quota_bytes": quota_bytes,
            "quota_readable": _bytes_to_readable(quota_bytes),
            "quota_source": quota_source,
            "usage_rate": usage_rate,
            "is_over_quota": quota_bytes is not None and used_bytes > quota_bytes,
            "kb_count": user_usage["kb_count"],
        }

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
        usage_data = self._get_personal_usage_data(
            strict=True,
            user_id=user_id,
            include_es=False,
        )
        self._check_personal_user_quota_from_usage(usage_data, user_id, upload_bytes)

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
            q["quota_limit_bytes"]
            for q in kb_quotas
            if q["quota_limit_bytes"] is not None
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
