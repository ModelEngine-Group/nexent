// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { PassThrough } from "node:stream";
import test from "node:test";
import vm from "node:vm";

const source = fs.readFileSync(
  new URL("../server.js", import.meta.url),
  "utf8"
);
function declaration(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, name);
  return source.slice(start, source.indexOf("\n}", start) + 2);
}

const initializationSource = fs
  .readFileSync(new URL("../build-config.js", import.meta.url), "utf8")
  .split("export function ensureDir")[1];

for (const [name, initial, expected] of [
  ["unconfigured", {}, "Nexent"],
  ["configured", { homeTitle: "Custom home" }, "Custom home"],
  ["cleared", { homeTitle: "", tabTitle: "Old home" }, ""],
  ["whitespace", { homeTitle: "   " }, "   "],
  ["legacy", { tabTitle: "Old home" }, "Old home"],
  ["cleared legacy", { tabTitle: "" }, ""],
]) {
  test(`startup preserves ${name} homepage title across both locales and restarts`, (t) => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "nexent-home-default-"));
    t.after(() => fs.rmSync(root, { recursive: true, force: true }));
    const builtIn = path.join(root, "built-in");
    const persistent = path.join(root, "persistent");
    for (const locale of ["zh", "en"]) {
      fs.mkdirSync(path.join(builtIn, locale), { recursive: true });
      fs.writeFileSync(
        path.join(builtIn, locale, "custom.json"),
        JSON.stringify({ ...initial, productName: `${locale} system` })
      );
    }
    const start = () =>
      vm.runInNewContext(
        `function ensureDir${initializationSource.replaceAll("export function", "function")}`,
        {
          fs,
          path,
          console,
          LOCALES_CONFIG_DIR: persistent,
          BUILT_IN_LOCALES_CONFIG_DIR: builtIn,
          fileUploadSizeLimit: 10,
        }
      );
    start();
    for (const locale of ["zh", "en"]) {
      const file = path.join(persistent, locale, "custom.json");
      const config = JSON.parse(fs.readFileSync(file, "utf8"));
      assert.equal(config.homeTitle, expected);
      assert.equal(config.productName, `${locale} system`);
      fs.writeFileSync(file, JSON.stringify({ ...config, homeTitle: "" }));
    }
    start();
    for (const locale of ["zh", "en"]) {
      const config = JSON.parse(
        fs.readFileSync(path.join(persistent, locale, "custom.json"), "utf8")
      );
      assert.equal(config.homeTitle, "");
      assert.equal(config.productName, `${locale} system`);
    }
  });
}
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64"
);
function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "nexent-branding-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const state = {
    zh: { productName: "System", pageSubtitle: "Keep", homeLogo: "" },
    en: { productName: "System", pageSubtitle: "Keep", homeLogo: "" },
  };
  const context = vm.createContext({
    fs,
    path,
    Buffer,
    createHash,
    ICON_UPLOAD_DIR: root,
    ensureDir: (directory) => fs.mkdirSync(directory, { recursive: true }),
    readLocaleConfig: (locale) => state[locale],
    saveLocaleConfig: (data, locale) => {
      state[locale] = JSON.parse(data);
    },
  });
  for (const name of [
    "renameFile",
    "updateLocalConfig",
    "handleLogoUpload",
    "updateAndSaveLocaleConfig",
  ])
    vm.runInContext(declaration(name), context);
  const upload = (bytes, name = "upload.tmp") => {
    const filename = path.join(root, name);
    fs.writeFileSync(filename, bytes);
    return { path: filename };
  };
  const fields = (zh = {}, en = {}) => ({
    configZh: [JSON.stringify(zh)],
    configEn: [JSON.stringify(en)],
  });
  return { root, state, context, upload, fields };
}

test("new optional localized titles and explicit blank system names survive legacy merges", (t) => {
  const f = fixture(t);
  f.context.updateAndSaveLocaleConfig(
    f.fields(
      { productName: "", homeTitle: " 标签 ", surprise: "ignored" },
      { homeTitle: "Tab" }
    )
  );
  assert.deepEqual(f.state.zh, {
    productName: "",
    pageSubtitle: "Keep",
    homeLogo: "",
    homeTitle: "标签",
  });
  assert.equal(f.state.en.homeTitle, "Tab");
  f.context.updateAndSaveLocaleConfig(f.fields({ homeTitle: "" }));
  assert.equal(f.state.zh.homeTitle, "");
  assert.equal(f.state.en.homeTitle, "Tab");
});

test("legacy title and upload fields populate homepage settings without changing system branding", (t) => {
  const f = fixture(t);
  f.state.zh.tabTitle = "Existing home";
  f.state.zh.tabLogo = "browser-tab-logo.png?v=abc";
  f.context.updateAndSaveLocaleConfig(f.fields({ tabTitle: "Legacy home" }), {
    tabLogo: [f.upload(png)],
  });
  assert.equal(f.state.zh.homeTitle, "Legacy home");
  assert.match(f.state.zh.homeLogo, /^home-logo\.png\?v=[a-f0-9]{12}$/);
  assert.equal(f.state.zh.productName, "System");
  assert.equal(f.state.zh.tabLogo, "browser-tab-logo.png?v=abc");
  f.context.updateAndSaveLocaleConfig(
    f.fields({ homeTitle: "", tabTitle: "Ignored fallback" })
  );
  assert.equal(f.state.zh.homeTitle, "");
  f.context.updateAndSaveLocaleConfig({
    ...f.fields(),
    removeTabLogo: ["true"],
  });
  assert.equal(f.state.zh.homeLogo, "");
});

for (const [extension, bytes] of [
  ["png", png],
  ["jpg", Buffer.from([255, 216, 255, 224, 0, 0, 255, 217])],
]) {
  test(`homepage ${extension} is versioned, shared between locales and independent from the system logo`, (t) => {
    const f = fixture(t);
    fs.writeFileSync(path.join(f.root, "modelengine-logo.png"), "system");
    f.context.updateAndSaveLocaleConfig(f.fields({ homeTitle: "Tab" }), {
      homeLogo: [f.upload(bytes)],
    });
    assert.match(
      f.state.zh.homeLogo,
      new RegExp(`^home-logo\\.${extension}\\?v=[a-f0-9]{12}$`)
    );
    assert.equal(f.state.zh.homeLogo, f.state.en.homeLogo);
    assert.deepEqual(
      fs.readFileSync(path.join(f.root, `home-logo.${extension}`)),
      bytes
    );
    assert.equal(
      fs.readFileSync(path.join(f.root, "modelengine-logo.png"), "utf8"),
      "system"
    );
  });
}

test("reset removes only canonical homepage assets and restores the shared empty setting", (t) => {
  const f = fixture(t);
  for (const name of [
    "home-logo.png",
    "home-logo.jpg",
    "modelengine-logo.png",
    "browser-tab-logo.png",
  ])
    fs.writeFileSync(path.join(f.root, name), png);
  f.context.updateAndSaveLocaleConfig({
    ...f.fields(),
    removeHomeLogo: ["true"],
  });
  assert.equal(f.state.zh.homeLogo, "");
  assert.equal(f.state.en.homeLogo, "");
  assert.equal(fs.existsSync(path.join(f.root, "home-logo.png")), false);
  assert.equal(fs.existsSync(path.join(f.root, "home-logo.jpg")), false);
  assert.ok(fs.existsSync(path.join(f.root, "modelengine-logo.png")));
  assert.ok(fs.existsSync(path.join(f.root, "browser-tab-logo.png")));
});

test("accepts the 200KB boundary and rejects oversized or non-image uploads before changing branding", (t) => {
  const f = fixture(t);
  const boundary = Buffer.concat([png, Buffer.alloc(200 * 1024 - png.length)]);
  f.context.updateAndSaveLocaleConfig(f.fields(), {
    homeLogo: [f.upload(boundary)],
  });
  const previous = structuredClone(f.state);
  for (const bytes of [
    Buffer.alloc(0),
    Buffer.from("<svg></svg>"),
    Buffer.concat([boundary, Buffer.from([0])]),
  ]) {
    assert.throws(
      () =>
        f.context.updateAndSaveLocaleConfig(f.fields({ homeTitle: "wrong" }), {
          homeLogo: [f.upload(bytes)],
        }),
      /Homepage logo/
    );
    assert.deepEqual(f.state, previous);
  }
});

test("invalid locale payloads do not move any uploaded system or homepage image", (t) => {
  const f = fixture(t);
  const system = f.upload(png, "system.tmp");
  const tab = f.upload(png);
  for (const value of ["not json", "null", "[]"]) {
    assert.throws(() =>
      f.context.updateAndSaveLocaleConfig(
        { configZh: [value], configEn: ["{}"] },
        { logo2: [system], homeLogo: [tab] }
      )
    );
    assert.ok(fs.existsSync(system.path));
    assert.ok(fs.existsSync(tab.path));
    assert.equal(
      fs.existsSync(path.join(f.root, "modelengine-logo.png")),
      false
    );
  }
});

test("rejects invalid branding types and length before changing stored configuration", (t) => {
  const f = fixture(t);
  const previous = structuredClone(f.state);
  for (const values of [
    { productName: 7 },
    { homeTitle: {} },
    { homeTitle: "x".repeat(51) },
  ]) {
    assert.throws(
      () => f.context.updateAndSaveLocaleConfig(f.fields(values)),
      /Invalid branding title/
    );
    assert.deepEqual(f.state, previous);
  }
  f.context.updateAndSaveLocaleConfig(
    f.fields({ homeTitle: "x".repeat(50) }, { homeTitle: "y".repeat(100) })
  );
  assert.equal(f.state.zh.homeTitle.length, 50);
  assert.equal(f.state.en.homeTitle.length, 100);
});

test("unauthorized configuration requests stop before multipart parsing or persistence", async () => {
  let parsed = false;
  let response;
  const context = vm.createContext({
    isSuperAdminRequest: async () => false,
    sendJsonResponse: (_res, status, body) => {
      response = { status, body: JSON.stringify(body) };
    },
    parseMultipartForm: () => {
      parsed = true;
    },
  });
  vm.runInContext("async " + declaration("handleProjectConfigApi"), context);
  assert.equal(
    await context.handleProjectConfigApi("/api/config/project-config", {}, {}),
    true
  );
  assert.equal(response.status, 403);
  assert.equal(parsed, false);
});

test("failed image submissions clean their own temporary upload without changing stored settings", async (t) => {
  const f = fixture(t);
  const invalid = f.upload(Buffer.from("invalid image"));
  const previous = structuredClone(f.state);
  Object.assign(f.context, {
    isSuperAdminRequest: async () => true,
    multiparty: { Form: class {} },
    parseMultipartForm: async () => ({
      fields: f.fields({ homeTitle: "must not persist" }),
      files: { homeLogo: [invalid] },
    }),
    console: { error: () => {} },
  });
  vm.runInContext("async " + declaration("handleProjectConfigApi"), f.context);
  let status;
  const response = {
    writeHead: (value) => {
      status = value;
    },
    end: () => {},
  };
  await f.context.handleProjectConfigApi(
    "/api/config/project-config",
    {},
    response
  );
  assert.equal(status, 400);
  assert.equal(fs.existsSync(invalid.path), false);
  assert.deepEqual(f.state, previous);
});

test("missing homepage images fall back to persisted system branding with no-store and correct HEAD behavior", async (t) => {
  const f = fixture(t);
  fs.writeFileSync(path.join(f.root, "modelengine-logo.png"), png);
  const assetsStart = source.indexOf("const PROJECT_CONFIG_ASSETS = {");
  const assetsEnd = source.indexOf("\n};", assetsStart) + 3;
  vm.runInContext(source.slice(assetsStart, assetsEnd), f.context);
  Object.assign(f.context, {
    PROJECT_CONFIG_DIR: f.root,
    BUILT_IN_PUBLIC_DIR: path.join(f.root, "builtin"),
  });
  vm.runInContext(declaration("handleProjectConfigAsset"), f.context);
  for (const method of ["GET", "HEAD"]) {
    const response = new PassThrough();
    let headers;
    response.writeHead = (status, value) => {
      assert.equal(status, 200);
      headers = value;
    };
    const chunks = [];
    response.on("data", (chunk) => chunks.push(chunk));
    const finished = new Promise((resolve) => response.on("end", resolve));
    assert.equal(
      f.context.handleProjectConfigAsset(
        "/home-logo.jpg",
        { method },
        response
      ),
      true
    );
    await finished;
    assert.equal(headers["Cache-Control"], "no-store");
    assert.equal(headers["Content-Type"], "image/png");
    assert.deepEqual(
      Buffer.concat(chunks),
      method === "GET" ? png : Buffer.alloc(0)
    );
  }
});
