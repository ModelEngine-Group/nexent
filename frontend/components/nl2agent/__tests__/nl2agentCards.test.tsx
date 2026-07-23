import assert from "node:assert/strict";
import { describe, it } from "vitest";
import React from "react";
import {
  resolveNl2AgentCardAgentId,
  resolveNl2AgentDraftAgentId,
  resolveNl2AgentRunnerId,
} from "@/lib/chat/nl2agentDraftContext";
import { nl2AgentContinuationScopeKey } from "@/lib/chat/nl2agentContinuation";

import {
  OnlineRecommendationGroup,
  renderValidatedNl2AgentCard,
  tryRenderNl2AgentCard,
} from "..";
import { LocalResourcesCard } from "../LocalResourcesCard";
import { ModelSelectionCard } from "../ModelSelectionCard";
import { AgentIdentityCard } from "../AgentIdentityCard";
import { RequirementsSummaryCard } from "../RequirementsSummaryCard";
import {
  FinalizeCard,
  canPublishFinalReview,
  getVerificationReviewFields,
  groupFinalReviewResources,
} from "../FinalizeCard";
import { WebMcpCard, type WebMcpCardItem } from "../WebMcpCard";
import { WebSkillCard, type WebSkillCardItem } from "../WebSkillCard";
import { getOnlineConfigurationBlockers } from "../OnlineConfigurationBar";
import type { Nl2AgentSessionState } from "@/services/nl2agentService";
import { validateNl2AgentCards } from "../cardValidation";
import {
  nl2AgentCardRegistry,
  renderStructuredNl2AgentCard,
} from "../cardRegistry";

type RenderedCardTestProps = {
  agentId: number;
  children: React.ReactNode;
  data: { agent_id?: number };
  item: { name?: string };
  recommendationBatchId: string;
  skills: unknown[];
  suggestedDisplayName: string;
  summary: unknown;
  tools: unknown[];
};

function assertElement(
  node: React.ReactNode
): asserts node is React.ReactElement<RenderedCardTestProps> {
  assert.equal(React.isValidElement(node), true);
}

function onlineChildren(node: React.ReactNode): React.ReactNode[] {
  assertElement(node);
  assert.equal(node.type, OnlineRecommendationGroup);
  return React.Children.toArray(node.props.children);
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

describe("tryRenderNl2AgentCard", () => {
  it("registers all seven structured card types", () => {
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

  it("renders a structured card without parsing a Markdown fence", () => {
    const node = renderStructuredNl2AgentCard(
      {
        card_type: "model_selection",
        card_key: "model_selection",
        payload: {},
      },
      202
    );

    assertElement(node);
    assert.equal(node.type, ModelSelectionCard);
    assert.equal(node.props.agentId, 202);
  });

  it("exposes the effective verification configuration in final review", () => {
    assert.deepEqual(getVerificationReviewFields({ enabled: false }), [
      { label: "Verification", value: "Disabled" },
    ]);
    assert.deepEqual(
      getVerificationReviewFields({
        enabled: true,
        strictness: "strict",
        max_final_rounds: 3,
        fail_policy: "warn",
      }),
      [
        { label: "Verification", value: "Enabled" },
        { label: "Strictness", value: "strict" },
        { label: "Max Verification Rounds", value: 3 },
        { label: "Failure Policy", value: "warn" },
      ]
    );
  });

  it("renders a prevalidated card AST without parsing raw JSON again", () => {
    const validation = validateNl2AgentCards(
      "```nl2agent-model-selection\n{}\n```",
      202
    );

    const node = renderValidatedNl2AgentCard(validation.cards[0]);

    assertElement(node);
    assert.equal(node.type, ModelSelectionCard);
    assert.equal(node.props.agentId, 202);
  });

  it("rejects invented search request cards before parsing their payload", () => {
    const node = tryRenderNl2AgentCard(
      "nl2agent-search-web-mcps",
      JSON.stringify({ query: "docx parser" }),
      202
    );

    assertElement(node);
    assert.match(
      JSON.stringify(node.props.children),
      /search must be executed by the agent/
    );
  });

  it("routes model-selection fenced data to ModelSelectionCard", () => {
    const node = tryRenderNl2AgentCard(
      "nl2agent-model-selection",
      JSON.stringify({ agent_id: 202 })
    );

    assertElement(node);
    assert.equal(node.type, ModelSelectionCard);
    assert.equal(node.props.agentId, 202);
  });

  it("routes the read-only requirements summary card", () => {
    const summary = {
      goal: "Build presentations",
      audience_or_scenario: "Office users",
      primary_input: "DOCX files",
      expected_output: "PPT files",
      key_constraints: "Preserve source facts",
    };
    const node = tryRenderNl2AgentCard(
      "nl2agent-requirements-summary",
      JSON.stringify(summary),
      202
    );

    assertElement(node);
    assert.equal(node.type, RequirementsSummaryCard);
    assert.equal(node.props.agentId, 202);
    assert.deepEqual(node.props.summary, summary);
  });

  it("normalizes model-selection language tags", () => {
    const node = tryRenderNl2AgentCard(
      " NL2AGENT-MODEL-SELECTION ",
      JSON.stringify({ agent_id: 202 })
    );

    assertElement(node);
    assert.equal(node.type, ModelSelectionCard);
  });

  it("routes agent-identity fenced data to AgentIdentityCard", () => {
    const node = tryRenderNl2AgentCard(
      "nl2agent-agent-identity",
      JSON.stringify({ agent_id: 202, display_name: "Document Assistant" })
    );

    assertElement(node);
    assert.equal(node.type, AgentIdentityCard);
    assert.equal(node.props.agentId, 202);
  });

  it("passes the generated display name into AgentIdentityCard", () => {
    const node = tryRenderNl2AgentCard(
      "nl2agent-agent-identity",
      JSON.stringify({
        agent_id: 202,
        display_name: "Document Presentation Assistant",
      })
    );

    assertElement(node);
    assert.equal(node.type, AgentIdentityCard);
    assert.equal(
      node.props.suggestedDisplayName,
      "Document Presentation Assistant"
    );
  });

  it("routes local-resource fenced data to LocalResourcesCard", () => {
    const node = tryRenderNl2AgentCard(
      "nl2agent-local-resources",
      JSON.stringify({
        agent_id: 202,
        recommendation_batch_id: "local_test",
        tools: [{ tool_id: 1, name: "Search" }],
        skills: [{ skill_id: 7, name: "Summarize" }],
      })
    );

    assertElement(node);
    assert.equal(node.type, LocalResourcesCard);
    assert.equal(node.props.agentId, 202);
    assert.equal(node.props.recommendationBatchId, "local_test");
    assert.deepEqual(node.props.tools, [
      { tool_id: 1, name: "Search", kind: "tool" },
    ]);
    assert.deepEqual(node.props.skills, [
      { skill_id: 7, name: "Summarize", kind: "skill" },
    ]);
  });

  it("does not default missing card agent_id to zero", () => {
    const node = tryRenderNl2AgentCard(
      "nl2agent-local-resources",
      JSON.stringify({
        tools: [{ tool_id: 1, name: "Search" }],
        skills: [],
      })
    );

    assertElement(node);
    assert.equal(node.type, "div");
    assert.match(String(node.props.children), /missing draft agent_id/);
  });

  it("routes web MCP fenced data to WebMcpCard", () => {
    const item: WebMcpCardItem = {
      recommendation_id: "community:github",
      name: "GitHub MCP",
      description: "Repository automation",
      source: "community",
      transport: "sse",
      install_options: [readyMcpOption],
    };
    const node = tryRenderNl2AgentCard(
      "nl2agent-web-mcp",
      JSON.stringify({
        agent_id: 202,
        recommendation_batch_id: "online_mcp",
        ...item,
      })
    );

    assertElement(node);
    const [card] = onlineChildren(node);
    assertElement(card);
    assert.equal(card.type, WebMcpCard);
    assert.equal(card.props.agentId, 202);
    assert.equal(card.props.item.name, item.name);
  });

  it("routes web MCP list fenced data to WebMcpCard items", () => {
    const items: WebMcpCardItem[] = [
      {
        recommendation_id: "community:browser",
        name: "Browser MCP",
        source: "community",
        install_options: [readyMcpOption],
      },
      {
        recommendation_id: "registry:github",
        name: "GitHub MCP",
        source: "registry",
        install_options: [readyMcpOption],
      },
    ];

    const node = tryRenderNl2AgentCard(
      "nl2agent-web-mcps",
      JSON.stringify({
        agent_id: 202,
        recommendation_batch_id: "online_mcp",
        items,
      })
    );

    assertElement(node);
    const children = onlineChildren(node);
    assert.equal(children.length, 2);
    children.forEach((child, index) => {
      assertElement(child);
      assert.equal(child.type, WebMcpCard);
      assert.equal(child.props.agentId, 202);
      assert.deepEqual(child.props.item, items[index]);
    });
  });

  it("recovers the draft agent ID from MCP list items", () => {
    const items = [
      {
        agent_id: 202,
        recommendation_id: "community:browser",
        name: "Browser MCP",
        source: "community",
        install_options: [readyMcpOption],
      },
    ];
    const node = tryRenderNl2AgentCard(
      "nl2agent-web-mcps",
      JSON.stringify({ recommendation_batch_id: "online_mcp", items })
    );

    assertElement(node);
    const [child] = onlineChildren(node);
    assertElement(child);
    assert.equal(child.type, WebMcpCard);
    assert.equal(child.props.agentId, 202);
  });

  it("uses the trusted conversation ID when an MCP list omits agent_id", () => {
    const node = tryRenderNl2AgentCard(
      "nl2agent-web-mcps",
      JSON.stringify({
        recommendation_batch_id: "online_mcp",
        items: [
          {
            recommendation_id: "community:browser",
            name: "Browser MCP",
            source: "community",
            install_options: [readyMcpOption],
          },
        ],
      }),
      202
    );

    assertElement(node);
    const [child] = onlineChildren(node);
    assertElement(child);
    assert.equal(child.type, WebMcpCard);
    assert.equal(child.props.agentId, 202);
  });

  it("renders an empty MCP list with the trusted conversation ID", () => {
    const node = tryRenderNl2AgentCard(
      "nl2agent-web-mcps",
      JSON.stringify({ recommendation_batch_id: "online_empty", items: [] }),
      202
    );

    assertElement(node);
    assert.equal(onlineChildren(node).length, 0);
  });

  it("rejects online cards that cannot be registered as a stable batch", () => {
    const node = tryRenderNl2AgentCard(
      "nl2agent-web-skills",
      JSON.stringify({ agent_id: 202, items: [] })
    );

    assertElement(node);
    assert.equal(node.type, "div");
    assert.match(
      String(node.props.children),
      /missing recommendation_batch_id/
    );
  });

  it("rejects a payload ID that conflicts with the active conversation", () => {
    const node = tryRenderNl2AgentCard(
      "nl2agent-web-mcps",
      JSON.stringify({
        agent_id: 303,
        recommendation_batch_id: "online_mcp",
        items: [],
      }),
      202
    );

    assertElement(node);
    assert.equal(node.type, "div");
    assert.match(
      String(node.props.children),
      /does not match the active conversation/
    );
  });

  it("uses the trusted ID for every NL2AGENT card family", () => {
    const cases = [
      [
        "nl2agent-requirements-summary",
        {
          goal: "Build presentations",
          audience_or_scenario: "Office users",
          primary_input: "DOCX files",
          expected_output: "PPT files",
          key_constraints: "Preserve source facts",
        },
        RequirementsSummaryCard,
      ],
      ["nl2agent-model-selection", {}, ModelSelectionCard],
      [
        "nl2agent-agent-identity",
        { display_name: "Document Assistant" },
        AgentIdentityCard,
      ],
      [
        "nl2agent-local-resources",
        { recommendation_batch_id: "batch", tools: [], skills: [] },
        LocalResourcesCard,
      ],
      [
        "nl2agent-web-skills",
        {
          recommendation_batch_id: "online_skill",
          items: [{ skill_id: 1, name: "skill" }],
        },
        WebSkillCard,
      ],
      [
        "nl2agent-finalize",
        {
          business_description: "Build an agent",
          duty_prompt: "Help the user.",
          greeting_message: "Hello",
        },
        FinalizeCard,
      ],
    ] as const;

    for (const [language, payload, component] of cases) {
      const node = tryRenderNl2AgentCard(
        language,
        JSON.stringify(payload),
        202
      );
      assertElement(node);
      if (language === "nl2agent-web-skills") {
        const [child] = onlineChildren(node);
        assertElement(child);
        assert.equal(child.type, component);
        assert.equal(child.props.agentId, 202);
      } else {
        assert.equal(node.type, component);
        assert.equal(
          language === "nl2agent-finalize"
            ? node.props.data.agent_id
            : node.props.agentId,
          202
        );
      }
    }
  });

  it("routes web skill list fenced data to WebSkillCard items", () => {
    const items: WebSkillCardItem[] = [
      { skill_id: 12, name: "doc-review" },
      { skill_id: 13, name: "code-review" },
    ];

    const node = tryRenderNl2AgentCard(
      "nl2agent-web-skills",
      JSON.stringify({
        agent_id: 202,
        recommendation_batch_id: "online_skill",
        items,
      })
    );

    assertElement(node);
    const children = onlineChildren(node);
    assert.equal(children.length, 2);
    children.forEach((child, index) => {
      assertElement(child);
      assert.equal(child.type, WebSkillCard);
      assert.equal(child.props.agentId, 202);
      assert.deepEqual(child.props.item, items[index]);
    });
  });

  it("derives a web skill display name from skill_name", () => {
    const node = tryRenderNl2AgentCard(
      "nl2agent-web-skill",
      JSON.stringify({
        agent_id: 202,
        recommendation_batch_id: "online_skill",
        skill_id: 12,
        skill_name: "doc-review",
      })
    );

    assertElement(node);
    const [card] = onlineChildren(node);
    assertElement(card);
    assert.equal(card.type, WebSkillCard);
    assert.equal(card.props.item.name, "doc-review");
  });

  it("renders a web skill list keyed only by skill names", () => {
    const node = tryRenderNl2AgentCard(
      "nl2agent-web-skills",
      JSON.stringify({
        agent_id: 202,
        recommendation_batch_id: "online_skill",
        items: [
          { skill_name: "document-builder", status: "installable" },
          { skill_name: "document-reader", status: "installable" },
        ],
      })
    );

    assertElement(node);
    const children = onlineChildren(node);
    assert.equal(children.length, 2);
    const [builder, reader] = children;
    assertElement(builder);
    assertElement(reader);
    assert.equal(builder.type, WebSkillCard);
    const builderItem = builder.props.item as WebSkillCardItem;
    const readerItem = reader.props.item as WebSkillCardItem;
    assert.equal(builderItem.name, "document-builder");
    assert.equal(builderItem.skill_id, undefined);
    assert.equal(readerItem.name, "document-reader");
  });
});

describe("online configuration blockers", () => {
  it("requires both online catalogs before completion", () => {
    const blockers = getOnlineConfigurationBlockers({
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

    assert.deepEqual(blockers.missingCatalogs, ["Skill"]);
    assert.equal(blockers.unresolvedMcpCount, 0);
  });

  it("blocks connected MCP workflows after both catalogs render", () => {
    const blockers = getOnlineConfigurationBlockers({
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

    assert.deepEqual(blockers.missingCatalogs, []);
    assert.equal(blockers.unresolvedMcpCount, 1);
  });
});

describe("final review persisted names", () => {
  it("groups local and online resources without using IDs as labels", () => {
    const state = {
      tools: [
        {
          tool_id: 11,
          name: "Document Parser",
          source: "local",
          origin: "local",
        },
        {
          tool_id: 12,
          name: "Web Fetch",
          source: "mcp",
          origin: "online",
        },
      ],
      skills: [
        {
          skill_id: 21,
          name: "Presentation Builder",
          source: "custom",
          origin: "local",
        },
        {
          skill_id: 22,
          name: "Official Research",
          source: "official",
          origin: "online",
        },
      ],
    } as Nl2AgentSessionState;

    const groups = groupFinalReviewResources(state);

    assert.deepEqual(
      groups.local.map((resource) => resource.name),
      ["Document Parser", "Presentation Builder"]
    );
    assert.deepEqual(
      groups.online.map((resource) => resource.name),
      ["Web Fetch", "Official Research"]
    );
  });

  it("blocks publication while any persisted reference is invalid", () => {
    const validState = {
      session_status: "active",
      current_stage: "final_review",
      identity_confirmed: true,
      invalid_references: [],
    } as unknown as Nl2AgentSessionState;
    const invalidState = {
      ...validState,
      invalid_references: [
        {
          reference_type: "tool" as const,
          reference_id: 404,
          reason: "not_found" as const,
        },
      ],
    };

    assert.equal(canPublishFinalReview(validState, true, false, null), true);
    assert.equal(canPublishFinalReview(invalidState, true, false, null), false);
    assert.equal(
      canPublishFinalReview(
        { ...validState, session_status: "completed" },
        true,
        false,
        null
      ),
      false
    );
  });
});

describe("resolveNl2AgentDraftAgentId", () => {
  it("uses the selected conversation mapping before the one-shot handoff", () => {
    assert.equal(resolveNl2AgentDraftAgentId(10, { "10": 202 }, 11, 303), 202);
  });

  it("does not leak a handoff draft into another conversation", () => {
    assert.equal(resolveNl2AgentDraftAgentId(10, {}, 11, 303), null);
    assert.equal(resolveNl2AgentDraftAgentId(11, {}, 11, 303), 303);
  });
});

describe("resolveNl2AgentRunnerId", () => {
  it("prefers the durable runner over a stale selected agent", () => {
    assert.equal(resolveNl2AgentRunnerId(101, "999"), 101);
  });

  it("uses the selected agent for a normal conversation", () => {
    assert.equal(resolveNl2AgentRunnerId(undefined, "999"), 999);
  });
});

describe("resolveNl2AgentCardAgentId", () => {
  it("falls back to the trusted ID when the model omits all IDs", () => {
    assert.deepEqual(resolveNl2AgentCardAgentId(undefined, [], 202), {
      agentId: 202,
      mismatch: false,
    });
  });

  it("rejects conflicting wrapper, item, or trusted IDs", () => {
    assert.equal(resolveNl2AgentCardAgentId(202, [303], 202).mismatch, true);
    assert.equal(resolveNl2AgentCardAgentId(303, [], 202).mismatch, true);
  });
});

describe("NL2AGENT action continuation scope", () => {
  it("isolates pending continuations by conversation and draft", () => {
    assert.notEqual(
      nl2AgentContinuationScopeKey(10, 202),
      nl2AgentContinuationScopeKey(11, 303)
    );
  });
});

describe("NL2AGENT final card validation", () => {
  it("rejects truncated fences and malformed schemas", () => {
    assert.equal(
      validateNl2AgentCards('```nl2agent-local-resources\n{"agent_id":202', 202)
        .failure?.reason,
      "truncated_fence"
    );
    assert.equal(
      validateNl2AgentCards(
        '```nl2agent-local-resources\n{"agent_id":202,"recommendation_batch_id":"local_1","tools":[{"tool_id":1}],"skills":[]}\n```',
        202
      ).failure?.reason,
      "invalid_schema"
    );
  });

  it("accepts empty result cards and rejects duplicate card types", () => {
    const card =
      '```nl2agent-web-skills\n{"agent_id":202,"recommendation_batch_id":"online_1","items":[]}\n```';
    assert.equal(validateNl2AgentCards(card, 202).failure, undefined);
    assert.equal(
      validateNl2AgentCards(`${card}\n${card}`, 202).failure?.reason,
      "invalid_schema"
    );
  });

  it("rejects payload IDs that conflict with the conversation draft", () => {
    assert.equal(
      validateNl2AgentCards(
        '```nl2agent-model-selection\n{"agent_id":303}\n```',
        202
      ).failure?.reason,
      "invalid_schema"
    );
  });
});
