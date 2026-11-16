# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""AIDP image URL and credential isolation regressions."""

from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlparse

import management.services.file.image_content  # noqa: F401 - Load the capability before legacy SDK stubs.
import pytest

from test.backend.management.import_patching import (
    patch_import_object_context,
    set_import_attribute,
)
from test.common.test_mocks import bootstrap_test_env

bootstrap_test_env()
from management.services.file import image_proxy as image_service_module


class TestIsAidpUrl:
    """``_is_aidp_url`` recognizes permitted AIDP image paths and the
    proxy reconstructs them against the configured AIDP authority before
    adding the Bearer header."""

    def test_matches_when_host_and_path_match(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "https://aidp.example.com")
        assert image_service_module._is_aidp_url(
            "https://aidp.example.com/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/img.png"
        )

    def test_accepts_alias_host_but_rewrites_to_configured_host(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "https://aidp.example.com")
        assert image_service_module._is_aidp_url(
            "https://other.host/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/img.png"
        )

    def test_rejects_right_host_wrong_path(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "https://aidp.example.com")
        assert not image_service_module._is_aidp_url(
            "https://aidp.example.com/some/other/path.png"
        )

    def test_rejects_when_env_empty(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "")
        assert not image_service_module._is_aidp_url(
            "https://aidp.example.com/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/img.png"
        )

    def test_ignores_trailing_slash_in_env(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "https://aidp.example.com/")
        assert image_service_module._is_aidp_url(
            "https://aidp.example.com/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/img.png"
        )

    def test_matches_view_image_path(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "https://aidp.example.com")
        assert image_service_module._is_aidp_url(
            "https://aidp.example.com/KnowledgeBase/Tenants/aidp/"
            "KnowledgeBases/75/ViewImage/image-id.png"
        )


class TestFetchAidpImage:
    """``_fetch_aidp_image`` must attach the Bearer header and disable
    redirects so credentials never leak to a 30x target."""

    @pytest.mark.asyncio
    async def test_attaches_bearer_header_and_returns_base64(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "https://aidp.example.com")
        set_import_attribute(monkeypatch, image_service_module, "AIDP_API_KEY", "secret-key")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=b"\x89PNG\r\n\x1a\nfake")
        mock_response.headers = {"Content-Type": "image/png"}
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch_import_object_context(
            image_service_module.aiohttp, "ClientSession", return_value=mock_session
        ):
            result = await image_service_module._fetch_aidp_image(
                "https://aidp.example.com/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/img.png"
            )

        assert result["success"] is True
        assert result["content_type"] == "image/png"
        # Header and redirect guards asserted
        call_kwargs = mock_session.get.call_args.kwargs
        assert call_kwargs["headers"] == {"Authorization": "Bearer secret-key"}
        assert call_kwargs["allow_redirects"] is False

    @pytest.mark.asyncio
    async def test_returns_error_when_api_key_missing(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "https://aidp.example.com")
        set_import_attribute(monkeypatch, image_service_module, "AIDP_API_KEY", "")
        result = await image_service_module._fetch_aidp_image(
            "https://aidp.example.com/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/img.png"
        )
        assert result["success"] is False
        assert "not configured" in result["error"]


class TestProxyImageImplAidpPath:
    """End-to-end: when the URL is AIDP-shaped, proxy_image_impl MUST route
    through the AIDP fetcher, NOT the data-process-service or loopback
    paths."""

    @pytest.mark.asyncio
    async def test_aidp_url_short_circuits_to_fetch_aidp_image(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "https://aidp.example.com")
        set_import_attribute(monkeypatch, image_service_module, "AIDP_API_KEY", "secret")

        sentinel = {"success": True, "base64": "abc", "content_type": "image/jpeg"}
        called = {"aidp": False, "direct": False, "dp": False}

        async def fake_aidp(url):
            called["aidp"] = True
            return sentinel

        async def fake_direct(url):
            called["direct"] = True

        aidp_spy = AsyncMock(side_effect=fake_aidp)
        direct_spy = AsyncMock(side_effect=fake_direct)

        with patch_import_object_context(image_service_module, "_fetch_aidp_image", aidp_spy), patch_import_object_context(
            image_service_module, "_fetch_image_directly", direct_spy
        ):
            result = await image_service_module.proxy_image_impl(
                "https://aidp.example.com/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/img.png"
            )

        assert result is sentinel
        assert called["aidp"] is True
        assert called["direct"] is False

    @pytest.mark.asyncio
    async def test_non_aidp_url_does_not_go_through_aidp_path(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "https://aidp.example.com")
        aidp = AsyncMock()
        fetch = AsyncMock(return_value={"success": True})
        with patch_import_object_context(image_service_module, "_fetch_aidp_image", aidp), patch_import_object_context(
            image_service_module, "_validate_loopback_url", return_value=None
        ), patch_import_object_context(image_service_module, "fetch_image_content", fetch):
            assert await image_service_module.proxy_image_impl("https://other.host/img.png") == {"success": True}
        aidp.assert_not_called()
        fetch.assert_awaited_once_with("https://other.host/img.png", user_id=None, tenant_id=None)


class TestValidateAndReconstructAidpUrl:
    """Validate that ``_validate_and_reconstruct_aidp_url`` enforces path,
    scheme, traversal, and authority replacement rules."""

    def test_returns_none_when_env_empty(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "")
        assert image_service_module._validate_and_reconstruct_aidp_url(
            "https://aidp.example.com/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/img.png"
        ) is None

    def test_returns_none_for_non_http_scheme(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "https://aidp.example.com")
        assert image_service_module._validate_and_reconstruct_aidp_url(
            "ftp://aidp.example.com/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/img.png"
        ) is None

    def test_returns_none_when_path_outside_prefix(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "https://aidp.example.com")
        assert image_service_module._validate_and_reconstruct_aidp_url(
            "https://aidp.example.com/other/path.png"
        ) is None

    def test_returns_none_when_path_contains_traversal_segments(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "https://aidp.example.com")
        assert image_service_module._validate_and_reconstruct_aidp_url(
            "https://aidp.example.com/KnowledgeBase/Tenants/aidp/../evil/img.png"
        ) is None

    def test_returns_none_when_path_ends_with_dotdot(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "https://aidp.example.com")
        assert image_service_module._validate_and_reconstruct_aidp_url(
            "https://aidp.example.com/KnowledgeBase/Tenants/aidp/.."
        ) is None

    def test_returns_none_when_query_present(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "https://aidp.example.com")
        assert image_service_module._validate_and_reconstruct_aidp_url(
            "https://aidp.example.com/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/img.png?foo=bar"
        ) is None

    def test_returns_none_when_fragment_present(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "https://aidp.example.com")
        assert image_service_module._validate_and_reconstruct_aidp_url(
            "https://aidp.example.com/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/img.png#frag"
        ) is None

    def test_returns_reconstructed_url_with_configured_authority(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "https://aidp.example.com")
        result = image_service_module._validate_and_reconstruct_aidp_url(
            "https://other.host/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/img.png"
        )
        assert result is not None
        # Host must be replaced with the configured authority, NOT the original host
        parsed_result = urlparse(result)
        assert parsed_result.netloc == "aidp.example.com"
        assert parsed_result.netloc != "other.host"

    def test_preserves_same_host_url(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "https://aidp.example.com")
        input_url = "https://aidp.example.com/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/img.png"
        result = image_service_module._validate_and_reconstruct_aidp_url(input_url)
        assert result is not None
        parsed_result = urlparse(result)
        assert parsed_result.netloc == "aidp.example.com"
        assert parsed_result.path == "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/img.png"

    def test_returns_none_when_parsed_path_is_none(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "https://aidp.example.com")
        # Empty string has no scheme/netloc/path -> must return None
        assert image_service_module._validate_and_reconstruct_aidp_url("") is None
        # Malformed input with no netloc -> must return None
        assert image_service_module._validate_and_reconstruct_aidp_url(":not-a-url") is None

    def test_returns_reconstructed_url_with_base_scheme_and_netloc(self, monkeypatch):
        # Input uses http, base uses https -> output must use base scheme
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "https://aidp.example.com")
        result = image_service_module._validate_and_reconstruct_aidp_url(
            "http://other.host/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/img.png"
        )
        assert result is not None
        parsed_result = urlparse(result)
        assert parsed_result.scheme == "https"
        assert parsed_result.netloc == "aidp.example.com"

    def test_returns_none_when_base_parsed_netloc_is_empty(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "file:///x")
        assert image_service_module._validate_and_reconstruct_aidp_url(
            "https://aidp.example.com/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/img.png"
        ) is None

    def test_returns_none_when_base_scheme_not_http(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "ftp://aidp.example.com")
        assert image_service_module._validate_and_reconstruct_aidp_url(
            "https://aidp.example.com/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/img.png"
        ) is None


class TestFetchAidpImageHostReplacement:
    """``_fetch_aidp_image`` must reconstruct the URL at the point of use so
    that the Bearer token is only sent to the configured AIDP authority."""

    @pytest.mark.asyncio
    async def test_uses_reconstructed_url_with_configured_host(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "https://aidp.example.com")
        set_import_attribute(monkeypatch, image_service_module, "AIDP_API_KEY", "test-api-key")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=b"fake-image-bytes")
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        input_url = (
            "https://alias.host/KnowledgeBase/Tenants/aidp/"
            "KnowledgeBases/kb-1/img.png"
        )

        with patch_import_object_context(
            image_service_module.aiohttp, "ClientSession", return_value=mock_session
        ):
            result = await image_service_module._fetch_aidp_image(input_url)

        assert result["success"] is True

        # The actual GET must use the reconstructed URL with the configured host
        call_args = mock_session.get.call_args
        called_url = call_args.args[0]
        parsed_called = urlparse(called_url)
        assert parsed_called.netloc == "aidp.example.com"
        assert parsed_called.netloc != "alias.host"
        assert parsed_called.path == "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/img.png"

        # Bearer header must use AIDP_API_KEY
        assert call_args.kwargs["headers"] == {"Authorization": "Bearer test-api-key"}
        # Redirects must be disabled
        assert call_args.kwargs["allow_redirects"] is False

    @pytest.mark.asyncio
    async def test_rejects_url_with_path_traversal(self, monkeypatch):
        set_import_attribute(monkeypatch, image_service_module, "AIDP_SERVER_URL", "https://aidp.example.com")
        set_import_attribute(monkeypatch, image_service_module, "AIDP_API_KEY", "test-api-key")

        traversal_url = (
            "https://aidp.example.com/KnowledgeBase/Tenants/../evil/img.png"
        )

        # _validate_and_reconstruct_aidp_url rejects traversal, so
        # _fetch_aidp_image returns a failure without making any HTTP call.
        result = await image_service_module._fetch_aidp_image(traversal_url)

        assert result["success"] is False
        assert result["error"] == "URL does not match configured AIDP host or KB path"
