// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

function loadTypescript(relativePath, context) {
  const source = fs.readFileSync(
    new URL(relativePath, import.meta.url),
    "utf8"
  );
  const result = ts.transpileModule(source, {
    reportDiagnostics: true,
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  });
  assert.equal(result.diagnostics?.length ?? 0, 0);
  const exports = {};
  vm.runInNewContext(result.outputText, { exports, ...context });
  return exports;
}

function loadRefreshService({
  canRefresh = true,
  valid = true,
  fetch,
  onExpiry = () => {},
}) {
  return loadTypescript("../services/sessionService.ts", {
    fetch,
    crypto: webcrypto,
    require: (name) =>
      name === "@/services/api"
        ? {
            API_ENDPOINTS: {
              user: { refreshToken: "/api/user/refresh_token" },
            },
          }
        : {
            canRefreshLocalSession: () => canRefresh,
            checkSessionValid: () => valid,
            getTokenExpiresAt: () => 1234,
            handleSessionExpired: onExpiry,
          },
  }).sessionService;
}

test("expired and legacy sessions make no renewal request", async () => {
  const fetch = () => assert.fail("unexpected renewal");
  assert.equal(
    await loadRefreshService({ fetch, canRefresh: false }).refreshToken(),
    null
  );
  assert.equal(
    await loadRefreshService({ fetch, valid: false }).refreshToken(),
    null
  );
});

test("retry preserves the request ID and simultaneous calls share a request", async () => {
  const requestIds = [];
  const service = loadRefreshService({
    fetch: async (url, options) => {
      assert.equal(url, "/api/user/refresh_token");
      requestIds.push(options.headers["X-Refresh-Request-Id"]);
      if (requestIds.length === 1) throw new Error("response lost");
      return {
        ok: true,
        json: async () => ({ data: { session: { expires_at: 5678 } } }),
      };
    },
  });
  const pending = service.refreshToken();
  assert.equal(pending, service.refreshToken());
  await assert.rejects(pending, /response lost/);
  assert.equal((await service.refreshToken()).expires_at, 5678);
  assert.equal(requestIds.length, 2);
  assert.equal(requestIds[0], requestIds[1]);
});

test("a rotation conflict keeps the session and invalid credentials expire it", async () => {
  let expirations = 0;
  const statuses = [409, 401];
  const service = loadRefreshService({
    fetch: async () => ({ ok: false, status: statuses.shift() }),
    onExpiry: () => {
      expirations += 1;
    },
  });
  assert.equal(await service.refreshToken(), null);
  assert.equal(expirations, 0);
  assert.equal(await service.refreshToken(), null);
  assert.equal(expirations, 1);
});

test("foreground activity starts renewal only inside the 30 minute window", async () => {
  const listeners = new Map();
  const effects = [];
  const now = 1_000_000_000;
  let expiresAt = now / 1_000 + 1_801;
  let requests = 0;
  const document = {
    hidden: false,
    addEventListener: (name, handler) => listeners.set(name, handler),
    removeEventListener: (name) => listeners.delete(name),
  };
  const window = {
    addEventListener: (name, handler) => listeners.set(name, handler),
    removeEventListener: (name) => listeners.delete(name),
  };
  const mocks = {
    react: {
      useEffect: (effect) => effects.push(effect),
      useRef: (current) => ({ current }),
      useCallback: (callback) => callback,
    },
    "@/components/providers/deploymentProvider": {
      useDeployment: () => ({ isDeploymentReady: false }),
    },
    "@/services/sessionService": {
      withLocalSessionLock: (callback) => callback(),
      sessionService: {
        refreshToken: async () => {
          requests += 1;
        },
      },
    },
    "@/lib/authFlow": {
      authFlowState: { isExplicitLogoutInProgress: () => false },
    },
    "@/const/constants": {
      TOKEN_REFRESH_BEFORE_EXPIRY_MS: 1_800_000,
      MIN_ACTIVITY_CHECK_INTERVAL_MS: 30_000,
    },
    "@/lib/session": {
      getTokenExpiresAt: () => expiresAt,
      canRefreshLocalSession: () => true,
      checkSessionValid: () => expiresAt * 1_000 > now,
    },
    "@/lib/casHeartbeat": { getHeartbeatIntervalMs: () => 300_000 },
  };
  const { useSessionManager } = loadTypescript(
    "../hooks/auth/useSessionManager.ts",
    {
      document,
      window,
      Date: { now: () => now },
      require: (name) => mocks[name] ?? {},
    }
  );
  useSessionManager({ id: "local-account" });
  effects.forEach((effect) => effect());
  const dispatch = async (type, isTrusted = true) => {
    listeners.get(type)({ type, isTrusted });
    await new Promise((resolve) => setImmediate(resolve));
  };
  await dispatch("click");
  expiresAt = now / 1_000;
  await dispatch("keydown");
  expiresAt = now / 1_000 + 1_800;
  await dispatch("visibilitychange");
  await dispatch("focus");
  await dispatch("click", false);
  assert.equal(requests, 0);
  await dispatch("keydown");
  assert.equal(requests, 1);
});
