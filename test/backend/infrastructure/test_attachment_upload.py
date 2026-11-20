# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify the exact attachment write and its ambiguous-failure behavior."""

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from botocore.exceptions import ReadTimeoutError
from nexent.storage.errors import InvalidInput, OutcomeUnknown

from infrastructure import attachment_upload


@pytest.fixture
def provider(mocker):
    raw = Mock()
    factory = mocker.patch.object(attachment_upload, "_configured_client", return_value=raw)
    mocker.patch.object(attachment_upload, "_configured_environment",
                        return_value=SimpleNamespace(MINIO_DEFAULT_BUCKET="owned"))
    return raw, factory


def test_attachment_preserves_exact_key_bytes_type_and_default_bucket(provider):
    raw, _ = provider
    key = r"attachments/user:one/a\b.pdf"

    def put(**args):
        assert (args["Bucket"], args["Key"]) == ("owned", key)
        assert args["Body"].read() == b"payload"
        assert args["ContentLength"] == 7 and args["ContentType"] == "application/pdf"
        return {"ETag": '"some-revision"'}

    raw.put_object.side_effect = put
    assert attachment_upload.put_attachment(BytesIO(b"payload"), key, None,
                                            content_type="application/pdf", size=7) == f"/owned/{key}"
    raw.put_object.assert_called_once()
    raw.close.assert_called_once()


def test_attachment_timeout_has_no_replay_or_delete(provider):
    raw, _ = provider
    raw.put_object.side_effect = ReadTimeoutError(endpoint_url="https://example.invalid")
    with pytest.raises(OutcomeUnknown):
        attachment_upload.put_attachment(BytesIO(b"a"), "attachments/user/a", "alternate",
                                         content_type="text/plain", size=1)
    assert raw.put_object.call_args.kwargs["Bucket"] == "alternate"
    raw.put_object.assert_called_once()
    raw.delete_object.assert_not_called()
    raw.close.assert_called_once()


def test_attachment_size_mismatch_never_contacts_storage(provider):
    _, factory = provider
    with pytest.raises(InvalidInput):
        attachment_upload.put_attachment(BytesIO(b"short"), "attachments/user/a", None,
                                         content_type="text/plain", size=6)
    factory.assert_not_called()
