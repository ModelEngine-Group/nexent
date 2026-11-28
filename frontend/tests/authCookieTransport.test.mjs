// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";
import cookie from "cookie";

const source = fs.readFileSync(
  new URL("../server.js", import.meta.url),
  "utf8"
);
const start = source.indexOf("const COOKIE_NAMES =");
const end = source.indexOf("function getPreferredLocale", start);
const now = 1234567770;
const context = vm.createContext({
  cookie,
  randomBytes,
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
    {
      nexent_session_scope: "a".repeat(32),
      ["nexent_refresh_token_" + "a".repeat(32)]: "cookie-refresh",
    },
    {}
  );
  assert.deepEqual(JSON.parse(body.toString()), {
    refresh_token: "cookie-refresh",
  });
});

function cookieResponse(write) {
  let headers = [];
  const res = {
    getHeader: () => headers,
    setHeader: (name, values) => {
      assert.equal(name, "Set-Cookie");
      headers = values;
    },
  };
  write(res);
  return Array.from(headers);
}

const cookiesFor = (session) =>
  cookieResponse((res) => context.setCookies(res, session));

for (const legacy of [false, true]) {
  test(`delayed renewal and logout cannot overwrite a later login (legacy: ${legacy})`, () => {
    const jar = {};
    const apply = (headers) => {
      for (const header of headers) {
        const [nameValue] = header.split(";");
        const [name, value] = nameValue.split("=");
        if (header.includes("Max-Age=0")) delete jar[name];
        else jar[name] = value;
      }
    };
    const login = (account, priorScope, isCas = false) =>
      cookieResponse((res) =>
        context.startBrowserSession(
          res,
          {
            access_token: account + "-access",
            refresh_token: account + "-refresh",
            expires_at: now + 60,
            refresh_expires_at: now + 600,
          },
          priorScope,
          isCas
        )
      );
    const renew = (scope) =>
      cookieResponse((res) =>
        context.setCookies(
          res,
          {
            access_token: "renewed-old-access",
            refresh_token: "renewed-old-refresh",
            expires_at: now + 120,
            refresh_expires_at: now + 600,
          },
          scope
        )
      );

    if (!legacy) apply(login("first", ""));
    else apply(renew(""));
    const first = context.sessionCookieScope(jar);
    assert.ok(context.getSessionCookie(jar, "nexent_access_token"));
    const delayedRenewal = renew(first);
    const logout = cookieResponse((res) =>
      context.clearAuthCookies(res, first)
    );
    apply(logout);
    apply(delayedRenewal);
    assert.equal(
      context.getSessionCookie(jar, "nexent_access_token"),
      undefined
    );
    assert.equal(
      context.withoutLegacyAccessCookie(
        "nexent_access_token=older; theme=light",
        jar
      ),
      " theme=light"
    );
    apply(login("second", first));
    const second = context.sessionCookieScope(jar);
    apply(delayedRenewal);
    apply(logout);
    assert.notEqual(second, first);
    assert.equal(context.sessionCookieScope(jar), second);
    assert.equal(
      context.getSessionCookie(jar, "nexent_access_token"),
      "second-access"
    );
    assert.equal(
      context.getSessionCookie(jar, "nexent_refresh_token"),
      "second-refresh"
    );
  });
}

test("a session without a refresh cookie receives 204 without forwarding a credential", () => {
  let status;
  let ended = false;
  const body = context.refreshBody(
    "/api/user/refresh_token",
    Buffer.alloc(0),
    {},
    {
      writeHead: (value) => {
        status = value;
      },
      end: () => {
        ended = true;
      },
    }
  );
  assert.equal(body, null);
  assert.equal(status, 204);
  assert.equal(ended, true);
});

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
  assert.equal(
    headers.some((value) => value.startsWith("nexent_can_refresh=")),
    false
  );
});
