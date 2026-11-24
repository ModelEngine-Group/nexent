# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run one real system-configuration consumer with a JSON command boundary."""

import asyncio
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import redis
from infrastructure.system_configuration.repository import SystemConfigurationRepository
from infrastructure.system_configuration.runtime import SystemConfigurationRuntime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


class _CountQuery:
    def filter(self, *args):
        return self

    def count(self):
        return 1


class _BusinessSession:
    def execute(self, *args, **kwargs):
        return None

    def query(self, *args):
        return _CountQuery()

    def scalar(self, *args):
        return 1


def _config_probe():
    from contracts.errors.exceptions import AppException, TenantResourceLimitError
    from management.api.evaluation import evaluation_set
    from management.db.identity import user_tenant

    session = _BusinessSession()
    tenant_limit = None
    try:
        user_tenant._validate_user_tenant_limit(session, "tenant-1", "USER")
    except TenantResourceLimitError as error:
        tenant_limit = error.limit

    upload = {}
    try:
        evaluation_set._validate_evaluation_set_file_size(
            b"x" * (1024 * 1024 + 1), "set.xlsx"
        )
    except AppException as error:
        upload = error.details
    return {
        "tenant_limit": tenant_limit,
        "limit_mb": upload.get("limit_mb"),
        "limit_bytes": upload.get("limit_bytes"),
        "existing_count": session.scalar(None),
    }


def _northbound_probe():
    from contracts.errors.exceptions import AppException
    from management.db.conversation import repository

    session = _BusinessSession()
    try:
        repository._enforce_user_conversation_limit(session, "user-1")
    except AppException as error:
        details = error.details
    else:
        details = {}
    return {
        "conversation_limit": details.get("limit"),
        "existing_count": details.get("current_count"),
    }


async def _runtime_probe():
    from infrastructure.system_configuration.runtime import get_config_snapshot
    from management.services.agent.preparation import run as preparation
    from management.services.agent.preparation.tools import (
        _build_parallel_executor_tool_config,
    )
    from nexent.core.tools.parallel_executor import ParallelExecutorTool

    agent_config = SimpleNamespace(
        model_name="model",
        capacity_snapshot=None,
        context_budget_snapshot=None,
        sandbox_policy=None,
    )
    with (
        patch.object(
            preparation, "_build_run_workspace", return_value="/tmp/config-test"
        ),
        patch.object(preparation, "_collect_run_minio_files", return_value=[]),
        patch.object(preparation, "_validate_run_minio_files", return_value=None),
        patch.object(preparation, "query_current_version_no", return_value=0),
        patch.object(
            preparation, "_ensure_agent_reasoning_snapshot", return_value=None
        ),
        patch.object(
            preparation,
            "join_minio_file_description_to_query",
            new=AsyncMock(return_value="query"),
        ),
        patch.object(
            preparation, "create_model_config_list", new=AsyncMock(return_value=[])
        ),
        patch.object(
            preparation,
            "create_agent_config",
            new=AsyncMock(return_value=agent_config),
        ),
        patch.object(preparation, "search_agent_info_by_agent_id", return_value={}),
        patch(
            "management.services.agent.model_parameters.bind_agent_model_profiles",
            return_value=None,
        ),
        patch.object(preparation, "apply_root_model_preferences", return_value=None),
        patch.object(
            preparation,
            "get_remote_mcp_server_list",
            new=AsyncMock(return_value=[]),
        ),
        patch.object(
            preparation,
            "get_tenant_local_mcp_server",
            return_value="http://example.invalid/mcp",
        ),
        patch.object(preparation, "filter_mcp_servers_and_tools", return_value=[]),
        patch.object(preparation, "_convert_history_with_minio_files", return_value=[]),
        patch(
            "management.services.agent.policy.build_sandbox_policy", return_value=None
        ),
        patch(
            "runtime.adapters.nexent.sandbox.resolve_sandbox_config", return_value=None
        ),
        patch.object(preparation, "get_redis_client", return_value=None),
        patch.object(preparation, "resolve_tool_user_context", return_value={}),
        patch.object(
            preparation, "build_run_info", side_effect=lambda **kwargs: kwargs
        ),
    ):
        prepared = await preparation.create_agent_run_info(
            agent_id=1,
            minio_files=[],
            query="query",
            history=[],
            tenant_id="tenant-1",
            user_id="user-1",
        )
    parallel_config = _build_parallel_executor_tool_config(
        get_config_snapshot().get("RUNTIME_PARALLEL_EXECUTOR_TIMEOUT_SECONDS")
    )
    parallel_tool = ParallelExecutorTool(**parallel_config.params)
    return {
        "mcp_request_timeout_seconds": prepared["mcp_request_timeout_seconds"],
        "mcp_tool_timeout_seconds": prepared["mcp_tool_timeout_seconds"],
        "parallel_timeout_seconds": parallel_tool.default_timeout_seconds,
    }


async def _business_probe(service):
    if service == "config":
        return _config_probe()
    if service == "northbound":
        return _northbound_probe()
    return await _runtime_probe()


def _emit(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


async def _run(service):
    import infrastructure.system_configuration.runtime as runtime_module

    engine = create_engine(
        os.environ["NEXENT_SYSTEM_CONFIG_TEST_DATABASE_URL"],
        hide_parameters=True,
        pool_pre_ping=True,
    )
    repository = SystemConfigurationRepository()

    async def load_values():
        with Session(engine) as session:
            return repository.load_snapshot(session, read_only=True).values

    def redis_factory():
        return redis.asyncio.Redis.from_url(
            os.environ["NEXENT_SYSTEM_CONFIG_TEST_REDIS_URL"],
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=0.5,
        )

    runtime = SystemConfigurationRuntime(
        loader=load_values,
        redis_factory=redis_factory,
        normal_interval=0.05,
        disconnected_interval=0.02,
    )
    runtime_module._process_runtime = runtime
    await runtime.start()
    try:
        _emit(
            {
                "type": "ready",
                "service": service,
                "pid": os.getpid(),
                "values": runtime.get_snapshot().to_dict(),
            }
        )
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            command = json.loads(line)
            if command["type"] == "stop":
                _emit({"type": "stopped"})
                break
            if command["type"] == "snapshot":
                _emit({"type": "snapshot", "values": runtime.get_snapshot().to_dict()})
            elif command["type"] == "business":
                _emit({"type": "business", "values": await _business_probe(service)})
    finally:
        await runtime.stop()
        runtime_module._process_runtime = None
        engine.dispose()


def main():
    service = sys.argv[1]
    try:
        asyncio.run(_run(service))
    except Exception as error:
        _emit({"type": "error", "message": f"{type(error).__name__}: {error}"})
        raise


if __name__ == "__main__":
    main()
