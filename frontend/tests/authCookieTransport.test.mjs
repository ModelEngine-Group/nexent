// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";
import cookie from "cookie";

const source = fs.readFileSync(
  new URL("../server.js", import.meta.url),
  "utf8"
);
const start = source.indexOf("const COOKIE_NAMES =");
const end = source.indexOf("function clearAuthCookies", start);
const now = 1234567770;
const context = vm.createContext({
  cookie,
  BASE_PATH: "",
  process,
  URL,
  Date: { now: () => now * 1000 },
});
vm.runInContext(
  source.slice(start, end) + ";globalThis.setCookies = setAuthCookies;",
  context
);

const refreshStart = source.indexOf("function prepareAuthRequestBody");
const refreshEnd = source.indexOf("function forwardAuthRequest", refreshStart);
context.Buffer = Buffer;
vm.runInContext(
  source.slice(refreshStart, refreshEnd) +
    ";globalThis.validateOrigin = isSameOriginRefresh;globalThis.refreshBody = prepareAuthRequestBody;",
  context
);

test("refresh accepts only the same browser origin and forwards the cookie credential", () => {
  const headers = {
    host: "nexent.example",
    origin: "https://nexent.example",
    "sec-fetch-site": "same-origin",
  };
  assert.equal(context.validateOrigin({ headers }), true);
  assert.equal(
    context.validateOrigin({
      headers: { ...headers, origin: "https://other.example" },
    }),
    false
  );
  assert.equal(
    context.validateOrigin({
      headers: { ...headers, "sec-fetch-site": "cross-site" },
    }),
    false
  );
  const body = context.refreshBody(
    "/api/user/refresh_token",
    Buffer.from('{"refresh_token":"supplied-by-caller"}'),
    { nexent_refresh_token: "cookie-refresh" },
    {}
  );
  assert.deepEqual(JSON.parse(body.toString()), {
    refresh_token: "cookie-refresh",
  });
});

function cookiesFor(session) {
  let headers = [];
  const res = {
    getHeader: () => headers,
    setHeader: (name, values) => {
      assert.equal(name, "Set-Cookie");
      headers = values;
    },
  };
  context.setCookies(res, session);
  return Array.from(headers);
}

test("native login clears a stale refresh cookie and keeps JWT HttpOnly", () => {
  const headers = cookiesFor({
    access_token: "native-jwt",
    refresh_token: "",
    expires_at: 1234567890,
    expires_in_seconds: 120,
  });
  const access = headers.find((value) =>
    value.startsWith("nexent_access_token=")
  );
  const refresh = headers.find((value) =>
    value.startsWith("nexent_refresh_token=")
  );
  assert.match(access, /HttpOnly/);
  assert.match(access, /Max-Age=120/);
  assert.match(refresh, /^nexent_refresh_token=;/);
  assert.match(refresh, /Max-Age=0/);
  assert.match(refresh, /HttpOnly/);
});

test("expiry cookie remains readable and agrees with the access token duration", () => {
  const headers = cookiesFor({
    access_token: "native-jwt",
    expires_at: 1234567890,
    expires_in_seconds: 120,
  });
  const expiry = headers.find((value) =>
    value.startsWith("nexent_token_expires_at=")
  );
  assert.match(expiry, /1234567890/);
  assert.match(expiry, /Max-Age=120/);
  assert.doesNotMatch(expiry, /HttpOnly/);
});

test("renewal keeps the refresh secret HttpOnly and uses remaining server-side lifetimes", () => {
  const headers = cookiesFor({
    access_token: "native-jwt",
    refresh_token: "local-refresh",
    expires_at: now + 70,
    expires_in_seconds: 120,
    refresh_expires_at: now + 800,
  });
  assert.match(
    headers.find((value) => value.startsWith("nexent_access_token=")),
    /Max-Age=70/
  );
  const refresh = headers.find((value) =>
    value.startsWith("nexent_refresh_token=")
  );
  assert.match(refresh, /Max-Age=800/);
  assert.match(refresh, /HttpOnly/);
  const marker = headers.find((value) =>
    value.startsWith("nexent_can_refresh=")
  );
  assert.match(marker, /^nexent_can_refresh=1;/);
  assert.doesNotMatch(marker, /local-refresh|HttpOnly/);
});
