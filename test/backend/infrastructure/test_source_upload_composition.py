# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Source grants are finite and composition closes every resource after failures."""

from time import monotonic

import pytest
from contracts.constants import environment
from nexent.storage.errors import InvalidInput, OutcomeUnknown, ScopeDenied
from nexent.storage.models import ObjectRef, OperationContext

from infrastructure import source_upload
from infrastructure.object_storage import composition


def test_source_grant_denies_other_keys_before_client_creation(monkeypatch, mocker):
    for name, value in {
        "MINIO_ENDPOINT": "http://fixture",
        "MINIO_ACCESS_KEY": "fixture-user",
        "MINIO_SECRET_KEY": "fixture-password",
        "MINIO_DEFAULT_BUCKET": "files",
    }.items():
        monkeypatch.setattr(environment, name, value)
    factory = mocker.patch.object(composition, "_configured_client")
    store = composition.bind_source_objects("tenant-a", "user-a", "source.txt", "files")
    with pytest.raises(ScopeDenied):
        store.stat(
            ObjectRef("files", "another.txt"),
            context=OperationContext("grant", monotonic() + 5),
        )
    factory.assert_not_called()


def test_incomplete_config_never_falls_back_to_default_cloud(monkeypatch):
    monkeypatch.setattr(environment, "MINIO_ENDPOINT", None)
    with pytest.raises(InvalidInput):
        composition.bind_source_objects("tenant-a", "user-a", "source.txt", "files")


def test_all_ports_close_even_if_one_close_fails(mocker, monkeypatch):
    monkeypatch.setattr(environment, "POSTGRES_PORT", "5432")
    engine = mocker.patch.object(source_upload, "create_engine").return_value
    records = mocker.patch.object(source_upload, "bind_source_records").return_value
    objects = mocker.patch.object(source_upload, "bind_source_objects").return_value
    objects.close.side_effect = RuntimeError("private")
    record = {
        "tenant_id": "tenant-a",
        "created_by": "user-a",
        "object_name": "source.txt",
        "bucket_name": "files",
    }
    with pytest.raises(OutcomeUnknown), source_upload.source_upload_ports(
        record, context=OperationContext("cleanup", monotonic() + 5)
    ):
        pass
    records.close.assert_called_once()
    engine.dispose.assert_called_once()
