# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Validate AgentOS probe failures and cancellation against a loopback provider."""

import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI

from backend.http import client as http_client
from contracts.constants import environment
from contracts.model import ModelOutletValidationRequest
from management.services.model import profiles as service
from nexent.core.model_service.concurrency import model_concurrency_limiter
from runtime.agentos.middleware import AgentOSMiddleware
from runtime.agentos.model_administration import create_model_administration_router
from shared.model_service_profiles import resolved_profile_for_test

pytestmark = [pytest.mark.case_id("MODEL-PROBE-D3-001"), pytest.mark.stage("D3")]


@pytest.fixture
def runtime_transport(monkeypatch):
    app = FastAPI()
    app.add_middleware(AgentOSMiddleware)
    app.include_router(create_model_administration_router(), prefix="/api")
    monkeypatch.setattr(environment, "JWT_SECRET", "agentos-test-signing-key")
    monkeypatch.setattr(environment, "RUNTIME_SERVICE_URL", "http://runtime.test")

    def create_client(**kwargs):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kwargs)

    monkeypatch.setattr(http_client, "create_httpx_client", create_client)


@pytest.mark.asyncio
@pytest.mark.parametrize("abandonment", ["disconnect", "checker_error", "caller_cancel"])
async def test_probe_abandonment(monkeypatch, runtime_transport, caplog, abandonment):
    received, release = Event(), Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            received.set()
            release.wait(5)
            self.send_response(200)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    draft = resolved_profile_for_test(f"http://127.0.0.1:{server.server_port}/v1")
    data = draft.model_dump(mode="json")
    data["outlet_id"] = data["connection"]["credential_ref"]["model_id"] = 42
    profile = draft.__class__.model_validate(data)
    monkeypatch.setattr(service, "_load_validation_outlet", lambda *_args: (profile, "synthetic-key", {}))

    async def read_boundary(_name, function, *args, **kwargs):
        return function(*args, **kwargs)

    import nexent.core.concurrency as concurrency
    monkeypatch.setattr(concurrency, "run_blocking", read_boundary)
    from management.db.model import outlets

    write = Mock()
    monkeypatch.setattr(outlets, "update_model_outlet_connectivity", write)

    async def disconnected():
        if received.is_set() and abandonment == "checker_error":
            raise RuntimeError("controlled checker failure")
        return received.is_set() and abandonment == "disconnect"

    task = asyncio.create_task(service.validate_model_outlet(
        ModelOutletValidationRequest(outlet_id=42), "controlled-tenant",
        is_disconnected=disconnected, user_id="test-actor",
    ))
    try:
        async with asyncio.timeout(3):
            while not received.is_set():
                if task.done():
                    await task
                await asyncio.sleep(0.01)
            if abandonment == "caller_cancel":
                task.cancel()
            expected = RuntimeError if abandonment == "checker_error" else asyncio.CancelledError
            with pytest.raises(expected):
                await task
        write.assert_not_called()
        assert not model_concurrency_limiter._entries
        assert not [
            t for t in asyncio.all_tasks()
            if t.get_name() in {"model-outlet-connectivity", "runtime-model-outlet-connectivity"} and not t.done()
        ]
        assert "event=model_connectivity_failed" not in caplog.text
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


@pytest.mark.asyncio
async def test_probe_authentication_diagnostic(runtime_transport, caplog):
    credential = "synthetic-test-credential"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            body = json.dumps({"error": {"message": f"denied {credential}"}}).encode()
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            profile = resolved_profile_for_test(f"http://127.0.0.1:{server.server_port}/v1")
            async with asyncio.timeout(10):
                result = await service.probe_model_profile(profile, credential, user_id="test-actor")
        finally:
            server.shutdown()
            thread.join(timeout=3)
            assert not thread.is_alive()

    assert result["ok"] is False
    error = result["error"]
    assert error["category"] == "MODEL_AUTHENTICATION_ERROR"
    assert error["http_status"] == 401
    assert set(error["messages"]) == {"zh", "en"}
    assert credential not in json.dumps(result)
    warnings = [r.getMessage() for r in caplog.records if r.name == "runtime.model.profile_probe"]
    assert warnings == [
        f"event=model_connectivity_failed request_id={error['request_id']} "
        "model_type=llm category=MODEL_AUTHENTICATION_ERROR http_status=401"
    ]
    assert credential not in caplog.text
