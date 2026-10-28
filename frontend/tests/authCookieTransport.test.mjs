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
const context = vm.createContext({ cookie, BASE_PATH: "", process });
vm.runInContext(
  source.slice(start, end) + ";globalThis.setCookies = setAuthCookies;",
  context
);

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
    expires_in_seconds: 3600,
  });
  const expiry = headers.find((value) =>
    value.startsWith("nexent_token_expires_at=")
  );
  assert.match(expiry, /1234567890/);
  assert.match(expiry, /Max-Age=3600/);
  assert.doesNotMatch(expiry, /HttpOnly/);
});
