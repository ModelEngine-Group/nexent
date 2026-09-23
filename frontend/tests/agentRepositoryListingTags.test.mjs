import assert from "node:assert/strict";
import test from "node:test";

import * as repositoryMine from "../lib/agentRepositoryMine.ts";

test("listing accepts selected tags from any tag definition", () => {
  const category = {
    definition_id: 10,
    values: [{ value_id: 100, normalized_value: "marketing" }],
  };
  const assignments = [
    { definition_id: 20, value_id: 200, display_value: "Internal" },
  ];

  assert.deepEqual(
    repositoryMine.getListingTagsFromAssignments(assignments, category),
    ["Internal"]
  );
});

test("listing preserves category preset keys", () => {
  const category = {
    definition_id: 10,
    values: [{ value_id: 100, normalized_value: "marketing" }],
  };

  assert.deepEqual(
    repositoryMine.getListingTagsFromAssignments(
      [{ definition_id: 10, value_id: 100, display_value: "Marketing" }],
      category
    ),
    ["marketing"]
  );
});

test("listing ignores empty and repeated tag values", () => {
  const assignments = [
    { definition_id: 20, value_id: 200, display_value: " Internal " },
    { definition_id: 30, value_id: 300, display_value: "Internal" },
    { definition_id: 40, value_id: 400, display_value: " " },
  ];

  assert.deepEqual(
    repositoryMine.getListingTagsFromAssignments(assignments, null),
    ["Internal"]
  );
});
