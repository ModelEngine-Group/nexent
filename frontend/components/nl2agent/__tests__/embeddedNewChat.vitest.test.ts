import { describe, expect, it } from "vitest";

import { nl2AgentComponentsByLanguage } from "../Nl2AgentFenceRenderer";

describe("embedded newchat NL2AGENT fence integration", () => {
  it("registers every NL2AGENT fenced-card language without a legacy renderer", () => {
    expect(Object.keys(nl2AgentComponentsByLanguage).sort()).toEqual([
      "nl2agent-agent-identity",
      "nl2agent-finalize",
      "nl2agent-local-resources",
      "nl2agent-model-selection",
      "nl2agent-requirements-summary",
      "nl2agent-web-mcp",
      "nl2agent-web-mcps",
      "nl2agent-web-skill",
      "nl2agent-web-skills",
    ]);
  });
});
