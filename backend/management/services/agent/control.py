# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Read durable execution ownership before touching cross-Pod run state."""

from contracts.errors.exceptions import RuntimeCoordinationUnavailableError
from infrastructure.redis.run_state import runtime_state_service
from management.services.execution_coordination import read_owned_agent_execution
from nexent.core.concurrency import ManagedTaskSpec, ThreadManagerError
from management.thread_management import config_thread_manager


async def get_owned_execution(tenant_id, user_id, identifier, *, active_only=False):
    try:
        return await config_thread_manager.run(
            "control-io", ManagedTaskSpec(task_name="runtime-read-owned-execution", owner=__name__),
            read_owned_agent_execution, tenant_id, user_id, identifier, active_only=active_only,
        )
    except ThreadManagerError as exc:
        raise RuntimeCoordinationUnavailableError("Runtime execution state is unavailable") from exc


async def request_owned_stop(tenant_id, user_id, identifier, expected_generation=None) -> bool:
    owned = await get_owned_execution(tenant_id, user_id, identifier, active_only=True)
    if owned is None:
        return False
    execution_id = owned[0]
    try:
        return await runtime_state_service.request_execution_cancel_async(
            user_id, identifier, execution_id, expected_generation,
        )
    except Exception as exc:
        raise RuntimeCoordinationUnavailableError("Runtime stop coordination is unavailable") from exc


async def read_owned_stream(user_id, identifier, execution_id):
    try:
        return await runtime_state_service.read_execution_stream_async(user_id, identifier, execution_id)
    except Exception as exc:
        raise RuntimeCoordinationUnavailableError("Runtime replay coordination is unavailable") from exc
