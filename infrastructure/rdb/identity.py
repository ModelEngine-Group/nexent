# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded, read-only identity snapshots without business ORM or SDK imports."""

import asyncio
from datetime import datetime

import asyncpg


class IdentityRejected(ValueError):
    """No unambiguous active identity exists."""


class IdentityStoreUnavailable(RuntimeError):
    """Sanitized storage failure; never includes query parameters or credentials."""


class IdentityRepository:
    def __init__(self, pool, *, timeout=5):
        self.pool, self.timeout = pool, timeout

    @classmethod
    async def open(cls, *, host, port, database, user, password, max_size=8, timeout=5):
        try:
            pool = await asyncpg.create_pool(
                host=host, port=port, database=database, user=user, password=password,
                min_size=1, max_size=max_size, timeout=timeout, command_timeout=timeout,
                server_settings={"application_name": "nexent-gateway-identity",
                                 "default_transaction_read_only": "on",
                                 "statement_timeout": str(int(timeout * 1000))},
            )
            return cls(pool, timeout=timeout)
        except (asyncpg.PostgresError, asyncpg.InterfaceError, asyncpg.InternalClientError, OSError, TimeoutError):
            raise IdentityStoreUnavailable("Identity database unavailable") from None

    async def close(self):
        try:
            async with asyncio.timeout(self.timeout):
                await self.pool.close()
        except (TimeoutError, asyncio.CancelledError):
            self.pool.terminate()
            raise

    @staticmethod
    def _one(rows):
        if len(rows) != 1:
            raise IdentityRejected("Identity unavailable or ambiguous")
        return dict(rows[0])

    async def snapshot(self, query):
        try:
            async with asyncio.timeout(self.timeout):
                async with self.pool.acquire(timeout=self.timeout) as connection:
                    try:
                        async with connection.transaction(isolation="repeatable_read", readonly=True):
                            return await self._snapshot(connection, query)
                    except (asyncpg.PostgresError, asyncpg.InterfaceError, asyncpg.InternalClientError, OSError):
                        # A server disconnect can leave a pending protocol operation.
                        # Never return that connection to the pool or retry identity.
                        connection.terminate()
                        raise IdentityStoreUnavailable("Identity database unavailable") from None
                    except asyncio.CancelledError:
                        connection.terminate()
                        raise
        except IdentityRejected:
            raise
        except (asyncpg.PostgresError, asyncpg.InterfaceError, asyncpg.InternalClientError, OSError, TimeoutError):
            raise IdentityStoreUnavailable("Identity database unavailable") from None

    async def _snapshot(self, connection, query):
        kind = query.get("kind")
        token_id = None
        if kind == "api_key":
            token = self._one(await connection.fetch(
                "SELECT user_id, token_id FROM nexent.user_token_info_t "
                "WHERE access_key=$1 AND delete_flag='N' LIMIT 2", query.get("access_key")))
            user_id, token_id = token["user_id"], token["token_id"]
        elif kind == "session":
            user_id = query.get("user_id")
        else:
            raise IdentityRejected("Unsupported identity kind")
        if not isinstance(user_id, str) or not user_id:
            raise IdentityRejected("Missing identity")
        account = self._one(await connection.fetch(
            "SELECT user_id, user_email, user_role, token_version FROM nexent.user_account_t "
            "WHERE user_id=$1 AND delete_flag='N' LIMIT 2", user_id))
        membership = self._one(await connection.fetch(
            "SELECT tenant_id FROM nexent.user_tenant_t "
            "WHERE user_id=$1 AND delete_flag='N' ORDER BY user_tenant_id LIMIT 1", user_id))
        session_active = True
        if kind == "session" and query.get("session_id"):
            # CAS stores naive local timestamps today. Gateway and Management
            # deployments use the same TZ; preserve the existing expiry contract.
            session_active = bool(await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM nexent.user_cas_session_t "
                "WHERE session_id=$1 AND user_id=$2 AND status='active' "
                "AND delete_flag='N' AND expires_at>$3)", query["session_id"], user_id, datetime.now()))
        return {"account": account, "membership": membership, "token_id": token_id,
                "session_active": session_active}
