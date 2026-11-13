// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import assert from "node:assert/strict";
import { test } from "node:test";
import { buildSkillDetailTree } from "../../lib/skillDetailFiles.ts";

test("builds nested directories and keeps duplicate basenames distinct", () => {
  const tree = buildSkillDetailTree([
    { path: "SKILL.md", content: "" },
    { path: "docs/deep/readme.md", content: "" },
    { path: "scripts/readme.md", content: "" },
  ]);
  assert.equal(tree[0].key, "SKILL.md");
  assert.equal(tree[1].children[0].children[0].key, "docs/deep/readme.md");
  assert.equal(tree[2].children[0].key, "scripts/readme.md");
  assert.equal(tree[1].isLeaf, false);
});

test("filters full paths case-insensitively while preserving ancestry", () => {
  const files = [
    { path: "docs/nested/Report.md", content: "" },
    { path: "scripts/task.py", content: "" },
  ];
  assert.deepEqual(buildSkillDetailTree(files, " REPORT "), [
    {
      key: "docs",
      title: "docs",
      isLeaf: false,
      children: [
        {
          key: "docs/nested",
          title: "nested",
          isLeaf: false,
          children: [
            { key: "docs/nested/Report.md", title: "Report.md", isLeaf: true },
          ],
        },
      ],
    },
  ]);
  assert.deepEqual(buildSkillDetailTree(files, "missing"), []);
  assert.deepEqual(buildSkillDetailTree([]), []);
});
