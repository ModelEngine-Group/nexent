// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

// Exercise the production handler without starting Next.js or opening sockets.
const source = readFileSync(new URL("../server.js", import.meta.url), "utf8");
const start = source.indexOf("function handleAllApiProxy(");
const end = source.indexOf("// ======================", start);
assert.ok(start >= 0 && end > start);

function dispatch(method, pathname) {
  const calls = [];
  const context = vm.createContext({
    AUTH_INTERCEPT_ENDPOINTS: new Set([
      "/api/user/signin",
      "/api/user/refresh_token",
    ]),
    HTTP_BACKEND: "http://config:5010",
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
  vm.runInContext(source.slice(start, end), context);
  const handled = context.handleAllApiProxy(pathname, { method }, {});
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
]) {
  test(`${method} ${path} routes to ${target}`, () => {
    const result = dispatch(method, path);
    assert.equal(result.handled, true);
    assert.equal(result.calls.length, 1);
    assert.equal(
      result.calls[0].target,
      `http://${target}:${target === "config" ? 5010 : 5014}`
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
