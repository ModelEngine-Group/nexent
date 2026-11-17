// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

// Exercise the production handler without starting Next.js or opening sockets.
const source = readFileSync(new URL("../server.js", import.meta.url), "utf8");
const start = source.indexOf("function handleAllApiProxy(");
const end = source.indexOf("// ======================", start);
const trajectoryHelper = source.indexOf("function isTrajectoryOpsRequest(");
assert.ok(start >= 0 && end > start && trajectoryHelper >= 0);

function dispatch(method, url) {
  const calls = [];
  const context = vm.createContext({
    AUTH_INTERCEPT_ENDPOINTS: new Set([
      "/api/user/signin",
      "/api/user/refresh_token",
    ]),
    HTTP_BACKEND: "http://config:5010",
    OPS_HTTP_BACKEND: "http://ops:5016",
    URL,
    PROXY_TIMEOUT_MS: 100,
    SSE_PROXY_TIMEOUT_MS: 200,
    forwardAuthRequest: (_req, _res, target) =>
      calls.push({ target, auth: true }),
    getRuntimeProxyConfig: (timeout) => ({
      target: "http://runtime:5014",
      proxyTimeout: timeout,
    }),
    proxy: { web: (_req, _res, config) => calls.push(config) },
  });
  vm.runInContext(
    source.slice(start, end) + source.slice(trajectoryHelper),
    context
  );
  const pathname = new URL(url, "http://localhost").pathname;
  const handled = context.handleAllApiProxy(pathname, { method, url }, {});
  return { handled, calls };
}

for (const [method, path, target] of [
  ["POST", "/api/file/storage", "runtime"],
  ["POST", "/api/file/storage/", "runtime"],
  ["GET", "/api/file/storage", "config"],
  ["DELETE", "/api/file/storage/attachments/owner/report.txt", "config"],
  ["POST", "/api/file/storage/batch-urls", "config"],
  ["GET", "/api/file/download/attachments/owner/report.txt", "config"],
  ["POST", "/api/file/upload", "config"],
  ["POST", "/api/file/preprocess", "runtime"],
  ["POST", "/api/agent/run", "runtime"],
  ["GET", "/api/conversation/42", "runtime"],
  ["GET", "/api/trajectory/records", "ops"],
  ["GET", "/api/trajectory/conversations/42", "ops"],
  ["GET", "/api/trajectory/conversations/42/snapshot", "ops"],
  ["GET", "/api/trajectory/conversations/42/contents/signed-reference", "ops"],
  ["POST", "/api/trajectory/cleanup", "ops"],
  ["GET", "/api/conversation/agent_groups?view=trajectory", "ops"],
  ["GET", "/api/conversation/agent_groups?view=chat", "runtime"],
  ["GET", "/api/ops/v1/monitoring/models/summary?start_date=2026-11-17", "ops"],
  ["POST", "/api/ops/v1/monitoring/models/refresh", "ops"],
  ["GET", "/api/ops/v1/monitoring/models/refreshes/signed-reference", "ops"],
  ["GET", "/api/ops/v1/monitoring-other/models", "config"],
  ["GET", "/api/trajectory_config", "config"],
]) {
  test(`${method} ${path} routes to ${target}`, () => {
    const result = dispatch(method, path);
    assert.equal(result.handled, true);
    assert.equal(result.calls.length, 1);
    assert.equal(
      result.calls[0].target,
      `http://${target}:${{ config: 5010, runtime: 5014, ops: 5016 }[target]}`
    );
  });
}

test("authentication interception and streaming timeout are preserved", () => {
  for (const path of ["/api/user/signin", "/api/user/refresh_token"]) {
    assert.equal(dispatch("POST", path).calls[0].auth, true);
  }
  assert.equal(dispatch("POST", "/api/agent/run").calls[0].proxyTimeout, 200);
  assert.equal(
    dispatch("GET", "/api/conversation/42").calls[0].proxyTimeout,
    100
  );
  assert.deepEqual(dispatch("GET", "/zh/newchat"), {
    handled: false,
    calls: [],
  });
});
