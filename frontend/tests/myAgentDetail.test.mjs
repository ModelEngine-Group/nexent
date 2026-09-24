import assert from "node:assert/strict";
import test from "node:test";

import {
  mapAgentInfoDetail,
  mapMyAgentDetail,
  mapRepositoryAgentDetail,
} from "../lib/myAgentDetail.ts";

test("maps a repository listing with its published version and repository metadata", () => {
  const view = mapRepositoryAgentDetail(
    {
      display_name: "Published Agent",
      version: { version_name: "V2" },
      tools: [{ tool_id: 42, enabled: true }],
      skills: [{ skill_id: 7, enabled: true }],
    },
    {
      agent_repository_id: 22,
      name: "Published Agent",
      status: "shared",
      downloads: 5,
      created_at: "2026-09-20",
    },
    ["Research"],
    {
      tools: [{ id: "42", name: "Search", origin_name: "Web Search" }],
      skills: [{ skill_id: 7, name: "Summarize" }],
    }
  );

  assert.equal(view.versionLabel, "V2");
  assert.deepEqual(view.tools, ["Web Search"]);
  assert.deepEqual(view.skills, ["Summarize"]);
  assert.deepEqual(view.tags, ["Research"]);
  assert.deepEqual(view.repositoryInfo, {
    downloads: 5,
    createdAt: "2026-09-20",
  });
});

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

test("maps the Agents page record to the shared detail view", () => {
  const view = mapAgentInfoDetail({
    display_name: "Research Assistant",
    description: "Finds sources",
    author: "Alice",
    model_names: ["Model A", "Model B"],
    current_version_no: 3,
    tools: [
      {
        id: "42",
        name: "Search",
        origin_name: "Web Search",
        display_names: ["Docs"],
      },
      { id: "43", name: "Reader", display_names: ["Docs", "Wiki"] },
    ],
    skills: [{ skill_id: 7, name: "Summarize" }],
    sub_agent_relations: [{ agent_id: 9, agent_name: "Writer" }],
    tags: ["internal", "internal"],
  });

  assert.deepEqual(view, {
    title: "Research Assistant",
    description: "Finds sources",
    author: "Alice",
    modelName: "Model A, Model B",
    versionLabel: "V3",
    tools: ["Web Search", "Reader"],
    skills: ["Summarize"],
    knowledgeBases: ["Docs", "Wiki"],
    subAgents: ["Writer"],
    tags: ["internal"],
  });
});
