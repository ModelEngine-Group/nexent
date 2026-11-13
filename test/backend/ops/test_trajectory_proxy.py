# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise actual Web proxy dispatch without starting Next.js or external services."""

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_web_dispatches_trajectory_queries_to_ops_only():
    source = (ROOT / "frontend/server.js").read_text()
    start = source.index("function handleAllApiProxy(")
    end = source.index("function sendJsonResponse(", start)
    helper = source[source.index("function isTrajectoryOpsRequest(") :]
    requests = [
        ("/api/trajectory/records", "GET", "ops"),
        ("/api/trajectory/cleanup", "POST", "ops"),
        ("/api/trajectory/cleanup/schedule", "PUT", "ops"),
        ("/api/conversation/agent_groups?view=trajectory", "GET", "ops"),
        (
            "/api/conversation/agent_groups/agent:42/conversations?view=trajectory",
            "GET",
            "ops",
        ),
        ("/api/conversation/agent_groups?view=chat", "GET", "runtime"),
        ("/api/conversation/agent_groups?search=trajectory", "GET", "runtime"),
        ("/api/conversation/delete?view=trajectory", "DELETE", "runtime"),
        ("/api/agent/run", "POST", "runtime"),
        ("/api/agent/create", "POST", "config"),
    ]
    script = (
        """
const assert = require('node:assert/strict');
const AUTH_INTERCEPT_ENDPOINTS = new Set();
const OPS_HTTP_BACKEND = 'ops', HTTP_BACKEND = 'config';
const PROXY_TIMEOUT_MS = 1234, SSE_PROXY_TIMEOUT_MS = 9876;
let actual;
const proxy = {web(req, res, config) { actual = config; }};
function getRuntimeProxyConfig(timeout) { return { target: 'runtime', timeout }; }
"""
        + source[start:end]
        + helper
        + """
for (const [url, method, target] of """
        + json.dumps(requests)
        + """) {
  actual = undefined;
  const pathname = new URL(url, 'http://localhost').pathname;
  assert.equal(handleAllApiProxy(pathname, {url, method}, {}), true);
  assert.equal(actual.target, target, url);
  assert.ok(actual.timeout > 0);
}
"""
    )
    result = subprocess.run(
        [shutil.which("node"), "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
