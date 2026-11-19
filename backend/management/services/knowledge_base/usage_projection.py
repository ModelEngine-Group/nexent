# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Pure source-byte quota responses shared by synchronous and AgentOS callers."""

from management.services.knowledge_base.quota_formatting import (
    bytes_to_readable as _bytes_to_readable,
)


def warning_level(usage_pct, critical_threshold=95, warning_threshold=80, *, terminal='exceeded'):
    if usage_pct is None:
        return 'normal'
    if usage_pct >= 100:
        return terminal
    if usage_pct >= critical_threshold:
        return 'critical'
    if usage_pct >= warning_threshold:
        return 'warning'
    return 'normal'


def project_usage(kb_list, storage_stats, tenant_source_bytes, hard_limit_info, warning_config, summary):
    tenant_warning_threshold = warning_config['warning_threshold_pct']
    tenant_critical_threshold = warning_config['critical_threshold_pct']
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
    tenant_minio_bytes = tenant_source_bytes

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
        kb_warning_level = warning_level(
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
    tenant_warning_level = warning_level(
        tenant_usage_pct,
        warning_config["critical_threshold_pct"],
        warning_config["warning_threshold_pct"],
        terminal="blocked",
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

    result["soft_allocated_total_bytes"] = summary["soft_allocated_total_bytes"]
    result["soft_allocated_readable"] = summary["soft_allocated_readable"]
    result["oversubscription_ratio"] = summary["oversubscription_ratio"]
    result["kbs_with_quota"] = summary["kbs_with_quota"]

    return result
