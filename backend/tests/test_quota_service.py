"""
Unit tests for QuotaService.

Covers: config methods, per-KB quota, usage tracking, warning levels,
quota enforcement, summary, and platform quota.
"""

import pytest
from unittest.mock import MagicMock, patch
from services.quota_service import (
    QuotaService,
    QuotaExceededError,
    _bytes_to_readable,
    GB,
    CACHE_TTL_SECONDS,
    DEFAULT_WARNING_THRESHOLD,
    DEFAULT_CRITICAL_THRESHOLD,
    _usage_cache,
)
from consts.exceptions import PlatformQuotaConflictError

# ═══════════════════════════════════════════════════════════════════════
# Task 11.5 — Warning Level Computation (pure logic, no DB mocks needed)
# ═══════════════════════════════════════════════════════════════════════

class TestWarningLevelComputation:
    """Tests for _compute_kb_warning_level and _compute_tenant_warning_level."""

    def test_kb_normal_below_80(self):
        assert QuotaService._compute_kb_warning_level(0) == "normal"
        assert QuotaService._compute_kb_warning_level(50) == "normal"
        assert QuotaService._compute_kb_warning_level(79.9) == "normal"

    def test_kb_warning_80_to_95(self):
        assert QuotaService._compute_kb_warning_level(80) == "warning"
        assert QuotaService._compute_kb_warning_level(90) == "warning"

    def test_kb_critical_95_to_100(self):
        assert QuotaService._compute_kb_warning_level(95) == "critical"
        assert QuotaService._compute_kb_warning_level(99.9) == "critical"

    def test_kb_exceeded_100_plus(self):
        assert QuotaService._compute_kb_warning_level(100) == "exceeded"
        assert QuotaService._compute_kb_warning_level(150) == "exceeded"

    def test_kb_none_usage(self):
        assert QuotaService._compute_kb_warning_level(None) == "normal"

    def test_tenant_normal_below_80(self):
        assert QuotaService._compute_tenant_warning_level(0) == "normal"
        assert QuotaService._compute_tenant_warning_level(50) == "normal"
        assert QuotaService._compute_tenant_warning_level(79) == "normal"

    def test_tenant_warning_80_to_95(self):
        assert QuotaService._compute_tenant_warning_level(80) == "warning"
        assert QuotaService._compute_tenant_warning_level(90) == "warning"
        assert QuotaService._compute_tenant_warning_level(94) == "warning"

    def test_tenant_critical_95_to_100(self):
        assert QuotaService._compute_tenant_warning_level(95) == "critical"
        assert QuotaService._compute_tenant_warning_level(99) == "critical"

    def test_tenant_blocked_100_plus(self):
        assert QuotaService._compute_tenant_warning_level(100) == "blocked"
        assert QuotaService._compute_tenant_warning_level(200) == "blocked"

    def test_tenant_none_usage(self):
        assert QuotaService._compute_tenant_warning_level(None) == "normal"

    def test_custom_thresholds(self):
        # Custom warning=70, critical=85
        assert QuotaService._compute_tenant_warning_level(75, 85, 70) == "warning"
        assert QuotaService._compute_tenant_warning_level(90, 85, 70) == "critical"
        assert QuotaService._compute_tenant_warning_level(60, 85, 70) == "normal"


# ═══════════════════════════════════════════════════════════════════════
# Task 11.5 — _bytes_to_readable
# ═══════════════════════════════════════════════════════════════════════

class TestBytesToReadable:
    def test_gb(self):
        assert _bytes_to_readable(GB) == "1.0 GB"
        assert _bytes_to_readable(10 * GB) == "10.0 GB"

    def test_mb(self):
        assert _bytes_to_readable(500 * 1024 * 1024) == "500.0 MB"

    def test_kb(self):
        assert _bytes_to_readable(500 * 1024) == "500.0 KB"

    def test_bytes(self):
        assert _bytes_to_readable(500) == "500 B"

    def test_none(self):
        assert _bytes_to_readable(None) is None

    def test_zero(self):
        assert _bytes_to_readable(0) == "0 B"


# ═══════════════════════════════════════════════════════════════════════
# Task 11.2 — Config Methods
# ═══════════════════════════════════════════════════════════════════════

class TestConfigMethods:
    """Tests for get_hard_limit, set_hard_limit, delete_hard_limit, warning config."""

    def test_get_hard_limit_returns_defaults_when_no_config(self, quota_service, mock_tenant_config_db):
        mock_tenant_config_db["get_single_config_info"].return_value = {}
        result = quota_service.get_hard_limit()
        assert result["hard_limit_bytes"] is None
        assert result["hard_limit_readable"] is None
        assert result["hard_limit_editable"] is True

    def test_get_hard_limit_returns_bytes_when_set(self, quota_service, mock_tenant_config_db):
        # Simulate 100GB stored
        def get_config(tenant_id, key):
            if key == "KB_QUOTA_TENANT_HARD_LIMIT_BYTES":
                return {"config_value": str(100 * GB), "tenant_config_id": 1}
            if key == "KB_QUOTA_HARD_LIMIT_EDITABLE":
                return {"config_value": "true", "tenant_config_id": 2}
            return {}
        mock_tenant_config_db["get_single_config_info"].side_effect = get_config

        result = quota_service.get_hard_limit()
        assert result["hard_limit_bytes"] == 100 * GB
        assert result["hard_limit_readable"] == "100.0 GB"
        assert result["hard_limit_editable"] is True

    def test_get_hard_limit_not_editable_when_su_set(self, quota_service, mock_tenant_config_db):
        def get_config(tenant_id, key):
            if key == "KB_QUOTA_TENANT_HARD_LIMIT_BYTES":
                return {"config_value": str(50 * GB), "tenant_config_id": 1}
            if key == "KB_QUOTA_HARD_LIMIT_EDITABLE":
                return {"config_value": "false", "tenant_config_id": 2}
            return {}
        mock_tenant_config_db["get_single_config_info"].side_effect = get_config

        result = quota_service.get_hard_limit()
        assert result["hard_limit_bytes"] == 50 * GB
        assert result["hard_limit_editable"] is False

    def test_set_hard_limit_stores_bytes(self, quota_service, mock_tenant_config_db):
        mock_tenant_config_db["get_single_config_info"].return_value = {}
        mock_tenant_config_db["insert_config"].return_value = True

        with patch.object(
            quota_service, "get_usage", return_value={"total_bytes": 0}
        ), patch.object(
            QuotaService,
            "get_platform_capacity",
            return_value={"capacity_bytes": None},
        ):
            result = quota_service.set_hard_limit(50)  # 50 GB
        assert result["hard_limit_bytes"] == 50 * GB
        assert "50" in result["hard_limit_readable"]

    def test_set_hard_limit_none_deletes(self, quota_service, mock_tenant_config_db):
        mock_tenant_config_db["get_single_config_info"].side_effect = [
            {"tenant_config_id": 41, "config_value": str(50 * GB)},
            {},
        ]
        mock_tenant_config_db["delete_config_by_tenant_config_id"].return_value = True

        result = quota_service.set_hard_limit(None)
        assert result["hard_limit_bytes"] is None
        mock_tenant_config_db["delete_config_by_tenant_config_id"].assert_called_once_with(41)

    def test_get_warning_config_defaults(self, quota_service, mock_tenant_config_db):
        mock_tenant_config_db["get_single_config_info"].return_value = {}
        result = quota_service.get_warning_config()
        assert result["warning_enabled"] is True  # default on
        assert result["warning_threshold_pct"] == DEFAULT_WARNING_THRESHOLD
        assert result["critical_threshold_pct"] == DEFAULT_CRITICAL_THRESHOLD

    def test_get_warning_config_reads_stored(self, quota_service, mock_tenant_config_db):
        def get_config(tenant_id, key):
            store = {
                "KB_QUOTA_WARNING_ENABLED": {"config_value": "false", "tenant_config_id": 1},
                "KB_QUOTA_WARNING_THRESHOLD_PCT": {"config_value": "70", "tenant_config_id": 2},
                "KB_QUOTA_CRITICAL_THRESHOLD_PCT": {"config_value": "90", "tenant_config_id": 3},
            }
            return store.get(key, {})
        mock_tenant_config_db["get_single_config_info"].side_effect = get_config

        result = quota_service.get_warning_config()
        assert result["warning_enabled"] is False
        assert result["warning_threshold_pct"] == 70
        assert result["critical_threshold_pct"] == 90

    def test_set_warning_config_validates_range(self, quota_service, mock_tenant_config_db):
        mock_tenant_config_db["get_single_config_info"].return_value = {}
        with pytest.raises(ValueError):
            quota_service.set_warning_config(warning_pct=150)
        with pytest.raises(ValueError):
            quota_service.set_warning_config(critical_pct=0)

    def test_set_warning_config_persists(self, quota_service, mock_tenant_config_db):
        # Simulate: first reads are empty (no config), then after insert we return stored values
        stored = {}
        def get_config(tenant_id, key):
            return stored.get(key, {})

        mock_tenant_config_db["get_single_config_info"].side_effect = get_config
        mock_tenant_config_db["insert_config"].side_effect = lambda d: stored.update({d["config_key"]: {"config_value": d["config_value"], "tenant_config_id": 1}}) or True

        result = quota_service.set_warning_config(
            enabled=False, warning_pct=75, critical_pct=92
        )
        # After set_warning_config calls get_warning_config which re-reads, the stored values should reflect
        assert result["warning_enabled"] is False
        assert result["warning_threshold_pct"] == 75
        assert result["critical_threshold_pct"] == 92


# ═══════════════════════════════════════════════════════════════════════
# Task 11.3 — Per-KB Soft Quota
# ═══════════════════════════════════════════════════════════════════════

class TestKbSoftQuota:
    """Tests for get_kb_soft_quota, set_kb_soft_quota, get_all_kb_quotas."""

    def test_get_all_kb_quotas(self, quota_service, mock_knowledge_db, sample_kb_list):
        mock_knowledge_db["get_knowledge_info_by_tenant_id"].return_value = sample_kb_list
        result = quota_service.get_all_kb_quotas()
        assert len(result) == 3
        assert result[0]["quota_limit_bytes"] == 30 * GB
        assert result[1]["quota_limit_bytes"] is None
        assert result[2]["quota_limit_bytes"] == 10 * GB

    def test_get_all_kb_quotas_empty(self, quota_service, mock_knowledge_db):
        mock_knowledge_db["get_knowledge_info_by_tenant_id"].return_value = []
        result = quota_service.get_all_kb_quotas()
        assert result == []

    def test_set_kb_soft_quota(self, quota_service, mock_knowledge_db):
        mock_knowledge_db["update_knowledge_record"].return_value = True
        result = quota_service.set_kb_soft_quota("kb-1", 50 * GB)
        assert result is True
        mock_knowledge_db["update_knowledge_record"].assert_called_once()

    def test_set_kb_soft_quota_none(self, quota_service, mock_knowledge_db):
        mock_knowledge_db["update_knowledge_record"].return_value = True
        result = quota_service.set_kb_soft_quota("kb-1", None)
        assert result is True


# ═══════════════════════════════════════════════════════════════════════
# Task 11.7 — Quota Summary
# ═══════════════════════════════════════════════════════════════════════

class TestQuotaSummary:
    """Tests for get_quota_summary."""

    def test_summary_with_quotas(self, quota_service, mock_knowledge_db, sample_kb_list):
        mock_knowledge_db["get_knowledge_info_by_tenant_id"].return_value = sample_kb_list
        with patch.object(quota_service, "get_hard_limit") as mock_limit:
            mock_limit.return_value = {
                "hard_limit_bytes": 100 * GB,
                "hard_limit_readable": "100.0 GB",
                "hard_limit_editable": True,
            }
            result = quota_service.get_quota_summary()

        assert result["soft_allocated_total_bytes"] == 40 * GB  # 30 + 0 + 10
        assert result["kb_count"] == 3
        assert result["kbs_with_quota"] == 2
        assert result["oversubscription_ratio"] == pytest.approx(0.4)  # 40/100

    def test_summary_no_quotas(self, quota_service, mock_knowledge_db):
        mock_knowledge_db["get_knowledge_info_by_tenant_id"].return_value = []
        with patch.object(quota_service, "get_hard_limit") as mock_limit:
            mock_limit.return_value = {
                "hard_limit_bytes": 100 * GB,
                "hard_limit_readable": "100.0 GB",
                "hard_limit_editable": True,
            }
            result = quota_service.get_quota_summary()

        assert result["soft_allocated_total_bytes"] == 0
        assert result["kb_count"] == 0
        assert result["kbs_with_quota"] == 0

    def test_summary_no_hard_limit(self, quota_service, mock_knowledge_db, sample_kb_list):
        mock_knowledge_db["get_knowledge_info_by_tenant_id"].return_value = sample_kb_list
        with patch.object(quota_service, "get_hard_limit") as mock_limit:
            mock_limit.return_value = {
                "hard_limit_bytes": None,
                "hard_limit_readable": None,
                "hard_limit_editable": True,
            }
            result = quota_service.get_quota_summary()

        assert result["oversubscription_ratio"] is None


# ═══════════════════════════════════════════════════════════════════════
# Task 11.6 — Quota Enforcement
# ═══════════════════════════════════════════════════════════════════════

class TestQuotaEnforcement:
    """Tests for check_hard_limit and check_hard_limit_post_write."""

    def test_check_allows_when_no_hard_limit(self, quota_service):
        with patch.object(quota_service, "get_hard_limit") as mock_limit, \
             patch.object(quota_service, "get_usage") as mock_usage:
            mock_limit.return_value = {"hard_limit_bytes": None}
            result = quota_service.check_hard_limit(GB)
            assert result is not None
            assert "quota_status" in result

    def test_check_allows_when_space_available(self, quota_service):
        with patch.object(quota_service, "get_hard_limit") as mock_limit, \
             patch.object(quota_service, "get_usage") as mock_usage:
            mock_limit.return_value = {"hard_limit_bytes": 100 * GB}
            mock_usage.return_value = {"total_bytes": 50 * GB}
            result = quota_service.check_hard_limit(10 * GB)  # 50 + 10 < 100
            assert result is not None

    def test_check_raises_when_exceeded(self, quota_service):
        with patch.object(quota_service, "get_hard_limit") as mock_limit, \
             patch.object(quota_service, "get_usage") as mock_usage:
            mock_limit.return_value = {"hard_limit_bytes": 100 * GB}
            mock_usage.return_value = {"total_bytes": 95 * GB}
            with pytest.raises(QuotaExceededError) as exc_info:
                quota_service.check_hard_limit(10 * GB)  # 95 + 10 > 100
            assert exc_info.value.usage_bytes == 95 * GB
            assert exc_info.value.hard_limit_bytes == 100 * GB
            assert exc_info.value.exceeded_by_bytes == 5 * GB

    def test_check_raises_at_boundary(self, quota_service):
        with patch.object(quota_service, "get_hard_limit") as mock_limit, \
             patch.object(quota_service, "get_usage") as mock_usage:
            mock_limit.return_value = {"hard_limit_bytes": 100 * GB}
            mock_usage.return_value = {"total_bytes": 100 * GB}
            with pytest.raises(QuotaExceededError):
                quota_service.check_hard_limit(1)  # even 1 byte over

    def test_post_write_check_allows_when_ok(self, quota_service):
        with patch.object(quota_service, "get_hard_limit") as mock_limit, \
             patch.object(quota_service, "get_usage") as mock_usage:
            mock_limit.return_value = {"hard_limit_bytes": 100 * GB}
            mock_usage.return_value = {"total_bytes": 80 * GB}
            result = quota_service.check_hard_limit_post_write(0)
            assert result is not None

    def test_post_write_check_raises_on_race_condition(self, quota_service):
        with patch.object(quota_service, "get_hard_limit") as mock_limit, \
             patch.object(quota_service, "get_usage") as mock_usage:
            mock_limit.return_value = {"hard_limit_bytes": 100 * GB}
            mock_usage.return_value = {"total_bytes": 105 * GB}
            with pytest.raises(QuotaExceededError):
                quota_service.check_hard_limit_post_write(0)

    def test_upload_status_contains_target_kb_and_warning_setting(self, quota_service):
        with patch.object(quota_service, "get_hard_limit") as mock_limit, \
             patch.object(quota_service, "get_usage") as mock_usage:
            mock_limit.return_value = {
                "hard_limit_bytes": 100 * GB,
                "hard_limit_readable": "100 GB",
            }
            mock_usage.return_value = {
                "total_bytes": 90 * GB,
                "total_readable": "90 GB",
                "usage_pct": 90,
                "tenant_warning_level": "warning",
                "warning_enabled": False,
                "breakdown": [
                    {
                        "index_name": "target-kb",
                        "usage_pct": 96,
                        "kb_warning_level": "critical",
                    },
                    {
                        "index_name": "other-kb",
                        "usage_pct": 20,
                        "kb_warning_level": "normal",
                    },
                ],
            }

            result = quota_service._build_quota_status("target-kb")["quota_status"]

        assert result["warning_enabled"] is False
        assert result["tenant_level"]["warning_level"] == "warning"
        assert result["kb_level"] == {
            "usage_pct": 96,
            "warning_level": "critical",
        }


# ═══════════════════════════════════════════════════════════════════════
# Task 11.8 — Platform Quota
# ═══════════════════════════════════════════════════════════════════════

class TestPlatformQuota:
    """Tests for platform-level quota methods."""

    def test_get_platform_capacity_returns_none_when_not_set(self):
        # get_platform_capacity imports get_single_config_info inside the method
        with patch("database.tenant_config_db.get_single_config_info") as mock_get:
            mock_get.return_value = {}
            result = QuotaService.get_platform_capacity()
            assert result["capacity_bytes"] is None
            assert result["capacity_readable"] is None

    def test_get_platform_capacity_reads_stored(self):
        with patch("database.tenant_config_db.get_single_config_info") as mock_get:
            mock_get.return_value = {"config_value": str(500 * GB), "tenant_config_id": 1}
            result = QuotaService.get_platform_capacity()
            assert result["capacity_bytes"] == 500 * GB
            assert "500" in result["capacity_readable"]

    def test_set_platform_capacity(self):
        with patch.object(QuotaService, "_set_tenant_config") as mock_set, patch.object(
            QuotaService,
            "_get_allocation_state",
            return_value={"total_allocated_bytes": 0},
        ):
            mock_set.return_value = True
            result = QuotaService.set_platform_capacity(500)
            assert result["capacity_bytes"] == 500 * GB

    def test_set_platform_capacity_none(self):
        with patch.object(QuotaService, "_delete_tenant_config") as mock_del:
            mock_del.return_value = True
            result = QuotaService.set_platform_capacity(None)
            assert result["capacity_bytes"] is None

    def test_set_tenant_hard_limit_by_su(self):
        with patch.object(QuotaService, "_set_tenant_config") as mock_set, patch.object(
            QuotaService, "get_usage", return_value={"total_bytes": 0}
        ), patch.object(
            QuotaService,
            "get_platform_capacity",
            return_value={"capacity_bytes": None},
        ):
            mock_set.return_value = True
            result = QuotaService.set_tenant_hard_limit("target-tenant", 200)
            assert result["hard_limit_bytes"] == 200 * GB
            # Should set hard_limit_editable = false
            editable_call = any(
                "KB_QUOTA_HARD_LIMIT_EDITABLE" in str(call) for call in mock_set.call_args_list
            )
            assert editable_call

    def test_rejects_tenant_quota_below_actual_usage(self):
        with patch.object(
            QuotaService, "get_usage", return_value={"total_bytes": 2 * GB}
        ), patch.object(
            QuotaService,
            "get_platform_capacity",
            return_value={"capacity_bytes": None},
        ):
            with pytest.raises(PlatformQuotaConflictError) as raised:
                QuotaService.set_tenant_hard_limit("target-tenant", limit_gb=1)

        assert raised.value.error == "TenantQuotaBelowUsage"
        assert raised.value.details["actual_usage_bytes"] == 2 * GB

    def test_rejects_tenant_quota_above_remaining_platform_capacity(self):
        with patch.object(
            QuotaService, "get_usage", return_value={"total_bytes": 0}
        ), patch.object(
            QuotaService,
            "get_platform_capacity",
            return_value={"capacity_bytes": 100 * GB},
        ), patch.object(
            QuotaService,
            "_get_allocation_state",
            return_value={
                "hard_limits": {"target-tenant": 50 * GB},
                "total_allocated_bytes": 90 * GB,
            },
        ):
            with pytest.raises(PlatformQuotaConflictError) as raised:
                QuotaService.set_tenant_hard_limit("target-tenant", limit_gb=70)

        assert raised.value.error == "PlatformCapacityExceeded"
        assert raised.value.details["remaining_allocatable_bytes"] == 10 * GB

    def test_rejects_platform_capacity_below_existing_allocations(self):
        with patch.object(
            QuotaService,
            "_get_allocation_state",
            return_value={"total_allocated_bytes": 200 * GB},
        ):
            with pytest.raises(PlatformQuotaConflictError) as raised:
                QuotaService.set_platform_capacity(100)

        assert raised.value.error == "PlatformCapacityBelowAllocation"

    def test_platform_overview_marks_legacy_unmanaged_tenants(self):
        with patch.object(
            QuotaService,
            "get_platform_capacity",
            return_value={"capacity_bytes": 100 * GB, "capacity_readable": "100.0 GB"},
        ), patch.object(
            QuotaService,
            "_get_allocation_state",
            return_value={
                "tenant_ids": ["managed", "legacy"],
                "hard_limits": {"managed": 40 * GB, "legacy": None},
                "total_allocated_bytes": 40 * GB,
                "unmanaged_tenant_count": 1,
            },
        ), patch.object(
            QuotaService,
            "get_usage",
            return_value={
                "total_bytes": 10 * GB,
                "warning_enabled": True,
                "tenant_warning_level": "normal",
            },
        ), patch("database.tenant_config_db.get_single_config_info", return_value={}):
            result = QuotaService.get_platform_overview()

        assert result["remaining_allocatable_bytes"] == 60 * GB
        assert result["allocation_percentage"] == 40
        assert result["unmanaged_tenant_count"] == 1
        assert result["capacity_management_enforced"] is False

    def test_delete_tenant_hard_limit(self):
        with patch.object(QuotaService, "_delete_tenant_config") as mock_del:
            mock_del.return_value = True
            result = QuotaService.delete_tenant_hard_limit("target-tenant")
            assert result is True

    def test_platform_overview_respects_tenant_warning_switch(self):
        with patch.object(
            QuotaService,
            "get_platform_capacity",
            return_value={"capacity_bytes": None, "capacity_readable": None},
        ), patch(
            "database.tenant_config_db.get_all_tenant_ids",
            return_value=["tenant-1"],
        ), patch(
            "database.tenant_config_db.get_single_config_info",
            side_effect=[
                {"config_value": str(100 * GB)},
                {"config_value": "Tenant 1"},
            ],
        ), patch.object(
            QuotaService,
            "get_usage",
            return_value={
                "total_bytes": 90 * GB,
                "warning_enabled": False,
                "tenant_warning_level": "critical",
            },
        ):
            result = QuotaService.get_platform_overview()

        tenant = result["tenants"][0]
        assert tenant["warning_enabled"] is False
        assert tenant["warning_level"] == "normal"


# ═══════════════════════════════════════════════════════════════════════
# Task 11.4 — Usage Tracking & Cache
# ═══════════════════════════════════════════════════════════════════════

class TestUsageTracking:
    """Tests for get_usage with caching and per-KB breakdown."""

    def test_get_usage_returns_cached_within_ttl(self, quota_service):
        _usage_cache.clear()
        with patch.object(quota_service, "_compute_usage") as mock_compute:
            mock_compute.return_value = {
                "total_bytes": 50 * GB,
                "total_readable": "50.0 GB",
                "kb_count": 2,
                "file_count": 10,
                "hard_limit_bytes": 100 * GB,
                "usage_pct": 50.0,
                "tenant_warning_level": "normal",
                "warning_enabled": True,
                "breakdown": [],
                "soft_allocated_total_bytes": 0,
                "soft_allocated_readable": "0 B",
                "oversubscription_ratio": 0,
                "kbs_with_quota": 0,
            }

            result1 = quota_service.get_usage(force_refresh=False)
            result2 = quota_service.get_usage(force_refresh=False)
            # Second call should use cache
            assert mock_compute.call_count == 1
            assert result1["total_bytes"] == 50 * GB

        _usage_cache.clear()

    def test_get_usage_force_refresh_bypasses_cache(self, quota_service):
        _usage_cache.clear()
        with patch.object(quota_service, "_compute_usage") as mock_compute:
            mock_compute.return_value = {
                "total_bytes": 50 * GB,
                "total_readable": "50.0 GB",
                "kb_count": 2,
                "file_count": 10,
                "hard_limit_bytes": 100 * GB,
                "usage_pct": 50.0,
                "tenant_warning_level": "normal",
                "warning_enabled": True,
                "breakdown": [],
            }

            quota_service.get_usage(force_refresh=False)
            quota_service.get_usage(force_refresh=True)
            assert mock_compute.call_count == 2

        _usage_cache.clear()

    def test_get_usage_detail_includes_breakdown(self, quota_service):
        _usage_cache.clear()
        with patch.object(quota_service, "_compute_usage") as mock_compute:
            mock_compute.return_value = {
                "total_bytes": 50 * GB,
                "total_readable": "50.0 GB",
                "kb_count": 2,
                "file_count": 10,
                "hard_limit_bytes": 100 * GB,
                "usage_pct": 50.0,
                "tenant_warning_level": "normal",
                "warning_enabled": True,
                "breakdown": [{"knowledge_id": 1}],
                "soft_allocated_total_bytes": 30 * GB,
                "oversubscription_ratio": 0.3,
                "kbs_with_quota": 1,
            }

            result = quota_service.get_usage(force_refresh=True, detail=True)
            assert "breakdown" in result
            assert len(result["breakdown"]) == 1

        _usage_cache.clear()

    def test_compute_usage_empty_tenant(self, quota_service, mock_knowledge_db):
        mock_knowledge_db["get_knowledge_info_by_tenant_id"].return_value = []
        with patch.object(quota_service, "get_hard_limit") as mock_limit, \
             patch.object(quota_service, "get_warning_config") as mock_warning, \
             patch.object(quota_service, "get_quota_summary") as mock_summary, \
             patch("services.vectordatabase_service.get_vector_db_core") as mock_vdb:
            mock_limit.return_value = {"hard_limit_bytes": None, "hard_limit_readable": None}
            mock_warning.return_value = {"warning_enabled": True, "warning_threshold_pct": 80, "critical_threshold_pct": 95}
            mock_summary.return_value = {
                "soft_allocated_total_bytes": 0,
                "soft_allocated_readable": "0 B",
                "oversubscription_ratio": None,
                "kb_count": 0,
                "kbs_with_quota": 0,
            }
            mock_vdb.return_value = MagicMock()

            result = quota_service._compute_usage()
            assert result["total_bytes"] == 0
            assert result["kb_count"] == 0
            assert result["file_count"] == 0

    def test_compute_usage_counts_all_tenant_kbs(self, quota_service, mock_knowledge_db):
        mock_knowledge_db["get_knowledge_info_by_tenant_id"].return_value = [
            {
                "knowledge_id": 1,
                "knowledge_name": "Visible KB",
                "index_name": "visible-kb",
                "quota_limit_bytes": 10 * GB,
            },
            {
                "knowledge_id": 2,
                "knowledge_name": "Hidden KB",
                "index_name": "hidden-kb",
                "quota_limit_bytes": 10 * GB,
            },
        ]
        mock_vdb = MagicMock()
        mock_vdb.get_indices_detail.return_value = {
            "visible-kb": {
                "base_info": {"store_size": "2 GB", "doc_count": 1},
            },
            "hidden-kb": {
                "base_info": {"store_size": "3 GB", "doc_count": 2},
            },
        }

        with patch.object(quota_service, "get_hard_limit") as mock_limit, \
             patch.object(quota_service, "get_warning_config") as mock_warning, \
             patch.object(quota_service, "get_quota_summary") as mock_summary, \
             patch("services.vectordatabase_service.get_vector_db_core", return_value=mock_vdb):
            mock_limit.return_value = {
                "hard_limit_bytes": 10 * GB,
                "hard_limit_readable": "10 GB",
            }
            mock_warning.return_value = {
                "warning_enabled": True,
                "warning_threshold_pct": 80,
                "critical_threshold_pct": 95,
            }
            mock_summary.return_value = {
                "soft_allocated_total_bytes": 20 * GB,
                "soft_allocated_readable": "20 GB",
                "oversubscription_ratio": 2,
                "kb_count": 2,
                "kbs_with_quota": 2,
            }

            result = quota_service._compute_usage()

        assert result["total_bytes"] == 5 * GB
        assert result["file_count"] == 3
        assert {item["index_name"] for item in result["breakdown"]} == {
            "visible-kb",
            "hidden-kb",
        }
