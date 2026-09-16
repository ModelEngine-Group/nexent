import assert from "node:assert/strict";
import test from "node:test";
import {
  appendGuidanceMessage,
  parseGuidanceMessage,
  // @ts-expect-error -- Node's built-in TypeScript runner needs the extension.
} from "../features/humanInteraction/guidanceMessage.ts";

const message = {
  request_id: "guidance-1",
  text: "Use short paragraphs\nKeep <script> as text",
  created_at: "2026-09-14T12:00:00Z",
};

test("stream and history restore the same plain user guidance without duplicates", () => {
  const parts: unknown[] = [{ type: "reasoning", text: "Working" }];
  assert.equal(appendGuidanceMessage(parts, JSON.stringify(message)), true);
  assert.equal(appendGuidanceMessage(parts, message), false);
  assert.deepEqual(parts[1], {
    type: "data",
    name: "user-steering",
    data: message,
  });
  assert.equal(
    appendGuidanceMessage(parts, { ...message, request_id: "guidance-2" }),
    true
  );
  assert.equal(parts.length, 3);
});

test("invalid guidance is ignored and untrusted display attributes are discarded", () => {
  for (const value of [
    "not json",
    null,
    {},
    { ...message, text: "" },
    { ...message, request_id: null },
  ]) {
    assert.equal(parseGuidanceMessage(value), null);
    assert.equal(appendGuidanceMessage([], value), false);
  }
  assert.deepEqual(
    parseGuidanceMessage({ ...message, role: "system", html: "<img>" }),
    message
  );
});
