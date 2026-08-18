import assert from "node:assert/strict";
import test from "node:test";

import { AgentRunError, buildAgentRunError } from "../lib/agentRunError.ts";

test("agent run errors preserve HTTP status and code", () => {
  const error = buildAgentRunError(503, "Service Unavailable", {
    code: "distributed_state_unavailable",
    message: "Distributed state is unavailable. Please try again later.",
  });

  assert.equal(error instanceof AgentRunError, true);
  assert.equal(error.status, 503);
  assert.equal(error.code, "distributed_state_unavailable");
});

test("agent run errors support nested FastAPI details", () => {
  const nested = buildAgentRunError(503, "Service Unavailable", {
    detail: {
      code: "distributed_state_unavailable",
      message: "Try again later.",
    },
  });
  const plain = buildAgentRunError(500, "Internal Server Error", {
    detail: "Backend failed.",
  });

  assert.equal(nested.status, 503);
  assert.equal(nested.code, "distributed_state_unavailable");
  assert.equal(plain.code, 500);
  assert.equal(plain.message, "Backend failed.");
});
