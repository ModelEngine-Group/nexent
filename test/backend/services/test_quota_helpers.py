# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Retained public quota formatting, warning and shared-cache regression assertions."""

import pytest
from management.services.knowledge_base.quota_formatting import (
    bytes_to_readable as _bytes_to_readable,
)
from management.services.knowledge_base.quota_formatting import parse_store_size
from management.services.knowledge_base.usage_cache import (
    _usage_cache,
    invalidate_usage_cache,
)
from management.services.knowledge_base.usage_projection import warning_level

GB = 1024 ** 3


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


class TestUsageTracking:
    """Keep the remaining shared cache invalidation contract."""

    def test_invalidate_usage_cache_is_tenant_scoped(self):
        _usage_cache.clear()
        _usage_cache["tenant-a"] = (0, {"total_bytes": 1})
        _usage_cache["tenant-b"] = (0, {"total_bytes": 2})

        invalidate_usage_cache("tenant-a")

        assert "tenant-a" not in _usage_cache
        assert "tenant-b" in _usage_cache
        invalidate_usage_cache()
        assert _usage_cache == {}
