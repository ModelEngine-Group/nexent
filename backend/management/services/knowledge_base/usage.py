# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from management.services.knowledge_base.quota_common import (
    ASSET_OWNER_TENANT_ID,
    DEFAULT_CRITICAL_THRESHOLD,
    DEFAULT_TENANT_ID,
    DEFAULT_WARNING_THRESHOLD,
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
    _bytes_to_readable,
    _gb_to_bytes,
    _is_displayable_tenant_id,
    _mb_to_bytes,
    _personal_quota_key,
    bytes_to_readable,
    delete_config_by_tenant_config_id,
    get_committed_bytes_by_kb,
    get_committed_source_bytes_by_paths,
    get_configs_by_tenant_id_and_keys,
    get_private_knowledge_info_by_creator,
    get_private_knowledge_info_by_tenant_id,
    get_single_config_info,
    insert_config,
    logger,
    logging,
    update_config_by_tenant_config_id,
    update_knowledge_record,
)
from management.services.knowledge_base.quota_formatting import parse_store_size


class KnowledgeUsageAccounting:
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
        include_es: bool = True,
    ) -> Dict[str, Any]:
        """Collect source-file quota usage and optional ES observability metrics.

        Source bytes come from the durable knowledge-storage ledger and are the
        authoritative quota metric. ES store size is queried only when requested
        for display or diagnostics; it must never make a source-byte quota check
        fail because Lucene storage is eventually reclaimed.
        """
        index_names = [
            kb.get("index_name")
            for kb in kb_list
            if kb.get("index_name")
            and not (exclude_datamate and kb.get("knowledge_sources") == "datamate")
        ]
        indices_detail: Dict[str, Any] = {}

        if include_es and index_names:
            try:
                from management.services.knowledge_base.service import (
                    get_vector_db_core,
                )

                vdb_core = get_vector_db_core()
                raw_indices_detail = vdb_core.get_indices_detail(index_names) or {}
                indices_detail = (
                    raw_indices_detail if isinstance(raw_indices_detail, dict) else {}
                )
            except AppException:
                # ES is an optional observability source. Preserve the source
                # ledger result even when its adapter reports an application
                # error, including during strict quota checks.
                logger.warning(
                    "Failed to query ES index stats for storage observability",
                    exc_info=True,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to query ES index stats for storage observability: %s",
                    exc,
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
            if include_es and not (exclude_datamate and is_datamate):
                detail = raw_detail if isinstance(raw_detail, dict) else {}
                base_info = (
                    detail.get("base_info")
                    if isinstance(detail.get("base_info"), dict)
                    else {}
                )
                store_size = base_info.get("store_size")
                es_bytes = parse_store_size(store_size)
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
            # ``stats`` is intentionally source-file bytes only. All quota
            # enforcement and usage percentages consume this mapping.
            stats[index_name] = source_bytes
            details[index_name] = {
                "store_size": store_size,
                "store_size_bytes": es_bytes,
                "source_size": _bytes_to_readable(source_bytes),
                "source_size_bytes": source_bytes,
                # Keep the legacy keys present for clients during the semantic
                # transition, but make them aliases of the quota metric rather
                # than the old source-plus-ES composite.
                "total_size": _bytes_to_readable(source_bytes),
                "total_size_bytes": source_bytes,
                "doc_count": doc_count,
                "chunk_count": chunk_count,
            }

        return {
            "stats": stats,
            "details": details,
            "total_es_bytes": sum(
                item["store_size_bytes"] for item in details.values()
            ),
            "total_bytes": sum(stats.values()),
        }

    def _get_personal_usage_data(
        self,
        strict: bool = False,
        user_id: Optional[str] = None,
        include_es: bool = True,
    ) -> Dict[str, Any]:
        """Aggregate PRIVATE KB storage using source bytes as the quota metric.

        Non-strict mode degrades storage-stat failures to zero usage so admin
        capacity views stay available. Strict mode applies to the durable source
        ledger; ES metrics remain best-effort observability data.
        """
        kb_list = (
            get_private_knowledge_info_by_creator(self.tenant_id, user_id)
            if user_id is not None
            else get_private_knowledge_info_by_tenant_id(self.tenant_id)
        )
        storage_stats = self._get_kb_storage_stats(
            kb_list,
            strict=strict,
            include_es=include_es,
        )
        return {
            "kbs": kb_list,
            "stats": storage_stats["stats"],
            "details": storage_stats["details"],
            "total_bytes": storage_stats.get("total_bytes", 0),
            "total_es_bytes": storage_stats.get("total_es_bytes", 0),
        }






    def get_pending_personal_upload_bytes(
        self,
        data: List[Dict[str, Any]],
        kb_record: Optional[Dict[str, Any]],
    ) -> int:
        """Calculate unique source bytes not yet committed to the storage ledger."""
        if not kb_record:
            return 0

        from management.services.knowledge_base.quota_rules import (
            source_sizes as collect_source_sizes,
        )

        source_sizes = collect_source_sizes(data)

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
