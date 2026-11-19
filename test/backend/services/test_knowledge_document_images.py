# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DOC-IMAGE-READ-01/02 retain bounded actor-aware object reads."""

from time import monotonic
from types import SimpleNamespace

import pytest
from management.services.knowledge_base import document_images
from nexent.storage.errors import DeadlineExceeded, InvalidInput, NotFound
from nexent.storage.models import OperationContext

from infrastructure.agentos_identity import ServicePrincipal


@pytest.fixture
def reader(mocker):
    mocker.patch.object(document_images.environment, "MINIO_DEFAULT_BUCKET", "files")
    read = mocker.patch.object(document_images, "read_object_image", return_value=b"original image bytes")
    return read, ServicePrincipal("operator", "tenant-a"), OperationContext("image-read", monotonic() + 10)


@pytest.mark.parametrize("url", ["s3://files/images_in_attachments/a.png", "/files/images_in_attachments/a.png",
                                 "images_in_attachments/a.png"])
def test_supported_object_addresses_keep_actual_actor_and_parent_deadline(reader, url):
    read, actor, context = reader
    assert document_images.read_document_image(url, actor, context=context) == b"original image bytes"
    read.assert_called_once_with("s3://files/images_in_attachments/a.png", user_id=actor.user_id,
                                 tenant_id=actor.tenant_id, context=context)


@pytest.mark.parametrize("url", ["s3://other/images_in_attachments/a.png", "https://example.invalid/image.png",
                                 "file:///tmp/image.png", "", "//other/image.png"])
def test_unsupported_or_foreign_bucket_address_never_reaches_object_reader(reader, url):
    read, actor, context = reader
    with pytest.raises((ValueError, InvalidInput)):
        document_images.read_document_image(url, actor, context=context)
    read.assert_not_called()


def test_current_attachment_permissions_are_checked_before_object_read(reader):
    read, actor, context = reader
    with pytest.raises(PermissionError):
        document_images.read_document_image("attachments/other/private.png", actor, context=context)
    read.assert_not_called()


def test_expired_context_cannot_open_an_object(reader):
    read, actor, _ = reader
    with pytest.raises(DeadlineExceeded):
        document_images.read_document_image("images_in_attachments/a.png", actor,
                                            context=OperationContext("expired", monotonic() - 1))
    read.assert_not_called()


@pytest.mark.parametrize("actor", [None, SimpleNamespace(user_id="", tenant_id="tenant-a"),
                                  SimpleNamespace(user_id="operator", tenant_id="")])
def test_missing_identity_cannot_open_an_object(reader, actor):
    read, _, context = reader
    with pytest.raises(InvalidInput):
        document_images.read_document_image("images_in_attachments/a.png", actor, context=context)
    read.assert_not_called()


def test_missing_object_keeps_file_not_found_failure_without_replay(reader):
    read, actor, context = reader
    read.side_effect = NotFound()
    with pytest.raises(FileNotFoundError, match="Unable to fetch file from URL"):
        document_images.read_document_image("images_in_attachments/a.png", actor, context=context)
    assert read.call_count == 1
