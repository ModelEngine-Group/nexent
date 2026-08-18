import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  atomicWriteFile,
  readLocaleConfig,
  saveLocaleConfig,
} from "../build-config.js";

test("locale configuration uses atomic shared writes and built-in fallback", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "nexent-project-config-"));
  const sharedDir = path.join(root, "shared");
  const fallbackDir = path.join(root, "fallback");
  fs.mkdirSync(path.join(fallbackDir, "zh"), { recursive: true });
  fs.writeFileSync(
    path.join(fallbackDir, "zh", "custom.json"),
    JSON.stringify({ source: "fallback" })
  );

  try {
    assert.deepEqual(readLocaleConfig("zh", sharedDir, fallbackDir), {
      source: "fallback",
    });

    saveLocaleConfig(JSON.stringify({ source: "shared" }), "zh", sharedDir);

    assert.deepEqual(readLocaleConfig("zh", sharedDir, fallbackDir), {
      source: "shared",
    });
    assert.deepEqual(fs.readdirSync(path.join(sharedDir, "zh")), [
      "custom.json",
    ]);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("locale configuration returns an empty object for missing or invalid files", (t) => {
  const root = fs.mkdtempSync(
    path.join(os.tmpdir(), "nexent-project-config-invalid-")
  );
  const invalidDir = path.join(root, "invalid", "en");
  fs.mkdirSync(invalidDir, { recursive: true });
  fs.writeFileSync(path.join(invalidDir, "custom.json"), "not-json");
  t.mock.method(console, "log", () => {});

  try {
    assert.deepEqual(readLocaleConfig("zh", path.join(root, "missing")), {});
    assert.deepEqual(readLocaleConfig("en", path.join(root, "invalid")), {});
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("atomic writes remove their temporary file after a write failure", (t) => {
  const root = fs.mkdtempSync(
    path.join(os.tmpdir(), "nexent-project-config-write-")
  );
  const target = path.join(root, "custom.json");
  const originalWriteFileSync = fs.writeFileSync;
  t.mock.method(fs, "writeFileSync", (descriptor, ...args) => {
    if (typeof descriptor === "number") {
      throw new Error("simulated write failure");
    }
    return originalWriteFileSync(descriptor, ...args);
  });

  try {
    assert.throws(
      () => atomicWriteFile(target, "content"),
      /simulated write failure/
    );
    assert.deepEqual(fs.readdirSync(root), []);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
