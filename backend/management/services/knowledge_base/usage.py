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
            item["total_bytes"] += usage_data["stats"].get(kb.get("index_name", ""), 0)
            detail = usage_data.get("details", {}).get(kb.get("index_name", ""), {})
            item["es_physical_bytes"] = item.get("es_physical_bytes", 0) + int(
                detail.get("store_size_bytes", 0) or 0
            )

        for user_id in user_ids or set():
            grouped.setdefault(
                user_id,
                {"kbs": [], "kb_count": 0, "total_bytes": 0, "es_physical_bytes": 0},
            )

        return grouped

    def _aggregate_personal_usage_by_user(
        self,
        usage_data: Dict[str, Any],
        user_ids: Optional[set[str]] = None,
        default_quota: Any = _UNSET,
        effective_quota_by_user: Optional[Dict[str, Tuple[Optional[int], str]]] = None,
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
            es_physical_bytes = user_data.get("es_physical_bytes")
            items.append(
                {
                    "user_id": user_id,
                    "user_name": email_map.get(user_id) or user_id,
                    "email": email_map.get(user_id),
                    "kb_count": user_data["kb_count"],
                    "total_bytes": total_bytes,
                    "total_readable": _bytes_to_readable(total_bytes),
                    "es_physical_bytes": es_physical_bytes,
                    "es_physical_readable": _bytes_to_readable(es_physical_bytes),
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
                }
            )

        if keyword:
            lowered_keyword = keyword.strip().lower()
            if lowered_keyword:
                items = [
                    item
                    for item in items
                    if lowered_keyword in str(item["user_name"]).lower()
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
                item["usage_rate"] if item["usage_rate"] is not None else -1
            ),
        }
        key_func = sort_keys.get(sort_by, sort_keys["total_bytes"])
        items.sort(key=key_func, reverse=sort_order.lower() != "asc")

        total = len(items)
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        start = (page - 1) * page_size
        paged = items[start : start + page_size] if page_size > 0 else items
        from management.services.permission.identity.display import enrich_cas_usernames

        enrich_cas_usernames(paged, {"cas_username": "user_id"})
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
            kbs.append(
                {
                    "kb_id": kb.get("knowledge_id"),
                    "knowledge_id": kb.get("knowledge_id"),
                    "index_name": index_name,
                    "name": kb.get("knowledge_name") or index_name,
                    "source": kb.get("knowledge_sources"),
                    "doc_count": detail.get("doc_count", 0),
                    "chunk_count": detail.get("chunk_count", 0),
                    "store_size": detail.get("store_size"),
                    "store_size_bytes": detail.get("store_size_bytes", 0),
                    "es_physical_size": detail.get("store_size"),
                    "es_physical_size_bytes": detail.get("store_size_bytes", 0),
                    "source_size": detail.get("source_size"),
                    "source_size_bytes": detail.get("source_size_bytes", 0),
                    "total_size": detail.get("total_size"),
                    "total_size_bytes": detail.get("total_size_bytes", 0),
                    "quota_limit_bytes": quota_limit_bytes,
                    "quota_limit_readable": _bytes_to_readable(quota_limit_bytes),
                    "updated_at": (
                        kb.get("last_doc_update_time") or kb.get("update_time")
                    ),
                }
            )

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
        user_ids = {kb.get("created_by") for kb in kb_list if kb.get("created_by")}
        effective_quota_by_user, default_quota = self._get_personal_effective_quota_map(
            user_ids
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
            "total_es_physical_bytes": usage_data["total_es_bytes"],
            "total_es_physical_readable": _bytes_to_readable(
                usage_data["total_es_bytes"]
            ),
            "allocated_quota_bytes": allocated_quota_bytes,
            "allocated_quota_readable": _bytes_to_readable(allocated_quota_bytes),
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
            source = str(item.get("path_or_url") or item.get("filename") or "").strip()
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
        Compute actual storage usage from the committed source-file ledger.
        Elasticsearch physical index size is returned separately for
        observability and is never part of the quota metric.
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
                # Quota usage is based on source files. Keep ES bytes in a
                # separate field so Lucene segment reclamation cannot affect
                # admission checks or displayed quota usage.
                "bytes": detail.get("source_size_bytes", 0),
                "source_bytes": detail.get("source_size_bytes", 0),
                "total_bytes": detail.get("source_size_bytes", 0),
                "es_bytes": detail.get("store_size_bytes", 0),
                "file_count": detail.get("doc_count", 0),
            }
            for name, detail in storage_stats.get("details", {}).items()
        }
        tenant_minio_bytes = get_tenant_committed_source_bytes(self.tenant_id)

        breakdown = []
        total_es_bytes = storage_stats.get("total_es_bytes", 0)
        total_files = 0

        for kb in kb_list:
            index_name = kb.get("index_name", "")
            kb_id = kb.get("knowledge_id")
            kb_name = kb.get("knowledge_name", index_name)
            soft_quota_bytes = kb.get("quota_limit_bytes")

            kb_stats = stats_lookup.get(index_name, {})
            kb_actual_bytes = kb_stats.get("total_bytes", 0)
            kb_es_bytes = kb_stats.get("es_bytes", 0)
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

            breakdown.append(
                {
                    "knowledge_id": kb_id,
                    "knowledge_name": kb_name,
                    "index_name": index_name,
                    "soft_quota_bytes": soft_quota_bytes,
                    "soft_quota_readable": _bytes_to_readable(soft_quota_bytes),
                    "actual_bytes": kb_actual_bytes,
                    "actual_readable": _bytes_to_readable(kb_actual_bytes),
                    "es_physical_bytes": kb_es_bytes,
                    "es_physical_readable": _bytes_to_readable(kb_es_bytes),
                    "usage_pct": kb_usage_pct,
                    "file_count": kb_file_count,
                    "kb_warning_level": kb_warning_level,
                }
            )

        # Tenant totals include all active tenant ledger rows, including rows whose
        # KB is no longer returned in the active KB list. This avoids silently
        # dropping retained source objects from the tenant hard-limit calculation.
        # The durable source-file ledger is the sole quota metric. ES physical
        # bytes are observability data and are intentionally excluded from the
        # hard-limit calculation because segment merges/reclamation are async.
        total_bytes = tenant_minio_bytes

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
            "es_physical_bytes": total_es_bytes,
            "es_physical_readable": _bytes_to_readable(total_es_bytes),
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
