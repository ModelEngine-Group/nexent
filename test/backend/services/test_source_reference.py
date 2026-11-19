# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Retain source identity normalization independently of retired storage orchestration."""

import pytest
from management.services.knowledge_base import source_reference
from management.services.knowledge_base.source_reference import (
    resolve_storage_reference,
)


@pytest.fixture(autouse=True)
def default_bucket(monkeypatch):
    monkeypatch.setattr(source_reference, 'MINIO_DEFAULT_BUCKET', 'test-bucket')


@pytest.mark.parametrize(
    ("path_or_url", "expected"),
    [
        ("knowledge_base/a.pdf", ("test-bucket", "knowledge_base/a.pdf")),
        (
            "attachments/asset_owner/user-a/a.pdf",
            ("test-bucket", "attachments/asset_owner/user-a/a.pdf"),
        ),
        ("s3://other-bucket/knowledge_base/a.pdf", ("other-bucket", "knowledge_base/a.pdf")),
        ("/other-bucket/knowledge_base/a.pdf", ("other-bucket", "knowledge_base/a.pdf")),
        ("https://example.com/a.pdf", None),
        ("", None),
    ],
)
def test_resolve_storage_reference_normalizes_kb_source_paths(path_or_url, expected):
    result = resolve_storage_reference(path_or_url)

    if expected is None:
        assert result is None
    else:
        assert (result.bucket_name, result.object_name) == expected
