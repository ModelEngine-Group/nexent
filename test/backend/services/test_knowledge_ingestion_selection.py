# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Source selection requires a current authorized identity, never a guessed filename."""

from types import SimpleNamespace

import pytest
from management.services.knowledge_base.ingestion_selection import (
    resolve_ingestion_file,
)
from nexent.storage.errors import NotFound, ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure.rdb.cleanse_resources import bind_cleanse_resources
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def selection(resources):  # noqa: F811
    _, update, engine, tables = resources
    update(
        "cleanse_files",
        source_key="knowledge_base/source.txt",
        object_name="knowledge_base/source.txt",
        bucket_name="bucket",
    )
    records = bind_cleanse_resources(
        StorageScope("management", "tenant-a", "user-a", set(tables)), engine
    )
    try:
        yield records, update
    finally:
        records.close()


def resolve(selection, details, *, destination="minio"):
    return resolve_ingestion_file(
        selection[0],
        SimpleNamespace(user_id="user-a", tenant_id="tenant-a"),
        "kb-one",
        details,
        destination=destination,
        context=context(),
    )


def test_id_and_exact_object_alias_select_the_same_file(selection):
    row = resolve(
        selection,
        {"file_id": "b" * 32, "path_or_url": "s3://bucket/knowledge_base/source.txt"},
    )
    assert row["file_id"] == "b" * 32 and row["knowledge_id"] == 1
    assert (
        resolve(selection, {"path_or_url": "knowledge_base/source.txt"})["file_id"]
        == row["file_id"]
    )


@pytest.mark.parametrize(
    "path",
    ["source.txt", "s3://other/knowledge_base/source.txt", "https://host/source.txt"],
)
def test_wrong_alias_cannot_override_an_authorized_id(selection, path):
    with pytest.raises((ScopeDenied, NotFound)):
        resolve(selection, {"file_id": "b" * 32, "path_or_url": path})


def test_filename_is_not_a_source_selector(selection):
    with pytest.raises((ScopeDenied, NotFound)):
        resolve(selection, {"filename": "source.txt"})


def test_wrong_id_is_never_replaced_by_a_matching_path(selection):
    with pytest.raises(NotFound):
        resolve(
            selection, {"file_id": "f" * 32, "path_or_url": "knowledge_base/source.txt"}
        )


@pytest.mark.parametrize("tenant_id", [None, "other-tenant"])
def test_missing_or_foreign_tenant_cannot_select_a_source(selection, tenant_id):
    with pytest.raises(ScopeDenied):
        resolve_ingestion_file(
            selection[0],
            SimpleNamespace(user_id="user-a", tenant_id=tenant_id),
            "kb-one",
            {"file_id": "b" * 32},
            destination="minio",
            context=context(),
        )


def test_current_edit_permission_is_required_before_returning_source(selection):
    selection[1]("cleanse_memberships", delete_flag="Y")
    with pytest.raises(ScopeDenied):
        resolve(selection, {"file_id": "b" * 32})


def test_local_alias_is_registered_and_never_treated_as_a_server_read(selection):
    alias = "C:/managed/knowledge/" + "b" * 32 + "/source.txt"
    selection[1]("cleanse_files", local_source_path=alias)
    assert (
        resolve(selection, {"path_or_url": alias}, destination="local")["file_id"]
        == "b" * 32
    )
    with pytest.raises((ScopeDenied, NotFound)):
        resolve(
            selection,
            {"file_id": "b" * 32, "path_or_url": "C:/private/secret"},
            destination="local",
        )
