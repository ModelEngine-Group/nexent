// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import assert from "node:assert/strict";
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

test("legacy refresh service returns no credential and makes no request", async () => {
  let requests = 0;
  const context = {
    fetch: () => {
      requests += 1;
      throw new Error("unexpected refresh request");
    },
    require: () => ({
      fetchWithAuth: () => {
        requests += 1;
        throw new Error("unexpected auth request");
      },
    }),
  };
  const { sessionService } = loadTypescript(
    "../services/sessionService.ts",
    context
  );
  assert.equal(await sessionService.refreshToken(), null);
  assert.equal(requests, 0);
});

test("legacy hook refresh reports unavailable without calling a token service", async () => {
  let requests = 0;
  const { refreshSession } = loadTypescript(
    "../hooks/auth/useSessionManager.ts",
    {
      require: () => ({
        sessionService: {
          refreshToken: () => {
            requests += 1;
          },
        },
      }),
    }
  );
  assert.equal(await refreshSession(), false);
  assert.equal(requests, 0);
});
