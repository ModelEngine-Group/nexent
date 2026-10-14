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
    DEFAULT_WARNING_THRESHOLD,
    DEFAULT_CRITICAL_THRESHOLD,
    _usage_cache,
)
from consts.error_code import ErrorCode
from consts.exceptions import AppException, PlatformQuotaConflictError


@pytest.fixture
def mock_tenant_config_db():
    """Mock tenant configuration persistence used by QuotaService."""
    with patch("services.quota_service.get_single_config_info") as mock_get, \
         patch("services.quota_service.get_configs_by_tenant_id_and_keys") as mock_get_many, \
         patch("services.quota_service.insert_config") as mock_insert, \
         patch("services.quota_service.update_config_by_tenant_config_id") as mock_update, \
         patch("services.quota_service.delete_config_by_tenant_config_id") as mock_delete:
        mock_get_many.return_value = {}
        yield {
            "get_single_config_info": mock_get,
            "get_configs_by_tenant_id_and_keys": mock_get_many,
            "insert_config": mock_insert,
            "update_config_by_tenant_config_id": mock_update,
            "delete_config_by_tenant_config_id": mock_delete,
        }


@pytest.fixture
def mock_knowledge_db():
    """Mock knowledge base persistence used by QuotaService."""
    with patch("services.quota_service.get_knowledge_info_by_tenant_id") as mock_list, \
         patch("services.quota_service.update_knowledge_record") as mock_update, \
         patch("services.quota_service.get_committed_bytes_by_kb", return_value={}) as mock_kb_bytes, \
         patch("services.quota_service.get_tenant_committed_source_bytes", return_value=0) as mock_tenant_bytes, \
         patch("services.quota_service.get_private_knowledge_info_by_tenant_id") as mock_private_list, \
         patch("services.quota_service.get_private_knowledge_info_by_creator") as mock_creator_list, \
         patch("services.quota_service.get_user_email_map") as mock_email_map:
        mock_creator_list.return_value = []
        yield {
            "get_knowledge_info_by_tenant_id": mock_list,
            "update_knowledge_record": mock_update,
            "get_committed_bytes_by_kb": mock_kb_bytes,
            "get_tenant_committed_source_bytes": mock_tenant_bytes,
            "get_private_knowledge_info_by_tenant_id": mock_private_list,
            "get_private_knowledge_info_by_creator": mock_creator_list,
            "get_user_email_map": mock_email_map,
        }


@pytest.fixture
def quota_service():
    """Create a quota service for an isolated test tenant."""
    return QuotaService("test-tenant-id", "test-user-id")


@pytest.fixture
def sample_kb_list():
    """Return representative knowledge bases with mixed quota settings."""
    return [
        {
            "knowledge_id": 1,
            "index_name": "kb-1-abc123",
            "knowledge_name": "Research Docs",
            "quota_limit_bytes": 30 * GB,
        },
        {
            "knowledge_id": 2,
            "index_name": "kb-2-def456",
            "knowledge_name": "Sales Docs",
            "quota_limit_bytes": None,
        },
        {
            "knowledge_id": 3,
            "index_name": "kb-3-ghi789",
            "knowledge_name": "Ops Docs",
            "quota_limit_bytes": 10 * GB,
        },
    ]


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


class TestStoreSizeParsing:
    @pytest.mark.parametrize(
        ("raw_value", "expected"),
        [
            (None, 0),
            (1024, 1024),
            ("", 0),
            ("invalid", 0),
            ("1 MB", 1024 * 1024),
            ("2 KB", 2 * 1024),
            ("3 B", 3),
            ("1 XB", 0),
            ("not-a-number MB", 0),
        ],
    )
    def test_parse_store_size(self, raw_value, expected):
        assert QuotaService._parse_store_size(raw_value) == expected


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

    def test_get_platform_capacity_ignores_invalid_stored_value(self):
        with patch(
            "database.tenant_config_db.get_single_config_info",
            return_value={"config_value": "invalid"},
        ):
            result = QuotaService.get_platform_capacity()

        assert result == {"capacity_bytes": None, "capacity_readable": None}

    def test_quota_input_supports_mb(self):
        assert QuotaService._quota_input_to_bytes(None, 100) == 100 * 1024 * 1024

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

    def test_set_tenant_hard_limit_none_removes_platform_management(self):
        with patch.object(QuotaService, "_delete_tenant_config") as mock_delete:
            result = QuotaService.set_tenant_hard_limit("target-tenant")

        assert result == {
            "hard_limit_bytes": None,
            "hard_limit_readable": None,
        }
        assert mock_delete.call_count == 2

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

    def test_allocation_state_excludes_virtual_tenants(self):
        from consts.const import ASSET_OWNER_TENANT_ID, DEFAULT_TENANT_ID

        with patch(
            "database.tenant_config_db.get_all_tenant_ids",
            return_value=["tenant-1", DEFAULT_TENANT_ID, "", ASSET_OWNER_TENANT_ID],
        ), patch(
            "database.tenant_config_db.get_single_config_info",
            return_value={"config_value": str(20 * GB)},
        ) as mock_get_config:
            result = QuotaService._get_allocation_state(ASSET_OWNER_TENANT_ID)

        assert result["tenant_ids"] == ["tenant-1"]
        assert result["total_allocated_bytes"] == 20 * GB
        mock_get_config.assert_called_once_with("tenant-1", "KB_QUOTA_TENANT_HARD_LIMIT_BYTES")

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

    def test_platform_overview_tolerates_tenant_usage_failure(self):
        with patch.object(
            QuotaService,
            "get_platform_capacity",
            return_value={"capacity_bytes": None, "capacity_readable": None},
        ), patch.object(
            QuotaService,
            "_get_allocation_state",
            return_value={
                "tenant_ids": ["tenant-1"],
                "hard_limits": {"tenant-1": 10 * GB},
                "total_allocated_bytes": 10 * GB,
                "unmanaged_tenant_count": 0,
            },
        ), patch.object(
            QuotaService, "get_usage", side_effect=RuntimeError("usage failed")
        ), patch(
            "database.tenant_config_db.get_single_config_info", return_value={}
        ):
            result = QuotaService.get_platform_overview()

        assert result["tenants"][0]["actual_bytes"] == 0
        assert result["tenants"][0]["warning_enabled"] is False
        assert result["tenants"][0]["warning_level"] == "normal"

    def test_platform_overview_aggregates_available_es_physical_usage(self):
        with patch.object(
            QuotaService,
            "get_platform_capacity",
            return_value={"capacity_bytes": 100 * GB, "capacity_readable": "100.0 GB"},
        ), patch.object(
            QuotaService,
            "_get_allocation_state",
            return_value={
                "tenant_ids": ["tenant-1", "tenant-2"],
                "hard_limits": {"tenant-1": 40 * GB, "tenant-2": 40 * GB},
                "total_allocated_bytes": 80 * GB,
                "unmanaged_tenant_count": 0,
            },
        ), patch.object(
            QuotaService,
            "get_usage",
            side_effect=[
                {
                    "total_bytes": 10 * GB,
                    "es_physical_bytes": 2 * GB,
                    "warning_enabled": True,
                    "tenant_warning_level": "normal",
                },
                {
                    "total_bytes": 5 * GB,
                    "es_physical_bytes": 3 * GB,
                    "warning_enabled": True,
                    "tenant_warning_level": "normal",
                },
            ],
        ), patch(
            "database.tenant_config_db.get_single_config_info", return_value={}
        ):
            result = QuotaService.get_platform_overview()

        assert result["total_es_physical_bytes"] == 5 * GB
        assert [tenant["es_physical_bytes"] for tenant in result["tenants"]] == [2 * GB, 3 * GB]


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
             patch("management.services.knowledge_base.service.get_vector_db_core") as mock_vdb:
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
             patch("management.services.knowledge_base.service.get_vector_db_core", return_value=mock_vdb):
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

        assert result["total_bytes"] == 0
        assert result["file_count"] == 3
        assert {item["index_name"] for item in result["breakdown"]} == {
            "visible-kb",
            "hidden-kb",
        }

    @pytest.mark.parametrize(
        ("es_size", "kb_source_bytes", "expected_bytes"),
        [
            ("200 MB", 300 * 1024 * 1024, 300 * 1024 * 1024),
            ("0 B", 300 * 1024 * 1024, 300 * 1024 * 1024),
            ("200 MB", 0, 0),
        ],
    )
    def test_compute_usage_uses_source_bytes_and_reports_es_separately(
        self,
        quota_service,
        mock_knowledge_db,
        es_size,
        kb_source_bytes,
        expected_bytes,
    ):
        mock_knowledge_db["get_knowledge_info_by_tenant_id"].return_value = [{
            "knowledge_id": 7,
            "knowledge_name": "Composite KB",
            "index_name": "composite-kb",
            "quota_limit_bytes": 1024 * 1024 * 1024,
        }]
        mock_knowledge_db["get_committed_bytes_by_kb"].return_value = {
            7: kb_source_bytes,
        }
        mock_knowledge_db["get_tenant_committed_source_bytes"].return_value = kb_source_bytes
        mock_vdb = MagicMock()
        mock_vdb.get_indices_detail.return_value = {
            "composite-kb": {
                "base_info": {"store_size": es_size, "doc_count": 4},
            },
        }

        with patch.object(
            quota_service,
            "get_hard_limit",
            return_value={
                "hard_limit_bytes": 1024 * 1024 * 1024,
                "hard_limit_readable": "1.0 GB",
            },
        ), patch.object(
            quota_service,
            "get_warning_config",
            return_value={
                "warning_enabled": True,
                "warning_threshold_pct": 80,
                "critical_threshold_pct": 95,
            },
        ), patch.object(
            quota_service,
            "get_quota_summary",
            return_value={
                "soft_allocated_total_bytes": 1024 * 1024 * 1024,
                "soft_allocated_readable": "1.0 GB",
                "oversubscription_ratio": 1,
                "kb_count": 1,
                "kbs_with_quota": 1,
            },
        ), patch(
            "management.services.knowledge_base.service.get_vector_db_core",
            return_value=mock_vdb,
        ):
            result = quota_service._compute_usage()

        assert result["total_bytes"] == expected_bytes
        assert result["breakdown"][0]["actual_bytes"] == expected_bytes
        assert result["es_physical_bytes"] == quota_service._parse_store_size(es_size)
        assert result["breakdown"][0]["es_physical_bytes"] == quota_service._parse_store_size(es_size)
        assert result["file_count"] == 4
        assert result["breakdown"][0]["file_count"] == 4

    def test_tenant_total_includes_all_active_ledger_rows(
        self,
        quota_service,
        mock_knowledge_db,
    ):
        mock_knowledge_db["get_knowledge_info_by_tenant_id"].return_value = [{
            "knowledge_id": 7,
            "knowledge_name": "Active KB",
            "index_name": "active-kb",
            "quota_limit_bytes": None,
        }]
        mock_knowledge_db["get_committed_bytes_by_kb"].return_value = {7: 300}
        mock_knowledge_db["get_tenant_committed_source_bytes"].return_value = 350
        mock_vdb = MagicMock()
        mock_vdb.get_indices_detail.return_value = {
            "active-kb": {"base_info": {"store_size": 200, "doc_count": 2}},
        }

        with patch.object(
            quota_service,
            "get_hard_limit",
            return_value={"hard_limit_bytes": None, "hard_limit_readable": None},
        ), patch.object(
            quota_service,
            "get_warning_config",
            return_value={
                "warning_enabled": True,
                "warning_threshold_pct": 80,
                "critical_threshold_pct": 95,
            },
        ), patch.object(
            quota_service,
            "get_quota_summary",
            return_value={
                "soft_allocated_total_bytes": 0,
                "soft_allocated_readable": "0 B",
                "oversubscription_ratio": None,
                "kb_count": 1,
                "kbs_with_quota": 0,
            },
        ), patch(
            "management.services.knowledge_base.service.get_vector_db_core",
            return_value=mock_vdb,
        ):
            result = quota_service._compute_usage()

        assert result["total_bytes"] == 350
        assert result["breakdown"][0]["actual_bytes"] == 300
        assert result["breakdown"][0]["usage_pct"] is None
        assert result["breakdown"][0]["kb_warning_level"] == "normal"

    def test_invalidate_usage_cache_is_tenant_scoped(self):
        _usage_cache.clear()
        _usage_cache["tenant-a"] = (0, {"total_bytes": 1})
        _usage_cache["tenant-b"] = (0, {"total_bytes": 2})

        QuotaService.invalidate_usage_cache("tenant-a")

        assert "tenant-a" not in _usage_cache
        assert "tenant-b" in _usage_cache
        QuotaService.invalidate_usage_cache()
        assert _usage_cache == {}

class TestPersonalKbCapacity:
    """Tests for personal KB quota config, aggregation, and enforcement."""

    def test_get_personal_user_quota_reads_config(
        self, quota_service, mock_tenant_config_db
    ):
        mock_tenant_config_db["get_single_config_info"].return_value = {
            "config_value": str(2 * GB)
        }

        assert quota_service.get_personal_user_quota("user-1") == 2 * GB
        mock_tenant_config_db["get_single_config_info"].assert_called_with(
            "test-tenant-id", "PERSONAL_KB_QUOTA_user-1"
        )

    def test_get_personal_user_quota_returns_none_for_missing_config(
        self, quota_service, mock_tenant_config_db
    ):
        mock_tenant_config_db["get_single_config_info"].return_value = None

        assert quota_service.get_personal_user_quota("user-1") is None

    def test_set_personal_user_quota_updates_config(
        self, quota_service, mock_tenant_config_db, mock_knowledge_db
    ):
        mock_knowledge_db[
            "get_private_knowledge_info_by_tenant_id"
        ].return_value = []
        mock_tenant_config_db["get_single_config_info"].return_value = None
        mock_tenant_config_db["insert_config"].return_value = True

        result = quota_service.set_personal_user_quota(
            "user-1", quota_limit_bytes=2 * GB
        )

        assert result["user_id"] == "user-1"
        assert result["quota_limit_bytes"] == 2 * GB
        inserted = mock_tenant_config_db["insert_config"].call_args.args[0]
        assert inserted["config_key"] == "PERSONAL_KB_QUOTA_user-1"
        assert inserted["config_value"] == str(2 * GB)

    def test_set_personal_user_quota_keeps_legacy_non_strict_usage_mode(
        self, quota_service, mock_tenant_config_db
    ):
        mock_tenant_config_db["get_single_config_info"].return_value = None
        mock_tenant_config_db["insert_config"].return_value = True
        usage_data = {"kbs": [], "stats": {}}

        with patch.object(
            quota_service,
            "_get_personal_usage_data",
            return_value=usage_data,
        ) as get_usage:
            quota_service.set_personal_user_quota(
                "user-1", quota_limit_bytes=2 * GB
            )

        get_usage.assert_called_once_with(user_id="user-1", include_es=False)

    def test_set_personal_user_quota_unlimited_deletes_config(
        self, quota_service, mock_tenant_config_db
    ):
        mock_tenant_config_db["get_single_config_info"].return_value = {
            "tenant_config_id": 42
        }
        mock_tenant_config_db["delete_config_by_tenant_config_id"].return_value = True

        result = quota_service.set_personal_user_quota("user-1", unlimited=True)

        assert result["quota_limit_bytes"] is None
        mock_tenant_config_db[
            "delete_config_by_tenant_config_id"
        ].assert_called_once_with(42)

    def test_get_personal_default_quota_reads_config(
        self, quota_service, mock_tenant_config_db
    ):
        mock_tenant_config_db["get_single_config_info"].return_value = {
            "config_value": str(3 * GB)
        }

        assert quota_service.get_personal_default_quota() == 3 * GB
        mock_tenant_config_db["get_single_config_info"].assert_called_with(
            "test-tenant-id", "PERSONAL_KB_QUOTA_DEFAULT"
        )

    def test_set_personal_default_quota_updates_config(
        self, quota_service, mock_tenant_config_db
    ):
        mock_tenant_config_db["get_single_config_info"].return_value = {
            "tenant_config_id": 7,
            "config_value": "old",
        }
        mock_tenant_config_db["update_config_by_tenant_config_id"].return_value = True

        result = quota_service.set_personal_default_quota(
            quota_limit_bytes=5 * GB
        )

        assert result["quota_limit_bytes"] == 5 * GB
        mock_tenant_config_db[
            "update_config_by_tenant_config_id"
        ].assert_called_once_with(7, str(5 * GB))

    def test_set_personal_default_quota_unlimited_deletes_config(
        self, quota_service, mock_tenant_config_db
    ):
        mock_tenant_config_db["get_single_config_info"].return_value = {
            "tenant_config_id": 8
        }
        mock_tenant_config_db["delete_config_by_tenant_config_id"].return_value = True

        result = quota_service.set_personal_default_quota(unlimited=True)

        assert result["quota_limit_bytes"] is None
        mock_tenant_config_db[
            "delete_config_by_tenant_config_id"
        ].assert_called_once_with(8)

    def test_effective_quota_individual_wins_over_default(
        self, quota_service, mock_tenant_config_db
    ):
        def _config(tenant_id, key):
            if key == "PERSONAL_KB_QUOTA_user-1":
                return {"config_value": str(10 * GB)}
            if key == "PERSONAL_KB_QUOTA_DEFAULT":
                return {"config_value": str(5 * GB)}
            return None

        mock_tenant_config_db["get_single_config_info"].side_effect = _config

        assert quota_service._get_personal_effective_quota("user-1") == (
            10 * GB,
            "individual",
        )

    def test_effective_quota_falls_back_to_default(
        self, quota_service, mock_tenant_config_db
    ):
        def _config(tenant_id, key):
            if key == "PERSONAL_KB_QUOTA_DEFAULT":
                return {"config_value": str(5 * GB)}
            return None

        mock_tenant_config_db["get_single_config_info"].side_effect = _config

        assert quota_service._get_personal_effective_quota("user-1") == (
            5 * GB,
            "default",
        )

    def test_effective_quota_is_unlimited_when_no_config(
        self, quota_service, mock_tenant_config_db
    ):
        mock_tenant_config_db["get_single_config_info"].return_value = None

        assert quota_service._get_personal_effective_quota("user-1") == (
            None,
            "unlimited",
        )

    def test_effective_quota_map_reads_all_user_configs_in_one_query(
        self, quota_service, mock_tenant_config_db
    ):
        mock_tenant_config_db[
            "get_configs_by_tenant_id_and_keys"
        ].return_value = {
            "PERSONAL_KB_QUOTA_user-1": str(10 * GB),
            "PERSONAL_KB_QUOTA_DEFAULT": str(5 * GB),
        }

        resolved, default_quota = quota_service._get_personal_effective_quota_map(
            {"user-1", "user-2"}
        )

        assert resolved == {
            "user-1": (10 * GB, "individual"),
            "user-2": (5 * GB, "default"),
        }
        assert default_quota == 5 * GB
        mock_tenant_config_db[
            "get_configs_by_tenant_id_and_keys"
        ].assert_called_once_with(
            "test-tenant-id",
            [
                "PERSONAL_KB_QUOTA_user-1",
                "PERSONAL_KB_QUOTA_user-2",
                "PERSONAL_KB_QUOTA_DEFAULT",
            ],
        )

    def test_list_personal_capacity_users_sorts_and_paginates(
        self, quota_service, mock_knowledge_db, mock_tenant_config_db
    ):
        kb_list = [
            {
                "knowledge_id": 1,
                "index_name": "kb-a",
                "created_by": "user-a",
                "knowledge_name": "A",
            },
            {
                "knowledge_id": 2,
                "index_name": "kb-b",
                "created_by": "user-a",
                "knowledge_name": "B",
            },
            {
                "knowledge_id": 3,
                "index_name": "kb-c",
                "created_by": "user-b",
                "knowledge_name": "C",
            },
        ]
        mock_knowledge_db[
            "get_private_knowledge_info_by_tenant_id"
        ].return_value = kb_list
        mock_knowledge_db["get_committed_bytes_by_kb"].return_value = {
            1: 1 * GB,
            2: 2 * GB,
            3: 4 * GB,
        }
        mock_knowledge_db["get_user_email_map"].return_value = {
            "user-a": "beta@example.com",
            "user-b": "alpha@example.com",
        }
        mock_vdb = MagicMock()
        mock_vdb.get_indices_detail.return_value = {
            "kb-a": {
                "base_info": {"store_size": "1 GB", "doc_count": 1}
            },
            "kb-b": {
                "base_info": {"store_size": "2 GB", "doc_count": 2}
            },
            "kb-c": {
                "base_info": {"store_size": "4 GB", "doc_count": 4}
            },
        }

        def _config(tenant_id, key):
            if key == "PERSONAL_KB_QUOTA_user-a":
                return {"config_value": str(2 * GB)}
            if key == "PERSONAL_KB_QUOTA_user-b":
                return {"config_value": str(4 * GB)}
            return None

        mock_tenant_config_db["get_single_config_info"].side_effect = _config
        mock_tenant_config_db[
            "get_configs_by_tenant_id_and_keys"
        ].return_value = {
            "PERSONAL_KB_QUOTA_user-a": str(2 * GB),
            "PERSONAL_KB_QUOTA_user-b": str(4 * GB),
        }

        with patch(
            "management.services.knowledge_base.service.get_vector_db_core",
            return_value=mock_vdb,
        ):
            by_total = quota_service.list_personal_capacity_users(
                page=1,
                page_size=10,
                sort_by="total_bytes",
                sort_order="desc",
            )
            by_name = quota_service.list_personal_capacity_users(
                page=1,
                page_size=1,
                sort_by="user_name",
                sort_order="asc",
            )
            by_kb_count = quota_service.list_personal_capacity_users(
                page=1,
                page_size=10,
                sort_by="kb_count",
                sort_order="desc",
            )
            by_quota = quota_service.list_personal_capacity_users(
                page=1,
                page_size=10,
                sort_by="quota_limit_bytes",
                sort_order="asc",
            )
            by_keyword = quota_service.list_personal_capacity_users(
                page=1,
                page_size=10,
                sort_by="total_bytes",
                sort_order="desc",
                keyword="BETA",
            )
            by_usage_rate = quota_service.list_personal_capacity_users(
                page=1,
                page_size=10,
                sort_by="usage_rate",
                sort_order="asc",
            )

        assert [item["user_id"] for item in by_total["items"]] == [
            "user-b",
            "user-a",
        ]
        assert by_name["items"][0]["user_id"] == "user-b"
        assert by_name["total_pages"] == 2
        assert [item["user_id"] for item in by_kb_count["items"]] == [
            "user-a",
            "user-b",
        ]
        assert [item["user_id"] for item in by_quota["items"]] == [
            "user-a",
            "user-b",
        ]
        assert [item["user_id"] for item in by_keyword["items"]] == ["user-a"]
        assert by_keyword["total"] == 1
        assert [item["user_id"] for item in by_usage_rate["items"]] == [
            "user-b",
            "user-a",
        ]
        user_a = next(
            item for item in by_total["items"] if item["user_id"] == "user-a"
        )
        assert user_a["kb_count"] == 2
        assert user_a["total_bytes"] == 3 * GB
        assert user_a["usage_rate"] == 150.0
        assert next(
            item for item in by_usage_rate["items"] if item["user_id"] == "user-b"
        )["usage_rate"] == 100.0

    def test_get_personal_capacity_summary_aggregates(
        self, quota_service, mock_knowledge_db, mock_tenant_config_db
    ):
        kb_list = [
            {
                "knowledge_id": 1,
                "index_name": "kb-a",
                "created_by": "user-a",
                "knowledge_name": "A",
            },
            {
                "knowledge_id": 2,
                "index_name": "kb-b",
                "created_by": "user-a",
                "knowledge_name": "B",
            },
            {
                "knowledge_id": 3,
                "index_name": "kb-c",
                "created_by": "user-b",
                "knowledge_name": "C",
            },
            {
                "knowledge_id": 4,
                "index_name": "kb-d",
                "created_by": "user-c",
                "knowledge_name": "D",
            },
        ]
        mock_knowledge_db[
            "get_private_knowledge_info_by_tenant_id"
        ].return_value = kb_list
        mock_knowledge_db["get_committed_bytes_by_kb"].return_value = {
            1: 1 * GB,
            2: 2 * GB,
            3: 4 * GB,
            4: 8 * GB,
        }
        mock_vdb = MagicMock()
        mock_vdb.get_indices_detail.return_value = {
            "kb-a": {"base_info": {"store_size": "1 GB"}},
            "kb-b": {"base_info": {"store_size": "2 GB"}},
            "kb-c": {"base_info": {"store_size": "4 GB"}},
            "kb-d": {"base_info": {"store_size": "8 GB"}},
        }

        def _config(tenant_id, key):
            if key == "PERSONAL_KB_QUOTA_user-a":
                return {"config_value": str(10 * GB)}
            if key == "PERSONAL_KB_QUOTA_user-b":
                return {"config_value": str(20 * GB)}
            if key == "PERSONAL_KB_QUOTA_DEFAULT":
                return {"config_value": str(5 * GB)}
            return None

        mock_tenant_config_db["get_single_config_info"].side_effect = _config
        mock_tenant_config_db[
            "get_configs_by_tenant_id_and_keys"
        ].return_value = {
            "PERSONAL_KB_QUOTA_user-a": str(10 * GB),
            "PERSONAL_KB_QUOTA_user-b": str(20 * GB),
            "PERSONAL_KB_QUOTA_DEFAULT": str(5 * GB),
        }

        with patch(
            "management.services.knowledge_base.service.get_vector_db_core",
            return_value=mock_vdb,
        ):
            result = quota_service.get_personal_capacity_summary()

        assert result["user_count"] == 3
        assert result["kb_count"] == 4
        assert result["total_bytes"] == 15 * GB
        assert result["allocated_quota_bytes"] == 35 * GB
        assert result["default_quota_bytes"] == 5 * GB

    def test_pending_personal_upload_bytes_deduplicates_chunks_and_ledger_entries(
        self, quota_service
    ):
        data = [
            {"path_or_url": "knowledge_base/a.txt", "file_size": 100},
            {"path_or_url": "knowledge_base/a.txt", "file_size": 100},
            {"path_or_url": "knowledge_base/b.txt", "file_size": "50"},
            {"file_size": -10},
            {"file_size": None},
            {"file_size": "bad"},
            "not-a-dict",
            {"other": 1},
        ]

        with patch(
            "services.quota_service.get_committed_source_bytes_by_paths",
            return_value={"knowledge_base/b.txt": 50},
        ) as get_committed:
            result = quota_service.get_pending_personal_upload_bytes(
                data,
                {"knowledge_id": 1},
            )

        assert result == 100
        get_committed.assert_called_once_with(
            tenant_id="test-tenant-id",
            knowledge_id=1,
            paths={
                "knowledge_base/a.txt": 100,
                "knowledge_base/b.txt": 50,
            },
        )

    def test_parse_quota_value_handles_none_and_invalid(self):
        assert QuotaService._parse_quota_value(None) is None
        assert QuotaService._parse_quota_value("128") == 128
        assert QuotaService._parse_quota_value("bad") == 0
        assert QuotaService._parse_quota_value("   ") == 0

    def test_personal_usage_includes_source_storage(
        self, quota_service, mock_knowledge_db
    ):
        kbs = [
            {
                "knowledge_id": 1,
                "index_name": "kb-a",
                "created_by": "user-1",
            }
        ]
        mock_knowledge_db[
            "get_private_knowledge_info_by_tenant_id"
        ].return_value = kbs
        mock_knowledge_db["get_committed_bytes_by_kb"].return_value = {1: 1 * GB}
        mock_vdb = MagicMock()
        mock_vdb.get_indices_detail.return_value = {
            "kb-a": {"base_info": {"store_size": "4 GB"}}
        }

        with patch(
            "management.services.knowledge_base.service.get_vector_db_core",
            return_value=mock_vdb,
        ):
            result = quota_service._get_personal_usage_data(strict=True)

        assert result["stats"]["kb-a"] == 1 * GB
        assert result["details"]["kb-a"]["store_size_bytes"] == 4 * GB
        assert result["details"]["kb-a"]["source_size_bytes"] == 1 * GB
        assert result["details"]["kb-a"]["total_size_bytes"] == 1 * GB
        assert result["total_es_bytes"] == 4 * GB

    def test_personal_usage_strict_allows_missing_es_index(
        self, quota_service, mock_knowledge_db, mock_tenant_config_db
    ):
        mock_knowledge_db[
            "get_private_knowledge_info_by_tenant_id"
        ].return_value = [
            {"knowledge_id": 1, "index_name": "missing-kb", "created_by": "user-1"}
        ]
        mock_knowledge_db[
            "get_private_knowledge_info_by_creator"
        ].return_value = mock_knowledge_db[
            "get_private_knowledge_info_by_tenant_id"
        ].return_value
        mock_vdb = MagicMock()
        mock_vdb.get_indices_detail.return_value = {}

        with patch(
            "management.services.knowledge_base.service.get_vector_db_core",
            return_value=mock_vdb,
        ):
            quota_service.check_personal_user_quota("user-1", 1)

    def test_set_personal_user_quota_below_usage_rejected(
        self, quota_service, mock_knowledge_db, mock_tenant_config_db
    ):
        mock_knowledge_db[
            "get_private_knowledge_info_by_tenant_id"
        ].return_value = [
            {
                "knowledge_id": 1,
                "index_name": "kb-a",
                "created_by": "user-1",
            }
        ]
        mock_knowledge_db[
            "get_private_knowledge_info_by_creator"
        ].return_value = mock_knowledge_db[
            "get_private_knowledge_info_by_tenant_id"
        ].return_value
        mock_knowledge_db["get_committed_bytes_by_kb"].return_value = {1: 10 * GB}
        mock_tenant_config_db["get_single_config_info"].return_value = None
        mock_vdb = MagicMock()
        mock_vdb.get_indices_detail.return_value = {
            "kb-a": {"base_info": {"store_size": "10 GB"}}
        }

        with patch(
            "management.services.knowledge_base.service.get_vector_db_core",
            return_value=mock_vdb,
        ):
            with pytest.raises(AppException, match="below current usage") as raised:
                quota_service.set_personal_user_quota(
                    "user-1", quota_limit_bytes=5 * GB
                )

            assert raised.value.error_code == ErrorCode.TENANT_PERSONAL_KB_QUOTA_BELOW_USAGE

    def _mock_personal_usage(self, mock_knowledge_db, kbs, stats):
        mock_knowledge_db[
            "get_private_knowledge_info_by_tenant_id"
        ].return_value = kbs
        mock_knowledge_db[
            "get_private_knowledge_info_by_creator"
        ].return_value = kbs
        mock_vdb = MagicMock()
        mock_vdb.get_indices_detail.return_value = {
            index_name: {"base_info": {"store_size": store_size}}
            for index_name, store_size in stats.items()
        }
        source_bytes_by_kb = {
            kb["knowledge_id"]: QuotaService._parse_store_size(store_size)
            for kb, store_size in zip(kbs, stats.values())
        }
        mock_knowledge_db["get_committed_bytes_by_kb"].return_value = source_bytes_by_kb
        mock_knowledge_db["get_tenant_committed_source_bytes"].return_value = sum(
            source_bytes_by_kb.values()
        )
        return mock_vdb

    def test_check_quota_tenant_hard_limit_exceeded(
        self, quota_service, mock_knowledge_db
    ):
        kbs = [
            {
                "knowledge_id": 1,
                "index_name": "kb-a",
                "created_by": "user-1",
            }
        ]
        mock_vdb = self._mock_personal_usage(
            mock_knowledge_db, kbs, {"kb-a": "4 GB"}
        )

        with patch(
            "management.services.knowledge_base.service.get_vector_db_core",
            return_value=mock_vdb,
        ), patch.object(
            quota_service,
            "get_hard_limit",
            return_value={"hard_limit_bytes": 5 * GB},
        ), patch.object(
            quota_service,
            "_get_personal_effective_quota",
            return_value=(None, "unlimited"),
        ):
            with pytest.raises(
                AppException,
                match="Tenant personal KB storage full",
            ):
                quota_service.check_personal_kb_quota(
                    "user-1", 2 * GB
                )

    def test_check_quota_user_quota_exceeded(
        self, quota_service, mock_knowledge_db
    ):
        kbs = [
            {
                "knowledge_id": 1,
                "index_name": "kb-a",
                "created_by": "user-1",
            }
        ]
        mock_vdb = self._mock_personal_usage(
            mock_knowledge_db, kbs, {"kb-a": "4 GB"}
        )

        with patch(
            "management.services.knowledge_base.service.get_vector_db_core",
            return_value=mock_vdb,
        ), patch.object(
            quota_service,
            "get_hard_limit",
            return_value={"hard_limit_bytes": None},
        ), patch.object(
            quota_service,
            "_get_personal_effective_quota",
            return_value=(5 * GB, "individual"),
        ):
            with pytest.raises(
                AppException, match="Personal KB quota exceeded"
            ):
                quota_service.check_personal_kb_quota(
                    "user-1", 2 * GB
                )

    def test_check_personal_user_quota_exceeded(
        self, quota_service, mock_knowledge_db
    ):
        kbs = [
            {
                "knowledge_id": 1,
                "index_name": "kb-a",
                "created_by": "user-1",
            }
        ]
        mock_vdb = self._mock_personal_usage(
            mock_knowledge_db, kbs, {"kb-a": "4 GB"}
        )

        with patch(
            "management.services.knowledge_base.service.get_vector_db_core",
            return_value=mock_vdb,
        ), patch.object(
            quota_service,
            "_get_personal_effective_quota",
            return_value=(5 * GB, "individual"),
        ):
            with pytest.raises(
                AppException, match="Personal KB quota exceeded"
            ):
                quota_service.check_personal_user_quota(
                    "user-1", 2 * GB
                )

    def test_get_personal_self_capacity(self, quota_service, mock_knowledge_db):
        kbs = [
            {
                "knowledge_id": 1,
                "index_name": "kb-a",
                "created_by": "user-1",
            },
            {
                "knowledge_id": 2,
                "index_name": "kb-b",
                "created_by": "user-2",
            },
        ]
        mock_vdb = self._mock_personal_usage(
            mock_knowledge_db, kbs, {"kb-a": "4 GB", "kb-b": "2 GB"}
        )

        with patch(
            "management.services.knowledge_base.service.get_vector_db_core",
            return_value=mock_vdb,
        ), patch.object(
            quota_service,
            "_get_personal_effective_quota",
            return_value=(5 * GB, "individual"),
        ):
            result = quota_service.get_personal_self_capacity("user-1")

        assert result["used_bytes"] == 4 * GB
        assert result["quota_bytes"] == 5 * GB
        assert result["quota_source"] == "individual"
        assert result["usage_rate"] == 80.0
        assert result["is_over_quota"] is False
        assert result["kb_count"] == 1
        mock_knowledge_db[
            "get_private_knowledge_info_by_creator"
        ].assert_called_once_with("test-tenant-id", "user-1")
        mock_knowledge_db[
            "get_private_knowledge_info_by_tenant_id"
        ].assert_not_called()

    def test_check_quota_private_kb_quota_blocks_upload(
        self, quota_service, mock_knowledge_db
    ):
        kbs = [
            {
                "knowledge_id": 1,
                "index_name": "kb-a",
                "created_by": "user-1",
            }
        ]
        mock_vdb = self._mock_personal_usage(
            mock_knowledge_db, kbs, {"kb-a": "4 GB"}
        )
        kb_record = {
            "index_name": "kb-a",
            "quota_limit_bytes": 5 * GB,
        }

        with patch(
            "management.services.knowledge_base.service.get_vector_db_core",
            return_value=mock_vdb,
        ), patch.object(
            quota_service,
            "get_hard_limit",
            return_value={"hard_limit_bytes": None},
        ), patch.object(
            quota_service,
            "_get_personal_effective_quota",
            return_value=(None, "unlimited"),
        ):
            with pytest.raises(
                AppException,
                match="KB quota exceeded",
            ):
                quota_service.check_personal_kb_quota(
                    "user-1",
                    2 * GB,
                    kb_record=kb_record,
                )

    def test_check_quota_zero_quota_disables_uploads(
        self, quota_service, mock_knowledge_db
    ):
        kbs = [
            {
                "knowledge_id": 1,
                "index_name": "kb-a",
                "created_by": "user-1",
            }
        ]
        mock_vdb = self._mock_personal_usage(
            mock_knowledge_db, kbs, {"kb-a": "0 B"}
        )

        with patch(
            "management.services.knowledge_base.service.get_vector_db_core",
            return_value=mock_vdb,
        ), patch.object(
            quota_service,
            "get_hard_limit",
            return_value={"hard_limit_bytes": None},
        ), patch.object(
            quota_service,
            "_get_personal_effective_quota",
            return_value=(0, "individual"),
        ):
            with pytest.raises(
                AppException, match="disabled"
            ):
                quota_service.check_personal_kb_quota(
                    "user-1", 1
                )

    def test_check_quota_strict_es_failure_does_not_block_source_quota(
        self, quota_service, mock_knowledge_db, mock_tenant_config_db
    ):
        kbs = [
            {
                "knowledge_id": 1,
                "index_name": "kb-a",
                "created_by": "user-1",
            }
        ]
        mock_knowledge_db[
            "get_private_knowledge_info_by_tenant_id"
        ].return_value = kbs
        mock_tenant_config_db["get_single_config_info"].return_value = None

        with patch(
            "management.services.knowledge_base.service.get_vector_db_core",
            side_effect=RuntimeError("es down"),
        ):
            quota_service.check_personal_kb_quota("user-1", 1)

    def test_get_personal_usage_data_non_strict_es_failure_degrades(
        self, quota_service, mock_knowledge_db
    ):
        kbs = [
            {
                "knowledge_id": 1,
                "index_name": "kb-a",
                "created_by": "user-1",
            }
        ]
        mock_knowledge_db[
            "get_private_knowledge_info_by_tenant_id"
        ].return_value = kbs

        with patch(
            "management.services.knowledge_base.service.get_vector_db_core",
            side_effect=RuntimeError("es down"),
        ):
            result = quota_service._get_personal_usage_data(
                strict=False
            )

        assert result["total_bytes"] == 0
        assert result["stats"] == {"kb-a": 0}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, False),
        (-1, False),
        ("-1 MB", False),
        ("1", False),
        ("1 XB", False),
        ("bad MB", False),
        ("1 mb", True),
        ("0 B", True),
    ],
)
def test_personal_store_size_validation(value, expected):
    assert QuotaService._is_valid_store_size(value) is expected


def test_personal_storage_stats_skips_datamate_and_missing_index(
    quota_service, mock_knowledge_db
):
    kb_list = [
        {"knowledge_id": 1, "index_name": "kb-a", "knowledge_sources": "elasticsearch"},
        {"knowledge_id": 2, "index_name": "datamate-a", "knowledge_sources": "datamate"},
        {"knowledge_id": 3, "index_name": "", "knowledge_sources": "elasticsearch"},
    ]
    with patch(
        "management.services.knowledge_base.service.get_vector_db_core",
        return_value=MagicMock(
            get_indices_detail=MagicMock(
                return_value={"kb-a": {"base_info": {"store_size": "1 MB"}}}
            )
        ),
    ), patch(
        "services.quota_service.get_committed_bytes_by_kb",
        return_value={1: 10, 2: 20, 3: 30},
    ):
        result = quota_service._get_kb_storage_stats(
            kb_list, exclude_datamate=True
        )

    assert result["stats"] == {"kb-a": 10, "datamate-a": 20}
    assert result["details"]["datamate-a"]["store_size_bytes"] == 0
    assert result["details"]["kb-a"]["source_size_bytes"] == 10


@pytest.mark.parametrize(
    "detail",
    [None, {"error": "ES error"}, {"base_info": {}}, {"base_info": {"store_size": "bad"}}],
)
def test_personal_storage_stats_strict_allows_invalid_es_detail(quota_service, detail):
    vdb = MagicMock()
    vdb.get_indices_detail.return_value = {"kb-a": detail}
    with patch(
        "management.services.knowledge_base.service.get_vector_db_core", return_value=vdb
    ), patch(
        "services.quota_service.get_committed_bytes_by_kb", return_value={}
    ):
        result = quota_service._get_kb_storage_stats(
            [{"knowledge_id": 1, "index_name": "kb-a"}], strict=True
        )
    assert result["stats"] == {"kb-a": 0}
    assert result["details"]["kb-a"]["store_size_bytes"] == 0


def test_personal_storage_stats_strict_source_query_failure_is_unavailable(quota_service):
    vdb = MagicMock()
    vdb.get_indices_detail.return_value = {
        "kb-a": {"base_info": {"store_size": "1 MB"}}
    }
    with patch(
        "management.services.knowledge_base.service.get_vector_db_core", return_value=vdb
    ), patch(
        "services.quota_service.get_committed_bytes_by_kb",
        side_effect=RuntimeError("ledger down"),
    ), pytest.raises(AppException, match="source storage stats"):
        quota_service._get_kb_storage_stats(
            [{"knowledge_id": 1, "index_name": "kb-a"}], strict=True
        )


def test_personal_effective_quota_map_accepts_preloaded_default(
    quota_service, mock_tenant_config_db
):
    mock_tenant_config_db["get_configs_by_tenant_id_and_keys"].return_value = {
        "PERSONAL_KB_QUOTA_user-1": str(10 * GB),
    }

    resolved, default_quota = quota_service._get_personal_effective_quota_map(
        {"user-1", "user-2"}, default_quota=5 * GB
    )

    assert resolved == {
        "user-1": (10 * GB, "individual"),
        "user-2": (5 * GB, "default"),
    }
    assert default_quota == 5 * GB
    mock_tenant_config_db["get_configs_by_tenant_id_and_keys"].assert_called_once_with(
        "test-tenant-id",
        ["PERSONAL_KB_QUOTA_user-1", "PERSONAL_KB_QUOTA_user-2"],
    )


def test_get_personal_self_capacity_without_quota_has_no_rate(
    quota_service, mock_knowledge_db
):
    mock_knowledge_db["get_private_knowledge_info_by_creator"].return_value = []
    with patch.object(
        quota_service,
        "_get_kb_storage_stats",
        return_value={"stats": {}, "details": {}, "total_bytes": 0},
    ), patch.object(
        quota_service,
        "_get_personal_effective_quota",
        return_value=(None, "unlimited"),
    ):
        result = quota_service.get_personal_self_capacity("user-1")

    assert result["quota_source"] == "unlimited"
    assert result["usage_rate"] is None
    assert result["is_over_quota"] is False


def test_get_personal_kb_details_returns_sorted_paged_storage_details(quota_service):
    usage_data = {
        "kbs": [
            {
                "knowledge_id": 1,
                "index_name": "older",
                "knowledge_name": "Older",
                "knowledge_sources": "elasticsearch",
                "last_doc_update_time": "2026-08-01",
                "quota_limit_bytes": None,
            },
            {
                "knowledge_id": 2,
                "index_name": "newer",
                "knowledge_name": "Newer",
                "knowledge_sources": "elasticsearch",
                "last_doc_update_time": "2026-08-02",
                "quota_limit_bytes": 2048,
            },
        ],
        "details": {
            "older": {"doc_count": 1, "total_size_bytes": 10},
            "newer": {
                "doc_count": 2,
                "chunk_count": 3,
                "store_size": "1 KB",
                "store_size_bytes": 1024,
                "source_size": "1 KB",
                "source_size_bytes": 1024,
                "total_size": "2 KB",
                "total_size_bytes": 2048,
            },
        },
    }
    with patch.object(quota_service, "_get_personal_usage_data", return_value=usage_data):
        result = quota_service.get_personal_kb_details("user-1", page=1, page_size=1)

    assert result["total"] == 2
    assert result["total_pages"] == 2
    assert result["kbs"][0]["index_name"] == "newer"
    assert result["kbs"][0]["chunk_count"] == 3
    assert result["kbs"][0]["quota_limit_bytes"] == 2048


def test_pending_personal_upload_bytes_handles_invalid_knowledge_id(quota_service):
    with patch(
        "services.quota_service.get_committed_source_bytes_by_paths"
    ) as get_committed:
        result = quota_service.get_pending_personal_upload_bytes(
            [{"filename": "a.txt", "file_size": "12"}],
            {"knowledge_id": "not-an-int"},
        )

    assert result == 12
    get_committed.assert_not_called()


def test_personal_quota_zero_bytes_allows_zero_byte_upload(
    quota_service, mock_knowledge_db
):
    mock_knowledge_db["get_private_knowledge_info_by_creator"].return_value = []
    with patch.object(
        quota_service,
        "_get_kb_storage_stats",
        return_value={"stats": {}, "details": {}, "total_bytes": 0},
    ), patch.object(
        quota_service,
        "_get_personal_effective_quota",
        return_value=(0, "individual"),
    ):
        quota_service.check_personal_user_quota("user-1", 0)


def test_personal_kb_quota_ignores_missing_or_unlimited_kb_record(quota_service):
    usage_data = {"total_bytes": 0, "stats": {}}
    with patch.object(quota_service, "_get_personal_usage_data", return_value=usage_data), patch.object(
        quota_service, "get_hard_limit", return_value={"hard_limit_bytes": None}
    ), patch.object(
        quota_service,
        "_check_personal_user_quota_from_usage",
    ) as check_user, patch.object(
        quota_service,
        "_check_personal_kb_quota_from_usage",
    ) as check_kb:
        quota_service.check_personal_kb_quota("user-1", 10, kb_record=None)

    check_user.assert_called_once_with(usage_data, "user-1", 10)
    check_kb.assert_called_once_with(usage_data, 10, None)
