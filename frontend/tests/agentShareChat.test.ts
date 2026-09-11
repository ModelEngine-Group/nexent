import assert from "node:assert/strict";
import test from "node:test";

import {
  extractAgentShareHistory,
  getAgentShareFinalAnswerChunk,
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
