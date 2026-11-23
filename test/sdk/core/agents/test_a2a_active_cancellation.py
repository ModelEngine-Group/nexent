import asyncio

import pytest
from nexent.core.agents.a2a_agent_proxy import A2AAgentInfo, ExternalA2AAgentProxy
from nexent.core.concurrency import RunCancellationScope


class _BlockingClient:
    def __init__(self, entered: asyncio.Event):
        self.entered = entered
        self.close_count = 0

    async def post(self, *args, **kwargs):
        self.entered.set()
        await asyncio.Event().wait()

    async def aclose(self):
        self.close_count += 1


class _BlockingStreamResponse:
    def __init__(self, entered: asyncio.Event):
        self.entered = entered

    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        yield 'data: {"artifactUpdate":{"artifact":{"parts":[{"text":"part"}]}}}'
        self.entered.set()
        await asyncio.Event().wait()


class _StreamContext:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


class _BlockingStreamingClient(_BlockingClient):
    def stream(self, *args, **kwargs):
        return _StreamContext(_BlockingStreamResponse(self.entered))


@pytest.mark.asyncio
async def test_ut_sdk_tlm_030_run_cancel_cancels_active_a2a_task(monkeypatch):
    entered = asyncio.Event()
    client = _BlockingClient(entered)
    monkeypatch.setattr(
        "nexent.core.agents.a2a_agent_proxy.httpx.AsyncClient",
        lambda **kwargs: client,
    )
    scope = RunCancellationScope()
    proxy = ExternalA2AAgentProxy(
        A2AAgentInfo("a", "agent", "http://a2a.invalid", timeout=10),
        cancellation_scope=scope,
    )

    async def invoke():
        async with proxy:
            return await proxy.call("hello")

    task = asyncio.create_task(invoke())
    await asyncio.wait_for(entered.wait(), timeout=1)
    scope.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)
    assert client.close_count == 1


@pytest.mark.asyncio
async def test_ut_sdk_tlm_030_total_deadline_closes_a2a_client(monkeypatch, caplog):
    entered = asyncio.Event()
    client = _BlockingClient(entered)
    monkeypatch.setattr(
        "nexent.core.agents.a2a_agent_proxy.httpx.AsyncClient",
        lambda **kwargs: client,
    )
    proxy = ExternalA2AAgentProxy(
        A2AAgentInfo("a", "agent", "http://a2a.invalid", timeout=0.02)
    )

    with pytest.raises(TimeoutError):
        async with proxy:
            await proxy.call("hello")

    assert entered.is_set()
    assert client.close_count == 1
    timeout_records = [
        record for record in caplog.records
        if "event=a2a_request_timeout" in record.getMessage()
    ]
    assert len(timeout_records) == 1
    assert timeout_records[0].levelname == "WARNING"
    assert "agent_id=a" in timeout_records[0].getMessage()
    assert "timeout_seconds=0.020" in timeout_records[0].getMessage()
    assert not [record for record in caplog.records if record.levelname == "ERROR"]


@pytest.mark.asyncio
async def test_ut_sdk_tlm_030_total_deadline_covers_partial_stream_stall(monkeypatch, caplog):
    entered = asyncio.Event()
    client = _BlockingStreamingClient(entered)
    monkeypatch.setattr(
        "nexent.core.agents.a2a_agent_proxy.httpx.AsyncClient",
        lambda **kwargs: client,
    )
    proxy = ExternalA2AAgentProxy(
        A2AAgentInfo("a", "agent", "http://a2a.invalid", timeout=0.02)
    )

    async with proxy:
        events = [event async for event in proxy.call_streaming("hello")]

    assert entered.is_set()
    assert events[0]["artifactUpdate"]["artifact"]["parts"][0]["text"] == "part"
    assert events[-1]["statusUpdate"]["status"]["state"] == "TASK_STATE_FAILED"
    assert client.close_count == 1
    timeout_records = [
        record for record in caplog.records
        if "event=a2a_stream_timeout" in record.getMessage()
    ]
    assert len(timeout_records) == 1
    assert timeout_records[0].levelname == "WARNING"
    assert "phase=next_chunk" in timeout_records[0].getMessage()
    assert "event_count=1" in timeout_records[0].getMessage()
    assert not [record for record in caplog.records if record.levelname == "ERROR"]
