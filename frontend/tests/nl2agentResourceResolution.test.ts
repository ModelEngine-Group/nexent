import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const {
  getNl2AgentCardPhase,
  isSafeNl2AgentResourceCard,
} = require("../lib/nl2agent-resource-resolution.ts");

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
