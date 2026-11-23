import assert from "node:assert/strict";
import test from "node:test";
import {
  appendClarificationPart,
  formatClarificationQuery,
  isClarificationFallback,
  isHumanInteractionEvent,
  parseClarification,
  renderQuestionText,
  toCardQuestions,
  // @ts-expect-error -- Node's built-in TypeScript runner needs the extension.
} from "../lib/clarification.ts";

const raw = {
  schema_version: 1,
  questions: [
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
      allow_other: true,
    },
  ],
};
const form = parseClarification(raw)!;
const answers = [
  { questionId: "goal", value: "Notice", otherText: null },
  { questionId: "audience", value: "client", otherText: "Partners" },
  { questionId: "constraints", value: ["short", "formal"], otherText: "Today" },
];

test("human_interaction SSE content renders directly as a JSON object", () => {
  const event = JSON.parse(
    JSON.stringify({ type: "human_interaction", content: raw, unit_index: 9 })
  );
  assert.equal(isHumanInteractionEvent(event), true);
  assert.equal(isHumanInteractionEvent({ type: "final_answer" }), false);
  const parts: { type: string; name?: string; data?: unknown }[] = [];
  assert.equal(
    appendClarificationPart(parts, event.content, event.unit_index),
    true
  );
  assert.deepEqual(parts, [
    {
      type: "data",
      name: "clarification",
      data: { form, unitIndex: 9, completed: undefined },
    },
  ]);
});

test("structured form preserves all original card controls", () => {
  const questions = toCardQuestions(form.questions);
  assert.deepEqual(
    questions.map((q) => q.type),
    ["text", "single_choice", "multiple_choice"]
  );
  assert.equal(questions[1].allowOther, true);
  assert.equal(questions[1].otherInputExpanded, true);
  assert.equal(questions[2].required, false);
});

test("answers become an ordered ordinary query using labels and other text", () => {
  const query = formatClarificationQuery(form, [...answers].reverse(), "zh");
  assert.equal(
    query,
    "补充上一轮问题：\n1. Goal?\n   回答：Notice\n2. Audience?\n   回答：Clients；其他补充：Partners\n3. Constraints?\n   回答：Brief；Formal；其他补充：Today"
  );
  assert.match(
    formatClarificationQuery(form, answers, "en"),
    /Answers to the previous questions/
  );
});

test("invalid, duplicate, missing and overlong answers do not send", () => {
  for (const value of ["forged", ["team"]]) {
    assert.throws(() =>
      formatClarificationQuery(
        form,
        [answers[0], { ...answers[1], value }, answers[2]],
        "en"
      )
    );
  }
  assert.throws(() => formatClarificationQuery(form, answers.slice(1), "zh"));
  assert.throws(() =>
    formatClarificationQuery(form, [...answers, answers[0]], "zh")
  );
  assert.throws(() =>
    formatClarificationQuery(
      form,
      [{ ...answers[0], value: "x".repeat(8001) }, ...answers.slice(1)],
      "zh"
    )
  );
});

test("only exact valid-card fallback text is hidden and repeated units deduplicate", () => {
  const parts: { type: string; name?: string; data?: unknown }[] = [];
  appendClarificationPart(parts, JSON.stringify(raw), 2);
  appendClarificationPart(parts, JSON.stringify(raw), 2);
  assert.equal(parts.length, 1);
  assert.equal(isClarificationFallback(parts, renderQuestionText(form)), true);
  assert.equal(isClarificationFallback(parts, "Other business answer"), false);
  assert.equal(
    appendClarificationPart(parts, '{"schema_version":2}', 3),
    false
  );
  assert.equal(parts.length, 1);
});

test("unsupported or malformed forms leave text fallback available", () => {
  for (const invalid of [
    null,
    "{",
    { ...raw, schema_version: 2 },
    { ...raw, questions: [] },
    { ...raw, execute: "code" },
    { ...raw, questions: [raw.questions[0], raw.questions[0]] },
    { ...raw, questions: [{ ...raw.questions[0], allow_other: true }] },
    {
      ...raw,
      questions: [
        { ...raw.questions[1], options: [{ id: "one", label: "one" }] },
      ],
    },
  ]) {
    assert.equal(parseClarification(invalid), null);
  }
});
