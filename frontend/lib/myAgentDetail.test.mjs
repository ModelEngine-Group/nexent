import assert from "node:assert/strict";
import test from "node:test";

import { mapMyAgentDetail } from "./myAgentDetail.ts";

test("maps the version detail into visible My Agents sections", () => {
  const view = mapMyAgentDetail(
    {
      name: "coding-helper",
      display_name: "代码助手",
      description: "  帮助审查代码  ",
      author: "我",
      model_names: ["Claude 3.5 Sonnet"],
      version: { version_name: "v1.1.0" },
      tools: [
        {
          tool_id: 1,
          origin_name: "file_operations",
          display_names: ["团队代码规范"],
        },
        {
          tool_id: 2,
          name: "code_interpreter",
          display_names: ["团队代码规范"],
        },
      ],
      skills: [{ skill_id: 3, name: "code_review" }],
      sub_agent_relations: [{ agent_id: 4, agent_name: "单元测试生成助手" }],
    },
    { tags: ["开发", "代码审查", "开发"] }
  );

  assert.equal(view.title, "代码助手");
  assert.equal(view.description, "帮助审查代码");
  assert.equal(view.modelName, "Claude 3.5 Sonnet");
  assert.equal(view.versionLabel, "v1.1.0");
  assert.deepEqual(view.tools, ["file_operations", "code_interpreter"]);
  assert.deepEqual(view.skills, ["code_review"]);
  assert.deepEqual(view.knowledgeBases, ["团队代码规范"]);
  assert.deepEqual(view.subAgents, ["单元测试生成助手"]);
  assert.deepEqual(view.tags, ["开发", "代码审查"]);
});

test("omits names that the version endpoint does not provide", () => {
  const view = mapMyAgentDetail(
    {
      name: "draft",
      description: "",
      tools: [{ tool_id: 1 }],
      skills: [{ skill_id: 2 }],
      sub_agent_relations: [{ agent_id: 3 }],
      version: { version_name: "Draft" },
    },
    { tags: [] }
  );

  assert.deepEqual(view.tools, []);
  assert.deepEqual(view.skills, []);
  assert.deepEqual(view.subAgents, []);
  assert.deepEqual(view.knowledgeBases, []);
});
