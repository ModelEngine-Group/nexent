# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Object byte uploads preserve exact keys and client outcomes."""

import pytest

from database import attachment_db


@pytest.mark.parametrize("outcome", [(True, None), (False, "storage unavailable")])
def test_upload_file_bytes_preserves_content_key_and_outcome(mocker, outcome):
    upload = mocker.patch.object(
        attachment_db.minio_client, "upload_fileobj", return_value=outcome,
    )
    content = b"\xff\xd8\xffimage"
    key = "agent-icons/tenant-a/42/icon"

    assert attachment_db.upload_file_bytes(content, key) == outcome

    upload.assert_called_once()
    stream, object_name = upload.call_args.args
    assert stream.getvalue() == content
    assert object_name == key


def test_upload_file_bytes_propagates_client_exception(mocker):
    mocker.patch.object(
        attachment_db.minio_client, "upload_fileobj", side_effect=OSError("offline"),
    )

    with pytest.raises(OSError, match="offline"):
        attachment_db.upload_file_bytes(b"image", "icons/42")
