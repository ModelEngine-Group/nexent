import assert from "node:assert/strict";
import test from "node:test";

import {
  buildAgentShareRunPayload,
  extractAgentShareHistory,
  getAgentShareFinalAnswerChunk,
  getAgentShareLoadAction,
  getAgentSharePageState,
  getAgentShareStreamError,
  parseAgentShareSseLine,
  // @ts-ignore -- Node's built-in TypeScript runner needs the extension.
} from "../lib/agentShareChat.ts";

test("maps only a visitor's displayable history into the share chat", () => {
  assert.deepEqual(
    extractAgentShareHistory([
      {
        message: [
          { role: "user", message_id: 1, message: "Hello" },
          {
            role: "assistant",
            message_id: 2,
            message: [
              { type: "model_output", content: "hidden work" },
              { type: "final_answer", content: "Welcome" },
            ],
          },
        ],
      },
    ]),
    [
      { id: "history-user-1", role: "user", content: "Hello" },
      { id: "history-assistant-2", role: "assistant", content: "Welcome" },
    ]
  );
});

test("accepts only explicit final-answer and error SSE events", () => {
  const answer = parseAgentShareSseLine(
    'data: {"type":"final_answer","content":"Hello"}'
  );
  const error = parseAgentShareSseLine(
    'data: {"type":"error","content":"Unavailable"}'
  );

  assert.equal(answer && getAgentShareFinalAnswerChunk(answer), "Hello");
  assert.equal(error && getAgentShareStreamError(error), "Unavailable");
  assert.equal(parseAgentShareSseLine("event: stream_status"), null);
  assert.equal(
    getAgentShareFinalAnswerChunk({ type: "model_output", content: "hidden" }),
    null
  );
});

test("does not load Agent share data before authentication completes", () => {
  assert.equal(
    getAgentShareLoadAction({
      shareToken: "signed-token",
      isAuthChecking: true,
      isAuthenticated: false,
    }),
    "wait"
  );
  assert.equal(
    getAgentShareLoadAction({
      shareToken: "signed-token",
      isAuthChecking: false,
      isAuthenticated: false,
    }),
    "wait"
  );
  assert.equal(
    getAgentShareLoadAction({
      shareToken: "signed-token",
      isAuthChecking: false,
      isAuthenticated: true,
    }),
    "load"
  );
});

test("maps all unavailable Agent share failures to one page state", () => {
  for (const failure of ["invalid-token", "revoked", "agent-unavailable"]) {
    assert.equal(
      getAgentSharePageState({
        isAuthChecking: false,
        isAuthenticated: true,
        isLoading: false,
        hasMetadata: false,
        hasUnavailableError: Boolean(failure),
      }),
      "unavailable"
    );
  }
});

test("builds the fixed Agent share run request without client scope fields", () => {
  const payload = buildAgentShareRunPayload("  hello  ", "Asia/Shanghai");
  assert.deepEqual(payload, {
    query: "hello",
    timezone: "Asia/Shanghai",
  });
  assert.equal("agent_id" in payload, false);
  assert.equal("conversation_id" in payload, false);
  assert.equal("tenant_id" in payload, false);
});
