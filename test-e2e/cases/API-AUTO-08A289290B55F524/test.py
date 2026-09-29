"""D2 contract test: Agent icon upload/read service layer.

Covers content-type whitelist (gif/jpeg/png/webp), the 2 MB upper bound,
EDIT permission enforcement, invalid/missing icon errors, and icon_url
write-back, against upload_agent_icon_impl / get_agent_icon_impl.
"""

import io

import pytest

from management.services.agent import service as agent_service
from consts.exceptions import ForbiddenError


_TWO_MB_PLUS_ONE = 2 * 1024 * 1024 + 1

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG_BYTES = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
)
GIF_BYTES = b"GIF89a" + b"\x00" * 16
WEBP_BYTES = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 16


@pytest.mark.asyncio
@pytest.mark.stage("D2")
@pytest.mark.case_id("API-AUTO-08A289290B55F524")
async def test_agent_icon_upload_read_contract(monkeypatch):
    agent_id = 900001
    tenant_id = "tenant-d2-icon"
    user_id = "user-d2-editor"
    icon_url = f"/api/agent/{agent_id}/icon"

    state = {"permission": "EDIT", "tenant_id": tenant_id, "icon_url": None}
    stored_content = {"value": None}
    icon_writes = []

    async def fake_get_agent_info(agent_id_arg, tenant_id_arg, version_no=0, user_id=None):
        return dict(state)

    def fake_update_agent_icon(*, agent_id, tenant_id, icon_url, user_id):
        icon_writes.append(
            {
                "agent_id": agent_id,
                "tenant_id": tenant_id,
                "icon_url": icon_url,
                "user_id": user_id,
            }
        )

    def fake_get_file_stream(object_name):
        if stored_content["value"] is None:
            return None
        return io.BytesIO(stored_content["value"])

    class _FakeMinio:
        def __init__(self):
            self.uploaded = []

        def upload_fileobj(self, file_obj, object_name):
            data = file_obj.read()
            self.uploaded.append(data)
            stored_content["value"] = data
            return (True, "")

    fake_minio = _FakeMinio()

    monkeypatch.setattr(agent_service, "get_agent_info_impl", fake_get_agent_info)
    monkeypatch.setattr(agent_service, "update_agent_icon", fake_update_agent_icon)
    monkeypatch.setattr(agent_service, "get_file_stream", fake_get_file_stream)
    monkeypatch.setattr(agent_service, "minio_client", fake_minio)

    result = await agent_service.upload_agent_icon_impl(agent_id, PNG_BYTES, tenant_id, user_id)
    assert result == {"icon_url": icon_url, "content_type": "image/png"}
    assert len(icon_writes) == 1

    for content, expected_type in (
        (JPEG_BYTES, "image/jpeg"),
        (GIF_BYTES, "image/gif"),
        (WEBP_BYTES, "image/webp"),
    ):
        result = await agent_service.upload_agent_icon_impl(agent_id, content, tenant_id, user_id)
        assert result["content_type"] == expected_type
        assert result["icon_url"] == icon_url

    writes_before = len(icon_writes)
    uploads_before = len(fake_minio.uploaded)

    with pytest.raises(ValueError, match="Agent icon file is empty"):
        await agent_service.upload_agent_icon_impl(agent_id, b"", tenant_id, user_id)
    assert len(icon_writes) == writes_before
    assert len(fake_minio.uploaded) == uploads_before

    with pytest.raises(ValueError, match="Agent icon must not exceed 2 MB"):
        await agent_service.upload_agent_icon_impl(agent_id, b"\x00" * _TWO_MB_PLUS_ONE, tenant_id, user_id)
    assert len(icon_writes) == writes_before
    assert len(fake_minio.uploaded) == uploads_before

    with pytest.raises(ValueError, match="Agent icon must be a PNG, JPEG, GIF, or WebP image"):
        await agent_service.upload_agent_icon_impl(agent_id, b"plain text, not an image", tenant_id, user_id)
    assert len(icon_writes) == writes_before
    assert len(fake_minio.uploaded) == uploads_before

    state["permission"] = "READ_ONLY"
    with pytest.raises(ForbiddenError, match="You do not have permission to edit this agent"):
        await agent_service.upload_agent_icon_impl(agent_id, PNG_BYTES, tenant_id, user_id)
    assert len(icon_writes) == writes_before
    assert len(fake_minio.uploaded) == uploads_before

    state["permission"] = "EDIT"
    state["icon_url"] = icon_url
    await agent_service.upload_agent_icon_impl(agent_id, PNG_BYTES, tenant_id, user_id)

    content, content_type = await agent_service.get_agent_icon_impl(agent_id, tenant_id, user_id)
    assert content == PNG_BYTES
    assert content_type == "image/png"

    state["icon_url"] = None
    with pytest.raises(FileNotFoundError, match="Agent icon not found"):
        await agent_service.get_agent_icon_impl(agent_id, tenant_id, user_id)

    last_write = icon_writes[-1]
    assert last_write["icon_url"] == icon_url
    assert last_write["agent_id"] == agent_id
    assert last_write["tenant_id"] == tenant_id
    assert last_write["user_id"] == user_id
