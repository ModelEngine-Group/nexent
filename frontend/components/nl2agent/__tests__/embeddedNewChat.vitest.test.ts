import { describe, expect, it } from "vitest";

import {
  nl2AgentComponentsByLanguage,
  preprocessNl2AgentFences,
} from "../Nl2AgentFenceRenderer";

describe("embedded newchat NL2AGENT fence integration", () => {
  it("routes every hyphenated card fence through a word-only language alias", () => {
    const canonicalLanguages = [
      "nl2agent-agent-identity",
      "nl2agent-finalize",
      "nl2agent-local-resources",
      "nl2agent-model-selection",
      "nl2agent-requirements-summary",
      "nl2agent-web-mcp",
      "nl2agent-web-mcps",
      "nl2agent-web-skill",
      "nl2agent-web-skills",
    ];

    for (const language of canonicalLanguages) {
      const processed = preprocessNl2AgentFences(
        `Before\n\`\`\`${language}\n{}\n\`\`\`\nAfter`
      );
      const alias = language.replaceAll("-", "");

      expect(processed).toContain(`\`\`\`${alias}\n`);
      expect(nl2AgentComponentsByLanguage[alias]).toBeDefined();
    }
  });

  it("does not rewrite unknown or inline NL2AGENT text", () => {
    const content =
      "Use `nl2agent-finalize` here.\n```nl2agent-unknown\n{}\n```";

    expect(preprocessNl2AgentFences(content)).toBe(content);
  });
});
