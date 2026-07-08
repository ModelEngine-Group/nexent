import assert from "node:assert/strict";
import { describe, it } from "node:test";
import React from "react";

import { tryRenderNl2AgentCard } from "..";
import { LocalResourcesCard } from "../LocalResourcesCard";
import { WebMcpCard, type WebMcpCardItem } from "../WebMcpCard";

function assertElement(
  node: React.ReactNode
): asserts node is React.ReactElement<any> {
  assert.equal(React.isValidElement(node), true);
}

describe("tryRenderNl2AgentCard", () => {
  it("routes local-resource fenced data to LocalResourcesCard", () => {
    const node = tryRenderNl2AgentCard(
      "nl2agent-local-resources",
      JSON.stringify({
        agent_id: 202,
        tools: [{ tool_id: 1, name: "Search" }],
        skills: [{ skill_id: 7, name: "Summarize" }],
      })
    );

    assertElement(node);
    assert.equal(node.type, LocalResourcesCard);
    assert.equal(node.props.agentId, 202);
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
      JSON.stringify(item),
      (nextItem) => {
        installedItem = nextItem;
      }
    );

    assertElement(node);
    assert.equal(node.type, WebMcpCard);
    assert.deepEqual(node.props.item, item);
    node.props.onInstall(node.props.item);
    assert.deepEqual(installedItem, item);
  });
});
