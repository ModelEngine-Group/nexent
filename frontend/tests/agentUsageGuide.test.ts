import assert from "node:assert/strict";
import test from "node:test";

import {
  buildAgentUsageGuidePath,
  // @ts-ignore -- Node's built-in TypeScript runner needs the extension.
} from "../lib/agentUsageGuide.ts";

test("builds the published Agent repository guide URL", () => {
  assert.equal(
    buildAgentUsageGuidePath("zh", 41),
    "/zh/agent-space?tab=mine&agent_id=41&guide=usage"
  );
});
