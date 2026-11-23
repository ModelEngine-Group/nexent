"""Model preparation must not grant permissions or cross tenant boundaries."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "automation"))
from shared import model_catalog


def identity(role="USER", tenant="tenant-runtime"):
    return SimpleNamespace(role=role, configured_tenant="fixture-tenant", tenant_id=tenant,
                           access_token="fixture-user-session")


def response(code, body):
    return httpx.Response(code, json=body, request=httpx.Request("GET", "http://fixture.test/model/list"))


class ModelCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_discovery_uses_same_tenant_admin(self):
        owner = identity()
        admin = identity("ADMIN")
        admin.access_token = "fixture-admin-session"
        api = SimpleNamespace(get=AsyncMock(side_effect=[
            response(403, {"message": "Missing required permission: model:read"}),
            response(200, [{"model_id": 7, "model_type": "llm"}]),
            response(200, {"config": {"models": {"llm": {"id": 7}}}}),
        ]))
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=api)
        context.__aexit__ = AsyncMock(return_value=False)
        with patch.object(model_catalog, "client", return_value=context) as make_client, \
                patch.object(model_catalog, "load_yaml", return_value={"users": [
                    {"id": "fixture-admin", "tenant": "fixture-tenant", "role": "admin"}]}), \
                patch.object(model_catalog, "sign_in", AsyncMock(return_value=admin)):
            rows, selected, reader = await model_catalog.load_model_catalog(owner)
        self.assertEqual(rows[0]["model_id"], 7)
        self.assertEqual(selected["config"]["models"]["llm"]["id"], 7)
        self.assertIs(reader, admin)
        self.assertEqual([call.kwargs["token"] for call in make_client.call_args_list],
                         ["fixture-user-session", "fixture-admin-session", "fixture-admin-session"])
        self.assertEqual(owner.role, "USER")
        self.assertEqual(owner.access_token, "fixture-user-session")

    async def test_actual_cross_tenant_admin_is_rejected(self):
        with patch.object(model_catalog, "load_yaml", return_value={"users": [
                {"id": "fixture-admin", "tenant": "fixture-tenant", "role": "admin"}]}), \
                patch.object(model_catalog, "sign_in", AsyncMock(return_value=identity("ADMIN", "other-tenant"))):
            with self.assertRaises(model_catalog.AssetDependencyError):
                await model_catalog.catalog_reader(identity())

    async def test_ambiguous_or_missing_admin_does_not_guess(self):
        for users in [[], [
            {"id": "a", "tenant": "fixture-tenant", "role": "admin"},
            {"id": "b", "tenant": "fixture-tenant", "role": "admin"},
        ]]:
            with patch.object(model_catalog, "load_yaml", return_value={"users": users}), \
                    patch.object(model_catalog, "sign_in", AsyncMock()) as login:
                with self.assertRaises(model_catalog.AssetDependencyError):
                    await model_catalog.catalog_reader(identity())
                login.assert_not_awaited()

    async def test_admin_denial_or_auth_failure_is_not_bypassed(self):
        for who, code in [(identity("ADMIN"), 403), (identity(), 401), (identity(), 500)]:
            api = SimpleNamespace(get=AsyncMock(return_value=response(code, {})))
            context = MagicMock()
            context.__aenter__ = AsyncMock(return_value=api)
            context.__aexit__ = AsyncMock(return_value=False)
            with patch.object(model_catalog, "client", return_value=context), \
                    patch.object(model_catalog, "catalog_reader", AsyncMock()) as reader:
                with self.assertRaises(AssertionError):
                    await model_catalog.load_model_catalog(who)
                reader.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

