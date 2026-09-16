import assert from "node:assert/strict";
import test from "node:test";

import {
  toCardQuestions,
  toHumanAnswers,
  // @ts-expect-error -- Node's built-in TypeScript runner needs the extension.
} from "../features/humanInteraction/clarification.ts";

test("all structured questions map to trusted card fields", () => {
  const questions = toCardQuestions([
    { id: "goal", type: "text", title: "Goal?", required: true },
    {
      id: "audience",
      type: "single_choice",
      title: "Audience?",
      required: true,
      options: [
        { id: "team", label: "Team" },
        { id: "client", label: "Clients" },
      ],
      allow_other: true,
    },
    {
      id: "constraints",
      type: "multiple_choice",
      title: "Constraints?",
      required: false,
      options: [
        { id: "short", label: "Brief" },
        { id: "formal", label: "Formal" },
      ],
    },
  ]);
  assert.deepEqual(
    questions.map((q) => q.type),
    ["text", "single_choice", "multiple_choice"]
  );
  assert.equal(questions[1].allowOther, true);
  assert.equal(questions[1].otherInputExpanded, true);
  assert.equal(questions[2].required, false);
});

test("submission preserves every answer, option ID and other input", () => {
  assert.deepEqual(
    toHumanAnswers([
      { questionId: "goal", value: "Notice", otherText: null },
      { questionId: "audience", value: "client", otherText: "Partners" },
      {
        questionId: "constraints",
        value: ["short", "formal"],
        otherText: "Today",
      },
    ]),
    [
      { question_id: "goal", value: "Notice", other_text: null },
      { question_id: "audience", value: "client", other_text: "Partners" },
      {
        question_id: "constraints",
        value: ["short", "formal"],
        other_text: "Today",
      },
    ]
  );
});
