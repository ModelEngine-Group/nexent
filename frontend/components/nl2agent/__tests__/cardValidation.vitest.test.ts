import { describe, expect, it } from "vitest";

import { parseNl2AgentCard, validateNl2AgentCards } from "../cardValidation";

describe("canonical NL2AGENT card validation", () => {
  it("uses the trusted conversation draft ID when the payload omits it", () => {
    const result = parseNl2AgentCard("nl2agent-model-selection", "{}", 202);

    expect(result.failure).toBeUndefined();
    expect(result.cards[0].agentId).toBe(202);
  });

  it("rejects a payload ID that conflicts with the conversation", () => {
    const result = parseNl2AgentCard(
      "nl2agent-agent-identity",
      JSON.stringify({ agent_id: 303, display_name: "Writer" }),
      202
    );

    expect(result.failure?.agentIdError).toBe("mismatch");
  });

  it("accepts empty online result batches", () => {
    const result = parseNl2AgentCard(
      "nl2agent-web-mcps",
      JSON.stringify({ recommendation_batch_id: "online_empty", items: [] }),
      202
    );

    expect(result.failure).toBeUndefined();
  });

  it("rejects malformed MCP installation options", () => {
    const result = parseNl2AgentCard(
      "nl2agent-web-mcps",
      JSON.stringify({
        recommendation_batch_id: "online_mcp",
        items: [
          {
            recommendation_id: "registry:broken",
            name: "Broken MCP",
            install_options: [{ option_id: "remote", type: "remote" }],
          },
        ],
      }),
      202
    );

    expect(result.failure?.reason).toBe("invalid_schema");
  });

  it("rejects undeclared card fields", () => {
    const result = parseNl2AgentCard(
      "nl2agent-agent-identity",
      JSON.stringify({ display_name: "Writer", injected: true }),
      202
    );

    expect(result.failure?.reason).toBe("invalid_schema");
  });

  it("detects truncated and duplicate fenced cards", () => {
    expect(
      validateNl2AgentCards(
        '```nl2agent-local-resources\n{"recommendation_batch_id":"local_1"',
        202
      ).failure?.reason
    ).toBe("truncated_fence");

    const card = "```nl2agent-model-selection\n{}\n```";
    expect(validateNl2AgentCards(`${card}\n${card}`, 202).failure?.reason).toBe(
      "invalid_schema"
    );
  });
});
