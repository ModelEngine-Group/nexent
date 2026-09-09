import assert from "node:assert/strict";
import test from "node:test";

import {
  trimAgentText,
  // @ts-ignore -- Node's built-in TypeScript runner needs the extension.
} from "../lib/agentText.ts";

test("normalizes missing and blank agent text to an empty string", () => {
  assert.equal(trimAgentText(undefined), "");
  assert.equal(trimAgentText("   "), "");
});

test("trims agent text without changing its content", () => {
  assert.equal(trimAgentText("  support-agent  "), "support-agent");
});
