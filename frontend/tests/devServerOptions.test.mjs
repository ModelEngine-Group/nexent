// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";
import { getDevBundlerOptions } from "../dev-server-options.mjs";

function dependencies(t, linked) {
  const root = mkdtempSync(path.join(tmpdir(), "nexent-dev-bundler-"));
  t.after(() => {
    assert.equal(path.dirname(root), tmpdir());
    assert.ok(path.basename(root).startsWith("nexent-dev-bundler-"));
    rmSync(root, { recursive: true, force: true });
  });
  const modules = path.join(root, "node_modules");
  if (linked) {
    const target = path.join(root, "shared-dependencies");
    mkdirSync(target);
    symlinkSync(
      target,
      modules,
      process.platform === "win32" ? "junction" : "dir"
    );
  } else {
    mkdirSync(modules);
  }
  return modules;
}

test("development with a real dependency link explicitly selects Webpack", (t) => {
  assert.deepEqual(getDevBundlerOptions(true, dependencies(t, true)), {
    webpack: true,
  });
});

test("ordinary development keeps Turbopack", (t) => {
  assert.deepEqual(getDevBundlerOptions(true, dependencies(t, false)), {
    turbo: true,
  });
});

test("production does not select a development bundler for linked dependencies", (t) => {
  assert.deepEqual(getDevBundlerOptions(false, dependencies(t, true)), {});
});
