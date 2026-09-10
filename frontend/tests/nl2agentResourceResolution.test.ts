import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const {
  getNl2AgentCardPhase,
  isSafeNl2AgentResourceCard,
} = require("../lib/nl2agent-resource-resolution.ts");
const {
  abandonResourceGapRequirement,
  buildResourceGapResolutionResult,
  canSubmitResourceGapResolution,
  createResourceGapRequirementStates,
  markResourceGapSkillCreated,
  restoreResourceGapRequirement,
  saveResourceGapRequirementEdit,
  startResourceGapRequirementEdit,
} = require("../lib/nl2agent-resource-gap.ts");

test("v2 installation cards reject configuration and installation details", () => {
  assert.equal(
    isSafeNl2AgentResourceCard({
      schema_version: 2,
      subtype: "suggested_resource_installation",
      agent_id: 42,
      resources: [
        {
          candidate_ref: "tenant_mcp_repository:7",
          resource_type: "mcp_server",
          source: "TENANT_MCP_REPOSITORY",
          name: "Weather MCP",
          description: "Weather lookup",
          requirement_ids: ["weather"],
          config: { authorization_token: "secret" },
        },
      ],
    }),
    false
  );
});

test("v2 binding cards only accept installed resource sources", () => {
  assert.equal(
    isSafeNl2AgentResourceCard({
      schema_version: 2,
      subtype: "installed_resource_binding",
      agent_id: 42,
      resources: [
        {
          candidate_ref: "tenant_skill_repository:7",
          resource_type: "skill",
          source: "TENANT_SKILL_REPOSITORY",
          name: "Report",
          description: "Creates reports",
          requirement_ids: ["report"],
        },
      ],
    }),
    false
  );
});

test("card subtypes map to mutually exclusive resource phases", () => {
  assert.equal(
    getNl2AgentCardPhase("suggested_resource_installation"),
    "installing"
  );
  assert.equal(
    getNl2AgentCardPhase("resource_gap_resolution"),
    "resolving_gap"
  );
  assert.equal(getNl2AgentCardPhase("installed_resource_binding"), "binding");
  assert.equal(getNl2AgentCardPhase("requirement_clarification"), "clarifying");
});

const gapRequirements = [
  {
    requirement_id: "inventory",
    query: "查询库存",
    resource_name_hint: "库存系统",
    search_terms: ["库存", "inventory"],
  },
  {
    requirement_id: "report",
    query: "生成日报",
    resource_name_hint: null,
    search_terms: ["日报", "report"],
  },
  {
    requirement_id: "email",
    query: "发送邮件",
    resource_name_hint: "邮件服务",
    search_terms: ["邮件", "email"],
  },
];

test("resource-gap resolution keeps a complete snapshot and emits one batch action", () => {
  let states = createResourceGapRequirementStates(gapRequirements);
  states = startResourceGapRequirementEdit(states, "inventory");
  states = saveResourceGapRequirementEdit(
    states,
    "inventory",
    "查询 ERP 中的实时库存"
  );
  states = abandonResourceGapRequirement(states, "report");
  states = markResourceGapSkillCreated(states, "email");

  assert.equal(canSubmitResourceGapResolution(states), true);
  assert.deepEqual(buildResourceGapResolutionResult(gapRequirements, states), {
    requirements: [
      {
        requirement_id: "inventory",
        resolution: "revised",
        query: "查询 ERP 中的实时库存",
      },
      {
        requirement_id: "email",
        resolution: "skill_created",
        query: "发送邮件",
      },
    ],
    abandoned_requirement_ids: ["report"],
  });
});

test("resource-gap resolution blocks unfinished edits and restores deleted changes", () => {
  let states = createResourceGapRequirementStates(gapRequirements);
  states = startResourceGapRequirementEdit(states, "inventory");
  assert.equal(canSubmitResourceGapResolution(states), false);

  states = saveResourceGapRequirementEdit(states, "inventory", "更新库存查询");
  states = abandonResourceGapRequirement(states, "inventory");
  states = restoreResourceGapRequirement(states, "inventory");

  assert.equal(states.inventory.status, "revised");
  assert.equal(states.inventory.query, "更新库存查询");
});
