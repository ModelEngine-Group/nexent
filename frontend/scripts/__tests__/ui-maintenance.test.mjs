// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { checkBoundaries, inspectBoundaries } from "../ui-boundaries.mjs";
import {
  digest,
  transformSource,
  prepareCandidate,
  acceptCandidate,
  upstreamStatus,
} from "../ui-upstream.mjs";

const artifactRoot = path.resolve(
  process.env.UI_TEST_ARTIFACT_DIR ??
    path.join(os.tmpdir(), "nexent-ui-maintenance")
);
fs.mkdirSync(artifactRoot, { recursive: true });

test("candidate tampering and baseline drift are rejected before working writes", async (t) => {
  const data = await withCandidate(t);
  const before = fs.readFileSync(
    path.join(data.root, "components/ui/sample.tsx"),
    "utf8"
  );
  fs.writeFileSync(
    path.join(data.output, "raw.txt"),
    "export const tampered = true;\n"
  );
  await assert.rejects(
    acceptCandidate({
      root: data.root,
      directory: data.output,
      reviewed: true,
    }),
    /Candidate source or transform changed/
  );
  fs.writeFileSync(
    path.join(data.output, "raw.txt"),
    data.raw.replace("first = 1", "first = 10")
  );
  data.write("vendor/shadcn/baselines/sample.raw.txt", "changed ancestor");
  await assert.rejects(
    acceptCandidate({
      root: data.root,
      directory: data.output,
      reviewed: true,
    }),
    /baseline changed/
  );
  assert.equal(
    fs.readFileSync(path.join(data.root, "components/ui/sample.tsx"), "utf8"),
    before
  );
});

test("a write failure restores the complete source and baseline transaction", async (t) => {
  const data = await withCandidate(t);
  const files = [
    "components/ui/sample.tsx",
    "vendor/shadcn/manifest.json",
    "vendor/shadcn/baselines/sample.raw.txt",
    "vendor/shadcn/baselines/sample.generated.txt",
  ];
  const before = files.map((file) =>
    fs.readFileSync(path.join(data.root, file), "utf8")
  );
  const write = fs.writeFileSync.bind(fs);
  let failOnce = true;
  t.mock.method(fs, "writeFileSync", (file, ...args) => {
    if (String(file).endsWith("manifest.json") && failOnce) {
      failOnce = false;
      throw new Error("controlled write failure");
    }
    return write(file, ...args);
  });
  await assert.rejects(
    acceptCandidate({
      root: data.root,
      directory: data.output,
      reviewed: true,
    }),
    /controlled write failure/
  );
  assert.deepEqual(
    files.map((file) => fs.readFileSync(path.join(data.root, file), "utf8")),
    before
  );
});

test("common cannot regain Ant Design even through an old budget entry", (t) => {
  const { root, write } = fixture(t);
  write("components/common/Example.tsx", 'import { Button } from "antd";');
  const baseline = inspectBoundaries(root).legacyImports;
  assert.match(
    checkBoundaries(root, baseline).violations.join("\n"),
    /common components must not depend/
  );
});

function fixture(t) {
  const root = fs.mkdtempSync(path.join(artifactRoot, "fixture-"));
  t.after(() => {
    assert.ok(root.startsWith(artifactRoot + path.sep));
    fs.rmSync(root, { recursive: true, force: true });
  });
  const write = (relative, contents) => {
    const full = path.join(root, relative);
    fs.mkdirSync(path.dirname(full), { recursive: true });
    fs.writeFileSync(full, contents);
  };
  return { root, write };
}

test("dependency budgets permit removals but reject new named, dynamic and type imports", (t) => {
  const { root, write } = fixture(t);
  write("app/page.tsx", 'import { Button } from "antd";');
  const baseline = inspectBoundaries(root).legacyImports;
  assert.deepEqual(checkBoundaries(root, baseline).violations, []);
  write("app/page.tsx", 'import { Button, Modal } from "antd";');
  assert.match(
    checkBoundaries(root, baseline).violations.join("\n"),
    /antd:Modal/
  );
  write(
    "app/page.tsx",
    'export type { ModalProps } from "antd"; import("antd/es/table");'
  );
  assert.equal(checkBoundaries(root, baseline).violations.length, 2);
  write("app/page.tsx", "export {};");
  assert.deepEqual(checkBoundaries(root, baseline).violations, []);
});

test("basic UI rejects relative business dependencies and unsupported component bases", (t) => {
  const { root, write } = fixture(t);
  write(
    "components/ui/button.tsx",
    'import { x } from "../../services/api"; import { y } from "@base-ui/react";'
  );
  assert.equal(checkBoundaries(root, {}).violations.length, 2);
});

async function upstreamFixture(t) {
  const { root, write } = fixture(t);
  const raw = "export const first = 1;\n\nexport const second = 2;\n";
  write(".prettierrc", '{"semi":true}');
  write("components.json", '{"style":"new-york"}');
  const base = await transformSource(raw, "sample", root);
  const entry = {
    ownership: "upstream-managed",
    provenance: "verified",
    target: "components/ui/sample.tsx",
    sourcePath: "apps/v4/registry/new-york-v4/ui/sample.tsx",
    commit: "a".repeat(40),
    rawBaseline: "baselines/sample.raw.txt",
    generatedBaseline: "baselines/sample.generated.txt",
    rawSha256: digest(raw),
    generatedSha256: digest(base),
    transform: "radix-new-york-v4-v2",
  };
  write("vendor/shadcn/baselines/sample.raw.txt", raw);
  write("vendor/shadcn/baselines/sample.generated.txt", base);
  write("components/ui/sample.tsx", base.replace("second = 2", "second = 20"));
  write(
    "vendor/shadcn/manifest.json",
    JSON.stringify({ components: { sample: entry } })
  );
  return {
    root,
    write,
    raw,
    base,
    entry,
    output: path.join(artifactRoot, `candidate-${path.basename(root)}`),
  };
}

async function withCandidate(
  t,
  transform = (raw) => raw.replace("first = 1", "first = 10")
) {
  const data = await upstreamFixture(t);
  t.after(() => {
    assert.ok(data.output.startsWith(artifactRoot + path.sep));
    fs.rmSync(data.output, { recursive: true, force: true });
  });
  const candidate = await prepareCandidate({
    root: data.root,
    name: "sample",
    commit: "b".repeat(40),
    output: data.output,
    fetchSource: async () => transform(data.raw),
  });
  return { ...data, candidate };
}

test("preview merges upstream changes and preserves local changes without writing working files", async (t) => {
  const data = await withCandidate(t);
  const merged = fs.readFileSync(path.join(data.output, "merged.tsx"), "utf8");
  assert.equal(data.candidate.conflicted, false);
  assert.match(merged, /first = 10/);
  assert.match(merged, /second = 20/);
  assert.match(
    fs.readFileSync(path.join(data.root, "components/ui/sample.tsx"), "utf8"),
    /first = 1;/
  );
  await assert.rejects(
    acceptCandidate({ root: data.root, directory: data.output }),
    /--reviewed/
  );
  await acceptCandidate({
    root: data.root,
    directory: data.output,
    reviewed: true,
  });
  assert.equal(upstreamStatus(data.root)[0].commit, "b".repeat(40));
  assert.equal(upstreamStatus(data.root)[0].locallyModified, true);
});

test("conflicts block acceptance without overwriting local source", async (t) => {
  const data = await withCandidate(t, (raw) =>
    raw.replace("second = 2", "second = 99")
  );
  assert.equal(data.candidate.conflicted, true);
  await assert.rejects(
    acceptCandidate({
      root: data.root,
      directory: data.output,
      reviewed: true,
      resolved: true,
    }),
    /Resolve conflicts/
  );
  assert.match(
    fs.readFileSync(path.join(data.root, "components/ui/sample.tsx"), "utf8"),
    /second = 20/
  );
});

test("stale working files and tampered candidate sources cannot be accepted", async (t) => {
  const data = await withCandidate(t);
  data.write("components/ui/sample.tsx", "export const concurrent = true;\n");
  await assert.rejects(
    acceptCandidate({
      root: data.root,
      directory: data.output,
      reviewed: true,
    }),
    /changed since preview/
  );
  assert.match(
    fs.readFileSync(path.join(data.root, "components/ui/sample.tsx"), "utf8"),
    /concurrent/
  );
});

test("unknown ancestors, mutable refs and unsupported bases are rejected", async (t) => {
  const data = await upstreamFixture(t);
  await assert.rejects(
    prepareCandidate({
      root: data.root,
      name: "sample",
      commit: "main",
      output: data.output,
    }),
    /immutable/
  );
  await assert.rejects(
    transformSource('import { x } from "@base-ui/react";', "sample", data.root),
    /unsupported/
  );
  data.entry.transform = "radix-new-york-v4-v1";
  data.write(
    "vendor/shadcn/manifest.json",
    JSON.stringify({ components: { sample: data.entry } })
  );
  let fetched = false;
  await assert.rejects(
    prepareCandidate({
      root: data.root,
      name: "sample",
      commit: "b".repeat(40),
      output: data.output,
      fetchSource: async () => {
        fetched = true;
        return data.raw;
      },
    }),
    /Unsupported source or transform/
  );
  assert.equal(fetched, false);
  assert.equal(fs.existsSync(data.output), false);
  data.entry.transform = "radix-new-york-v4-v2";
  data.entry.provenance = "unknown";
  data.write(
    "vendor/shadcn/manifest.json",
    JSON.stringify({ components: { sample: data.entry } })
  );
  await assert.rejects(
    prepareCandidate({
      root: data.root,
      name: "sample",
      commit: "b".repeat(40),
      output: data.output,
    }),
    /Unknown upstream ancestor/
  );
});

test("repeating an identical update preserves the accepted local result", async (t) => {
  const data = await withCandidate(t, (raw) => raw);
  await acceptCandidate({
    root: data.root,
    directory: data.output,
    reviewed: true,
  });
  const before = fs.readFileSync(
    path.join(data.root, "components/ui/sample.tsx"),
    "utf8"
  );
  const secondOutput = data.output + "-repeat";
  t.after(() => {
    assert.ok(secondOutput.startsWith(artifactRoot + path.sep));
    fs.rmSync(secondOutput, { recursive: true, force: true });
  });
  await prepareCandidate({
    root: data.root,
    name: "sample",
    commit: "b".repeat(40),
    output: secondOutput,
    fetchSource: async () => data.raw,
  });
  assert.equal(
    fs.readFileSync(path.join(secondOutput, "merged.tsx"), "utf8"),
    before
  );
});
