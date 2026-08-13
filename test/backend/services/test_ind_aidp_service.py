import pytest
import httpx

from services import ind_aidp_service


@pytest.mark.asyncio
async def test_list_uses_posted_credentials_without_global_aidp_config(monkeypatch):
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            request=request,
            json={"value": [{"kds_id": "kb-1", "kds_name": "KB 1"}], "has_more": False},
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def client_factory(**kwargs):
        kwargs["transport"] = transport
        return real_async_client(**kwargs)

    monkeypatch.setattr(ind_aidp_service.httpx, "AsyncClient", client_factory)

    result = await ind_aidp_service.fetch_ind_aidp_knowledge_bases_impl(
        server_url="https://independent-aidp.example",
        api_key="instance-secret",
        tenant_id="aidp",
    )

    assert result["value"][0]["kds_id"] == "kb-1"
    request = captured["request"]
    assert request.headers["Authorization"] == "Bearer instance-secret"
    assert request.url.path == "/KnowledgeBase/Tenants/aidp/KnowledgeBases"


@pytest.mark.asyncio
async def test_image_fetch_uses_resolved_instance_credentials(monkeypatch):
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "image/png"},
            content=b"png-bytes",
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def client_factory(**kwargs):
        kwargs["transport"] = transport
        return real_async_client(**kwargs)

    monkeypatch.setattr(ind_aidp_service.httpx, "AsyncClient", client_factory)
    monkeypatch.setattr(ind_aidp_service, "IND_AIDP_IMAGE_SIGNING_KEY", "signing-secret")
    monkeypatch.setattr(
        ind_aidp_service,
        "_resolve_image_credentials",
        lambda _: ("https://independent-aidp.example", "instance-secret", "aidp", "kb/image.png"),
    )
    builder = ind_aidp_service.create_ind_aidp_image_url_builder(
        agent_id=1,
        tool_id=2,
        tenant_id="tenant-a",
        version_no=0,
        aidp_tenant_id="aidp",
    )
    image_ref = builder("kb/image.png").rsplit("/", 1)[-1]

    content, content_type = await ind_aidp_service.fetch_ind_aidp_image_impl(image_ref)

    assert content == b"png-bytes"
    assert content_type == "image/png"
    assert captured["request"].headers["Authorization"] == "Bearer instance-secret"


def test_image_ref_is_signed_and_does_not_contain_api_key(monkeypatch):
    monkeypatch.setattr(ind_aidp_service, "IND_AIDP_IMAGE_SIGNING_KEY", "signing-secret")
    builder = ind_aidp_service.create_ind_aidp_image_url_builder(
        agent_id=10,
        tool_id=20,
        tenant_id="tenant-a",
        version_no=3,
        aidp_tenant_id="aidp",
    )

    url = builder("kb-1/images/a.png")

    assert url.startswith("/api/ind-aidp/images/")
    assert "api-key" not in url
    payload = ind_aidp_service._decode_image_ref(url.rsplit("/", 1)[-1])
    assert payload["agent_id"] == 10
    assert payload["tool_id"] == 20
    assert payload["image_path"] == "kb-1/images/a.png"


def test_tampered_image_ref_is_rejected(monkeypatch):
    monkeypatch.setattr(ind_aidp_service, "IND_AIDP_IMAGE_SIGNING_KEY", "signing-secret")
    builder = ind_aidp_service.create_ind_aidp_image_url_builder(
        agent_id=1,
        tool_id=2,
        tenant_id="tenant-a",
        version_no=0,
        aidp_tenant_id="aidp",
    )
    image_ref = builder("kb/image.png").rsplit("/", 1)[-1]

    with pytest.raises(ind_aidp_service.IndependentAidpServiceError, match="Invalid"):
        ind_aidp_service._decode_image_ref(f"{image_ref}x")


def test_image_path_rejects_traversal():
    with pytest.raises(ValueError, match="invalid"):
        ind_aidp_service._normalize_image_path("../secret", "aidp")


def test_resolve_credentials_requires_independent_tool_class(monkeypatch):
    monkeypatch.setattr(
        ind_aidp_service,
        "query_tool_instances_by_id",
        lambda **_: {"params": {"server_url": "https://aidp.example", "api_key": "secret"}},
    )
    monkeypatch.setattr(
        ind_aidp_service,
        "query_tools_by_ids",
        lambda _: [{"class_name": "AidpSearchTool"}],
    )

    with pytest.raises(ind_aidp_service.IndependentAidpServiceError, match="unavailable"):
        ind_aidp_service._resolve_image_credentials(
            {
                "agent_id": 1,
                "tool_id": 2,
                "tenant_id": "tenant-a",
                "version_no": 0,
                "aidp_tenant_id": "aidp",
                "image_path": "kb/image.png",
            }
        )
