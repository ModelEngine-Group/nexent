# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Validate actual outbound HTTP cancellation without a persistent database."""

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from unittest.mock import Mock

import pytest

from contracts.model import ModelOutletValidationRequest
from management.services.model import profiles as service
from nexent.core.model_service.concurrency import model_concurrency_limiter
from shared.model_service_profiles import resolved_profile_for_test

pytestmark = [pytest.mark.case_id("MODEL-PROBE-D3-001"), pytest.mark.stage("D3")]


@pytest.mark.asyncio
@pytest.mark.parametrize("abandonment", ["disconnect", "checker_error", "caller_cancel"])
async def test_abandoned_probe(monkeypatch, abandonment):
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

    write, receipt = Mock(), Mock()
    monkeypatch.setattr(outlets, "update_model_outlet_connectivity", write)
    monkeypatch.setattr(service, "_issue_check_receipt", receipt)

    async def disconnected():
        if received.is_set() and abandonment == "checker_error":
            raise RuntimeError("controlled checker failure")
        return received.is_set() and abandonment == "disconnect"

    task = asyncio.create_task(service.validate_model_outlet(
        ModelOutletValidationRequest(outlet_id=42), "controlled-tenant", is_disconnected=disconnected,
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
        receipt.assert_not_called()
        assert not model_concurrency_limiter._entries
        assert not [t for t in asyncio.all_tasks() if t.get_name() == "model-outlet-connectivity" and not t.done()]
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
