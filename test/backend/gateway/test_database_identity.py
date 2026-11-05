# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only identity snapshots, policy and pool ownership with isolated collaborators."""

import asyncio
import ast
from contextlib import asynccontextmanager
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import httpx
import pytest

from gateway.application import create_gateway_app
from gateway.configuration import GatewaySettings, load_settings
from gateway.security.database_provider import DatabaseIdentityProvider
from gateway.security.identity import IdentityError
from gateway.security.management_client import IdentityUnavailable
from infrastructure.database.identity import IdentityRejected, IdentityRepository, IdentityStoreUnavailable


def snapshot(role="USER", tenant="t1", version=3, active=True):
    return {"account": {"user_id": "u1", "user_role": role, "user_email": "fixture@example.test", "token_version": version},
            "membership": {"tenant_id": tenant}, "token_id": 7, "session_active": active}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,role,tenant,expected", [
    ("session", "USER", "t1", "t1"), ("api_key", "ADMIN", "t1", "t1"),
    ("session", "SU", "", "tenant_id"), ("session", "ASSET_OWNER", "", "asset_owner_tenant_id"),
    ("session", "USER", "", None), ("api_key", "SU", "", None),
    ("api_key", "ASSET_OWNER", "", None), ("session", "", "t1", None),
])
async def test_policy_preserves_canonical_roles_and_empty_tenant_rules(kind, role, tenant, expected):
    repository = SimpleNamespace(snapshot=AsyncMock(return_value=snapshot(role, tenant)))
    provider = DatabaseIdentityProvider(repository)
    query = {"kind": kind, "token_version": 3, "session_id": "s1", "language": "en"}
    if expected is None:
        with pytest.raises(IdentityError):
            await provider(query)
    else:
        result = await provider(query)
        assert result["tenant_id"] == expected and result["role"] == role
        assert result["email"] == "fixture@example.test" and result["language"] == "en"
        assert result["session_id"] == ("s1" if kind == "session" else None)
    repository.snapshot.assert_awaited_once_with(query)


@pytest.mark.asyncio
@pytest.mark.parametrize("version,active", [(2, True), (True, True), (3, False)])
async def test_session_revision_and_revocation_fail_closed(version, active):
    provider = DatabaseIdentityProvider(SimpleNamespace(snapshot=AsyncMock(return_value=snapshot(active=active))))
    with pytest.raises(IdentityError):
        await provider({"kind": "session", "token_version": version})


@pytest.mark.asyncio
@pytest.mark.parametrize("error,expected", [(IdentityRejected("secret"), IdentityError),
                                           (IdentityStoreUnavailable("password=secret"), IdentityUnavailable)])
async def test_provider_sanitizes_storage_failures(error, expected):
    provider = DatabaseIdentityProvider(SimpleNamespace(snapshot=AsyncMock(side_effect=error)))
    with pytest.raises(expected) as caught:
        await provider({"kind": "session"})
    assert "secret" not in str(caught.value)


class Pool:
    def __init__(self, connection):
        self.connection = connection
        self.events = []
        self.close = AsyncMock()
        self.terminate = MagicMock()

    @asynccontextmanager
    async def acquire(self, *, timeout):
        self.events.append(("acquire", timeout))
        try:
            yield self.connection
        finally:
            self.events.append("release")


def repository(rows, *, cas=True):
    transactions = []

    @asynccontextmanager
    async def transaction(**kwargs):
        transactions.append(kwargs)
        yield

    connection = SimpleNamespace(fetch=AsyncMock(side_effect=rows), fetchval=AsyncMock(return_value=cas),
                                 transaction=transaction, terminate=MagicMock())
    pool = Pool(connection)
    return IdentityRepository(pool), connection, pool, transactions


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["session", "api_key"])
async def test_snapshot_uses_one_read_only_transaction_and_bound_parameters(kind):
    account, membership = {"user_id": "u1"}, {"tenant_id": "t1"}
    rows = [[account], [membership]]
    if kind == "api_key": rows.insert(0, [{"user_id": "u1", "token_id": 7}])
    repo, connection, pool, transactions = repository(rows)
    result = await repo.snapshot({"kind": kind, "user_id": "u1", "access_key": "key' OR true--", "session_id": "s1"})
    assert result["account"] == account and result["membership"] == membership
    assert transactions == [{"isolation": "repeatable_read", "readonly": True}]
    assert pool.events == [("acquire", 5), "release"]
    if kind == "api_key":
        args = connection.fetch.await_args_list[0].args
        assert args[1] == "key' OR true--" and args[1] not in args[0]
        connection.fetchval.assert_not_awaited()
    else:
        args = connection.fetchval.await_args.args
        assert "user_id=$2" in args[0] and args[1:3] == ("s1", "u1")


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [[], [{"user_id": "u1"}, {"user_id": "u1"}]])
async def test_missing_or_ambiguous_accounts_reject_and_release_connection(rows):
    repo, _, pool, _ = repository([rows])
    with pytest.raises(IdentityRejected):
        await repo.snapshot({"kind": "session", "user_id": "u1"})
    assert pool.events[-1] == "release"


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [asyncpg.PostgresConnectionError("password=secret"),
                                   asyncpg.InterfaceError("secret"), asyncpg.InternalClientError("secret"),
                                   OSError("secret"), TimeoutError("secret")])
async def test_database_errors_are_sanitized_and_connection_released(error):
    repo, connection, pool, _ = repository([])
    connection.fetch.side_effect = error
    with pytest.raises(IdentityStoreUnavailable) as caught:
        await repo.snapshot({"kind": "session", "user_id": "u1"})
    assert "secret" not in str(caught.value) and pool.events[-1] == "release"
    connection.terminate.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_stalled_query_is_bounded_and_never_reused(cancel):
    repo, connection, pool, _ = repository([])
    started = asyncio.Event()
    async def stuck(*args):
        started.set()
        await asyncio.Event().wait()
    connection.fetch.side_effect = stuck
    repo.timeout = .02
    task = asyncio.create_task(repo.snapshot({"kind": "session", "user_id": "u1"}))
    await started.wait()
    if cancel: task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else IdentityStoreUnavailable):
        await task
    connection.terminate.assert_called_once()
    assert pool.events[-1] == "release" and connection.fetch.await_count == 1


@pytest.mark.asyncio
async def test_api_only_account_preserves_null_email_contract():
    record = snapshot()
    record["account"]["user_email"] = None
    provider = DatabaseIdentityProvider(SimpleNamespace(snapshot=AsyncMock(return_value=record)))
    assert (await provider({"kind": "api_key"}))["email"] is None


@pytest.mark.asyncio
async def test_pool_open_and_shutdown_have_finite_timeouts(monkeypatch):
    pool = Pool(None)
    factory = AsyncMock(return_value=pool)
    monkeypatch.setattr("infrastructure.database.identity.asyncpg.create_pool", factory)
    repo = await IdentityRepository.open(host="host", port=5432, database="fixture", user="reader", password="secret")
    options = factory.await_args.kwargs
    assert options["server_settings"]["default_transaction_read_only"] == "on"
    assert options["command_timeout"] == options["timeout"] == 5
    await repo.close()
    pool.close.assert_awaited_once()
    pool.terminate.assert_not_called()
    async def stuck(): await asyncio.Event().wait()
    pool.close.side_effect = stuck
    repo.timeout = 0.01
    with pytest.raises(TimeoutError):
        await repo.close()
    pool.terminate.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_owns_default_repository_and_does_not_open_management_lookup(monkeypatch):
    repo = SimpleNamespace(snapshot=AsyncMock(), close=AsyncMock())
    factory = AsyncMock(return_value=repo)
    monkeypatch.setattr(IdentityRepository, "open", factory)
    app = create_gateway_app(settings=GatewaySettings(jwt_secret="fixture", db_password="database-secret"),
                             transport=httpx.MockTransport(lambda request: pytest.fail("Unexpected HTTP lookup")))
    async with app.router.lifespan_context(app):
        assert isinstance(app.state.identity_lookup, DatabaseIdentityProvider)
        factory.assert_awaited_once()
    repo.close.assert_awaited_once()


@pytest.mark.parametrize("name,value", [("GATEWAY_DB_PORT", "0"), ("GATEWAY_DB_POOL_SIZE", "0"),
                                         ("GATEWAY_DB_POOL_SIZE", "65"), ("GATEWAY_DB_TIMEOUT", "nan"),
                                         ("GATEWAY_DB_TIMEOUT", "inf"), ("GATEWAY_DB_TIMEOUT", "0")])
def test_invalid_database_configuration_fails_without_secret_disclosure(name, value):
    with pytest.raises(ValueError): load_settings({name: value})


def test_database_credentials_are_required_and_redacted():
    with pytest.raises(ValueError): GatewaySettings().database_options()
    settings = load_settings({"GATEWAY_DB_PASSWORD": "database-secret"})
    assert settings.database_options()["password"] == "database-secret"
    assert "database-secret" not in repr(settings)


def test_database_package_never_imports_business_configuration_or_orm():
    directory = Path(__file__).resolve().parents[3] / "backend/infrastructure/database"
    allowed = set(sys.stdlib_module_names) | {"asyncpg"}
    for path in directory.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = ([node.module] if isinstance(node, ast.ImportFrom) else
                       [item.name for item in node.names] if isinstance(node, ast.Import) else [])
            assert all(module and module.split(".")[0] in allowed for module in modules), path
