import assert from "node:assert/strict";
import test from "node:test";

import { mapSkillRepositoryDetail } from "../lib/skillRepositoryDetail.ts";

test("maps repository skill detail and falls back to its creation date", () => {
  const view = mapSkillRepositoryDetail({
    skill_repository_id: 11,
    name: " Search ",
    description: " Find sources ",
    author: " Alice ",
    status: "shared",
    tags: ["Research", "", " Search "],
    downloads: 12,
    updated_at: "invalid",
    created_at: "2026-09-20T10:30:00Z",
  });

  assert.deepEqual(view, {
    title: "Search",
    description: "Find sources",
    author: "Alice",
    status: "shared",
    tags: ["Research", "Search"],
    downloads: 12,
    updatedAt: "2026-09-20",
  });
});
