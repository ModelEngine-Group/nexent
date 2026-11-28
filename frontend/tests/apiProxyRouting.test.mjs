// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

// Exercise the production handler without starting Next.js or opening sockets.
const source = readFileSync(new URL("../server.js", import.meta.url), "utf8");

for (const [setting, secure] of [[undefined, true], ["true", true], ["false", false], ["invalid", true]]) {
  test(`session and OAuth cookies use the configured transport (${setting})`, () => {
    const context = vm.createContext({
      BASE_PATH: "/nexent",
      process: { env: { NODE_ENV: "production", NEXENT_AUTH_COOKIE_SECURE: setting } },
      cookie: { serialize: (name, value, options) => ({ name, value, ...options }) },
    });
    const cookieStart = source.indexOf("const COOKIE_NAMES");
    const cookieEnd = source.indexOf("function getPreferredLocale", cookieStart);
    vm.runInContext(source.slice(cookieStart, cookieEnd), context);
    let cookies = [];
    const response = {
      getHeader: () => cookies,
      setHeader: (_name, value) => { cookies = value; },
    };
    context.setAuthCookies(response, { access_token: "access", refresh_token: "refresh", expires_at: 42 });
    context.setPendingOAuthCookie(response, "pending");
    assert.equal(cookies.length, 4);
    assert.ok(cookies.every((entry) => entry.secure === secure && entry.sameSite === "lax"));
    assert.ok(cookies.every((entry) => entry.httpOnly === (entry.name !== "nexent_token_expires_at")));

    cookies = [];
    context.clearAuthCookies(response);
    context.clearPendingOAuthCookie(response);
    assert.ok(cookies.every((entry) => entry.secure === secure && entry.path === "/nexent"));
    assert.ok(cookies.filter((entry) => entry.name !== "nexent_signed_out").every((entry) => entry.maxAge === 0));
    assert.equal(cookies.find((entry) => entry.name === "nexent_signed_out").value, "1");

    cookies = [];
    context.setAuthCookies(response, { access_token: "access" });
    assert.equal(cookies[1].name, "nexent_refresh_token");
    assert.equal(cookies[1].secure, secure);
    assert.equal(cookies[1].maxAge, 0);
  });
}

test("auth proxy replaces chunked encoding with the buffered response length", async () => {
  const payload = Buffer.from(JSON.stringify({ data: { has_pending: true } }));
  const upstream = Object.assign(new EventEmitter(), {
    statusCode: 200,
    headers: { "transfer-encoding": "chunked", "content-type": "application/json" },
  });
  const context = vm.createContext({
    Buffer,
    URL,
    COOKIE_NAMES: { ACCESS_TOKEN: "access", OAUTH_PENDING: "pending" },
    sessionCookieScope: () => "",
    getSessionCookie: () => undefined,
    collectRequestBody: async () => Buffer.alloc(0),
    prepareAuthRequestBody: (_path, body) => body,
    parseCookies: () => ({}),
    http: {
      request: (_options, receive) => Object.assign(new EventEmitter(), {
        write() {},
        end() {
          receive(upstream);
          upstream.emit("data", payload);
          upstream.emit("end");
        },
      }),
    },
  });
  const start = source.indexOf("function forwardAuthRequest(");
  const end = source.indexOf("\n}\n", start) + 2;
  assert.ok(start >= 0 && end > start);
  vm.runInContext(source.slice(start, end), context);

  let responseHeaders;
  const body = await new Promise((resolve) => {
    context.forwardAuthRequest({
      method: "GET", url: "/api/user/oauth/pending", parsedPathname: "/api/user/oauth/pending", headers: {},
    }, {
      getHeader: () => undefined,
      writeHead: (_status, headers) => { responseHeaders = headers; },
      end: resolve,
    }, "http://management:5010");
  });
  assert.equal(responseHeaders["transfer-encoding"], undefined);
  assert.equal(responseHeaders["content-length"], String(payload.length));
  assert.deepEqual(body, payload);
});

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
  const req = { method, url: pathname };
  const handled = context.handleAllApiProxy(pathname, req, {});
  return { handled, calls, req };
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
  ["POST", "/api/agent/run", "config"],
  ["POST", "/api/agent/run/", "config"],
  ["GET", "/api/agent/stop/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "config"],
  ["GET", "/api/agent/stop/42", "config"],
  ["GET", "/api/agent/automations", "config"],
  ["POST", "/api/agent/nl2agent/run", "runtime"],
  ["POST", "/api/skills/nl2skill/run", "runtime"],
  ["GET", "/api/conversation/42", "runtime"],
  ["GET", "/api/trajectory/records", "config"],
  ["GET", "/api/trajectory/conversations/42", "config"],
  ["GET", "/api/trajectory/conversations/42/snapshot", "config"],
  [
    "GET",
    "/api/trajectory/conversations/42/contents/signed-reference",
    "config",
  ],
  ["POST", "/api/trajectory/cleanup", "config"],
  ["GET", "/api/trajectory_config", "config"],
  ["GET", "/api/ops/v1/monitoring/models/summary", "config"],
  ["POST", "/api/ops/v1/monitoring/models/refresh", "config"],
  ["GET", "/api/ops/v1/monitoring/models/refreshes/signed-reference", "config"],
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
  assert.equal(dispatch("GET", "/api/agent/stop/42").calls[0].proxyTimeout, 100);
  assert.equal(
    dispatch("GET", "/api/conversation/42").calls[0].proxyTimeout,
    100
  );
  assert.deepEqual(dispatch("GET", "/zh/newchat"), {
    handled: false,
    calls: [],
    req: { method: "GET", url: "/zh/newchat" },
  });
});

test("system configuration requests preserve their URL through the Gateway proxy", () => {
  for (const [method, path] of [
    ["GET", "/api/system_configurations"],
    ["PATCH", "/api/system_configurations"],
    ["POST", "/api/system_configurations/recommendations"],
  ]) {
    const result = dispatch(method, path);
    assert.equal(result.handled, true);
    assert.equal(result.calls[0].target, "http://config:5010");
    assert.equal(result.req.url, path);
  }
});
