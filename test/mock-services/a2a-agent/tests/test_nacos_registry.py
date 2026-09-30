"""Admin authentication is independent of Nacos client API authentication."""
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import httpx

from app.config import Settings
from app.nacos_registry import NacosRegistry


class RegistryAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_login_is_required_in_both_client_auth_modes(self):
        for enabled in (False, True):
            with self.subTest(client_auth=enabled):
                registry = NacosRegistry(replace(Settings.from_env(), nacos_auth_enabled=enabled))
                client = AsyncMock()
                client.post.return_value = httpx.Response(200, json={"code": 0}, request=httpx.Request("POST", "http://mock/register"))
                with patch("app.nacos_registry.httpx.AsyncClient") as factory, patch.object(registry, "_login", new=AsyncMock(return_value="synthetic-admin-token")) as login:
                    factory.return_value.__aenter__.return_value = client
                    await registry.register_once()
                login.assert_awaited_once_with(client)
                self.assertEqual(client.post.call_args.kwargs["headers"], {"accessToken": "synthetic-admin-token"})
                self.assertTrue(registry.state.registered)

    async def test_login_failure_prevents_registration(self):
        registry = NacosRegistry(Settings.from_env())
        client = AsyncMock()
        with patch("app.nacos_registry.httpx.AsyncClient") as factory, patch.object(registry, "_login", new=AsyncMock(side_effect=RuntimeError("login failed"))):
            factory.return_value.__aenter__.return_value = client
            with self.assertRaisesRegex(RuntimeError, "login failed"):
                await registry.register_once()
        client.post.assert_not_awaited()
        self.assertFalse(registry.state.registered)
