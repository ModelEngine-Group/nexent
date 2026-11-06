// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");
const ts = require("../../d1/frontend/node_modules/typescript");
const source = ts.transpileModule(fs.readFileSync(path.join(__dirname, "atomic-file.ts"), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText;

function fixture(platform, failures, code = "EPERM") {
  let writes = 0, renames = 0, waits = 0;
  const operations = {
    mkdirSync() {},
    writeFileSync() { writes++; },
    renameSync() {
      renames++;
      if (renames <= failures) throw Object.assign(new Error("controlled file lock"), { code });
    },
  };
  const context = { exports: {}, process: { platform }, Atomics: { wait() { waits++; } },
    require(name) { return name === "node:fs" ? operations : require(name); } };
  vm.runInNewContext(source, context);
  return { run: () => context.exports.atomicJson("status.json", { status: "RUNNING" }),
    counts: () => ({ writes, renames, waits }) };
}

test("Windows transient sharing locks retain one complete write and retry replacement", () => {
  const value = fixture("win32", 2);
  value.run();
  assert.deepEqual(value.counts(), { writes: 1, renames: 3, waits: 2 });
});
test("Persistent Windows errors remain failures after a bounded retry", () => {
  const value = fixture("win32", Infinity);
  assert.throws(value.run, /controlled file lock/);
  assert.deepEqual(value.counts(), { writes: 1, renames: 9, waits: 8 });
});
test("Non-sharing errors and POSIX errors propagate immediately", () => {
  for (const [platform, code] of [["linux", "EPERM"], ["win32", "ENOENT"]]) {
    const value = fixture(platform, 2, code);
    assert.throws(value.run, /controlled file lock/);
    assert.deepEqual(value.counts(), { writes: 1, renames: 1, waits: 0 });
  }
});
