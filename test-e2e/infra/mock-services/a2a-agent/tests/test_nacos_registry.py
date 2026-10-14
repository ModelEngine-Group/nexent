"""Admin authentication is independent of Nacos client API authentication."""
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import httpx

from app.config import Settings
from app.cards import card_dict
from app.nacos_registry import NacosRegistry


class RegistryAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_updates_only_owned_conflict_and_verifies_readback(self):
        registry = NacosRegistry(Settings.from_env())
        card = card_dict(registry.settings.advertised_base_url, "basic", name=registry.settings.nacos_agent_name)
        client = AsyncMock()
        request = httpx.Request("POST", "http://mock/register")
        client.post.return_value = httpx.Response(409, request=request)
        client.get.return_value = httpx.Response(200, json={"code": 0, "data": card}, request=request)
        client.put.return_value = httpx.Response(200, json={"code": 0}, request=request)
        with patch("app.nacos_registry.httpx.AsyncClient") as factory, patch.object(registry, "_login", new=AsyncMock(return_value="test-token")):
            factory.return_value.__aenter__.return_value = client
            await registry.register_once()
        self.assertTrue(registry.state.registered)
        self.assertEqual(client.get.await_count, 2)
        client.put.assert_awaited_once()
        self.assertEqual(client.put.call_args.kwargs["data"]["setAsLatest"], "true")

    async def test_conflict_cannot_overwrite_foreign_card(self):
        registry = NacosRegistry(Settings.from_env())
        request = httpx.Request("POST", "http://mock/register")
        card = card_dict(registry.settings.advertised_base_url, "basic", name=registry.settings.nacos_agent_name)
        foreign_cards = (
            {}, {**card, "name": "another-agent"},
            {**card, "version": "2.0.0"},
            {**card, "description": "Not this Mock"},
            {**card, "supportedInterfaces": [{"url": "http://another-service/agent"}]},
        )
        for data in foreign_cards:
            client = AsyncMock()
            client.post.return_value = httpx.Response(409, request=request)
            client.get.return_value = httpx.Response(200, json={"code": 0, "data": data}, request=request)
            with patch("app.nacos_registry.httpx.AsyncClient") as factory, patch.object(registry, "_login", new=AsyncMock(return_value="test-token")):
                factory.return_value.__aenter__.return_value = client
                with self.assertRaisesRegex(RuntimeError, "not owned"):
                    await registry.register_once()
            client.put.assert_not_awaited()
            self.assertFalse(registry.state.registered)

    async def test_conflict_update_failure_and_bad_readback_are_not_ready(self):
        registry = NacosRegistry(Settings.from_env())
        card = card_dict(registry.settings.advertised_base_url, "basic", name=registry.settings.nacos_agent_name)
        request = httpx.Request("POST", "http://mock/register")
        for status, readback in ((500, card), (200, {})):
            client = AsyncMock()
            client.post.return_value = httpx.Response(409, request=request)
            client.get.side_effect = [httpx.Response(200, json={"code": 0, "data": value}, request=request) for value in (card, readback)]
            client.put.return_value = httpx.Response(status, json={"code": 0}, request=request)
            with patch("app.nacos_registry.httpx.AsyncClient") as factory, patch.object(registry, "_login", new=AsyncMock(return_value="test-token")):
                factory.return_value.__aenter__.return_value = client
                with self.assertRaises((RuntimeError, httpx.HTTPStatusError)):
                    await registry.register_once()
            self.assertFalse(registry.state.registered)

    async def test_non_conflict_registration_error_is_not_recovered(self):
        registry = NacosRegistry(Settings.from_env())
        client = AsyncMock()
        client.post.return_value = httpx.Response(403, request=httpx.Request("POST", "http://mock/register"))
        with patch("app.nacos_registry.httpx.AsyncClient") as factory, patch.object(registry, "_login", new=AsyncMock(return_value="test-token")):
            factory.return_value.__aenter__.return_value = client
            with self.assertRaises(httpx.HTTPStatusError):
                await registry.register_once()
        client.get.assert_not_awaited()
        client.put.assert_not_awaited()

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
