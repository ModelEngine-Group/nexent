# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Redis-triggered, database-reconciled immutable system configuration snapshots."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress

from infrastructure.system_configuration.catalog import (
    DEFAULT_CATALOG,
    ConfigValue,
    SystemConfigurationSnapshot,
)

logger = logging.getLogger(__name__)

CONFIGURATION_CHANNEL = "nexent:system-configuration"
CONFIGURATION_CHANGED = "configuration_changed"


class ConfigurationNotReadyError(RuntimeError):
    """Indicate that no valid database snapshot is available locally."""


class SystemConfigurationRuntime:
    def __init__(
        self,
        *,
        loader: Callable[[], Awaitable[Mapping[str, ConfigValue]]],
        redis_factory: Callable | None = None,
        normal_interval: float = 5.0,
        disconnected_interval: float = 2.0,
    ) -> None:
        self._loader = loader
        self._redis_factory = redis_factory or self._default_redis_factory
        self._normal_interval = normal_interval
        self._disconnected_interval = disconnected_interval
        self._snapshot: SystemConfigurationSnapshot | None = None
        self._refresh_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._redis = None
        self._pubsub = None

    @staticmethod
    def _default_redis_factory():
        from contracts.constants.environment import REDIS_URL
        from redis.asyncio import Redis

        return Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=7,
        )

    def get_snapshot(self) -> SystemConfigurationSnapshot:
        if self._snapshot is None:
            raise ConfigurationNotReadyError(
                "No valid system configuration snapshot is available"
            )
        return self._snapshot

    @property
    def is_ready(self) -> bool:
        """Report whether at least one valid database snapshot was loaded."""
        return self._snapshot is not None

    def store_snapshot(self, values: Mapping[str, ConfigValue]) -> None:
        """Validate and publish a snapshot for synchronous command consumers."""
        self._snapshot = DEFAULT_CATALOG.build_snapshot(values)

    async def refresh(self) -> bool:
        async with self._refresh_lock:
            try:
                values = await self._loader()
                snapshot = DEFAULT_CATALOG.build_snapshot(values)
            except Exception:  # noqa: BLE001 - retain the last valid snapshot
                logger.error(
                    "System configuration refresh failed; retaining the last valid snapshot"
                )
                return False
            self._snapshot = snapshot
            return True

    async def poll_once(self, pubsub) -> None:
        message = await pubsub.get_message(
            ignore_subscribe_messages=True,
            timeout=self._normal_interval,
        )
        if message is not None and message.get("channel") == CONFIGURATION_CHANNEL:
            while True:
                duplicate = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=0,
                )
                if duplicate is None:
                    break
        await self.refresh()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop_event.clear()
        await self.refresh()
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    self._redis = self._redis_factory()
                    self._pubsub = self._redis.pubsub()
                    await self._pubsub.subscribe(CONFIGURATION_CHANNEL)
                    await self.refresh()
                    while not self._stop_event.is_set():
                        await self.poll_once(self._pubsub)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - reconnect through polling
                    logger.error(
                        "System configuration Redis connection failed; using database polling"
                    )
                    await self._close_connection()
                    await self.refresh()
                    with suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(
                            self._stop_event.wait(),
                            timeout=self._disconnected_interval,
                        )
        finally:
            await self._close_connection()

    async def _close_connection(self) -> None:
        pubsub, redis = self._pubsub, self._redis
        self._pubsub, self._redis = None, None
        if pubsub is not None:
            close = getattr(pubsub, "aclose", None) or pubsub.close
            result = close()
            if result is not None:
                await result
        if redis is not None:
            close = getattr(redis, "aclose", None) or redis.close
            result = close()
            if result is not None:
                await result

    async def stop(self) -> None:
        self._stop_event.set()
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await self._close_connection()


_process_runtime: SystemConfigurationRuntime | None = None
_process_database = None


async def start_system_configuration(run_database) -> SystemConfigurationRuntime:
    """Start the single process-local implementation with a managed DB runner."""
    global _process_runtime
    global _process_database
    if _process_runtime is None:
        from infrastructure.system_configuration.database import configuration_database
        from infrastructure.system_configuration.repository import SystemConfigurationRepository

        _process_database = configuration_database
        repository = SystemConfigurationRepository()

        def load_values():
            with _process_database.session() as session:
                return repository.load_snapshot(session, read_only=True).values

        async def loader():
            return await run_database(load_values)

        _process_runtime = SystemConfigurationRuntime(loader=loader)
    await _process_runtime.start()
    return _process_runtime


async def stop_system_configuration() -> None:
    global _process_runtime
    global _process_database
    runtime, _process_runtime = _process_runtime, None
    if runtime is not None:
        await runtime.stop()
    if _process_database is not None:
        _process_database.dispose()
        _process_database = None


def get_config_snapshot() -> SystemConfigurationSnapshot:
    """Read only the current process memory, never a network dependency."""
    if _process_runtime is None:
        raise ConfigurationNotReadyError("System configuration runtime has not started")
    return _process_runtime.get_snapshot()


def load_system_configuration() -> None:
    """Load one database snapshot without starting Redis for a standalone command."""
    global _process_runtime
    global _process_database
    from infrastructure.system_configuration.database import configuration_database
    from infrastructure.system_configuration.repository import SystemConfigurationRepository

    _process_database = configuration_database
    repository = SystemConfigurationRepository()

    def load_values():
        with _process_database.session() as session:
            return repository.load_snapshot(session, read_only=True).values

    if _process_runtime is None:

        async def loader():
            return load_values()

        _process_runtime = SystemConfigurationRuntime(loader=loader)
    _process_runtime.store_snapshot(load_values())
