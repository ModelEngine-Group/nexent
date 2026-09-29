import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import apps.northbound_base_app as nba


@pytest.mark.stage('D5')
@pytest.mark.case_id('REL-AUTO-ECAC7A02C22B21FF')
@pytest.mark.asyncio
async def test_northbound_startup_recovery_and_shutdown_contract():
    recover = AsyncMock(return_value={'a2a_tasks': 3})
    cleanup = AsyncMock(return_value=None)
    manager = MagicMock()
    manager.run = AsyncMock(return_value=None)

    with (
        patch.object(nba, 'northbound_thread_manager', manager),
        patch(
            'services.startup_recovery_service.recover_northbound_tasks',
            recover,
        ),
        patch(
            'services.startup_recovery_service.schedule_interrupted_upload_cleanup',
            cleanup,
        ),
    ):
        await nba.recover_northbound_tasks_on_startup()

    manager.run.assert_awaited_once()
    profile, spec, fn = manager.run.await_args.args
    assert profile == 'control-io'
    assert isinstance(spec, nba.ManagedTaskSpec)
    assert spec.task_name == 'recover-northbound-tasks'
    assert spec.owner == 'apps.northbound_base_app'
    assert fn is recover
    cleanup.assert_awaited_once_with(nba.NORTHBOUND_SERVICE_NAME)

    manager = MagicMock()
    manager.state = nba.ManagerState.CREATED
    manager.start = MagicMock(return_value=None)
    manager.run = AsyncMock(return_value=None)
    manager.shutdown = AsyncMock(return_value=None)
    recover = AsyncMock(return_value={'a2a_tasks': 0})
    cleanup = AsyncMock(return_value=None)

    with (
        patch.object(nba, 'northbound_thread_manager', manager),
        patch(
            'services.startup_recovery_service.recover_northbound_tasks',
            recover,
        ),
        patch(
            'services.startup_recovery_service.schedule_interrupted_upload_cleanup',
            cleanup,
        ),
        patch.object(nba, 'set_default_thread_manager') as set_default,
        patch.object(nba, 'clear_default_thread_manager') as clear_default,
        patch.object(nba.runtime_state_service, 'set_thread_manager') as set_thread,
    ):
        async with nba.northbound_lifespan(None):
            set_default.assert_called_once_with(manager)
            set_thread.assert_called_once_with(manager)
            manager.start.assert_called_once_with()
            manager.run.assert_awaited_once()

    clear_default.assert_called_once_with(manager)
    manager.shutdown.assert_awaited_once_with(
        timeout=nba.NORTHBOUND_THREAD_SHUTDOWN_GRACE_SECONDS
    )

    async def _run_impl(profile, spec, fn, *args, **kwargs):
        return await fn(*args, **kwargs)

    async def _failing_recover():
        raise RuntimeError('recovery failed')

    manager = MagicMock()
    manager.state = nba.ManagerState.CREATED
    manager.start = MagicMock(return_value=None)
    manager.run = AsyncMock(side_effect=_run_impl)
    manager.shutdown = AsyncMock(return_value=None)

    with (
        patch.object(nba, 'northbound_thread_manager', manager),
        patch(
            'services.startup_recovery_service.recover_northbound_tasks',
            _failing_recover,
        ),
        patch(
            'services.startup_recovery_service.schedule_interrupted_upload_cleanup',
            AsyncMock(return_value=None),
        ),
        patch.object(nba, 'set_default_thread_manager'),
        patch.object(nba, 'clear_default_thread_manager'),
        patch.object(nba.runtime_state_service, 'set_thread_manager'),
    ):
        with pytest.raises(RuntimeError, match='recovery failed'):
            async with nba.northbound_lifespan(None):
                pytest.fail('lifespan yielded after a failed recovery')

    snapshot = {'service_name': 'northbound', 'lanes': {}}
    manager = MagicMock()
    manager.snapshot = MagicMock(return_value=snapshot)
    with patch.object(nba, 'northbound_thread_manager', manager):
        result = await nba.thread_capacity()
    assert result == snapshot
    manager.snapshot.assert_called_once_with()

    route = next(
        r for r in nba.northbound_app.routes
        if r.path == '/internal/thread-capacity'
    )
    assert route.include_in_schema is False
    assert route.dependencies == []
