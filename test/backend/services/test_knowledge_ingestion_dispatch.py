# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management owns bounded cursor discovery and shutdown without submission retries."""

import asyncio
from contextlib import contextmanager
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from management.services.knowledge_base import ingestion_dispatch as dispatch
from nexent.storage.errors import Conflict, OutcomeUnknown, ScopeDenied, Unavailable
from nexent.storage.models import Page


@pytest.fixture
def cycle(monkeypatch):
    events = []
    rows = [
        {"file_id": c * 32, "tenant_id": "tenant-" + c, "user_id": "user-" + c, 'operation': 'ingest'}
        for c in ("a", "b")
    ]
    records = Mock()
    records.query.return_value = Page(tuple(rows), "next-page")

    @contextmanager
    def ports(*, context):
        context.remaining()
        try:
            yield records
        finally:
            events.append("closed")

    async def blocking(name, fn, *args, **kwargs):
        assert (
            kwargs.pop("lane") == "control-io"
            and kwargs.pop("owner") == "management.knowledge_base"
        )
        return fn(*args, **kwargs)

    monkeypatch.setattr(dispatch, "ingestion_dispatch_ports", ports)
    monkeypatch.setattr(dispatch, "run_blocking", blocking)
    coordinator = SimpleNamespace(advance=AsyncMock())

    async def advance(*args, **kwargs):
        assert events == ["closed"]

    coordinator.advance.side_effect = advance
    return SimpleNamespace(**locals())


async def test_page_is_closed_before_advance_and_original_actor_is_used(cycle):
    s = cycle
    count, cursor = await dispatch.dispatch_once(
        s.coordinator, stop=Event(), cursor="previous-page"
    )
    assert count == 2 and cursor == "next-page"
    page = s.records.query.call_args.args[2]
    assert page.limit == 100 and page.cursor == "previous-page"
    calls = s.coordinator.advance.call_args_list
    assert [c.args[1].user_id for c in calls] == ["user-a", "user-b"]
    assert [c.args[1].tenant_id for c in calls] == ["tenant-a", "tenant-b"]


async def test_existing_scan_routes_deletion_to_current_request_actor_without_ingesting(cycle, monkeypatch):
    s = cycle
    s.rows[0].update(operation='delete', user_id='deleting-editor')
    deletion = SimpleNamespace(advance=AsyncMock())
    factory = Mock(return_value=deletion)
    monkeypatch.setattr(dispatch, 'default_deletion_coordinator', factory)
    assert await dispatch.dispatch_once(s.coordinator, stop=Event()) == (2, 'next-page')
    factory.assert_called_once_with(s.coordinator)
    args = deletion.advance.call_args.args
    assert args[0] == 'a' * 32 and args[1].user_id == 'deleting-editor' and args[1].tenant_id == 'tenant-a'
    s.coordinator.advance.assert_awaited_once()
    assert s.coordinator.advance.call_args.args[0] == 'b' * 32


async def test_expected_deletion_cas_race_skips_only_that_row(cycle, monkeypatch):
    from management.services.knowledge_base.deletion_journal import DeletionPhaseChanged

    s = cycle
    s.rows[0]['operation'] = 'delete'
    deletion = SimpleNamespace(advance=AsyncMock(side_effect=DeletionPhaseChanged()))
    monkeypatch.setattr(dispatch, 'default_deletion_coordinator', Mock(return_value=deletion))
    assert await dispatch.dispatch_once(s.coordinator, stop=Event()) == (1, 'next-page')
    assert deletion.advance.await_count == s.coordinator.advance.await_count == 1


def test_default_deletion_reuses_existing_cleanse_and_agentos_client():
    ingestion = dispatch.default_coordinator()
    deletion = dispatch.default_deletion_coordinator(ingestion)
    assert deletion.cleanse is ingestion.cleanse and deletion.client is ingestion.client


async def test_serve_preserves_cursor_then_wraps_without_replaying_submit(cycle):
    s = cycle
    stop = Event()
    s.records.query.side_effect = [
        Page((s.rows[0],), "page-two"),
        Page((s.rows[1],), None),
        Page((s.rows[0],), None),
    ]
    advances = 0

    async def advance(file_id, actor, *, context):
        nonlocal advances
        advances += 1
        if advances == 3:
            stop.set()

    s.coordinator.advance.side_effect = advance
    await dispatch.serve(s.coordinator, stop=stop, poll_seconds=0.01)
    assert [call.args[2].cursor for call in s.records.query.call_args_list] == [
        None,
        "page-two",
        None,
    ]


@pytest.mark.parametrize(
    "error", [Unavailable(), Conflict(), OutcomeUnknown(), ScopeDenied()]
)
async def test_failure_ends_dispatch_without_retry_or_next_file(cycle, error):
    cycle.coordinator.advance.side_effect = error
    with pytest.raises(type(error)):
        await dispatch.serve(cycle.coordinator, stop=Event())
    cycle.coordinator.advance.assert_awaited_once()
    cycle.records.query.assert_called_once()


async def test_stopped_dispatch_does_not_open_storage(cycle):
    stop = Event()
    stop.set()
    assert await dispatch.dispatch_once(
        cycle.coordinator, stop=stop, cursor="cursor"
    ) == (0, "cursor")
    cycle.records.query.assert_not_called()


async def test_lifespan_cancels_owned_task_and_preserves_other_required_tasks(cycle):
    marker = object()
    app = SimpleNamespace(state=SimpleNamespace(required_background_tasks=(marker,)))
    started, stopped = asyncio.Event(), asyncio.Event()

    async def advance(file_id, actor, *, context):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            assert context.cancelled.is_set()
            stopped.set()

    cycle.coordinator.advance.side_effect = advance
    async with dispatch.ingestion_lifespan(
        app, enabled=True, coordinator=cycle.coordinator
    ):
        await asyncio.wait_for(started.wait(), 1)
        owned = app.state.required_background_tasks[-1]
        assert owned.get_name() == "management-knowledge-ingestion"
    assert stopped.is_set() and owned.done()
    assert app.state.required_background_tasks == (marker,)


async def test_disabled_lifespan_does_not_construct_coordinator(cycle, monkeypatch):
    factory = Mock(side_effect=AssertionError("disabled"))
    monkeypatch.setattr(dispatch, "default_coordinator", factory)
    app = SimpleNamespace(state=SimpleNamespace())
    async with dispatch.ingestion_lifespan(app, enabled=False):
        await asyncio.sleep(0)
    factory.assert_not_called()
    cycle.records.query.assert_not_called()


async def test_failed_task_stays_failed_and_logs_only_exception_type(cycle, caplog):
    app = SimpleNamespace(state=SimpleNamespace())
    cycle.coordinator.advance.side_effect = RuntimeError("private-source-token")
    with caplog.at_level("WARNING"):
        async with dispatch.ingestion_lifespan(
            app, enabled=True, coordinator=cycle.coordinator
        ):
            (task,) = app.state.required_background_tasks
            await asyncio.wait({task}, timeout=1)
            await asyncio.sleep(0)
            assert task.done() and isinstance(task.exception(), RuntimeError)
            cycle.coordinator.advance.assert_awaited_once()
    assert (
        "knowledge_ingestion_dispatch_failed" in caplog.text
        and "private-source-token" not in caplog.text
    )


def test_default_coordinator_uses_shared_parser_version_and_agentos_transport(
    monkeypatch,
):
    from contracts.constants import environment

    monkeypatch.setattr(environment, "RUNTIME_SERVICE_URL", "http://runtime:5014")
    coordinator = dispatch.default_coordinator()
    assert (
        coordinator.cleanse.parser_version
        == environment.KNOWLEDGE_CLEANSE_PARSER_VERSION
    )
    assert coordinator.cleanse.parser_version == environment.APP_VERSION + "-cleanse-v2"
    assert coordinator.client.runtime_url == "http://runtime:5014"


async def test_failed_dispatch_makes_ready_unavailable_but_keeps_liveness(cycle):
    import httpx
    from fastapi import FastAPI

    from backend.http.server.health import install_health_contract

    app = FastAPI()
    install_health_contract(app)
    cycle.coordinator.advance.side_effect = Unavailable()
    async with dispatch.ingestion_lifespan(
        app, enabled=True, coordinator=cycle.coordinator
    ):
        (task,) = app.state.required_background_tasks
        await asyncio.wait({task}, timeout=1)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://fixture"
        ) as client:
            assert (await client.get("/health/ready")).status_code == 503
            assert (await client.get("/health/live")).status_code == 200


@pytest.mark.parametrize("seconds", [True, 0, -1, float("nan"), float("inf"), 31])
async def test_invalid_poll_does_not_open_storage(cycle, seconds):
    from nexent.storage.errors import InvalidInput

    with pytest.raises(InvalidInput):
        await dispatch.serve(cycle.coordinator, stop=Event(), poll_seconds=seconds)
    cycle.records.query.assert_not_called()


async def test_phase_race_skips_one_item_without_retry_and_advances_the_next(cycle):
    from management.services.knowledge_base.ingestion_journal import (
        IngestionPhaseChanged,
    )

    cycle.coordinator.advance.side_effect = [IngestionPhaseChanged(), None]
    count, cursor = await dispatch.dispatch_once(cycle.coordinator, stop=Event())
    assert count == 1 and cursor == "next-page"
    assert [call.args[0] for call in cycle.coordinator.advance.call_args_list] == [
        "a" * 32,
        "b" * 32,
    ]
