"""D2 Agent icon contract at the real service/storage boundary."""
import io
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest

from consts.exceptions import ForbiddenError
from database import attachment_db, client as database_client
from management.services.agent import service as agent_service

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
GIF = b"GIF89a" + b"\x00" * 16
WEBP = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 16


@pytest.mark.asyncio
@pytest.mark.stage("D2")
@pytest.mark.case_id("API-AUTO-08A289290B55F524")
async def test_agent_icon_upload_read_contract(monkeypatch):
    # These identifiers belong only to the controlled in-memory collaborators.
    agent_id, tenant_id, user_id = 17, "fixture-tenant", "fixture-editor"
    state = {"permission": "EDIT", "tenant_id": tenant_id, "icon_url": None}
    writes, uploads, urls = [], [], []

    async def read_agent(*args, **kwargs):
        return dict(state)

    def write_icon(**values):
        writes.append(values)
        state["icon_url"] = values["icon_url"]

    class Storage:
        content = None
        fail = False

        def upload_fileobj(self, stream, object_name):
            assert object_name == f"agent-icons/{tenant_id}/{agent_id}/icon"
            if self.fail:
                return False, "controlled upload failure"
            self.content = stream.read()
            uploads.append(self.content)
            return True, ""

    storage = Storage()
    monkeypatch.setattr(agent_service, "get_agent_info_impl", read_agent)
    monkeypatch.setattr(agent_service, "is_system_agent", lambda *args: False)
    monkeypatch.setattr(agent_service, "update_agent_icon", write_icon)
    # Keep real upload/read/validation functions, replacing only object storage.
    monkeypatch.setattr(database_client, "minio_client", storage)
    monkeypatch.setattr(attachment_db, "get_file_stream",
                        lambda name: io.BytesIO(storage.content) if storage.content is not None else None)

    for content, mime in [(PNG, "image/png"), (JPEG, "image/jpeg"), (GIF, "image/gif"), (WEBP, "image/webp")]:
        result = await agent_service.upload_agent_icon_impl(agent_id, content, tenant_id, user_id)
        assert result["content_type"] == mime
        parsed = urlsplit(result["icon_url"])
        assert parsed.path == f"/api/agent/{agent_id}/icon"
        version = parse_qs(parsed.query)["v"]
        assert len(version) == 1 and UUID(hex=version[0]).hex == version[0]
        urls.append(result["icon_url"])
        assert state["icon_url"] == result["icon_url"]
        assert writes[-1] == {"agent_id": agent_id, "tenant_id": tenant_id,
                              "icon_url": result["icon_url"], "user_id": user_id}
        assert await agent_service.get_agent_icon_impl(agent_id, tenant_id, user_id) == (content, mime)
    assert len(set(urls)) == 4

    before = len(writes), len(uploads), state["icon_url"]
    for content, message in [
        (b"", "Icon file is empty"),
        (b"\x00" * (2 * 1024 * 1024 + 1), "Icon must not exceed 2 MB"),
        (b"not an image", "Icon must be a PNG, JPEG, GIF, or WebP image"),
    ]:
        with pytest.raises(ValueError) as error:
            await agent_service.upload_agent_icon_impl(agent_id, content, tenant_id, user_id)
        assert str(error.value) == message
        assert (len(writes), len(uploads), state["icon_url"]) == before

    state["permission"] = "READ_ONLY"
    with pytest.raises(ForbiddenError):
        await agent_service.upload_agent_icon_impl(agent_id, PNG, tenant_id, user_id)
    assert (len(writes), len(uploads), state["icon_url"]) == before
    state["permission"] = "EDIT"
    monkeypatch.setattr(agent_service, "is_system_agent", lambda *args: True)
    with pytest.raises(ForbiddenError, match="System Agent"):
        await agent_service.upload_agent_icon_impl(agent_id, PNG, tenant_id, user_id)
    assert (len(writes), len(uploads), state["icon_url"]) == before
    monkeypatch.setattr(agent_service, "is_system_agent", lambda *args: False)

    storage.fail = True
    with pytest.raises(ValueError, match="Failed to upload icon"):
        await agent_service.upload_agent_icon_impl(agent_id, PNG, tenant_id, user_id)
    assert (len(writes), len(uploads), state["icon_url"]) == before

    state["icon_url"] = None
    with pytest.raises(FileNotFoundError, match="Agent icon not found"):
        await agent_service.get_agent_icon_impl(agent_id, tenant_id, user_id)
    state["icon_url"] = urls[-1]
    storage.content = None
    with pytest.raises(FileNotFoundError, match="Icon not found"):
        await agent_service.get_agent_icon_impl(agent_id, tenant_id, user_id)
    storage.content = b"invalid stored image"
    with pytest.raises(FileNotFoundError, match="Icon is invalid"):
        await agent_service.get_agent_icon_impl(agent_id, tenant_id, user_id)
