// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { checkBoundaries } from "../ui-boundaries.mjs";

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "nexent-ui-boundaries-"));
  t.after(() => {
    assert.ok(root.startsWith(os.tmpdir() + path.sep));
    fs.rmSync(root, { recursive: true, force: true });
  });
  const write = (relative, contents) => {
    const full = path.join(root, relative);
    fs.mkdirSync(path.dirname(full), { recursive: true });
    fs.writeFileSync(full, contents);
  };
  return { root, write };
}

test("common rejects named, type, dynamic and re-exported legacy dependencies", (t) => {
  const { root, write } = fixture(t);
  for (const source of [
    'import { Button } from "antd";',
    'export type { ModalProps } from "antd";',
    'import("antd/es/table");',
    'export { Button } from "antd";',
  ]) {
    write("components/common/Example.tsx", source);
    assert.match(
      checkBoundaries(root).violations.join("\n"),
      /common components must not depend/
    );
  }
});

test("legacy business consumers remain allowed without a dependency budget", (t) => {
  const { root, write } = fixture(t);
  write("app/page.tsx", 'import { Button } from "antd";');
  const result = checkBoundaries(root);
  assert.deepEqual(result.violations, []);
  assert.deepEqual(result.legacyImports, { "app/page.tsx": ["antd:Button"] });
});

test("basic UI rejects relative business dependencies and unsupported component bases", (t) => {
  const { root, write } = fixture(t);
  write(
    "components/ui/button.tsx",
    'import { x } from "../../services/api"; import { y } from "@base-ui/react";'
  );
  assert.equal(checkBoundaries(root).violations.length, 2);
});

test("basic UI accepts local primitives and semantic utilities without snapshots", (t) => {
  const { root, write } = fixture(t);
  write(
    "components/ui/button.tsx",
    'import { cn } from "@/lib/utils"; import { Slot } from "radix-ui";'
  );
  assert.deepEqual(checkBoundaries(root).violations, []);
});
