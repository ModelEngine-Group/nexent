import assert from "node:assert/strict";
import { describe, it } from "node:test";
import React from "react";
import {
  resolveNl2AgentCardAgentId,
  resolveNl2AgentDraftAgentId,
} from "@/lib/chat/nl2agentDraftContext";

import { tryRenderNl2AgentCard } from "..";
import { LocalResourcesCard } from "../LocalResourcesCard";
import { ModelSelectionCard } from "../ModelSelectionCard";
import { AgentIdentityCard } from "../AgentIdentityCard";
import { FinalizeCard } from "../FinalizeCard";
import { WebMcpCard, type WebMcpCardItem } from "../WebMcpCard";
import { WebSkillCard, type WebSkillCardItem } from "../WebSkillCard";

function assertElement(
  node: React.ReactNode
): asserts node is React.ReactElement<any> {
  assert.equal(React.isValidElement(node), true);
}

describe("tryRenderNl2AgentCard", () => {
  it("rejects invented search request cards before parsing their payload", () => {
    const node = tryRenderNl2AgentCard(
      "nl2agent-search-web-mcps",
      JSON.stringify({ query: "docx parser" }),
      undefined,
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
      JSON.stringify({ agent_id: 202 })
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

  it("passes the web MCP install callback into WebMcpCard", () => {
    const item: WebMcpCardItem = {
      name: "GitHub MCP",
      description: "Repository automation",
      source: "community",
      url: "https://example.com/mcp",
      transport: "sse",
    };
    let installedItem: WebMcpCardItem | null = null;

    const node = tryRenderNl2AgentCard(
      "nl2agent-web-mcp",
      JSON.stringify({ agent_id: 202, ...item }),
      (nextItem) => {
        installedItem = nextItem;
      }
    );

    assertElement(node);
    assert.equal(node.type, WebMcpCard);
    assert.equal(node.props.agentId, 202);
    assert.equal(node.props.item.name, item.name);
    node.props.onInstall(node.props.item);
    assert.deepEqual(installedItem, node.props.item);
  });

  it("routes web MCP list fenced data to WebMcpCard items", () => {
    const items: WebMcpCardItem[] = [
      { name: "Browser MCP", source: "community" },
      { name: "GitHub MCP", source: "registry" },
    ];

    const node = tryRenderNl2AgentCard(
      "nl2agent-web-mcps",
      JSON.stringify({ agent_id: 202, items })
    );

    assertElement(node);
    const children = React.Children.toArray(node.props.children);
    assert.equal(children.length, 2);
    children.forEach((child, index) => {
      assertElement(child);
      assert.equal(child.type, WebMcpCard);
      assert.equal(child.props.agentId, 202);
      assert.deepEqual(child.props.item, items[index]);
    });
  });

  it("recovers the draft agent ID from MCP list items", () => {
    const items = [{ agent_id: 202, name: "Browser MCP", source: "community" }];
    const node = tryRenderNl2AgentCard(
      "nl2agent-web-mcps",
      JSON.stringify({ items })
    );

    assertElement(node);
    const [child] = React.Children.toArray(node.props.children);
    assertElement(child);
    assert.equal(child.type, WebMcpCard);
    assert.equal(child.props.agentId, 202);
  });

  it("uses the trusted conversation ID when an MCP list omits agent_id", () => {
    const node = tryRenderNl2AgentCard(
      "nl2agent-web-mcps",
      JSON.stringify({ items: [{ name: "Browser MCP", source: "community" }] }),
      undefined,
      202
    );

    assertElement(node);
    const [child] = React.Children.toArray(node.props.children);
    assertElement(child);
    assert.equal(child.type, WebMcpCard);
    assert.equal(child.props.agentId, 202);
  });

  it("renders an empty MCP list with the trusted conversation ID", () => {
    const node = tryRenderNl2AgentCard(
      "nl2agent-web-mcps",
      JSON.stringify({ items: [] }),
      undefined,
      202
    );

    assertElement(node);
    assert.equal(React.Children.count(node.props.children), 0);
  });

  it("rejects a payload ID that conflicts with the active conversation", () => {
    const node = tryRenderNl2AgentCard(
      "nl2agent-web-mcps",
      JSON.stringify({ agent_id: 303, items: [] }),
      undefined,
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
      ["nl2agent-model-selection", {}, ModelSelectionCard],
      ["nl2agent-agent-identity", {}, AgentIdentityCard],
      [
        "nl2agent-local-resources",
        { recommendation_batch_id: "batch", tools: [], skills: [] },
        LocalResourcesCard,
      ],
      [
        "nl2agent-web-skills",
        { items: [{ skill_id: 1, name: "skill" }] },
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
        undefined,
        202
      );
      assertElement(node);
      if (language === "nl2agent-web-skills") {
        const [child] = React.Children.toArray(node.props.children);
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
      JSON.stringify({ agent_id: 202, items })
    );

    assertElement(node);
    const children = React.Children.toArray(node.props.children);
    assert.equal(children.length, 2);
    children.forEach((child, index) => {
      assertElement(child);
      assert.equal(child.type, WebSkillCard);
      assert.equal(child.props.agentId, 202);
      assert.deepEqual(child.props.item, items[index]);
    });
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
