// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import http from "node:http";
import { once } from "node:events";
import { test } from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../server.js", import.meta.url), "utf8");
const start = source.indexOf("function forwardAuthRequest(");
const end = source.indexOf("\n// ====", start);

for (const outcome of ["session", "pending", "expired", "error", "json", "logout"]) {
  test(`OAuth proxy preserves flow-cookie clearing on ${outcome}`, async (t) => {
    const clearedFlow = "nexent_casdoor_flow=; Max-Age=0; Path=/; HttpOnly";
    const backend = http.createServer((req, res) => {
      const data = {
        session: { data: { session: { access_token: "synthetic-token" } } },
        pending: {
          data: {
            requires_account_completion: true,
            pending_token: "synthetic-pending",
          },
        },
        expired: { data: { oauth_error: "casdoor_flow_expired" } },
        error: { data: { oauth_error: "callback_failed" } },
        json: { message: "unchanged" },
        logout: { message: "logged out" },
      }[outcome];
      const body = JSON.stringify(data);
      res.writeHead(200, {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(body),
        "Set-Cookie": [clearedFlow],
      });
      res.end(body);
    });
    backend.listen(0, "127.0.0.1");
    await once(backend, "listening");
    t.after(() => backend.close());
    const backendUrl = `http://127.0.0.1:${backend.address().port}/callback`;
    const context = {
      URL,
      URLSearchParams,
      Buffer,
      http,
      https: http,
      console,
      COOKIE_NAMES: {},
      parseCookies: () => ({}),
      collectRequestBody: async () => Buffer.alloc(0),
      prepareAuthRequestBody: (_path, body) => body,
      setAuthCookies: (res) =>
        res.setHeader("Set-Cookie", [
          ...(res.getHeader("Set-Cookie") || []),
          "access_token=synthetic-token; HttpOnly",
        ]),
      setPendingOAuthCookie: (res) =>
        res.setHeader("Set-Cookie", [
          ...(res.getHeader("Set-Cookie") || []),
          "pending=synthetic-pending; HttpOnly",
        ]),
      getPreferredLocale: () => "zh",
      withBasePath: (path) => path,
      clearAuthCookies: (res) =>
        res.setHeader("Set-Cookie", ["access_token=; Max-Age=0; HttpOnly"]),
    };
    vm.runInNewContext(source.slice(start, end), context);
    const proxy = http.createServer((req, res) => {
      req.parsedPathname =
        outcome === "logout" ? "/api/user/logout" : "/api/user/oauth/callback";
      context.forwardAuthRequest(req, res, backendUrl);
    });
    proxy.listen(0, "127.0.0.1");
    await once(proxy, "listening");
    t.after(() => proxy.close());
    const response = await new Promise((resolve, reject) => {
      http
        .get(`http://127.0.0.1:${proxy.address().port}/callback`, (res) => {
          res.resume();
          resolve(res);
        })
        .on("error", reject);
    });
    assert.ok(response.headers["set-cookie"].includes(clearedFlow));
    assert.equal(
      response.statusCode,
      outcome === "json" || outcome === "logout" ? 200 : 302
    );
    if (outcome === "session") {
      assert.equal(response.headers.location, "/");
      assert.ok(
        response.headers["set-cookie"].some((value) =>
          value.startsWith("access_token=")
        )
      );
    } else if (outcome === "pending") {
      assert.equal(response.headers.location, "/zh/oauth/complete");
    } else if (outcome === "expired") {
      assert.match(response.headers.location, /oauth_error=casdoor_flow_expired/);
      assert.ok(response.headers["set-cookie"].every((value) => !value.startsWith("access_token=")));
    } else if (outcome === "error") {
      assert.match(response.headers.location, /oauth_error=callback_failed/);
    }
  });
}
