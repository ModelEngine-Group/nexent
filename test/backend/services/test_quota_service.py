# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""
Unit tests for QuotaService.

Covers: config methods, per-KB quota, usage tracking, warning levels,
quota enforcement, summary, and platform quota.
"""

from unittest.mock import MagicMock, patch

import pytest
from contracts.errors.exceptions import AppException
from management.services.knowledge_base.quota import (
    GB,
    QuotaService,
    _usage_cache,
)
from management.services.knowledge_base.quota_formatting import (
    bytes_to_readable as _bytes_to_readable,
)
from management.services.knowledge_base.quota_formatting import parse_store_size
from management.services.knowledge_base.usage_projection import warning_level

from test.backend.management.import_patching import patch_import_context


@pytest.fixture
def mock_tenant_config_db():
    """Mock tenant configuration persistence used by QuotaService."""
    with patch_import_context("management.services.knowledge_base.quota.get_single_config_info") as mock_get, \
         patch_import_context("management.services.knowledge_base.quota.get_configs_by_tenant_id_and_keys") as mock_get_many, \
         patch_import_context("management.services.knowledge_base.quota.insert_config") as mock_insert, \
         patch_import_context("management.services.knowledge_base.quota.update_config_by_tenant_config_id") as mock_update, \
         patch_import_context("management.services.knowledge_base.quota.delete_config_by_tenant_config_id") as mock_delete:
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
    with patch_import_context("management.services.knowledge_base.quota.get_knowledge_info_by_tenant_id") as mock_list, \
         patch_import_context("management.services.knowledge_base.quota.update_knowledge_record") as mock_update, \
         patch_import_context("management.services.knowledge_base.quota.get_committed_bytes_by_kb", return_value={}) as mock_kb_bytes, \
         patch_import_context("management.services.knowledge_base.quota.get_tenant_committed_source_bytes", return_value=0) as mock_tenant_bytes, \
         patch_import_context("management.services.knowledge_base.quota.get_private_knowledge_info_by_tenant_id") as mock_private_list, \
         patch_import_context("management.services.knowledge_base.quota.get_private_knowledge_info_by_creator") as mock_creator_list, \
         patch_import_context("management.services.knowledge_base.quota.get_user_email_map") as mock_email_map:
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
        assert warning_level(0) == "normal"
        assert warning_level(50) == "normal"
        assert warning_level(79.9) == "normal"

    def test_kb_warning_80_to_95(self):
        assert warning_level(80) == "warning"
        assert warning_level(90) == "warning"

    def test_kb_critical_95_to_100(self):
        assert warning_level(95) == "critical"
        assert warning_level(99.9) == "critical"

    def test_kb_exceeded_100_plus(self):
        assert warning_level(100) == "exceeded"
        assert warning_level(150) == "exceeded"

    def test_kb_none_usage(self):
        assert warning_level(None) == "normal"

    def test_tenant_normal_below_80(self):
        assert warning_level(0, terminal="blocked") == "normal"
        assert warning_level(50, terminal="blocked") == "normal"
        assert warning_level(79, terminal="blocked") == "normal"

    def test_tenant_warning_80_to_95(self):
        assert warning_level(80, terminal="blocked") == "warning"
        assert warning_level(90, terminal="blocked") == "warning"
        assert warning_level(94, terminal="blocked") == "warning"

    def test_tenant_critical_95_to_100(self):
        assert warning_level(95, terminal="blocked") == "critical"
        assert warning_level(99, terminal="blocked") == "critical"

    def test_tenant_blocked_100_plus(self):
        assert warning_level(100, terminal="blocked") == "blocked"
        assert warning_level(200, terminal="blocked") == "blocked"

    def test_tenant_none_usage(self):
        assert warning_level(None, terminal="blocked") == "normal"

    def test_custom_thresholds(self):
        # Custom warning=70, critical=85
        assert warning_level(75, 85, 70, terminal="blocked") == "warning"
        assert warning_level(90, 85, 70, terminal="blocked") == "critical"
        assert warning_level(60, 85, 70, terminal="blocked") == "normal"


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
        assert parse_store_size(raw_value) == expected


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


# ═══════════════════════════════════════════════════════════════════════
# Task 11.6 — Quota Enforcement
# ═══════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════
# Task 11.8 — Platform Quota
# ═══════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════
# Task 11.4 — Usage Tracking & Cache
# ═══════════════════════════════════════════════════════════════════════

class TestUsageTracking:
    """Keep the remaining shared cache invalidation contract."""

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

        with patch_import_context(
            "management.services.knowledge_base.quota.get_committed_source_bytes_by_paths",
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

        with patch_import_context(
            "management.services.knowledge_base.service.get_vector_db_core",
            return_value=mock_vdb,
        ):
            result = quota_service._get_personal_usage_data(strict=True)

        assert result["stats"]["kb-a"] == 1 * GB
        assert result["details"]["kb-a"]["store_size_bytes"] == 4 * GB
        assert result["details"]["kb-a"]["source_size_bytes"] == 1 * GB
        assert result["details"]["kb-a"]["total_size_bytes"] == 1 * GB
        assert result["total_es_bytes"] == 4 * GB



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
            kb["knowledge_id"]: parse_store_size(store_size)
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

        with patch_import_context(
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

        with patch_import_context(
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

        with patch_import_context(
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

        with patch_import_context(
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

        with patch_import_context(
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

        with patch_import_context(
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
    with patch_import_context(
        "management.services.knowledge_base.service.get_vector_db_core",
        return_value=MagicMock(
            get_indices_detail=MagicMock(
                return_value={"kb-a": {"base_info": {"store_size": "1 MB"}}}
            )
        ),
    ), patch_import_context(
        "management.services.knowledge_base.quota.get_committed_bytes_by_kb",
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
    with patch_import_context(
        "management.services.knowledge_base.service.get_vector_db_core", return_value=vdb
    ), patch_import_context(
        "management.services.knowledge_base.quota.get_committed_bytes_by_kb", return_value={}
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
    with patch_import_context(
        "management.services.knowledge_base.service.get_vector_db_core", return_value=vdb
    ), patch_import_context(
        "management.services.knowledge_base.quota.get_committed_bytes_by_kb",
        side_effect=RuntimeError("ledger down"),
    ), pytest.raises(AppException, match="source storage stats"):
        quota_service._get_kb_storage_stats(
            [{"knowledge_id": 1, "index_name": "kb-a"}], strict=True
        )








def test_pending_personal_upload_bytes_handles_invalid_knowledge_id(quota_service):
    with patch_import_context(
        "management.services.knowledge_base.quota.get_committed_source_bytes_by_paths"
    ) as get_committed:
        result = quota_service.get_pending_personal_upload_bytes(
            [{"filename": "a.txt", "file_size": "12"}],
            {"knowledge_id": "not-an-int"},
        )

    assert result == 12
    get_committed.assert_not_called()


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
