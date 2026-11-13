// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import assert from "node:assert/strict";
import { test } from "node:test";
import { getSkillRepositoryIconKind } from "../../lib/skillRepositoryIcon.ts";

test("recognizes document and presentation names with token boundaries", () => {
  for (const name of ["workspace-file-summarizer", "xlsx", "PDF-reader"]) {
    assert.equal(getSkillRepositoryIconKind({ name }), "document");
  }
  for (const name of ["ppt-generator", "PPT Create", "slides"]) {
    assert.equal(getSkillRepositoryIconKind({ name }), "presentation");
  }
});

test("uses tags before names, and explicit icon identifiers before tags", () => {
  assert.equal(
    getSkillRepositoryIconKind({ name: "custom", tags: ["演示文稿"] }),
    "presentation"
  );
  assert.equal(
    getSkillRepositoryIconKind({ name: "ppt", tags: ["file-management"] }),
    "document"
  );
  assert.equal(
    getSkillRepositoryIconKind({
      name: "ppt",
      tags: ["presentation"],
      icon: "file-text",
    }),
    "document"
  );
  assert.equal(
    getSkillRepositoryIconKind({ name: "ppt", icon: "layers" }),
    "general"
  );
});

test("keeps unsupported or ambiguous values on the generic fallback", () => {
  for (const name of ["", "skill-creator", "slack-gif-creator", "profile"]) {
    assert.equal(
      getSkillRepositoryIconKind({ name, tags: [], icon: null }),
      "general"
    );
  }
  assert.equal(
    getSkillRepositoryIconKind({ name: "ppt-generator", icon: "unknown" }),
    "presentation"
  );
});
