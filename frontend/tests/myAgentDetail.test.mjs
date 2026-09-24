import assert from "node:assert/strict";
import test from "node:test";

import { mapMyAgentDetail } from "../lib/myAgentDetail.ts";

test("resolves tool and skill names from version instance IDs", () => {
  const detail = {
    display_name: "Assistant",
    tools: [{ tool_id: 42, enabled: true }],
    skills: [{ skill_id: 7, enabled: true }],
  };

  const view = mapMyAgentDetail(
    detail,
    { tags: [] },
    {
      tools: [{ id: "42", name: "Search", origin_name: "Web Search" }],
      skills: [{ skill_id: 7, name: "Summarize" }],
    }
  );

  assert.deepEqual(view.tools, ["Web Search"]);
  assert.deepEqual(view.skills, ["Summarize"]);
});

test("keeps instance names when a catalog entry is unavailable", () => {
  const detail = {
    tools: [{ tool_id: 42, origin_name: "Archived Tool", enabled: true }],
    skills: [{ skill_id: 7, name: "Archived Skill", enabled: true }],
  };

  const view = mapMyAgentDetail(
    detail,
    { tags: [] },
    { tools: [], skills: [] }
  );

  assert.deepEqual(view.tools, ["Archived Tool"]);
  assert.deepEqual(view.skills, ["Archived Skill"]);
});

test("retains bound resources by ID while names are unavailable", () => {
  const detail = {
    tools: [{ tool_id: 42, enabled: true }],
    skills: [{ skill_id: 7, enabled: true }],
  };

  const view = mapMyAgentDetail(detail, { tags: [] });

  assert.deepEqual(view.tools, ["#42"]);
  assert.deepEqual(view.skills, ["#7"]);
});
