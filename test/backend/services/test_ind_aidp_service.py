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


# ---------------------------------------------------------------------------
# Validation and error-path coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_url", ["", "   ", None])
def test_normalize_base_url_required(bad_url):
    with pytest.raises(ValueError, match="required"):
        ind_aidp_service._normalize_base_url(bad_url)


def test_normalize_base_url_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="absolute"):
        ind_aidp_service._normalize_base_url("ftp://files.example")


def test_normalize_base_url_rejects_embedded_credentials_and_query():
    with pytest.raises(ValueError, match="cannot contain"):
        ind_aidp_service._normalize_base_url(
            "https://user:pass@aidp.example/kb?x=1#frag"
        )


def test_validate_tenant_id_required_and_path_characters():
    with pytest.raises(ValueError, match="required"):
        ind_aidp_service._validate_tenant_id(" ")
    with pytest.raises(ValueError, match="invalid path"):
        ind_aidp_service._validate_tenant_id("a/b#c?d")
    assert ind_aidp_service._validate_tenant_id(" aidp ") == "aidp"


@pytest.mark.asyncio
async def test_list_requires_api_key():
    with pytest.raises(ValueError, match="api_key"):
        await ind_aidp_service.fetch_ind_aidp_knowledge_bases_impl(
            server_url="https://independent-aidp.example",
            api_key="   ",
        )


def _client_factory_for(transport):
    real_async_client = httpx.AsyncClient

    def client_factory(**kwargs):
        kwargs["transport"] = transport
        return real_async_client(**kwargs)

    return client_factory


@pytest.mark.asyncio
async def test_list_auth_error_401(monkeypatch):

    async def handler(request):
        return httpx.Response(401, request=request)

    monkeypatch.setattr(
        ind_aidp_service.httpx, "AsyncClient",
        _client_factory_for(httpx.MockTransport(handler)),
    )
    with pytest.raises(ind_aidp_service.IndependentAidpServiceError, match="authentication"):
        await ind_aidp_service.fetch_ind_aidp_knowledge_bases_impl(
            server_url="https://independent-aidp.example", api_key="secret"
        )


@pytest.mark.asyncio
async def test_list_generic_http_error(monkeypatch):

    async def handler(request):
        return httpx.Response(502, request=request)

    monkeypatch.setattr(
        ind_aidp_service.httpx, "AsyncClient",
        _client_factory_for(httpx.MockTransport(handler)),
    )
    with pytest.raises(ind_aidp_service.IndependentAidpServiceError, match="HTTP 502"):
        await ind_aidp_service.fetch_ind_aidp_knowledge_bases_impl(
            server_url="https://independent-aidp.example", api_key="secret"
        )


@pytest.mark.asyncio
async def test_list_connection_error(monkeypatch):
    def raise_connect(*_a, **_k):
        raise httpx.ConnectError("no route")

    transport = httpx.MockTransport(raise_connect)
    monkeypatch.setattr(
        ind_aidp_service.httpx, "AsyncClient",
        _client_factory_for(transport),
    )
    with pytest.raises(ind_aidp_service.IndependentAidpServiceError, match="connection failed"):
        await ind_aidp_service.fetch_ind_aidp_knowledge_bases_impl(
            server_url="https://independent-aidp.example", api_key="secret"
        )


@pytest.mark.asyncio
async def test_list_invalid_json_response(monkeypatch):

    async def handler(request):
        return httpx.Response(200, request=request, content=b"not-json")

    monkeypatch.setattr(
        ind_aidp_service.httpx, "AsyncClient",
        _client_factory_for(httpx.MockTransport(handler)),
    )
    with pytest.raises(ind_aidp_service.IndependentAidpServiceError, match="invalid JSON"):
        await ind_aidp_service.fetch_ind_aidp_knowledge_bases_impl(
            server_url="https://independent-aidp.example", api_key="secret"
        )


@pytest.mark.asyncio
async def test_list_non_object_response(monkeypatch):

    async def handler(request):
        return httpx.Response(200, request=request, json=["not", "an", "object"])

    monkeypatch.setattr(
        ind_aidp_service.httpx, "AsyncClient",
        _client_factory_for(httpx.MockTransport(handler)),
    )
    with pytest.raises(ind_aidp_service.IndependentAidpServiceError, match="must be an object"):
        await ind_aidp_service.fetch_ind_aidp_knowledge_bases_impl(
            server_url="https://independent-aidp.example", api_key="secret"
        )


def test_sign_requires_signing_key(monkeypatch):
    monkeypatch.setattr(ind_aidp_service, "IND_AIDP_IMAGE_SIGNING_KEY", "")
    with pytest.raises(ind_aidp_service.IndependentAidpServiceError, match="not configured"):
        ind_aidp_service._sign("payload")


def test_image_path_empty_and_query_rejected():
    with pytest.raises(ValueError, match="empty"):
        ind_aidp_service._normalize_image_path("  ", "aidp")
    with pytest.raises(ValueError, match="query or fragment"):
        ind_aidp_service._normalize_image_path("kb/a.png?x=1", "aidp")


def test_image_path_strips_known_tenant_prefix():
    path = ind_aidp_service._normalize_image_path(
        "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb/a.png", "aidp"
    )
    assert path == "kb/a.png"


def test_decode_ref_rejects_missing_required_fields(monkeypatch):
    monkeypatch.setattr(ind_aidp_service, "IND_AIDP_IMAGE_SIGNING_KEY", "signing-secret")
    payload = {
        "agent_id": 1,
        "tool_id": 2,
        "tenant_id": "tenant-a",
        "version_no": 0,
        "aidp_tenant_id": "aidp",
        # image_path intentionally missing
    }
    encoded = ind_aidp_service._b64encode(
        __import__("json").dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    ref = f"{encoded}.{ind_aidp_service._sign(encoded)}"

    with pytest.raises(ind_aidp_service.IndependentAidpServiceError, match="Invalid"):
        ind_aidp_service._decode_image_ref(ref)


def test_resolve_credentials_success(monkeypatch):
    monkeypatch.setattr(
        ind_aidp_service,
        "query_tool_instances_by_id",
        lambda **_: {"params": {
            "server_url": "https://independent-aidp.example",
            "api_key": "secret",
            "tenant_id": "aidp",
        }},
    )
    monkeypatch.setattr(
        ind_aidp_service,
        "query_tools_by_ids",
        lambda _: [{"class_name": ind_aidp_service._IMAGE_CLASS_NAME}],
    )

    base_url, api_key, aidp_tenant_id, image_path = (
        ind_aidp_service._resolve_image_credentials({
            "agent_id": 1,
            "tool_id": 2,
            "tenant_id": "tenant-a",
            "version_no": 0,
            "aidp_tenant_id": "aidp",
            "image_path": "kb/a.png",
        })
    )

    assert base_url == "https://independent-aidp.example"
    assert api_key == "secret"
    assert aidp_tenant_id == "aidp"
    assert image_path == "kb/a.png"


def test_resolve_credentials_missing_api_key(monkeypatch):
    monkeypatch.setattr(
        ind_aidp_service,
        "query_tool_instances_by_id",
        lambda **_: {"params": {"server_url": "https://independent-aidp.example"}},
    )
    monkeypatch.setattr(
        ind_aidp_service,
        "query_tools_by_ids",
        lambda _: [{"class_name": ind_aidp_service._IMAGE_CLASS_NAME}],
    )

    with pytest.raises(ind_aidp_service.IndependentAidpServiceError, match="credential"):
        ind_aidp_service._resolve_image_credentials({
            "agent_id": 1,
            "tool_id": 2,
            "tenant_id": "tenant-a",
            "version_no": 0,
            "aidp_tenant_id": "aidp",
            "image_path": "kb/a.png",
        })


def test_resolve_credentials_tenant_mismatch(monkeypatch):
    monkeypatch.setattr(
        ind_aidp_service,
        "query_tool_instances_by_id",
        lambda **_: {"params": {
            "server_url": "https://independent-aidp.example",
            "api_key": "secret",
            "tenant_id": "other",
        }},
    )
    monkeypatch.setattr(
        ind_aidp_service,
        "query_tools_by_ids",
        lambda _: [{"class_name": ind_aidp_service._IMAGE_CLASS_NAME}],
    )

    with pytest.raises(ind_aidp_service.IndependentAidpServiceError, match="no longer matches"):
        ind_aidp_service._resolve_image_credentials({
            "agent_id": 1,
            "tool_id": 2,
            "tenant_id": "tenant-a",
            "version_no": 0,
            "aidp_tenant_id": "aidp",
            "image_path": "kb/a.png",
        })


def _make_image_ref(monkeypatch):
    monkeypatch.setattr(ind_aidp_service, "IND_AIDP_IMAGE_SIGNING_KEY", "signing-secret")
    monkeypatch.setattr(
        ind_aidp_service,
        "_resolve_image_credentials",
        lambda _: ("https://independent-aidp.example", "secret", "aidp", "kb/a.png"),
    )
    builder = ind_aidp_service.create_ind_aidp_image_url_builder(
        agent_id=1, tool_id=2, tenant_id="tenant-a", version_no=0, aidp_tenant_id="aidp"
    )
    return builder("kb/a.png").rsplit("/", 1)[-1]


@pytest.mark.asyncio
async def test_image_fetch_rejects_non_image_content(monkeypatch):

    async def handler(request):
        return httpx.Response(
            200, request=request,
            headers={"content-type": "text/html"},
            content=b"<html></html>",
        )

    monkeypatch.setattr(
        ind_aidp_service.httpx, "AsyncClient",
        _client_factory_for(httpx.MockTransport(handler)),
    )
    image_ref = _make_image_ref(monkeypatch)

    with pytest.raises(ind_aidp_service.IndependentAidpServiceError, match="non-image"):
        await ind_aidp_service.fetch_ind_aidp_image_impl(image_ref)


@pytest.mark.asyncio
async def test_image_fetch_rejects_oversized_content(monkeypatch):

    async def handler(request):
        return httpx.Response(
            200, request=request,
            headers={"content-type": "image/png"},
            content=b"x" * (20 * 1024 * 1024 + 1),
        )

    monkeypatch.setattr(
        ind_aidp_service.httpx, "AsyncClient",
        _client_factory_for(httpx.MockTransport(handler)),
    )
    image_ref = _make_image_ref(monkeypatch)

    with pytest.raises(ind_aidp_service.IndependentAidpServiceError, match="20 MB"):
        await ind_aidp_service.fetch_ind_aidp_image_impl(image_ref)


@pytest.mark.asyncio
async def test_image_fetch_http_error(monkeypatch):

    async def handler(request):
        return httpx.Response(404, request=request)

    monkeypatch.setattr(
        ind_aidp_service.httpx, "AsyncClient",
        _client_factory_for(httpx.MockTransport(handler)),
    )
    image_ref = _make_image_ref(monkeypatch)

    with pytest.raises(ind_aidp_service.IndependentAidpServiceError, match="HTTP 404"):
        await ind_aidp_service.fetch_ind_aidp_image_impl(image_ref)


@pytest.mark.asyncio
async def test_image_fetch_request_error(monkeypatch):
    def raise_connect(*_a, **_k):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(
        ind_aidp_service.httpx, "AsyncClient",
        _client_factory_for(httpx.MockTransport(raise_connect)),
    )
    image_ref = _make_image_ref(monkeypatch)

    with pytest.raises(ind_aidp_service.IndependentAidpServiceError, match="image request failed"):
        await ind_aidp_service.fetch_ind_aidp_image_impl(image_ref)
