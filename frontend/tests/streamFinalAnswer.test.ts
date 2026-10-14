import assert from "node:assert/strict";
import test from "node:test";
// @ts-expect-error -- Node's built-in TypeScript runner needs the extension.
import { stripStreamedFinalAnswerEcho } from "../lib/streamFinalAnswer.ts";

test("OC-030 removes a streamed answer echo while preserving preceding thought", () => {
  assert.equal(
    stripStreamedFinalAnswerEcho(
      "Thinking first. Final answer.",
      "Final answer."
    ),
    "Thinking first. "
  );
  assert.equal(
    stripStreamedFinalAnswerEcho("Final answer.", "Final answer."),
    ""
  );
});

test("OC-030 leaves unrelated reasoning and empty final events untouched", () => {
  assert.equal(
    stripStreamedFinalAnswerEcho("Call final_answer(...)", "Done."),
    null
  );
  assert.equal(stripStreamedFinalAnswerEcho("Reasoning", ""), null);
});
