# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Read durable execution ownership before touching cross-Pod run state."""

from sqlalchemy.exc import SQLAlchemyError

from contracts.errors.exceptions import RuntimeCoordinationUnavailableError
from infrastructure.rdb.agent_execution import find_owned_agent_execution
from infrastructure.redis.run_state import creator_runtime_state_service as runtime_state_service
from nexent.core.concurrency import ManagedTaskSpec, ThreadManagerError
from management.thread_management import config_thread_manager


async def get_owned_execution(tenant_id, user_id, identifier, *, agent_scope, active_only=False):
    try:
        return await config_thread_manager.run(
            "control-io", ManagedTaskSpec(task_name="runtime-read-owned-execution", owner=__name__),
            find_owned_agent_execution, tenant_id, user_id, identifier, agent_scope=agent_scope, active_only=active_only,
        )
    except (SQLAlchemyError, ThreadManagerError) as exc:
        raise RuntimeCoordinationUnavailableError("Runtime execution state is unavailable") from exc


async def read_owned_stream(user_id, identifier, execution_id):
    try:
        return await runtime_state_service.read_execution_stream_async(user_id, identifier, execution_id)
    except Exception as exc:
        raise RuntimeCoordinationUnavailableError("Runtime replay coordination is unavailable") from exc
