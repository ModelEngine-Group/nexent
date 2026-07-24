import assert from "node:assert/strict";
import React from "react";
import { describe, it } from "vitest";

import {
  resolveNl2AgentCardAgentId,
  resolveNl2AgentDraftAgentId,
  resolveNl2AgentRunnerId,
} from "@/lib/chat/nl2agentDraftContext";
import { nl2AgentContinuationScopeKey } from "@/lib/chat/nl2agentContinuation";
import type { Nl2AgentSessionState } from "@/services/nl2agentService";
import { AgentIdentityCard } from "../AgentIdentityCard";
import {
  nl2AgentCardRegistry,
  renderStructuredNl2AgentCard,
  renderStructuredNl2AgentEnvelope,
  type StructuredNl2AgentCard,
} from "../cardRegistry";
import { CatalogSnapshotIdentifier } from "../CatalogSnapshotIdentifier";
import {
  canPublishFinalReview,
  FinalizeCard,
  getVerificationReviewFields,
  groupFinalReviewResources,
} from "../FinalizeCard";
import { LocalResourcesCard } from "../LocalResourcesCard";
import { ModelSelectionCard } from "../ModelSelectionCard";
import { getOnlineConfigurationBlockers } from "../OnlineConfigurationBar";
import { RequirementsSummaryCard } from "../RequirementsSummaryCard";
import { WebMcpCard } from "../WebMcpCard";
import { WebSkillCard } from "../WebSkillCard";

function assertElement(
  node: React.ReactNode
): asserts node is React.ReactElement<Record<string, unknown>> {
  assert.equal(React.isValidElement(node), true);
}

const readyMcpOption = {
  option_id: "remote",
  type: "remote" as const,
  label: "Remote endpoint",
  requires_configuration: false,
  fields: [],
  supported: true,
  status: "ready" as const,
};

describe("structured NL2AGENT card registry", () => {
  it("registers all seven server-defined card types", () => {
    assert.deepEqual(Object.keys(nl2AgentCardRegistry).sort(), [
      "agent_identity",
      "final_review",
      "local_resources",
      "model_selection",
      "requirements_summary",
      "web_mcp",
      "web_skill",
    ]);
  });

  it("renders every card from a structured envelope without Markdown parsing", () => {
    const cards = [
      {
        card_type: "requirements_summary",
        card_key: "requirements_summary",
        payload: {
          agent_id: 202,
          goal: "Build reports",
          audience_or_scenario: "Analysts",
          primary_input: "Documents",
          expected_output: "A report",
          key_constraints: "Preserve facts",
        },
      },
      {
        card_type: "model_selection",
        card_key: "model_selection",
        payload: { agent_id: 202 },
      },
      {
        card_type: "local_resources",
        card_key: "local_1",
        payload: {
          agent_id: 202,
          recommendation_batch_id: "local_1",
          tools: [{ tool_id: 1, name: "Parser" }],
          skills: [{ skill_id: 2, name: "Writer" }],
        },
      },
      {
        card_type: "web_mcp",
        card_key: "mcp_1",
        payload: {
          agent_id: 202,
          recommendation_batch_id: "mcp_1",
          items: [
            {
              recommendation_id: "registry:test",
              name: "Test MCP",
              install_options: [readyMcpOption],
            },
          ],
        },
      },
      {
        card_type: "web_skill",
        card_key: "skill_1",
        payload: {
          agent_id: 202,
          recommendation_batch_id: "skill_1",
          items: [{ skill_id: 3, name: "Research" }],
        },
      },
      {
        card_type: "agent_identity",
        card_key: "agent_identity",
        payload: { agent_id: 202, display_name: "Report Builder" },
      },
      {
        card_type: "final_review",
        card_key: "final_review",
        payload: {
          agent_id: 202,
          business_description: "Build reports",
          duty_prompt: "Create accurate reports.",
          greeting_message: "How can I help?",
        },
      },
    ] as StructuredNl2AgentCard[];

    const rendered = renderStructuredNl2AgentEnvelope({
      schema_version: 1,
      draft_agent_id: 202,
      workflow_revision: 8,
      cards,
    });

    assert.equal(rendered.length, 7);
    const direct = cards.map((card) =>
      renderStructuredNl2AgentCard(card, 202, 8)
    );
    assertElement(direct[0]);
    assert.equal(direct[0].type, RequirementsSummaryCard);
    assert.equal(direct[0].props.workflowRevision, 8);
    assertElement(direct[1]);
    assert.equal(direct[1].type, ModelSelectionCard);
    assert.equal(direct[1].props.workflowRevision, 8);
    assertElement(direct[2]);
    assert.equal(direct[2].type, "div");
    const localChildren = React.Children.toArray(
      direct[2].props.children as React.ReactNode
    );
    assertElement(localChildren[0]);
    assert.equal(localChildren[0].type, CatalogSnapshotIdentifier);
    assertElement(localChildren[1]);
    assert.equal(localChildren[1].type, LocalResourcesCard);
    assert.equal(localChildren[1].props.workflowRevision, 8);
    assertElement(direct[3]);
    const mcpChildren = React.Children.toArray(
      direct[3].props.children as React.ReactNode
    );
    assertElement(mcpChildren[0]);
    assert.equal(mcpChildren[0].type, WebMcpCard);
    assert.equal(mcpChildren[0].props.workflowRevision, 8);
    assertElement(direct[4]);
    const skillChildren = React.Children.toArray(
      direct[4].props.children as React.ReactNode
    );
    assertElement(skillChildren[0]);
    assert.equal(skillChildren[0].type, WebSkillCard);
    assert.equal(skillChildren[0].props.workflowRevision, 8);
    assertElement(direct[5]);
    assert.equal(direct[5].type, AgentIdentityCard);
    assert.equal(direct[5].props.workflowRevision, 8);
    assertElement(direct[6]);
    assert.equal(direct[6].type, FinalizeCard);
    assert.equal(direct[6].props.workflowRevision, 8);
  });

  it("exposes the effective verification configuration in final review", () => {
    assert.deepEqual(
      getVerificationReviewFields({ enabled: true, strictness: "strict" }),
      [
        { label: "Verification", value: "Enabled" },
        { label: "Strictness", value: "strict" },
      ]
    );
  });
});

describe("online configuration blockers", () => {
  it("requires both catalogs and resolved MCP binding", () => {
    const missing = getOnlineConfigurationBlockers({
      recommendations: {
        online_mcp: {
          resource_type: "mcp",
          item_keys: [],
          status: "presented",
        },
      },
      online_configuration_confirmed: false,
      mcp_workflows: {},
    });
    assert.deepEqual(missing.missingCatalogs, ["Skill"]);

    const unresolved = getOnlineConfigurationBlockers({
      recommendations: {
        online_mcp: {
          resource_type: "mcp",
          item_keys: [],
          status: "presented",
        },
        online_skill: {
          resource_type: "skill",
          item_keys: [],
          status: "presented",
        },
      },
      online_configuration_confirmed: false,
      mcp_workflows: {
        "registry:test": {
          recommendation_id: "registry:test",
          status: "connected",
        },
      },
    });
    assert.equal(unresolved.unresolvedMcpCount, 1);
  });
});

describe("final review persisted state", () => {
  it("groups named resources and blocks invalid references", () => {
    const state = {
      tools: [
        { tool_id: 11, name: "Parser", source: "local", origin: "local" },
        { tool_id: 12, name: "Fetch", source: "mcp", origin: "online" },
      ],
      skills: [
        { skill_id: 21, name: "Writer", source: "custom", origin: "local" },
      ],
    } as Nl2AgentSessionState;
    const groups = groupFinalReviewResources(state);
    assert.deepEqual(
      groups.local.map((item) => item.name),
      ["Parser", "Writer"]
    );
    assert.deepEqual(
      groups.online.map((item) => item.name),
      ["Fetch"]
    );

    const validState = {
      session_status: "active",
      current_stage: "final_review",
      identity_confirmed: true,
      invalid_references: [],
    } as unknown as Nl2AgentSessionState;
    assert.equal(canPublishFinalReview(validState, true, false, null), true);
    assert.equal(
      canPublishFinalReview(
        {
          ...validState,
          invalid_references: [
            { reference_type: "tool", reference_id: 404, reason: "not_found" },
          ],
        },
        true,
        false,
        null
      ),
      false
    );
  });
});

describe("NL2AGENT durable scope helpers", () => {
  it("keeps conversation, runner, card, and continuation scope isolated", () => {
    assert.equal(resolveNl2AgentDraftAgentId(10, { "10": 202 }, 11, 303), 202);
    assert.equal(resolveNl2AgentDraftAgentId(10, {}, 11, 303), null);
    assert.equal(resolveNl2AgentRunnerId(101, "999"), 101);
    assert.deepEqual(resolveNl2AgentCardAgentId(undefined, [], 202), {
      agentId: 202,
      mismatch: false,
    });
    assert.equal(resolveNl2AgentCardAgentId(202, [303], 202).mismatch, true);
    assert.notEqual(
      nl2AgentContinuationScopeKey(10, 202),
      nl2AgentContinuationScopeKey(11, 303)
    );
  });
});
