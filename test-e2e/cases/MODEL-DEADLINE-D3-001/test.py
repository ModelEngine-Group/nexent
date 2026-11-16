# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""A real slow HTTP peer cannot retain a synchronous model permit past the run budget."""

import asyncio
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

import pytest

from nexent.core.concurrency.cancellation import RunCancellationScope
from nexent.core.concurrency.context import _reset_current_thread_manager, _set_current_thread_manager
from nexent.core.concurrency.manager import ThreadManager
from nexent.core.concurrency.models import LanePolicy
from nexent.core.model_service.concurrency import ModelConcurrencyLimiter
from nexent.core.model_service.contracts import ModelMessage, ModelRequest
from nexent.core.model_service.http_sender import HttpRequestSender
from nexent.core.model_service.service import ModelService, ModelServiceError
from shared.model_service_profiles import resolved_profile_for_test

pytestmark = [pytest.mark.case_id("MODEL-DEADLINE-D3-001"), pytest.mark.stage("D3")]


@pytest.mark.parametrize("mode", ["body_drip", "headers_stall", "sse_comments", "sse_partial_frame"])
def test_deadline_interrupts_actual_http_and_releases_resources(mode):
    stop, disconnected = Event(), Event()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            if mode == "headers_stall":
                stop.wait(2)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json" if mode == "body_drip" else "text/event-stream")
            self.send_header("Content-Length", "100000")
            self.end_headers()
            chunk = {"body_drip": b" ", "sse_comments": b": keepalive\n\n",
                     "sse_partial_frame": b"data: "}[mode]
            try:
                for _ in range(60):
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    if stop.wait(0.03):
                        break
            except (BrokenPipeError, ConnectionResetError):
                disconnected.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    manager = ThreadManager("deadline-integration", {"control-io": LanePolicy("control-io", 1, 0)})
    manager.start()
    token = _set_current_thread_manager(manager)
    limiter, scope = ModelConcurrencyLimiter(), RunCancellationScope()
    profile = resolved_profile_for_test(f"http://127.0.0.1:{server.server_port}/v1")
    values = profile.model_dump()
    values["connection"].update(concurrency_limit=1, timeout_seconds=3)
    profile = type(profile).model_validate(values)
    service = ModelService(lambda _: HttpRequestSender(lambda _: {}), limiter=limiter)
    request = ModelRequest(request_id="deadline-integration", outlet_id=profile.outlet_id,
                           config_revision=profile.config_revision,
                           stream=mode.startswith("sse"), messages=[ModelMessage(semantic_role="user",
                           content_parts=[{"type": "text", "text": "controlled deadline fixture"}])])
    try:
        start = time.monotonic()
        if request.stream:
            with service.stream(request, profile, scope=scope, deadline=start + 0.3) as events:
                result = list(events)
            assert len(result) == 1 and result[0].type == "error"
            error = result[0].error
        else:
            with pytest.raises(ModelServiceError) as caught:
                service.invoke(request, profile, scope=scope, deadline=start + 0.3)
            error = caught.value.error
        assert error.category == "MODEL_RUN_DEADLINE" and not error.will_retry and error.attempt == 1
        assert 0.2 <= time.monotonic() - start < 1.2
        assert len(requests) == 1 and not scope.cancelled and not scope._closers
        assert not limiter._entries and not manager.snapshot().executions
        if mode != "headers_stall":
            assert disconnected.wait(0.5), "The actual socket must be shut down, not merely abandoned"
    finally:
        stop.set()
        _reset_current_thread_manager(token)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
        assert not server_thread.is_alive()
        assert not asyncio.run(manager.shutdown(timeout=2)).stuck_execution_ids
